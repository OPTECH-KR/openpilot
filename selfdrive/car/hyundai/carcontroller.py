from random import randint

from cereal import car
from openpilot.common.conversions import Conversions as CV
from openpilot.common.params import Params
from openpilot.common.numpy_fast import clip
from openpilot.common.realtime import DT_CTRL
from opendbc.can.packer import CANPacker
from openpilot.selfdrive.car import apply_driver_steer_torque_limits, common_fault_avoidance
from openpilot.selfdrive.car.hyundai import hyundaicanfd, hyundaican
from openpilot.selfdrive.car.hyundai.hyundaicanfd import CanBus
from openpilot.selfdrive.car.hyundai.values import HyundaiFlags, Buttons, CarControllerParams, CANFD_CAR, CAR

VisualAlert = car.CarControl.HUDControl.VisualAlert
LongCtrlState = car.CarControl.Actuators.LongControlState

# EPS faults if you apply torque while the steering angle is above 90 degrees for more than 1 second
# All slightly below EPS thresholds to avoid fault
MAX_ANGLE = 85
MAX_ANGLE_FRAMES = 89
MAX_ANGLE_CONSECUTIVE_FRAMES = 2


def process_hud_alert(enabled, fingerprint, hud_control):
  sys_warning = (hud_control.visualAlert in (VisualAlert.steerRequired, VisualAlert.ldw))

  # initialize to no line visible
  # TODO: this is not accurate for all cars
  sys_state = 1
  if hud_control.leftLaneVisible and hud_control.rightLaneVisible or sys_warning:  # HUD alert only display when LKAS status is active
    sys_state = 3 if enabled or sys_warning else 4
  elif hud_control.leftLaneVisible:
    sys_state = 5
  elif hud_control.rightLaneVisible:
    sys_state = 6

  # initialize to no warnings
  left_lane_warning = 0
  right_lane_warning = 0
  if hud_control.leftLaneDepart:
    left_lane_warning = 1 if fingerprint in (CAR.GENESIS_G90, CAR.GENESIS_G80) else 2
  if hud_control.rightLaneDepart:
    right_lane_warning = 1 if fingerprint in (CAR.GENESIS_G90, CAR.GENESIS_G80) else 2

  return sys_warning, sys_state, left_lane_warning, right_lane_warning


