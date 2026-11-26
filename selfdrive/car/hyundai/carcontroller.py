from cereal import car
from common.conversions import Conversions as CV
from common.numpy_fast import clip, interp
from common.realtime import DT_CTRL
from opendbc.can.packer import CANPacker
from selfdrive.car import apply_driver_steer_torque_limits
from selfdrive.car.hyundai import hyundaicanfd, hyundaican
from selfdrive.car.hyundai.angle_steer import apply_steer_angle_limits, torque_reduction_gain
from selfdrive.car.hyundai.values import HyundaiFlags, Buttons, CarControllerParams, CANFD_CAR, CAR, FEATURES, LEGACY_SAFETY_MODE_CAR, canfd_bus
import random
from random import randint
from common.params import Params

VisualAlert = car.CarControl.HUDControl.VisualAlert
LongCtrlState = car.CarControl.Actuators.LongControlState

# EPS faults if you apply torque while the steering angle is above 90 degrees for more than 1 second
# All slightly below EPS thresholds to avoid fault
MAX_ANGLE = 85
MAX_ANGLE_FRAMES = 89
MAX_ANGLE_CONSECUTIVE_FRAMES = 2

# RES that turns the car's own SCC on while openpilot is engaged (stock SCC cars), see optech_res_allowed().
# K7 HEV 2018 drive record 2026-11-24 (28 tries): every RES below 30 km/h without a lead (11..26 km/h) and every RES at
# a standstill was refused, and each refusal showed '스마트 크루즈 컨트롤 작동조건이 아님' on the cluster (SCC11
# DriverAlertDisplay 2, 21 times; the old rule kept pressing RES for up to 12 s). From 30 km/h, or moving with a lead,
# the car took it within 1-2 s. Hyundai/Kia manuals of these years: without a car ahead SCC sets from 30 km/h.
RES_MIN_KPH = 30.0       # no lead: from this speed
RES_LEAD_MIN_KPH = 5.0   # with a lead: once moving (at a standstill the car refuses RES)
RES_TRY_S = 3.0          # car SCC still off after this long -> stop pressing RES ...
RES_RETRY_KPH = 5.0      # ... until the speed is this much higher, a lead appears,
RES_HOLD_S = 15.0        # ... or this long has passed

OPTECH_STOPPED_MS = 3.0 / 3.6  # below this the car counts as stopped for the cluster's speed camera blink


