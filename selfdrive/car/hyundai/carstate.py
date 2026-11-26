from collections import deque
import copy
import math

from cereal import car
from openpilot.common.conversions import Conversions as CV
from opendbc.can.parser import CANParser
from opendbc.can.can_define import CANDefine
from openpilot.selfdrive.car.hyundai.hyundaicanfd import CanBus
from openpilot.selfdrive.car.hyundai.values import HyundaiFlags, CAR, DBC, CAN_GEARS, CAMERA_SCC_CAR, \
                                                   CANFD_CAR, EV_CAR, HYBRID_CAR, Buttons, CarControllerParams
from openpilot.selfdrive.car.hyundai.values import is_camera_scc, CAMERA_SCC_PARAM
from openpilot.common.params import put_bool_nonblocking
from openpilot.selfdrive.car.interfaces import CarStateBase
from openpilot.selfdrive.car.hyundai import pedal as hkg_pedal

PREV_BUTTON_SAMPLES = 8
CLUSTER_SAMPLE_RATE = 20  # frames
STANDSTILL_THRESHOLD = 12 * 0.03125 * CV.KPH_TO_MS

# optech (optech-hkg, Neokii / PolorBear): the Nexo sends its gear as one 16 bit value (ELECT_GEAR Elect_Gear_Shifter_NEXO)
GearShifter = car.CarState.GearShifter
NEXO_GEARS = {1546: GearShifter.drive, 2314: GearShifter.neutral, 2566: GearShifter.reverse, 2569: GearShifter.park}


def non_scc_cruise_signals(CP):
  """optech: cars without SCC (StarPilot get_non_scc_cruise_signals): the regular cruise control's
  (available msg, sig, engaged msg, sig, set speed msg, sig)"""
  if CP.carFingerprint == CAR.KIA_RAY_EV:
    return "LABEL11", "CC_React", "LABEL11", "CC_Engaged", "E_EMS11", "Cruise_Limit_Target"
  if CP.carFingerprint in EV_CAR:
    return "LABEL11", "CC_React", "EMS12", "ACC_ACT", "E_EMS11", "Cruise_Limit_Target"
  if CP.carFingerprint in HYBRID_CAR:
    return "E_CRUISE_CONTROL", "CRUISE_LAMP_M", "E_CRUISE_CONTROL", "CRUISE_LAMP_S", "ELECT_GEAR", "SLC_SET_SPEED"
  return "EMS16", "CRUISE_LAMP_M", "EMS16", "CRUISE_LAMP_S", "LVR12", "CF_Lvr_CruiseSet"


