from common.numpy_fast import clip
from selfdrive.car.hyundai.values import HyundaiFlags, canfd_bus


def get_e_can_bus(CP):
  # On the CAN-FD platforms, the LKAS camera is on both A-CAN and E-CAN. HDA2 cars
  # have a different harness than the HDA1 and non-HDA variants in order to split
  # a different bus, since the steering is done by different ECUs.
  return canfd_bus(CP, 1 if CP.flags & HyundaiFlags.CANFD_HDA2 else 0)


ANGLE_VALUES = ("LKAS_ANGLE_ACTIVE", "ADAS_StrAnglReqVal", "ADAS_ACIAnglTqRedcGainVal")


def _angle(lat_active, apply_angle, gain):
  # LKAS_ANGLE_ACTIVE 2 = steering by angle, 1 = available; the gain must be 0 while not steering (panda checks it)
  return {
    "LKAS_ANGLE_ACTIVE": 2 if lat_active else 1,
    "ADAS_StrAnglReqVal": apply_angle,
    "ADAS_ACIAnglTqRedcGainVal": gain if lat_active else 0.0,
  }


def create_steering_messages(packer, CP, enabled, lat_active, apply_steer, apply_angle=0., angle_gain=0.):

  ret = []
  if CP.flags & HyundaiFlags.CANFD_ANGLE_STEERING:
    return create_angle_steering_messages(packer, CP, enabled, lat_active, apply_angle, angle_gain)

  values = {
    "LKA_MODE": 2,
    "LKA_ICON": 2 if enabled else 1,
    "TORQUE_REQUEST": apply_steer,
    "LKA_ASSIST": 0,
    "STEER_REQ": 1 if lat_active else 0,
    "STEER_MODE": 0,
    "SET_ME_1": 0,
    "NEW_SIGNAL_1": 0,
    "NEW_SIGNAL_2": 0,
  }

  if CP.flags & HyundaiFlags.CANFD_HDA2:
    if CP.openpilotLongitudinalControl:
      ret.append(packer.make_can_msg("LFA", canfd_bus(CP, 1), values))
    if CP.flags & HyundaiFlags.CANFD_HDA2_ALT_STEERING:
      # LKAS_ALT (0x110) has its own layout; torque/request bits sit where LKAS has them (carrot-wip values)
      alt = {
        "LKA_MODE": 2,
        "LKA_ICON": 2 if enabled else 1,
        "TORQUE_REQUEST": apply_steer,
        "DampingGain": 100,
        "STEER_REQ": 1 if lat_active else 0,
        "HAS_LANE_SAFETY": 0,
        "VALUE63": 0,
        "VALUE64": 100,
      }
      ret.append(packer.make_can_msg("LKAS_ALT", canfd_bus(CP, 0), alt))
    else:
      ret.append(packer.make_can_msg("LKAS", canfd_bus(CP, 0), values))
  else:
    ret.append(packer.make_can_msg("LFA", canfd_bus(CP, 0), values))

  return ret

def create_angle_steering_messages(packer, CP, enabled, lat_active, apply_angle, gain):
  """LFA2 cars (StarPilot / sunnypilot hkg-angle-steering-2025): torque request and its bit stay 0, the wheel angle and the
  torque reduction gain carry the command. HDA2: LKAS or LKAS_ALT on the camera side; HDA1: in LFA, or plain LFA plus
  ADAS_CMD_35_10ms (0xCB) when the camera sends that message."""
  base = {
    "LKA_MODE": 2,
    "LKA_ICON": 2 if enabled else 1,
    "TORQUE_REQUEST": 0,
    "STEER_REQ": 0,
  }
  ret = []
  if CP.flags & HyundaiFlags.CANFD_HDA2:
    if CP.flags & HyundaiFlags.CANFD_HDA2_ALT_STEERING:
      values = dict(base, DampingGain=100, HAS_LANE_SAFETY=0, VALUE63=0, VALUE64=100, **_angle(lat_active, apply_angle, gain))
      ret.append(packer.make_can_msg("LKAS_ALT", canfd_bus(CP, 0), values))
    else:
      values = dict(base, LKA_ASSIST=0, STEER_MODE=0, **_angle(lat_active, apply_angle, gain))
      ret.append(packer.make_can_msg("LKAS", canfd_bus(CP, 0), values))
  elif CP.flags & HyundaiFlags.CANFD_ANGLE_ADAS_CMD:
    ret.append(packer.make_can_msg("LFA", canfd_bus(CP, 0), dict(base, LKA_ASSIST=0, STEER_MODE=0)))
    ret.append(packer.make_can_msg("ADAS_CMD_35_10ms", canfd_bus(CP, 0), {
      "ADAS_ActvACISta": 0,
      "ADAS_ActvACILvl2Sta": 2 if lat_active else 1,
      "ADAS_StrAnglReqVal": apply_angle,
      "ADAS_ACIAnglTqRedcGainVal": gain if lat_active else 0.0,
      "FCA_ESA_ActvSta": 0,
      "FCA_ESA_TqBstGainVal": 0.0,
    }))
  else:
    ret.append(packer.make_can_msg("LFA", canfd_bus(CP, 0), dict(base, LKA_ASSIST=0, STEER_MODE=0, **_angle(lat_active, apply_angle, gain))))
  return ret