def process_hud_alert(enabled, fingerprint, hud_control):
  sys_warning = (hud_control.visualAlert in (VisualAlert.steerRequired, VisualAlert.ldw))

  # initialize to no line visible
  # TODO: this is not accurate for all cars
  sys_state = 1
  # optech (K7 HEV HUD feedback, like OPKR which always sends both lanes visible): while openpilot is on show both
  # lane lines all the time, so the HUD lines just mean 'on'. The model's lane visibility flips around 50 % on faded
  # lines / intersections and made the lines come and go every second (drivelog still records the real values)
  if enabled:
    sys_state = 3
  elif hud_control.leftLaneVisible and hud_control.rightLaneVisible or sys_warning:  # HUD alert only display when LKAS status is active
    sys_state = 3 if enabled or sys_warning else 4
  elif hud_control.leftLaneVisible:
    sys_state = 5
  elif hud_control.rightLaneVisible:
    sys_state = 6
  # optech (K7 HEV HUD feedback): while openpilot is off show no lane lines, not lines that come and go with the model's
  # lane visibility (lane departure warnings still show)
  if not enabled and not sys_warning:
    sys_state = 1

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
    self.params = CarControllerParams(CP)
    self.packer = CANPacker(dbc_name)
    self.angle_limit_counter = 0
    self.frame = 0

    self.accel_last = 0
    self.apply_steer_last = 0
    # LFA2 angle steering (기타 차종)
    self.angle_steering = bool(CP.flags & HyundaiFlags.CANFD_ANGLE_STEERING)
    self.apply_angle_last = 0.
    self.angle_gain_last = 0.
    self.angle_max_gain = 1.0
    self.non_scc_speed_buttons = False
    self.car_fingerprint = CP.carFingerprint
    #self.send_lfa_mfa_lkas = True if self.car_fingerprint in FEATURES["send_lfa_mfa"] and self.car_fingerprint not in [CAR.HYUNDAI_GENESIS] else False
    self.send_lfa_mfa_lkas = CP.flags & HyundaiFlags.SEND_LFA.value
    self.last_button_frame = 0
    self.pcmCruiseButtonDelay = 0
    self.jerkStartLimit = 1.0
    self.speedCameraHapticEndFrame = 0
    self.hapticFeedbackWhenSpeedCamera = 0
    self.maxAngleFrames = MAX_ANGLE_FRAMES
    self.softHoldMode = 1
    self.blinking_signal = False #아이콘 깜박이용 1Hz
    self.blinking_frame = int(1.0 / DT_CTRL)
    self.steerDeltaUp = self.params.STEER_DELTA_UP
    self.steerDeltaDown = self.params.STEER_DELTA_DOWN
    self.button_wait = 12
    self.jerk_count = 0

    # for Legacy mode car auto resume (DH etc, not tested)
    self.resume_cnt = 0
    self.resume_wait_timer = 0
    self.button_alive = 0
    self.button_alive_frame = 0
    # RES while the car's SCC is off (optech_res_allowed)
    self.res_try_frame = -1    # frame of the first RES of the current try (-1: not trying)
    self.res_hold = False      # the car refused for RES_TRY_S: wait for a better chance
    self.res_hold_kph = 0.
    self.res_hold_lead = False
    self.res_hold_frame = 0
    # optech drive record: cruise buttons openpilot sent to the car (CLU11), counted since start -
    # RES while the car's SCC is off / RES while on / SET- / GAP / CANCEL (drivelog reads the change)
    self.btn_counts = [0, 0, 0, 0, 0]

  def drive_record_text(self, CS, can_sends):
    """carControl.debugTextCC for selfdrive/carrot/tools/drivelog.py (nothing else shows it)."""
    for msg in can_sends:
      if msg[0] == 1265:  # CLU11: CF_Clu_CruiseSwState is the low 3 bits of byte 0
        btn = msg[2][0] & 0x7
        if btn == Buttons.RES_ACCEL:
          self.btn_counts[1 if CS.out.cruiseState.enabled else 0] += 1
        elif btn == Buttons.SET_DECEL:
          self.btn_counts[2] += 1
        elif btn == Buttons.GAP_DIST:
          self.btn_counts[3] += 1
        elif btn == Buttons.CANCEL:
          self.btn_counts[4] += 1
    scc = CS.scc_diag if CS.scc_diag is not None else (-1, -1, -1, -1)
    cam = CS.cam_lkas_diag if CS.cam_lkas_diag is not None else (-1, -1)
    fca = CS.fca_diag if CS.fca_diag is not None else (-1, -1)
    fcw = CS.cam_fcw_diag if CS.cam_fcw_diag is not None else (-1, -1)
    return "OPT i={} a={} f={} m={} cl={} cw={} r0={} r1={} s={} g={} c={} fi={} fs={} cf={} cu={}".format(
      *scc, *cam, *self.btn_counts, *fca, *fcw)

  def optech_res_allowed(self, CS, lead):
    """May RES go to the car now to turn its SCC on? Only when the car can accept it (see RES_MIN_KPH): every refused
    RES shows '작동조건이 아님' on the cluster. Called on every frame a RES would be sent."""
    v_kph = CS.out.vEgo * CV.MS_TO_KPH
    if CS.out.brakePressed or CS.out.brakeLights or not (v_kph >= RES_MIN_KPH or (lead and v_kph >= RES_LEAD_MIN_KPH)):
      self.res_try_frame = -1
      return False
    if self.res_hold:
      if v_kph >= self.res_hold_kph + RES_RETRY_KPH or (lead and not self.res_hold_lead) or \
         (self.frame - self.res_hold_frame) * DT_CTRL >= RES_HOLD_S:
        self.res_hold = False
      else:
        return False
    if self.res_try_frame < 0:
      self.res_try_frame = self.frame
    elif (self.frame - self.res_try_frame) * DT_CTRL >= RES_TRY_S:
      self.res_try_frame = -1
      self.res_hold, self.res_hold_kph, self.res_hold_lead, self.res_hold_frame = True, v_kph, lead, self.frame
      return False
    return True

  def update(self, CC, CS):
    actuators = CC.actuators
    hud_control = CC.hudControl

    # steering torque
    new_steer = int(round(actuators.steer * self.params.STEER_MAX))
    self.params.STEER_DELTA_UP = self.steerDeltaUp
    self.params.STEER_DELTA_DOWN = self.steerDeltaDown
    apply_steer = apply_driver_steer_torque_limits(new_steer, self.apply_steer_last, CS.out.steeringTorque, self.params)

    if not CC.latActive:
      apply_steer = 0

    self.apply_steer_last = apply_steer

    # accel + longitudinal
    accel = clip(actuators.accel, CarControllerParams.ACCEL_MIN, CarControllerParams.ACCEL_MAX)
    stopping = actuators.longControlState == LongCtrlState.stopping
    set_speed_in_units = hud_control.setSpeed * (CV.MS_TO_KPH if CS.is_metric else CV.MS_TO_MPH)

    # HUD messages
    sys_warning, sys_state, left_lane_warning, right_lane_warning = process_hud_alert(CC.enabled, self.car_fingerprint,
                                                                                      hud_control)

    if CC.activeHda == 2 and self.speedCameraHapticEndFrame < 0: # 과속카메라 감속시작
      self.speedCameraHapticEndFrame = self.frame + (8.0 / DT_CTRL)  #6초간 켜줌..
    elif CC.activeHda != 2:
      self.speedCameraHapticEndFrame = -1

    if self.frame < self.speedCameraHapticEndFrame and self.hapticFeedbackWhenSpeedCamera>0:
      haptic_stop = (self.speedCameraHapticEndFrame - (5.0/DT_CTRL)) < self.frame < (self.speedCameraHapticEndFrame - (3.0/DT_CTRL))
      if not haptic_stop:
         left_lane_warning = right_lane_warning = self.hapticFeedbackWhenSpeedCamera 
     
    if self.frame % self.blinking_frame == 0:
      self.blinking_signal = True
    elif self.frame % self.blinking_frame == self.blinking_frame / 2:
      self.blinking_signal = False

    jerk = actuators.jerk
    #jerk = accel - self.accel_last
    can_sends = []

    # *** common hyundai stuff ***
    if self.frame % 100 == 0:
      self.jerkStartLimit = float(int(Params().get("JerkStartLimit", encoding="utf8"))) * 0.1
      self.hapticFeedbackWhenSpeedCamera = int(Params().get("HapticFeedbackWhenSpeedCamera", encoding="utf8"))
      self.maxAngleFrames = int(Params().get("MaxAngleFrames", encoding="utf8"))
      self.softHoldMode = int(Params().get("SoftHoldMode", encoding="utf8"))
      self.steerDeltaUp = int(Params().get("SteerDeltaUp", encoding="utf8"))
      self.steerDeltaDown = int(Params().get("SteerDeltaDown", encoding="utf8"))
      if self.angle_steering:
        self.angle_max_gain = min(max(int(Params().get("AngleSteerMaxGain", encoding="utf8") or 100), 30), 100) / 100.
      if self.CP.flags & HyundaiFlags.NON_SCC:
        self.non_scc_speed_buttons = Params().get_bool("CcOnlySpeedButtons")
      if self.CP.carFingerprint in CANFD_CAR:
        # the CAN FD panda safety allows torque rate up 2 / down 3 per frame and at least 89 valid frames
        # (HYUNDAI_CANFD_STEERING_LIMITS); the menu defaults (3 / 7) would make the panda drop every steering message
        self.steerDeltaUp = min(self.steerDeltaUp, 2)
        self.steerDeltaDown = min(self.steerDeltaDown, 3)
        self.maxAngleFrames = max(self.maxAngleFrames, MAX_ANGLE_FRAMES)

    # tester present - w/ no response (keeps relevant ECU disabled)
    if self.frame % 100 == 0 and not (self.CP.flags & HyundaiFlags.CANFD_CAMERA_SCC.value) and self.CP.openpilotLongitudinalControl:
      addr, bus = 0x7d0, 0
      if self.CP.flags & HyundaiFlags.CANFD_HDA2.value:
        addr, bus = 0x730, canfd_bus(self.CP, 1)
      can_sends.append([addr, 0, b"\x02\x3E\x80\x00\x00\x00\x00\x00", bus])

    # >90 degree steering fault prevention
    # Count up to MAX_ANGLE_FRAMES, at which point we need to cut torque to avoid a steering fault
    if CC.latActive and abs(CS.out.steeringAngleDeg) >= MAX_ANGLE:
      self.angle_limit_counter += 1
    else:
      self.angle_limit_counter = 0

    # Cut steer actuation bit for two frames and hold torque with induced temporary fault
    torque_fault = CC.latActive and self.angle_limit_counter > self.maxAngleFrames
    lat_active = CC.latActive and not torque_fault

    if self.angle_limit_counter >= self.maxAngleFrames + MAX_ANGLE_CONSECUTIVE_FRAMES:
      self.angle_limit_counter = 0

    # CAN-FD platforms
    if self.CP.carFingerprint in CANFD_CAR:
      hda2 = self.CP.flags & HyundaiFlags.CANFD_HDA2
      hda2_long = hda2 and self.CP.openpilotLongitudinalControl

      # steering control
      apply_angle = gain = 0.
      if self.angle_steering:
        # the angle the model wants, inside the panda's lateral accel/jerk limits; inactive = the wheel's own angle
        apply_angle = apply_steer_angle_limits(actuators.steeringAngleDeg, self.apply_angle_last, CS.out.vEgoRaw,
                                               CS.out.steeringAngleDeg, CC.latActive)
        apply_angle = round(apply_angle, 1)
        gain = torque_reduction_gain(CS.out.steeringTorque, CS.out.vEgoRaw, CC.latActive, self.angle_gain_last, self.angle_max_gain)
        self.apply_angle_last = apply_angle
        self.angle_gain_last = gain
      can_sends.extend(hyundaicanfd.create_steering_messages(self.packer, self.CP, CC.enabled, lat_active, apply_steer, apply_angle, gain))

      # disable LFA on HDA2
      if self.frame % 5 == 0 and hda2:
        if self.CP.flags & HyundaiFlags.CANFD_HDA2_ALT_STEERING:
          can_sends.append(hyundaicanfd.create_cam_0x362(self.packer, self.CP, CS.cam_0x362))
        else:
          can_sends.append(hyundaicanfd.create_cam_0x2a4(self.packer, self.CP, CS.cam_0x2a4))

      # LFA and HDA icons
      if self.frame % 5 == 0 and (not hda2 or hda2_long):
        can_sends.append(hyundaicanfd.create_lfahda_cluster(self.packer, self.CP, CC.enabled))

      if self.CP.openpilotLongitudinalControl:
        if hda2:
          can_sends.extend(hyundaicanfd.create_adrv_messages(self.packer, self.CP, self.frame))
        if self.frame % 2 == 0:
          can_sends.append(hyundaicanfd.create_acc_control(self.packer, self.CP, CC.enabled, self.accel_last, accel, stopping, CC.cruiseControl.override,
                                                           set_speed_in_units))
          self.accel_last = accel
      else:
        # button presses
        if (self.frame - self.last_button_frame) * DT_CTRL > 0.25:
          # cruise cancel
          if CC.cruiseControl.cancel:
            if self.CP.flags & HyundaiFlags.CANFD_ALT_BUTTONS:
              # HDA2 + alt buttons (Carnival 4th gen): no cancel message the panda allows; the driver's own button cancels
              if not hda2:
                can_sends.append(hyundaicanfd.create_acc_cancel(self.packer, self.CP, CS.cruise_info))
              self.last_button_frame = self.frame
            else:
              for _ in range(20):
                can_sends.append(hyundaicanfd.create_buttons(self.packer, self.CP, CS.buttons_counter+1, Buttons.CANCEL))
              self.last_button_frame = self.frame

          # cruise standstill resume
          elif CC.cruiseControl.resume:
            if self.CP.flags & HyundaiFlags.CANFD_ALT_BUTTONS:
              # TODO: resume for alt button cars
              pass
            else:
              for _ in range(20):
                can_sends.append(hyundaicanfd.create_buttons(self.packer, self.CP, CS.buttons_counter+1, Buttons.RES_ACCEL))
              self.last_button_frame = self.frame
    else:
      # openpilot off and nothing to warn about: the cluster / HUD shows what the stock camera shows (no faint white
      # car + lanes before SCC is set, K7 HEV tester 2026-11-26)
      stock_display = not CC.enabled and not sys_warning and not left_lane_warning and not right_lane_warning
      can_sends.append(hyundaican.create_lkas11(self.packer, self.frame, self.car_fingerprint, self.send_lfa_mfa_lkas, apply_steer, lat_active,
                                                torque_fault, CS.lkas11, sys_warning, sys_state, CC.enabled,
                                                hud_control.leftLaneVisible or CC.enabled, hud_control.rightLaneVisible or CC.enabled,
                                                left_lane_warning, right_lane_warning, stock_display=stock_display))

      if not self.CP.openpilotLongitudinalControl:
        if CC.cruiseControl.cancel:
          can_sends.append(hyundaican.create_clu11(self.packer, self.frame, CS.clu11, Buttons.CANCEL, self.CP.carFingerprint))
        elif CC.cruiseControl.resume:
          if self.CP.carFingerprint in LEGACY_SAFETY_MODE_CAR:            
            if self.resume_wait_timer > 0:
              self.resume_wait_timer -= 1
            else:
              can_sends.append(hyundaican.create_clu11_button(self.packer, self.frame, CS.clu11, Buttons.RES_ACCEL, self.CP.carFingerprint))
              self.resume_cnt += 1
              if self.resume_cnt >= int(randint(4, 5) * 2):
                self.resume_cnt = 0
                self.resume_wait_timer = int(randint(20, 25) * 2)
              
          else:
            # send resume at a max freq of 10Hz
            if (self.frame - self.last_button_frame) * DT_CTRL > 0.1:
              # send 25 messages at a time to increases the likelihood of resume being accepted
              #can_sends.extend([hyundaican.create_clu11(self.packer, self.frame, CS.clu11, Buttons.RES_ACCEL, self.CP.carFingerprint)] * 25)
              can_sends.append(hyundaican.create_clu11_button(self.packer, self.frame, CS.clu11, Buttons.RES_ACCEL, self.CP.carFingerprint))
              self.last_button_frame = self.frame
        else:
          self.resume_wait_timer = 0
          self.resume_cnt = 0
          if CS.out.cruiseState.enabled or not CC.enabled:
            self.res_try_frame = -1
            self.res_hold = False
          target = int(set_speed_in_units+0.5)
          current = int(CS.out.cruiseState.speed*CV.MS_TO_KPH + 0.5)

          #CC.debugTextCC = "BTN:00,T:{:.1f},C:{:.1f},{},{}".format(target, current, self.wait_timer, self.alive_timer)
          if self.CP.flags & HyundaiFlags.NON_SCC and not self.non_scc_speed_buttons:
            pass  # cruise-control-only car: the driver sets the speed unless '크루즈 속도 자동 조절' is on
          elif (self.frame - self.last_button_frame) > self.button_wait:
            if (self.frame - self.button_alive_frame) > self.button_alive:
              self.button_wait = randint(8,15)
              self.last_button_frame = self.frame
            elif CC.enabled and CS.cruise_buttons[-1] == Buttons.NONE:
              if not CS.out.cruiseState.enabled:
                # was: CC.longActive and (hud_control.leadVisible or current > 10.0), current = the car's set speed
                if CC.longActive and self.optech_res_allowed(CS, hud_control.leadVisible):
                  can_sends.append(hyundaican.create_clu11_button(self.packer, self.frame, CS.clu11, Buttons.RES_ACCEL, self.CP.carFingerprint))
                  CC.debugTextCC = "BTN:++,T:{:.1f},C:{:.1f}".format(target, current)
                #elif CC.longActive:
                #  can_sends.append(hyundaican.create_clu11_button(self.packer, self.frame, CS.clu11, Buttons.SET_DECEL, self.CP.carFingerprint))
                #  CC.debugTextCC = "BTN:--,T:{:.1f},C:{:.1f}".format(target, current)
                #elif CS.out.cruiseGap != hud_control.cruiseGap:
                #  can_sends.append(hyundaican.create_clu11_button(self.packer, self.frame, CS.clu11, Buttons.GAP_DIST, self.CP.carFingerprint))
                #  #print("currentGap = {}, target = {}".format(CS.out.cruiseGap, hud_control.cruiseGap))
              elif CS.out.cruiseGap != hud_control.cruiseGap:
                can_sends.append(hyundaican.create_clu11_button(self.packer, self.frame, CS.clu11, Buttons.GAP_DIST, self.CP.carFingerprint))
                CC.debugTextCC = "currentGap = {}, target = {}".format(CS.out.cruiseGap, hud_control.cruiseGap)
              elif target < current and current>= 31:
                can_sends.append(hyundaican.create_clu11_button(self.packer, self.frame, CS.clu11, Buttons.SET_DECEL, self.CP.carFingerprint))
                CC.debugTextCC = "BTN:--,T:{:.1f},C:{:.1f}".format(target, current)
              elif target > current and current < 160:
                can_sends.append(hyundaican.create_clu11_button(self.packer, self.frame, CS.clu11, Buttons.RES_ACCEL, self.CP.carFingerprint))
                CC.debugTextCC = "BTN:++,T:{:.1f},C:{:.1f}".format(target, current)
          else:
            self.button_alive = randint(4, 8) #randint(12, 18)
            self.button_alive_frame = self.frame

      #CC.debugTextCC = "230206"

      # K7 2020 also needs MDPS12 feedback toward the camera, or LKAS/FCA faults appear while openpilot steers (carrot-wip fix)
      if self.CP.carFingerprint in (CAR.GENESIS_G90_2019, CAR.GENESIS_G90, CAR.K7, CAR.K7_PE):
        can_sends.append(hyundaican.create_mdps12(self.packer, self.frame, CS.mdps12))

      if self.frame % 2 == 0 and self.CP.openpilotLongitudinalControl:
        # TODO: unclear if this is needed
        startingJerk = self.jerkStartLimit
        jerkLimit = 5.0
        self.jerk_count += DT_CTRL
        jerk_max = interp(self.jerk_count, [0, 1.5, 2.5], [startingJerk, startingJerk, jerkLimit])
        a_error = accel - CS.out.aEgo
        v_error = actuators.speed - CS.out.vEgo
        cb_upper = cb_lower = 0
        if actuators.longControlState == LongCtrlState.off:
          jerk_u = jerkLimit
          jerk_l = jerkLimit          
          self.jerk_count = 0
        elif actuators.longControlState == LongCtrlState.stopping or hud_control.softHold:
          jerk_u = 0.5
          jerk_l = jerkLimit
          self.jerk_count = 0
        else:
          jerk_u = min(max(0.5, jerk * 2.0), jerk_max)
          jerk_l = min(max(1.0, -jerk * 2.0), jerk_max)
          cb_upper = clip(0.9 + accel * 0.2, 0, 1.2)
          cb_lower = clip(0.8 + accel * 0.2, 0, 1.2)

        can_sends.extend(hyundaican.create_acc_commands_mix_scc(self.CP, self.packer, CC.enabled, accel, jerk_u, jerk_l, int(self.frame / 2),
                                                      hud_control, set_speed_in_units, stopping, CC, CS, self.softHoldMode, cb_upper, cb_lower))
        self.accel_last = accel

      # 20 Hz LFA MFA message
      if self.frame % 5 == 0 and self.CP.flags & HyundaiFlags.SEND_LFA.value:
        # the HDA icon / 'AUTO' set speed blinks while slowing for a speed camera; not while stopped (tester 2026-11-26:
        # at a red light 41 m before a 70 camera the cluster kept blinking 80 at 0 km/h), steady green then
        blink = self.blinking_signal and CS.out.vEgo > OPTECH_STOPPED_MS
        can_sends.append(hyundaican.create_lfahda_mfc(self.packer, CC, blink))

      # 5 Hz ACC options
      if self.frame % 20 == 0 and self.CP.openpilotLongitudinalControl: 
        if self.CP.sccBus == 0:
          can_sends.extend(hyundaican.create_acc_opt(self.CP, CS, self.packer))
        elif CS.scc13 is not None:
          can_sends.append(hyundaican.create_acc_opt_copy(self.CP, CS, self.packer))

      # 2 Hz front radar options
      if self.frame % 50 == 0 and self.CP.openpilotLongitudinalControl  and self.CP.sccBus == 0:
        can_sends.append(hyundaican.create_frt_radar_opt(self.packer))

    new_actuators = actuators.copy()
    new_actuators.steer = apply_steer / self.params.STEER_MAX
    new_actuators.accel = accel

    try:
      CC.debugTextCC = self.drive_record_text(CS, can_sends)
    except Exception:  # noqa: BLE001  (the drive record must never stop the car's messages)
      pass

    self.frame += 1
    return new_actuators, can_sends