class CarController:
  def __init__(self, dbc_name, CP, VM):
    self.CP = CP
    self.CAN = CanBus(CP)
    self.params = CarControllerParams(CP)
    self.packer = CANPacker(dbc_name)
    self.angle_limit_counter = 0
    self.frame = 0

    self.accel_last = 0
    self.apply_steer_last = 0
    self.car_fingerprint = CP.carFingerprint
    self.last_button_frame = 0

    # optech: set speed sync after engaging (set_speed_sync)
    self.set_current_speed = Params().get_bool("OptechCruiseSetCurrent")
    self.ldws_car = Params().get_bool("OptechLdwsCar")  # 토글 > LDWS 차량 (read at start: reboot to apply)
    self.cam_haptic = 0  # 과속 단속 알림 (read every 5 s in update)
    self.cruise_on_prev = False
    self.sync_target = 0  # set speed to reach, in the cluster unit; 0 = nothing to do
    self.sync_start_frame = 0
    self.sync_button_frame = 0
    self.sync_wait = 10
    self.sync_alive = 0
    self.sync_alive_frame = 0

  def update(self, CC, CS, now_nanos):
    actuators = CC.actuators
    hud_control = CC.hudControl

    # steering torque
    new_steer = int(round(actuators.steer * self.params.STEER_MAX))
    apply_steer = apply_driver_steer_torque_limits(new_steer, self.apply_steer_last, CS.out.steeringTorque, self.params)

    # >90 degree steering fault prevention
    self.angle_limit_counter, apply_steer_req = common_fault_avoidance(abs(CS.out.steeringAngleDeg) >= MAX_ANGLE, CC.latActive,
                                                                       self.angle_limit_counter, MAX_ANGLE_FRAMES,
                                                                       MAX_ANGLE_CONSECUTIVE_FRAMES)

    if not CC.latActive:
      apply_steer = 0

    # Hold torque with induced temporary fault when cutting the actuation bit
    torque_fault = CC.latActive and not apply_steer_req

    self.apply_steer_last = apply_steer

    # accel + longitudinal
    accel = clip(actuators.accel, CarControllerParams.ACCEL_MIN, CarControllerParams.ACCEL_MAX)
    stopping = actuators.longControlState == LongCtrlState.stopping
    set_speed_in_units = hud_control.setSpeed * (CV.MS_TO_KPH if CS.is_metric else CV.MS_TO_MPH)

    # HUD messages
    sys_warning, sys_state, left_lane_warning, right_lane_warning = process_hud_alert(CC.enabled, self.car_fingerprint,
                                                                                      hud_control)
    # optech '과속 단속 알림' 1 핸들 진동 / 2 계기판 표시 (optech-hkg): controlsd sets both lane departs together for it
    if self.frame % 500 == 0:
      try:
        self.cam_haptic = int(Params().get("HapticFeedbackWhenSpeedCamera", encoding="utf8") or 0)
      except ValueError:
        self.cam_haptic = 0
    if hud_control.leftLaneDepart and hud_control.rightLaneDepart and self.cam_haptic in (1, 2):
      left_lane_warning = right_lane_warning = self.cam_haptic

    can_sends = []

    # *** common hyundai stuff ***

    # tester present - w/ no response (keeps relevant ECU disabled)
    if self.frame % 100 == 0 and not (self.CP.flags & HyundaiFlags.CANFD_CAMERA_SCC.value) and self.CP.openpilotLongitudinalControl:
      # for longitudinal control, either radar or ADAS driving ECU
      addr, bus = 0x7d0, 0
      if self.CP.flags & HyundaiFlags.CANFD_HDA2.value:
        addr, bus = 0x730, self.CAN.ECAN
      can_sends.append([addr, 0, b"\x02\x3E\x80\x00\x00\x00\x00\x00", bus])

      # for blinkers
      if self.CP.flags & HyundaiFlags.ENABLE_BLINKERS:
        can_sends.append([0x7b1, 0, b"\x02\x3E\x80\x00\x00\x00\x00\x00", self.CAN.ECAN])

    # CAN-FD platforms
    if self.CP.carFingerprint in CANFD_CAR:
      hda2 = self.CP.flags & HyundaiFlags.CANFD_HDA2
      hda2_long = hda2 and self.CP.openpilotLongitudinalControl

      # steering control
      can_sends.extend(hyundaicanfd.create_steering_messages(self.packer, self.CP, self.CAN, CC.enabled, apply_steer_req, apply_steer))

      # prevent LFA from activating on HDA2 by sending "no lane lines detected" to ADAS ECU
      if self.frame % 5 == 0 and hda2:
        can_sends.append(hyundaicanfd.create_suppress_lfa(self.packer, self.CAN, CS.hda2_lfa_block_msg,
                                                          self.CP.flags & HyundaiFlags.CANFD_HDA2_ALT_STEERING))

      # LFA and HDA icons
      if self.frame % 5 == 0 and (not hda2 or hda2_long):
        can_sends.append(hyundaicanfd.create_lfahda_cluster(self.packer, self.CAN, CC.enabled))

      # blinkers
      if hda2 and self.CP.flags & HyundaiFlags.ENABLE_BLINKERS:
        can_sends.extend(hyundaicanfd.create_spas_messages(self.packer, self.CAN, self.frame, CC.leftBlinker, CC.rightBlinker))

      if self.CP.openpilotLongitudinalControl:
        if hda2:
          can_sends.extend(hyundaicanfd.create_adrv_messages(self.packer, self.CAN, self.frame))
        if self.frame % 2 == 0:
          can_sends.append(hyundaicanfd.create_acc_control(self.packer, self.CAN, CC.enabled, self.accel_last, accel, stopping, CC.cruiseControl.override,
                                                           set_speed_in_units))
          self.accel_last = accel
      else:
        # button presses
        can_sends.extend(self.create_button_messages(CC, CS, use_clu11=False))
    else:
      can_sends.append(hyundaican.create_lkas11(self.packer, self.frame, self.car_fingerprint, apply_steer, apply_steer_req,
                                                torque_fault, CS.lkas11, sys_warning, sys_state, CC.enabled,
                                                hud_control.leftLaneVisible, hud_control.rightLaneVisible,
                                                left_lane_warning, right_lane_warning, ldws_car=self.ldws_car))

      if not self.CP.openpilotLongitudinalControl:
        buttons = self.create_button_messages(CC, CS, use_clu11=True)
        sync = self.set_speed_sync(CC, CS)
        can_sends.extend(buttons if (buttons or CC.cruiseControl.cancel or CC.cruiseControl.resume) else sync)

      if self.frame % 2 == 0 and self.CP.openpilotLongitudinalControl:
        # TODO: unclear if this is needed
        jerk = 3.0 if actuators.longControlState == LongCtrlState.pid else 1.0
        use_fca = self.CP.flags & HyundaiFlags.USE_FCA.value
        can_sends.extend(hyundaican.create_acc_commands(self.packer, CC.enabled, accel, jerk, int(self.frame / 2),
                                                        hud_control.leadVisible, set_speed_in_units, stopping,
                                                        CC.cruiseControl.override, use_fca))

      # 20 Hz LFA MFA message
      if self.frame % 5 == 0 and self.CP.flags & HyundaiFlags.SEND_LFA.value:
        can_sends.append(hyundaican.create_lfahda_mfc(self.packer, CC.enabled))

      # 5 Hz ACC options
      if self.frame % 20 == 0 and self.CP.openpilotLongitudinalControl:
        can_sends.extend(hyundaican.create_acc_opt(self.packer))

      # 2 Hz front radar options
      if self.frame % 50 == 0 and self.CP.openpilotLongitudinalControl:
        can_sends.append(hyundaican.create_frt_radar_opt(self.packer))

    new_actuators = actuators.copy()
    new_actuators.steer = apply_steer / self.params.STEER_MAX
    new_actuators.steerOutputCan = apply_steer
    new_actuators.accel = accel

    self.frame += 1
    return new_actuators, can_sends

  def set_speed_sync(self, CC, CS):
    """optech: openpilot engaged while driving -> bring the car's own cruise (SCC) set speed to the current speed.

    The stock SCC starts from SET or from the last set speed (RES, e.g. 60 km/h) and then speeds up hard, which startles
    people. Right after engaging, openpilot presses SET- / RES+ (one CLU11 per frame for 4-8 frames, then a 8-15 frame
    pause: optech-hkg / apilot timing) until the set speed is the speed at engaging. After that the set speed is the
    driver's again: a cruise button pressed later than 1 s after engaging, braking, disengaging or 10 s end it.
    The panda allows SET- / RES+ only while engaged (safety_hyundai.h)."""
    cruise_on = CS.out.cruiseState.enabled
    to_unit = CV.MS_TO_KPH if CS.is_metric else CV.MS_TO_MPH
    if cruise_on and not self.cruise_on_prev and self.set_current_speed:
      v = CS.out.vEgoCluster if CS.out.vEgoCluster > 0.1 else CS.out.vEgo
      speed = v * to_unit
      if speed >= (10 if CS.is_metric else 6):  # driving, not starting from a stop
        self.sync_target = int(round(max(speed, 30 if CS.is_metric else 20)))  # the SCC sets nothing lower
        self.sync_start_frame = self.frame
        self.sync_button_frame = self.frame
    self.cruise_on_prev = cruise_on
    if not self.sync_target:
      return []

    set_speed = int(round(CS.out.cruiseState.speed * to_unit))
    driver_button = CS.cruise_buttons[-1] != Buttons.NONE
    since = (self.frame - self.sync_start_frame) * DT_CTRL
    done = set_speed == self.sync_target or since > 10.
    if done or not cruise_on or not CC.enabled or CS.out.brakePressed or (driver_button and since > 1.):
      self.sync_target = 0
      return []
    if driver_button:  # still holding the button that engaged
      return []

    if self.frame - self.sync_button_frame > self.sync_wait:
      if self.frame - self.sync_alive_frame > self.sync_alive:  # pressed long enough: let go and wait
        self.sync_wait = randint(8, 15)
        self.sync_button_frame = self.frame
      else:
        button = Buttons.SET_DECEL if set_speed > self.sync_target else Buttons.RES_ACCEL
        return [hyundaican.create_clu11(self.packer, self.frame, CS.clu11, button, self.CP.carFingerprint, CS.camera_scc,
                                        next_counter=True)]
    else:
      self.sync_alive = randint(4, 8)
      self.sync_alive_frame = self.frame
    return []

  def create_button_messages(self, CC: car.CarControl, CS: car.CarState, use_clu11: bool):
    can_sends = []
    if use_clu11:
      if CC.cruiseControl.cancel:
        can_sends.append(hyundaican.create_clu11(self.packer, self.frame, CS.clu11, Buttons.CANCEL, self.CP.carFingerprint, CS.camera_scc))
      elif CC.cruiseControl.resume:
        # send resume at a max freq of 10Hz
        if (self.frame - self.last_button_frame) * DT_CTRL > 0.1:
          # send 25 messages at a time to increases the likelihood of resume being accepted
          can_sends.extend([hyundaican.create_clu11(self.packer, self.frame, CS.clu11, Buttons.RES_ACCEL, self.CP.carFingerprint, CS.camera_scc)] * 25)
          if (self.frame - self.last_button_frame) * DT_CTRL >= 0.15:
            self.last_button_frame = self.frame
    else:
      if (self.frame - self.last_button_frame) * DT_CTRL > 0.25:
        # cruise cancel
        if CC.cruiseControl.cancel:
          if self.CP.flags & HyundaiFlags.CANFD_ALT_BUTTONS:
            can_sends.append(hyundaicanfd.create_acc_cancel(self.packer, self.CP, self.CAN, CS.cruise_info))
            self.last_button_frame = self.frame
          else:
            for _ in range(20):
              can_sends.append(hyundaicanfd.create_buttons(self.packer, self.CP, self.CAN, CS.buttons_counter+1, Buttons.CANCEL))
            self.last_button_frame = self.frame

        # cruise standstill resume
        elif CC.cruiseControl.resume:
          if self.CP.flags & HyundaiFlags.CANFD_ALT_BUTTONS:
            # TODO: resume for alt button cars
            pass
          else:
            for _ in range(20):
              can_sends.append(hyundaicanfd.create_buttons(self.packer, self.CP, self.CAN, CS.buttons_counter+1, Buttons.RES_ACCEL))
            self.last_button_frame = self.frame

    return can_sends