def create_cam_0x2a4(packer, CP, camera_values):
  camera_values.update({
    "BYTE7": 0,
  })
  return packer.make_can_msg("CAM_0x2a4", canfd_bus(CP, 0), camera_values)

def create_cam_0x362(packer, CP, camera_values):
  # LFA off on alt-steering HDA2 cars: same idea as BYTE7 = 0 in CAM_0x2a4 (lane lines and the bits next to them)
  values = dict(camera_values)
  values.update({
    "LEFT_LANE_LINE": 0,
    "RIGHT_LANE_LINE": 0,
    "SET_ME_0": 0,
    "SET_ME_0_2": 0,
  })
  return packer.make_can_msg("CAM_0x362", canfd_bus(CP, 0), values)

def create_buttons(packer, CP, cnt, btn):
  values = {
    "COUNTER": cnt,
    "SET_ME_1": 1,
    "CRUISE_BUTTONS": btn,
  }

  bus = canfd_bus(CP, 1 if CP.flags & HyundaiFlags.CANFD_HDA2 else 2)
  return packer.make_can_msg("CRUISE_BUTTONS", bus, values)

def create_acc_cancel(packer, CP, cruise_info_copy):
  values = cruise_info_copy
  values.update({
    "ACCMode": 4,
  })
  return packer.make_can_msg("SCC_CONTROL", get_e_can_bus(CP), values)

def create_lfahda_cluster(packer, CP, enabled):
  values = {
    "HDA_ICON": 1 if enabled else 0,
    "LFA_ICON": 2 if enabled else 0,
  }
  return packer.make_can_msg("LFAHDA_CLUSTER", get_e_can_bus(CP), values)


def create_acc_control(packer, CP, enabled, accel_last, accel, stopping, gas_override, set_speed):
  jerk = 5
  jn = jerk / 50
  if not enabled or gas_override:
    a_val, a_raw = 0, 0
  else:
    a_raw = accel
    a_val = clip(accel, accel_last - jn, accel_last + jn)
    if stopping:
      a_raw = 0

  values = {
    "ACCMode": 0 if not enabled else (2 if gas_override else 1),
    "MainMode_ACC": 1,
    "StopReq": 1 if stopping else 0,
    "aReqValue": a_val,
    "aReqRaw": a_raw,
    "VSetDis": set_speed,
    "JerkLowerLimit": jerk if enabled else 1,

    "ACC_ObjDist": 1,
    "ObjValid": 0,
    "OBJ_STATUS": 2,
    "SET_ME_2": 0x4,
    "SET_ME_3": 0x3,
    "SET_ME_TMP_64": 0x64,
    "NEW_SIGNAL_10": 4,
    "DISTANCE_SETTING": 4,
  }

  return packer.make_can_msg("SCC_CONTROL", get_e_can_bus(CP), values)



def create_adrv_messages(packer, CP, frame):
  # messages needed to car happy after disabling
  # the ADAS Driving ECU to do longitudinal control

  ret = []

  values = {
  }
  ret.append(packer.make_can_msg("ADRV_0x51", canfd_bus(CP, 0), values))

  if frame % 2 == 0:
    values = {
      'AEB_SETTING': 0x1,  # show AEB disabled icon
      'SET_ME_2': 0x2,
      'SET_ME_FF': 0xff,
      'SET_ME_FC': 0xfc,
      'SET_ME_9': 0x9,
    }
    ret.append(packer.make_can_msg("ADRV_0x160", canfd_bus(CP, 1), values))

  if frame % 5 == 0:
    values = {
      'SET_ME_1C': 0x1c,
      'SET_ME_FF': 0xff,
      'SET_ME_TMP_F': 0xf,
      'SET_ME_TMP_F_2': 0xf,
    }
    ret.append(packer.make_can_msg("ADRV_0x1ea", canfd_bus(CP, 1), values))

    values = {
      'SET_ME_E1': 0xe1,
      'SET_ME_3A': 0x3a,
    }
    ret.append(packer.make_can_msg("ADRV_0x200", canfd_bus(CP, 1), values))

  if frame % 20 == 0:
    values = {
      'SET_ME_15': 0x15,
    }
    ret.append(packer.make_can_msg("ADRV_0x345", canfd_bus(CP, 1), values))

  if frame % 100 == 0:
    values = {
      'SET_ME_22': 0x22,
      'SET_ME_41': 0x41,
    }
    ret.append(packer.make_can_msg("ADRV_0x1da", canfd_bus(CP, 1), values))

  return ret