class CarState(CarStateBase):
  def __init__(self, CP):
    super().__init__(CP)
    self.camera_scc = is_camera_scc(CP)
    self.scc_wrong_frames = 0
    self.scc_bus_changed = False
    self.nexo_gear = GearShifter.unknown
    self.tpms = [0., 0., 0., 0.]  # optech 주행 화면 (psi; controlsd puts it in controlsStateExt)
    can_define = CANDefine(DBC[CP.carFingerprint]["pt"])

    self.cruise_buttons = deque([Buttons.NONE] * PREV_BUTTON_SAMPLES, maxlen=PREV_BUTTON_SAMPLES)
    self.main_buttons = deque([Buttons.NONE] * PREV_BUTTON_SAMPLES, maxlen=PREV_BUTTON_SAMPLES)

    self.gear_msg_canfd = "GEAR_ALT" if CP.flags & HyundaiFlags.CANFD_ALT_GEARS else \
                          "GEAR_ALT_2" if CP.flags & HyundaiFlags.CANFD_ALT_GEARS_2 else \
                          "GEAR_SHIFTER"
    if CP.carFingerprint in CANFD_CAR:
      self.shifter_values = can_define.dv[self.gear_msg_canfd]["GEAR"]
    elif self.CP.carFingerprint in CAN_GEARS["use_cluster_gears"]:
      self.shifter_values = can_define.dv["CLU15"]["CF_Clu_Gear"]
    elif self.CP.carFingerprint in CAN_GEARS["use_tcu_gears"]:
      self.shifter_values = can_define.dv["TCU12"]["CUR_GR"]
    else:  # preferred and elect gear methods use same definition
      self.shifter_values = can_define.dv["LVR12"]["CF_Lvr_Gear"]

    self.accelerator_msg_canfd = "ACCELERATOR" if CP.carFingerprint in EV_CAR else \
                                 "ACCELERATOR_ALT" if CP.carFingerprint in HYBRID_CAR else \
                                 "ACCELERATOR_BRAKE_ALT"
    self.cruise_btns_msg_canfd = "CRUISE_BUTTONS_ALT" if CP.flags & HyundaiFlags.CANFD_ALT_BUTTONS else \
                                 "CRUISE_BUTTONS"
    self.is_metric = False
    self.buttons_counter = 0

    self.cruise_info = {}

    # On some cars, CLU15->CF_Clu_VehicleSpeed can oscillate faster than the dash updates. Sample at 5 Hz
    self.cluster_speed = 0
    self.cluster_speed_counter = CLUSTER_SAMPLE_RATE

    self.params = CarControllerParams(CP)
    self.pedal_valid = False  # optech: comma pedal (cars without SCC)
    self.pedal_state = 5

  # optech: where does the SCC really come from? While fingerprinting (relay open) both buses show it, so this is
  # checked on the road: SCC11 fresh on one side only for 3 s -> remember it for the next start (the panda's safety
  # mode is set at start). scc_bus_changed asks for a restart (alert in interface).
  def check_scc_bus(self, cp, cp_cam):
    if self.CP.carFingerprint in CANFD_CAR or self.CP.openpilotLongitudinalControl or self.CP.carFingerprint in CAMERA_SCC_CAR or \
       self.CP.flags & HyundaiFlags.NON_SCC:
      return
    now = cp.ts_nanos["WHL_SPD11"]["WHL_SPD_FL"]
    expected, other = (cp_cam, cp) if self.camera_scc else (cp, cp_cam)
    exp_age = now - expected.ts_nanos["SCC11"]["MainMode_ACC"]
    oth_age = now - other.ts_nanos["SCC11"]["MainMode_ACC"]
    wrong_side = now > 0 and exp_age > 1e9 and oth_age < 2e8
    self.scc_wrong_frames = self.scc_wrong_frames + 1 if wrong_side else 0
    if self.scc_wrong_frames == 300 and not self.scc_bus_changed:  # 3 s at 100 Hz
      self.scc_bus_changed = True
      put_bool_nonblocking(CAMERA_SCC_PARAM, not self.camera_scc)

  def update(self, cp, cp_cam):
    if self.CP.carFingerprint in CANFD_CAR:
      return self.update_canfd(cp, cp_cam)

    ret = car.CarState.new_message()
    cp_cruise = cp_cam if self.camera_scc else cp
    self.check_scc_bus(cp, cp_cam)
    self.is_metric = cp.vl["CLU11"]["CF_Clu_SPEED_UNIT"] == 0
    speed_conv = CV.KPH_TO_MS if self.is_metric else CV.MPH_TO_MS

    ret.doorOpen = any([cp.vl["CGW1"]["CF_Gway_DrvDrSw"], cp.vl["CGW1"]["CF_Gway_AstDrSw"],
                        cp.vl["CGW2"]["CF_Gway_RLDrSw"], cp.vl["CGW2"]["CF_Gway_RRDrSw"]])

    ret.seatbeltUnlatched = cp.vl["CGW1"]["CF_Gway_DrvSeatBeltSw"] == 0

    ret.wheelSpeeds = self.get_wheel_speeds(
      cp.vl["WHL_SPD11"]["WHL_SPD_FL"],
      cp.vl["WHL_SPD11"]["WHL_SPD_FR"],
      cp.vl["WHL_SPD11"]["WHL_SPD_RL"],
      cp.vl["WHL_SPD11"]["WHL_SPD_RR"],
    )
    ret.vEgoRaw = (ret.wheelSpeeds.fl + ret.wheelSpeeds.fr + ret.wheelSpeeds.rl + ret.wheelSpeeds.rr) / 4.
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)
    ret.standstill = ret.wheelSpeeds.fl <= STANDSTILL_THRESHOLD and ret.wheelSpeeds.rr <= STANDSTILL_THRESHOLD

    self.cluster_speed_counter += 1
    if self.cluster_speed_counter > CLUSTER_SAMPLE_RATE:
      self.cluster_speed = cp.vl["CLU15"]["CF_Clu_VehicleSpeed"]
      self.cluster_speed_counter = 0

      # Mimic how dash converts to imperial.
      # Sorento is the only platform where CF_Clu_VehicleSpeed is already imperial when not is_metric
      # TODO: CGW_USM1->CF_Gway_DrLockSoundRValue may describe this
      if not self.is_metric and self.CP.carFingerprint not in (CAR.KIA_SORENTO,):
        self.cluster_speed = math.floor(self.cluster_speed * CV.KPH_TO_MPH + CV.KPH_TO_MPH)

    ret.vEgoCluster = self.cluster_speed * speed_conv

    ret.steeringAngleDeg = cp.vl["SAS11"]["SAS_Angle"]
    ret.steeringRateDeg = cp.vl["SAS11"]["SAS_Speed"]
    ret.yawRate = cp.vl["ESP12"]["YAW_RATE"]
    ret.leftBlinker, ret.rightBlinker = self.update_blinker_from_lamp(
      50, cp.vl["CGW1"]["CF_Gway_TurnSigLh"], cp.vl["CGW1"]["CF_Gway_TurnSigRh"])
    ret.steeringTorque = cp.vl["MDPS12"]["CR_Mdps_StrColTq"]
    ret.steeringTorqueEps = cp.vl["MDPS12"]["CR_Mdps_OutTq"]
    ret.steeringPressed = self.update_steering_pressed(abs(ret.steeringTorque) > self.params.STEER_THRESHOLD, 5)
    ret.steerFaultTemporary = cp.vl["MDPS12"]["CF_Mdps_ToiUnavail"] != 0 or cp.vl["MDPS12"]["CF_Mdps_ToiFlt"] != 0

    # cruise state
    if self.CP.flags & HyundaiFlags.NON_SCC:
      # optech: no SCC: the car's regular cruise control (StarPilot get_non_scc_cruise_signals). With a comma pedal
      # openpilot cancels it while engaged and keeps its own state from the buttons
      avail_msg, avail_sig, on_msg, on_sig, speed_msg, speed_sig = non_scc_cruise_signals(self.CP)
      ret.cruiseState.available = cp.vl[avail_msg][avail_sig] != 0
      ret.cruiseState.enabled = cp.vl[on_msg][on_sig] != 0
      ret.cruiseState.standstill = False
      ret.cruiseState.speed = cp.vl[speed_msg][speed_sig] * speed_conv
    elif self.CP.openpilotLongitudinalControl:
      # These are not used for engage/disengage since openpilot keeps track of state using the buttons
      ret.cruiseState.available = cp.vl["TCS13"]["ACCEnable"] == 0
      ret.cruiseState.enabled = cp.vl["TCS13"]["ACC_REQ"] == 1
      ret.cruiseState.standstill = False
      ret.cruiseState.nonAdaptive = False
    else:
      ret.cruiseState.available = cp_cruise.vl["SCC11"]["MainMode_ACC"] == 1
      ret.cruiseState.enabled = cp_cruise.vl["SCC12"]["ACCMode"] != 0
      ret.cruiseState.standstill = cp_cruise.vl["SCC11"]["SCCInfoDisplay"] == 4.
      ret.cruiseState.nonAdaptive = cp_cruise.vl["SCC11"]["SCCInfoDisplay"] == 2.  # Shows 'Cruise Control' on dash
      ret.cruiseState.speed = cp_cruise.vl["SCC11"]["VSetDis"] * speed_conv

    # TODO: Find brake pressure
    ret.brake = 0
    ret.brakePressed = cp.vl["TCS13"]["DriverOverride"] == 2  # 2 includes regen braking by user on HEV/EV
    ret.brakeHoldActive = cp.vl["TCS15"]["AVH_LAMP"] == 2  # 0 OFF, 1 ERROR, 2 ACTIVE, 3 READY
    ret.parkingBrake = cp.vl["TCS13"]["PBRAKE_ACT"] == 1
    ret.accFaulted = cp.vl["TCS13"]["ACCEnable"] != 0  # 0 ACC CONTROL ENABLED, 1-3 ACC CONTROL DISABLED
    if self.CP.flags & HyundaiFlags.NON_SCC:
      ret.accFaulted = False  # ACCEnable means nothing without SCC
    if self.CP.flags & HyundaiFlags.NON_SCC_NO_TCS:
      ret.brakePressed = cp.vl["E_EMS11"]["Brake_Pedal_Pos"] > 0  # no TCS13 (Porter II EV, carrot)
      ret.parkingBrake = False

    if self.CP.carFingerprint in (HYBRID_CAR | EV_CAR):
      if self.CP.carFingerprint in HYBRID_CAR:
        ret.gas = cp.vl["E_EMS11"]["CR_Vcu_AccPedDep_Pos"] / 254.
      else:
        ret.gas = cp.vl["E_EMS11"]["Accel_Pedal_Pos"] / 254.
      ret.gasPressed = ret.gas > 0
      if self.CP.flags & HyundaiFlags.NON_SCC_PEDAL:
        # the pedal box sits between the pedal and the car: the car's pedal signal is openpilot's command, the
        # driver's own pedal is in GAS_SENSOR
        cp_pedal = getattr(self, "cp_pedal", None)
        self.pedal_valid = cp_pedal is not None and cp_pedal.can_valid
        self.pedal_state = int(cp_pedal.vl["GAS_SENSOR"]["STATE"]) if cp_pedal is not None else 5
        ret.accFaulted = not self.pedal_valid or self.pedal_state != 0
        if cp_pedal is not None:
          ret.gasPressed = hkg_pedal.driver_pressed(cp_pedal.vl["GAS_SENSOR"]["INTERCEPTOR_GAS"],
                                                    cp_pedal.vl["GAS_SENSOR"]["INTERCEPTOR_GAS2"])
    else:
      ret.gas = cp.vl["EMS12"]["PV_AV_CAN"] / 100.
      ret.gasPressed = bool(cp.vl["EMS16"]["CF_Ems_AclAct"])

    # Gear Selection via Cluster - For those Kia/Hyundai which are not fully discovered, we can use the Cluster Indicator for Gear Selection,
    # as this seems to be standard over all cars, but is not the preferred method.
    if self.CP.carFingerprint in (HYBRID_CAR | EV_CAR):
      gear = cp.vl["ELECT_GEAR"]["Elect_Gear_Shifter"]
    elif self.CP.carFingerprint in CAN_GEARS["use_cluster_gears"]:
      gear = cp.vl["CLU15"]["CF_Clu_Gear"]
    elif self.CP.carFingerprint in CAN_GEARS["use_tcu_gears"]:
      gear = cp.vl["TCU12"]["CUR_GR"]
    else:
      gear = cp.vl["LVR12"]["CF_Lvr_Gear"]

    if self.CP.carFingerprint == CAR.NEXO:
      # unknown values keep the last known gear (optech-hkg)
      self.nexo_gear = NEXO_GEARS.get(int(cp.vl["ELECT_GEAR"]["Elect_Gear_Shifter_NEXO"]), self.nexo_gear)
      ret.gearShifter = self.nexo_gear
    else:
      ret.gearShifter = self.parse_gear_shifter(self.shifter_values.get(gear))

    if not self.CP.openpilotLongitudinalControl and not self.CP.flags & HyundaiFlags.NON_SCC:
      aeb_src = "FCA11" if self.CP.flags & HyundaiFlags.USE_FCA.value else "SCC12"
      aeb_sig = "FCA_CmdAct" if self.CP.flags & HyundaiFlags.USE_FCA.value else "AEB_CmdAct"
      aeb_warning = cp_cruise.vl[aeb_src]["CF_VSM_Warn"] != 0
      scc_warning = cp_cruise.vl["SCC12"]["TakeOverReq"] == 1  # sometimes only SCC system shows an FCW
      aeb_braking = cp_cruise.vl[aeb_src]["CF_VSM_DecCmdAct"] != 0 or cp_cruise.vl[aeb_src][aeb_sig] != 0
      ret.stockFcw = (aeb_warning or scc_warning) and not aeb_braking
      ret.stockAeb = aeb_warning and aeb_braking

    if self.CP.enableBsm:
      ret.leftBlindspot = cp.vl["LCA11"]["CF_Lca_IndLeft"] != 0
      ret.rightBlindspot = cp.vl["LCA11"]["CF_Lca_IndRight"] != 0

    # optech 주행 화면 '타이어 공기압' (optech-hkg): psi; UNIT > 0 means the car sends kPa-ish steps (x 0.725)
    tpms_unit = cp.vl["TPMS11"]["UNIT"] * 0.725 if int(cp.vl["TPMS11"]["UNIT"]) > 0 else 1.
    self.tpms = [tpms_unit * cp.vl["TPMS11"][s] for s in ("PRESSURE_FL", "PRESSURE_FR", "PRESSURE_RL", "PRESSURE_RR")]

    # save the entire LKAS11 and CLU11
    self.lkas11 = copy.copy(cp_cam.vl["LKAS11"])
    self.clu11 = copy.copy(cp.vl["CLU11"])
    self.steer_state = cp.vl["MDPS12"]["CF_Mdps_ToiActive"]  # 0 NOT ACTIVE, 1 ACTIVE
    self.prev_cruise_buttons = self.cruise_buttons[-1]
    self.cruise_buttons.extend(cp.vl_all["CLU11"]["CF_Clu_CruiseSwState"])
    self.main_buttons.extend(cp.vl_all["CLU11"]["CF_Clu_CruiseSwMain"])

    return ret

  def update_canfd(self, cp, cp_cam):
    ret = car.CarState.new_message()

    self.is_metric = cp.vl["CRUISE_BUTTONS_ALT"]["DISTANCE_UNIT"] != 1
    speed_factor = CV.KPH_TO_MS if self.is_metric else CV.MPH_TO_MS

    if self.CP.carFingerprint in (EV_CAR | HYBRID_CAR):
      offset = 255. if self.CP.carFingerprint in EV_CAR else 1023.
      ret.gas = cp.vl[self.accelerator_msg_canfd]["ACCELERATOR_PEDAL"] / offset
      ret.gasPressed = ret.gas > 1e-5
    else:
      ret.gasPressed = bool(cp.vl[self.accelerator_msg_canfd]["ACCELERATOR_PEDAL_PRESSED"])

    ret.brakePressed = cp.vl["TCS"]["DriverBraking"] == 1

    ret.doorOpen = cp.vl["DOORS_SEATBELTS"]["DRIVER_DOOR"] == 1
    ret.seatbeltUnlatched = cp.vl["DOORS_SEATBELTS"]["DRIVER_SEATBELT"] == 0

    gear = cp.vl[self.gear_msg_canfd]["GEAR"]
    ret.gearShifter = self.parse_gear_shifter(self.shifter_values.get(gear))

    # TODO: figure out positions
    ret.wheelSpeeds = self.get_wheel_speeds(
      cp.vl["WHEEL_SPEEDS"]["WHEEL_SPEED_1"],
      cp.vl["WHEEL_SPEEDS"]["WHEEL_SPEED_2"],
      cp.vl["WHEEL_SPEEDS"]["WHEEL_SPEED_3"],
      cp.vl["WHEEL_SPEEDS"]["WHEEL_SPEED_4"],
    )
    ret.vEgoRaw = (ret.wheelSpeeds.fl + ret.wheelSpeeds.fr + ret.wheelSpeeds.rl + ret.wheelSpeeds.rr) / 4.
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)
    ret.standstill = ret.wheelSpeeds.fl <= STANDSTILL_THRESHOLD and ret.wheelSpeeds.rr <= STANDSTILL_THRESHOLD

    ret.steeringRateDeg = cp.vl["STEERING_SENSORS"]["STEERING_RATE"]
    ret.steeringAngleDeg = cp.vl["STEERING_SENSORS"]["STEERING_ANGLE"] * -1
    ret.steeringTorque = cp.vl["MDPS"]["STEERING_COL_TORQUE"]
    ret.steeringTorqueEps = cp.vl["MDPS"]["STEERING_OUT_TORQUE"]
    ret.steeringPressed = self.update_steering_pressed(abs(ret.steeringTorque) > self.params.STEER_THRESHOLD, 5)
    ret.steerFaultTemporary = cp.vl["MDPS"]["LKA_FAULT"] != 0

    # TODO: alt signal usage may be described by cp.vl['BLINKERS']['USE_ALT_LAMP']
    left_blinker_sig, right_blinker_sig = "LEFT_LAMP", "RIGHT_LAMP"
    if self.CP.carFingerprint == CAR.KONA_EV_2ND_GEN:
      left_blinker_sig, right_blinker_sig = "LEFT_LAMP_ALT", "RIGHT_LAMP_ALT"
    ret.leftBlinker, ret.rightBlinker = self.update_blinker_from_lamp(50, cp.vl["BLINKERS"][left_blinker_sig],
                                                                      cp.vl["BLINKERS"][right_blinker_sig])
    if self.CP.enableBsm:
      ret.leftBlindspot = cp.vl["BLINDSPOTS_REAR_CORNERS"]["FL_INDICATOR"] != 0
      ret.rightBlindspot = cp.vl["BLINDSPOTS_REAR_CORNERS"]["FR_INDICATOR"] != 0

    # cruise state
    # CAN FD cars enable on main button press, set available if no TCS faults preventing engagement
    ret.cruiseState.available = cp.vl["TCS"]["ACCEnable"] == 0
    if self.CP.openpilotLongitudinalControl:
      # These are not used for engage/disengage since openpilot keeps track of state using the buttons
      ret.cruiseState.enabled = cp.vl["TCS"]["ACC_REQ"] == 1
      ret.cruiseState.standstill = False
    else:
      cp_cruise_info = cp_cam if self.CP.flags & HyundaiFlags.CANFD_CAMERA_SCC else cp
      ret.cruiseState.enabled = cp_cruise_info.vl["SCC_CONTROL"]["ACCMode"] in (1, 2)
      ret.cruiseState.standstill = cp_cruise_info.vl["SCC_CONTROL"]["CRUISE_STANDSTILL"] == 1
      ret.cruiseState.speed = cp_cruise_info.vl["SCC_CONTROL"]["VSetDis"] * speed_factor
      self.cruise_info = copy.copy(cp_cruise_info.vl["SCC_CONTROL"])

    # Manual Speed Limit Assist is a feature that replaces non-adaptive cruise control on EV CAN FD platforms.
    # It limits the vehicle speed, overridable by pressing the accelerator past a certain point.
    # The car will brake, but does not respect positive acceleration commands in this mode
    # TODO: find this message on ICE & HYBRID cars + cruise control signals (if exists)
    if self.CP.carFingerprint in EV_CAR:
      ret.cruiseState.nonAdaptive = cp.vl["MANUAL_SPEED_LIMIT_ASSIST"]["MSLA_ENABLED"] == 1

    self.prev_cruise_buttons = self.cruise_buttons[-1]
    self.cruise_buttons.extend(cp.vl_all[self.cruise_btns_msg_canfd]["CRUISE_BUTTONS"])
    self.main_buttons.extend(cp.vl_all[self.cruise_btns_msg_canfd]["ADAPTIVE_CRUISE_MAIN_BTN"])
    self.buttons_counter = cp.vl[self.cruise_btns_msg_canfd]["COUNTER"]
    ret.accFaulted = cp.vl["TCS"]["ACCEnable"] != 0  # 0 ACC CONTROL ENABLED, 1-3 ACC CONTROL DISABLED

    if self.CP.flags & HyundaiFlags.CANFD_HDA2:
      self.hda2_lfa_block_msg = copy.copy(cp_cam.vl["CAM_0x362"] if self.CP.flags & HyundaiFlags.CANFD_HDA2_ALT_STEERING
                                          else cp_cam.vl["CAM_0x2a4"])

    return ret

  def get_can_parser(self, CP):
    if CP.carFingerprint in CANFD_CAR:
      return self.get_can_parser_canfd(CP)

    messages = [
      # address, frequency
      ("MDPS12", 50),
      ("TCS13", 50),
      ("TCS15", 10),
      ("CLU11", 50),
      ("CLU15", 5),
      ("ESP12", 100),
      ("CGW1", 10),
      ("CGW2", 5),
      ("CGW4", 5),
      ("WHL_SPD11", 50),
      ("SAS11", 100),
      ("TPMS11", 0),  # optech 주행 화면 '타이어 공기압': not checked (cars without it stay valid)
    ]

    if CP.flags & HyundaiFlags.NON_SCC:
      # optech: no SCC; messages a cruise-control-only car may not have are read when present (optech-hkg)
      optional = ("TCS15", "CLU15", "CGW2", "CGW4") + (("TCS13",) if CP.flags & HyundaiFlags.NON_SCC_NO_TCS else ())
      messages = [(m, 0) if m in optional else (m, f) for m, f in messages]
    elif not CP.openpilotLongitudinalControl and not is_camera_scc(CP):
      messages += [
        ("SCC11", 50),
        ("SCC12", 50),
      ]
      if CP.flags & HyundaiFlags.USE_FCA.value:
        messages.append(("FCA11", 50))
    elif not CP.openpilotLongitudinalControl:
      messages.append(("SCC11", 0))  # optech: only to notice the SCC moving back to this side (check_scc_bus)

    if CP.enableBsm:
      messages.append(("LCA11", 50))

    if CP.carFingerprint in (HYBRID_CAR | EV_CAR):
      messages.append(("E_EMS11", 50))
    else:
      messages += [
        ("EMS12", 100),
        ("EMS16", 100),
      ]

    if CP.carFingerprint in (HYBRID_CAR | EV_CAR):
      messages.append(("ELECT_GEAR", 20))
    elif CP.carFingerprint in CAN_GEARS["use_cluster_gears"]:
      pass
    elif CP.carFingerprint in CAN_GEARS["use_tcu_gears"]:
      messages.append(("TCU12", 100))
    else:
      messages.append(("LVR12", 100))

    if CP.flags & HyundaiFlags.NON_SCC:  # optech: the regular cruise control's messages
      avail_msg, _, on_msg, _, speed_msg, _ = non_scc_cruise_signals(CP)
      for m in (avail_msg, on_msg, speed_msg):
        if m not in [x[0] for x in messages]:
          messages.append((m, 10))

    return CANParser(DBC[CP.carFingerprint]["pt"], messages, 0)

  @staticmethod
  def get_body_can_parser(CP):
    # optech: the comma pedal's GAS_SENSOR on the cars without SCC (menu switch on and the pedal seen at the start)
    if CP.flags & HyundaiFlags.NON_SCC_PEDAL:
      return CANParser(hkg_pedal.PEDAL_DBC[CP.carFingerprint], [("GAS_SENSOR", 50)], 0)
    return None

  @staticmethod
  def get_cam_can_parser(CP):
    if CP.carFingerprint in CANFD_CAR:
      return CarState.get_cam_can_parser_canfd(CP)

    messages = [
      ("LKAS11", 100)
    ]

    if CP.flags & HyundaiFlags.NON_SCC:
      pass  # optech: no SCC on either side
    elif not CP.openpilotLongitudinalControl and is_camera_scc(CP):
      messages += [
        ("SCC11", 50),
        ("SCC12", 50),
      ]

      if CP.flags & HyundaiFlags.USE_FCA.value:
        messages.append(("FCA11", 50))
    elif not CP.openpilotLongitudinalControl:
      messages.append(("SCC11", 0))  # optech: only to notice an SCC on the camera side (check_scc_bus)

    return CANParser(DBC[CP.carFingerprint]["pt"], messages, 2)

  def get_can_parser_canfd(self, CP):
    messages = [
      (self.gear_msg_canfd, 100),
      (self.accelerator_msg_canfd, 100),
      ("WHEEL_SPEEDS", 100),
      ("STEERING_SENSORS", 100),
      ("MDPS", 100),
      ("TCS", 50),
      ("CRUISE_BUTTONS_ALT", 50),
      ("BLINKERS", 4),
      ("DOORS_SEATBELTS", 4),
    ]

    if CP.carFingerprint in EV_CAR:
      messages += [
        ("MANUAL_SPEED_LIMIT_ASSIST", 10),
      ]

    if not (CP.flags & HyundaiFlags.CANFD_ALT_BUTTONS):
      messages += [
        ("CRUISE_BUTTONS", 50)
      ]

    if CP.enableBsm:
      messages += [
        ("BLINDSPOTS_REAR_CORNERS", 20),
      ]

    if not (CP.flags & HyundaiFlags.CANFD_CAMERA_SCC.value) and not CP.openpilotLongitudinalControl:
      messages += [
        ("SCC_CONTROL", 50),
      ]

    return CANParser(DBC[CP.carFingerprint]["pt"], messages, CanBus(CP).ECAN)

  @staticmethod
  def get_cam_can_parser_canfd(CP):
    messages = []
    if CP.flags & HyundaiFlags.CANFD_HDA2:
      block_lfa_msg = "CAM_0x362" if CP.flags & HyundaiFlags.CANFD_HDA2_ALT_STEERING else "CAM_0x2a4"
      messages += [(block_lfa_msg, 20)]
    elif CP.flags & HyundaiFlags.CANFD_CAMERA_SCC:
      messages += [
        ("SCC_CONTROL", 50),
      ]

    return CANParser(DBC[CP.carFingerprint]["pt"], messages, CanBus(CP).CAM)
