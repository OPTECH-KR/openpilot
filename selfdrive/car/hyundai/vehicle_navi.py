"""CAN FD 순정 내비 (optech-hkg-fd, 2026-11-28).

carrot-wip befd99656 (PR #590 / #591 and the stock-navigation code under them, opendbc/car/hyundai/carstate.py) moved
onto the old C2 CANParser. Everything here runs only while one of the OPTECH switches is on (VehicleNaviCanControl,
VehicleNaviSchoolZoneControl, VehicleNaviCurveControl, VehicleNaviJunctionAssist; read at start, a change needs a
reboot): then the stock-navigation messages are added to the ECAN parser with check frequency 0, so a car without
them never sees a CAN error. hyundai_canfd.dbc has no checksum type, so no counter/checksum check either.

Differences from carrot:
  - The old parser has no per-message receive time or raw length. NaviParserView keeps a frame clock (10 ms) and
    marks a message as received when its vl_all has values this update; the raw length is the DBC length once seen
    (carrot rejects other lengths on the same address; we cannot tell them apart).
  - carrot's +/gas "skip this camera" requests and the section-average unlock are left out (they need its cruise.py);
    SpeedcamPolicy still drops stock mobile-enforcement zones like carrot does by default.
  - KIA PV5's camera / section state comes from A-CAN 0x380, which this branch does not read: PV5 gets bumps, curves
    and junctions only.
The outputs are the carrot CarState fields (cereal/car.capnp @56..@74) plus speedLimit / speedLimitDistance;
selfdrive/controls/lib/cruise_helper.py turns them into deceleration when the phone navigation sends nothing.
"""
import math
from collections import deque

from common.conversions import Conversions as CV
from common.params import Params
from common.realtime import DT_CTRL
from selfdrive.car.hyundai.navi_speedcam import SpeedcamPolicy
from selfdrive.car.hyundai.values import CAR

VEHICLE_SPEED_CAMERA_PARAM_UPDATE_FRAMES = round(1.0 / DT_CTRL)
VEHICLE_NAVI_MAX_EVENT_DISTANCE = 2500.0
VEHICLE_NAVI_PASSED_EVENT_DISTANCE = 30.0
VEHICLE_NAVI_CAMERA_MATCH_MARGIN = 40.0
VEHICLE_NAVI_MAX_EVENTS = 32
VEHICLE_NAVI_CAMERA_KINDS = (0, 1, 2)
VEHICLE_NAVI_CONTROLLED_ACCESS_LINK_CLASSES = (1, 2, 3)  # Freeway, IC, JC
VEHICLE_NAVI_CONTROLLED_ACCESS_ROAD_CLASSES = (1, 2)  # Freeway, arterial/city freeway
VEHICLE_NAVI_SCHOOL_ZONE_MAX_DISTANCE = 1000.0
VEHICLE_NAVI_POSITION_TIMEOUT_NS = 1_000_000_000
VEHICLE_NAVI_ROUTE_TIMEOUT_NS = 2_000_000_000
CANFD_HDA_INFO_MSG = "CANFD_HDA_INFO_364"
CANFD_NAVI_PROFILE_MSG = "CANFD_NAVI_PROFILE_093"
CANFD_NAVI_SEGMENT_MSG = "CANFD_NAVI_SEGMENT_099"
CANFD_NAVI_STATUS_MSG = "CANFD_NAVI_STATUS_380"
CANFD_NAVI_PROSHORT_MSG = "CANFD_NAVI_PROSHORT_094"
CANFD_NAVI_RAMP_MSG = "CANFD_NAVI_RAMP_098"
CANFD_NAVI_STUB_MSG = "CANFD_NAVI_STUB_09A"
LEGACY_NAVI_PROSHORT_MSG = "NEW_MSG_4BA"
LEGACY_NAVI_PROSHORT_4B7_MSG = "NEW_MSG_4B7"  # Alternate 8-byte PROSHORT address (e.g., GV80), selected by receipt.
LEGACY_NAVI_RAMP_4B0_MSG = "NEW_MSG_4B0"      # Alternate 8-byte ramp PROSHORT address (path=9, e.g., GV80).
LEGACY_NAVI_STUB_MSG = "NEW_MSG_4BF"
LEGACY_NAVI_PROFILE_4B8_MSG = "NEW_MSG_4B8"  # Alternate 8-byte PROLONG address, selected by receipt.
# 일부 현대·기아·제네시스 CAN FD 순정내비는 경로 상태(세그먼트)를 0x4B9가 아니라 0x4B5로 보낸다.
# BYTE_5의 bit 3이 안내 활성 표시다 (안내 중 1, 안내를 끄면 0, 안내 종료 시 프레임 자체가 끊기기도 함).
LEGACY_NAVI_SEGMENT_4B5_MSG = "NEW_MSG_4B5"
VEHICLE_NAVI_SEGMENT_4B5_ACTIVE_MASK = 0x08  # BYTE_5 bit 3
# 0x4B5는 안내 중에도 수 분씩 끊기는 일이 있어 스트림 중단 판정은 600초로 길게 잡는다.
VEHICLE_NAVI_SEGMENT_4B5_TIMEOUT_NS = 600_000_000_000
# 0x4B5/0x4B8/0x4DE 프로토콜 패밀리의 POSITION 메시지 (구간단속 실시간 평균속도 bits 21|9).
LEGACY_NAVI_POSITION_4DE_MSG = "NEW_MSG_4DE"
VEHICLE_NAVI_POSITION_INVALID_OFFSET = 8191
VEHICLE_NAVI_POSITION_INVALID_AVG_SPEED = 511
# 0x4B5/0x4B8/0x4DE 계열 방지턱 게이팅 상수.
VEHICLE_NAVI_GV80_BUMP_MAX_OFFSET = 700.0
VEHICLE_NAVI_GV80_BUMP_RESET_KEEP_DISTANCE = 120.0
VEHICLE_NAVI_GV80_FRC5_BUMP_MAX_MIN_OFFSET = 250.0
VEHICLE_NAVI_GV80_FRC5_BUMP_MAX_SPEED = 55.0 * CV.KPH_TO_MS
VEHICLE_NAVI_GV80_FRC5_BUMP_MAX_SPEED_LIMIT = 60.0
VEHICLE_NAVI_GV80_BUMP_RECONFIRM_DELTA = 20.0
VEHICLE_NAVI_GV80_RESET_TURN_STEER_DEG = 60.0
VEHICLE_NAVI_GV80_RESET_STEER_WINDOW_FRAMES = round(3.0 / DT_CTRL)
VEHICLE_NAVI_GV80_BUMP_PAIR_CHAIN_GAP = 60.0
VEHICLE_NAVI_GV80_BUMP_PAIR_MAX_KEEP = 180.0
VEHICLE_NAVI_SCHOOL_ZONE_PRE_DISTANCE = 150.0
VEHICLE_NAVI_MAX_CURVES = 64
VEHICLE_NAVI_CURVE_MAX_DISTANCE = 8190.0  # 13-bit offset; 8191 is the invalid sentinel
VEHICLE_NAVI_CURVE_RADIUS_SCALE = 4.4  # Empirical Hyundai/Kia CAN-FD scale: R ~= 4.4 * |v0 - 511| m
VEHICLE_NAVI_CURVE_DISTANCE_FACTOR = 2.0
VEHICLE_NAVI_CURVE_SHORT_SPOT_MAX_DISTANCE = 10.0
VEHICLE_NAVI_CURVE_SHORT_SPOT_MAX_SPEED = 60.0
VEHICLE_NAVI_CURVE_TARGET_LAT_ACCEL = 1.9
VEHICLE_NAVI_CURVE_ALLOWED_LINK_CLASSES = (1, 2)  # Freeway and IC/JC ramp only
VEHICLE_NAVI_RAMP_FRWINFO_VALUES = (1, 2, 3, 4)  # Fork warning within ~500 m
VEHICLE_NAVI_HDA_TIMEOUT_NS = 2_000_000_000
VEHICLE_NAVI_STUB_EXIT_BRANCH_TYPE = 0x49
VEHICLE_NAVI_STUB_MERGE_BRANCH_TYPE = 0x01
VEHICLE_NAVI_JUNCTION_MAX_DISTANCE = 2500.0
VEHICLE_NAVI_MAX_JUNCTIONS = 16
EV4_SECTION_DISTANCE_SCALE = 20.0
CANFD_NAVI_CAMERA_ACTIVE_BIT = 0x40
CANFD_NAVI_STATUS_TIMEOUT_NS = 1_000_000_000

FRAME_NS = int(DT_CTRL * 1e9)

# name -> (address, DBC length, signals read)
NAVI_MSGS = {
  "HDA_INFO_4A3": (0x4A3, 8, ["LinkClass", "Frwinfo", "SpeedUnit", "SPEED_LIMIT", "CountryCode", "MapSource",
                               "TollExist", "TunnelExist"]),
  "NEW_MSG_4B4": (0x4B4, 8, ["POS_OFFSET", "POS_CYCLIC_COUNTER", "POS_RANGE_AVG_SPEED"] + [f"BYTE_{i}" for i in range(1, 9)]),
  "NEW_MSG_4B9": (0x4B9, 8, [f"BYTE_{i}" for i in range(1, 9)]),
  "NEW_MSG_4BE": (0x4BE, 8, ["PROLONG_VALUE", "PROLONG_OFFSET", "PROLONG_CYCLIC_COUNTER", "PROLONG_UPDATE",
                             "PROLONG_PATH_INDEX", "PROLONG_PROFILE_TYPE"]),
  "NEW_MSG_4B5": (0x4B5, 8, [f"BYTE_{i}" for i in range(1, 9)]),
  "NEW_MSG_4DE": (0x4DE, 8, ["POS_OFFSET", "POS_PATH_INDEX", "POS_CYCLIC_COUNTER", "POS_RANGE_AVG_SPEED"]),
  "NEW_MSG_4BA": (0x4BA, 8, ["PROSHORT_OFFSET", "PROSHORT_PATH_INDEX", "PROSHORT_CYCLIC_COUNTER", "PROSHORT_ACCURACY",
                             "PROSHORT_DISTANCE", "PROSHORT_VALUE_0", "PROSHORT_VALUE_1", "PROSHORT_PROFILE_TYPE"]),
  "NEW_MSG_4B7": (0x4B7, 8, ["PROSHORT_OFFSET", "PROSHORT_PATH_INDEX", "PROSHORT_CYCLIC_COUNTER", "PROSHORT_ACCURACY",
                             "PROSHORT_DISTANCE", "PROSHORT_VALUE_0", "PROSHORT_VALUE_1", "PROSHORT_PROFILE_TYPE"]),
  "NEW_MSG_4B0": (0x4B0, 8, ["PROSHORT_OFFSET", "PROSHORT_PATH_INDEX", "PROSHORT_CYCLIC_COUNTER", "PROSHORT_ACCURACY",
                             "PROSHORT_DISTANCE", "PROSHORT_VALUE_0", "PROSHORT_VALUE_1", "PROSHORT_PROFILE_TYPE"]),
  "NEW_MSG_4BF": (0x4BF, 8, ["STUB_OFFSET", "STUB_PATH_INDEX", "STUB_CYCLIC_COUNTER", "STUB_SUB_PATH_FLAGS",
                             "STUB_BRANCH_TYPE", "STUB_ROAD_ATTR", "STUB_TURN_ANGLE", "STUB_LANE_FOW"]),
  "NEW_MSG_4B8": (0x4B8, 8, ["PROLONG_VALUE", "PROLONG_OFFSET", "PROLONG_CYCLIC_COUNTER", "PROLONG_UPDATE",
                             "PROLONG_PATH_INDEX", "PROLONG_PROFILE_TYPE"]),
  "CANFD_HDA_INFO_364": (0x364, 16, ["LinkClass", "Frwinfo", "SpeedUnit", "SPEED_LIMIT", "CountryCode", "MapSource",
                                     "TollExist", "TunnelExist"]),
  "CANFD_NAVI_PROFILE_093": (0x093, 24, ["PROLONG_VALUE", "PROLONG_OFFSET", "PROLONG_CYCLIC_COUNTER", "PROLONG_UPDATE",
                                         "PROLONG_PATH_INDEX", "PROLONG_PROFILE_TYPE"]),
  "CANFD_NAVI_SEGMENT_099": (0x099, 24, [f"BYTE_{i}" for i in range(1, 9)]),
  "CANFD_NAVI_PROSHORT_094": (0x094, 32, ["PROSHORT_OFFSET", "PROSHORT_PATH_INDEX", "PROSHORT_CYCLIC_COUNTER",
                                          "PROSHORT_ACCURACY", "PROSHORT_DISTANCE", "PROSHORT_VALUE_0", "PROSHORT_VALUE_1",
                                          "PROSHORT_PROFILE_TYPE"]),
  "CANFD_NAVI_RAMP_098": (0x098, 16, ["PROSHORT_OFFSET", "PROSHORT_PATH_INDEX", "PROSHORT_CYCLIC_COUNTER",
                                      "PROSHORT_ACCURACY", "PROSHORT_DISTANCE", "PROSHORT_VALUE_0", "PROSHORT_VALUE_1",
                                      "PROSHORT_PROFILE_TYPE"]),
  "CANFD_NAVI_STUB_09A": (0x09A, 24, ["STUB_OFFSET", "STUB_PATH_INDEX", "STUB_CYCLIC_COUNTER", "STUB_SUB_PATH_FLAGS",
                                      "STUB_BRANCH_TYPE", "STUB_ROAD_ATTR", "STUB_TURN_ANGLE", "STUB_LANE_FOW"]),
}
# messages whose raw bytes carrot reads (int.from_bytes / byte index): rebuilt from their BYTE_n signals
RAW_BYTE_MSGS = ("NEW_MSG_4B4", "NEW_MSG_4B5")

# the PR #589 messages (OptechFdSignalFix): name -> (address, DBC length, signals, max age frames)
SIGNAL_FIX_MSGS = {
  "BRAKE_LIGHT_412": (0x412, 8, ["STOP_LAMP"], 30),
  "IMU_01_10MS": (0x04A, 32, ["IMU_YawRtVal"], 15),
  "BLINDSPOTS_FRONT_CORNER_1": (0x1E5, 16, ["INDICATOR_LEFT", "INDICATOR_RIGHT"], 15),
}


def _params_int(params, key, default):
  try:
    raw = params.get(key)
    return int(raw) if raw not in (None, b"", "") else default
  except Exception:
    return default


def _params_bool(params, key, default):
  try:
    raw = params.get(key)
    return default if raw in (None, b"", "") else raw in (b"1", "1")
  except Exception:
    return default


def vehicle_navi_enabled():
  """Any stock-navigation switch on at start (the parser and this module only exist then)."""
  p = Params()
  return (_params_int(p, "VehicleNaviCanControl", 0) > 0 or _params_bool(p, "VehicleNaviSchoolZoneControl", False) or
          _params_bool(p, "VehicleNaviCurveControl", False) or _params_bool(p, "VehicleNaviJunctionAssist", False))


def signal_fix_enabled():
  return _params_bool(Params(), "OptechFdSignalFix", False)


def navi_message_names(CP):
  if CP.carFingerprint == CAR.KIA_PV5:
    names = [CANFD_HDA_INFO_MSG, CANFD_NAVI_PROFILE_MSG, CANFD_NAVI_SEGMENT_MSG, CANFD_NAVI_PROSHORT_MSG,
             CANFD_NAVI_RAMP_MSG, CANFD_NAVI_STUB_MSG]
  elif CP.carFingerprint == CAR.KIA_EV4:
    names = [CANFD_HDA_INFO_MSG, CANFD_NAVI_SEGMENT_MSG, CANFD_NAVI_PROFILE_MSG, CANFD_NAVI_PROSHORT_MSG,
             CANFD_NAVI_RAMP_MSG, CANFD_NAVI_STUB_MSG]
  else:
    names = ["HDA_INFO_4A3", "NEW_MSG_4B4", "NEW_MSG_4B9", "NEW_MSG_4BE", LEGACY_NAVI_SEGMENT_4B5_MSG,
             LEGACY_NAVI_POSITION_4DE_MSG, LEGACY_NAVI_PROSHORT_MSG, LEGACY_NAVI_PROSHORT_4B7_MSG,
             LEGACY_NAVI_RAMP_4B0_MSG, LEGACY_NAVI_STUB_MSG]
  return names + [LEGACY_NAVI_PROFILE_4B8_MSG]


def navi_parser_entries(CP):
  """(signals, checks) for the ECAN parser: frequency 0 = never makes the parser invalid."""
  signals, checks = [], []
  for name in navi_message_names(CP):
    signals += [(sig, name) for sig in NAVI_MSGS[name][2]]
    checks.append((name, 0))
  return signals, checks


def signal_fix_parser_entries():
  signals, checks = [], []
  for name, (_, _, sigs, _) in SIGNAL_FIX_MSGS.items():
    signals += [(sig, name) for sig in sigs]
    checks.append((name, 0))
  return signals, checks


class NaviParserView:
  """What carrot's newer CANParser gives (ts_nanos, dat, _last_update_nanos, bus_timeout), kept on the old parser."""
  def __init__(self, names):
    self.names = list(names)
    self.cp = None
    self.vl = {}
    self.ts_nanos = {}
    self.dat = {}
    self._last_update_nanos = 0
    self.bus_timeout = False

  def tick(self, cp, now_ns):
    self.cp = cp
    self.vl = cp.vl
    self._last_update_nanos = now_ns
    self.bus_timeout = cp.bus_timeout
    for name in self.names:
      got = cp.vl_all.get(name)
      if not got or not any(len(v) for v in got.values()):
        continue
      address, size, sigs = NAVI_MSGS[name]
      self.ts_nanos[name] = {sig: now_ns for sig in sigs}
      if name in RAW_BYTE_MSGS:
        values = cp.vl[name]
        self.dat[address] = bytes(int(values.get(f"BYTE_{i}", 0)) & 0xff for i in range(1, 9))
      else:
        self.dat[address] = bytes(size)


class VehicleNaviMixin:
  """carrot CarState's stock-navigation part. The CarState sets self.CP, self.is_metric and calls
  vehicle_navi_init(CP) in __init__ and vehicle_navi_update(cp, ret) at the end of update_canfd."""

  def vehicle_navi_init(self, CP):
    self.navi_params = Params()
    self.navi_frame = 0
    self.canfd_wrapped_navi = CP.carFingerprint == CAR.KIA_PV5
    self.canfd_ev4_navi = CP.carFingerprint == CAR.KIA_EV4
    self.canfd_wrapped_navi_full = self.canfd_ev4_navi
    self.hda_info_msg = CANFD_HDA_INFO_MSG if (self.canfd_wrapped_navi or self.canfd_ev4_navi) else "HDA_INFO_4A3"
    self.navi_segment_msg = CANFD_NAVI_SEGMENT_MSG if self.canfd_ev4_navi else "NEW_MSG_4B9"
    self.navi_profile_msg = CANFD_NAVI_PROFILE_MSG if (self.canfd_wrapped_navi or self.canfd_ev4_navi) else "NEW_MSG_4BE"
    self.navi_proshort_msg = CANFD_NAVI_PROSHORT_MSG if (self.canfd_wrapped_navi or self.canfd_ev4_navi) else LEGACY_NAVI_PROSHORT_MSG
    self.navi_ramp_msg = CANFD_NAVI_RAMP_MSG if (self.canfd_wrapped_navi or self.canfd_ev4_navi) else None
    self.navi_stub_msg = CANFD_NAVI_STUB_MSG if (self.canfd_wrapped_navi or self.canfd_ev4_navi) else LEGACY_NAVI_STUB_MSG
    self.vehicleNaviZoneControlSupported = not self.canfd_wrapped_navi  # Legacy kind-7 profile zones only
    self.navi_view = NaviParserView(navi_message_names(CP))
    # message name -> attribute holding its live vl dict (set once the message has been received)
    self.navi_cache_attrs = {}
    if self.canfd_wrapped_navi or self.canfd_ev4_navi:
      self.navi_cache_attrs.update({CANFD_HDA_INFO_MSG: "hda_info_4a3", CANFD_NAVI_PROFILE_MSG: "navi_profile_4be",
                                    CANFD_NAVI_PROSHORT_MSG: "navi_proshort_094", CANFD_NAVI_RAMP_MSG: "navi_ramp_098",
                                    CANFD_NAVI_STUB_MSG: "navi_stub_09a"})
      if self.canfd_wrapped_navi:
        self.navi_cache_attrs[CANFD_NAVI_SEGMENT_MSG] = "navi_curve_segment_099"
      else:
        self.navi_cache_attrs[CANFD_NAVI_SEGMENT_MSG] = "navi_segment_4b9"
    else:
      self.navi_cache_attrs.update({"HDA_INFO_4A3": "hda_info_4a3", "NEW_MSG_4B4": "navi_position_4b4",
                                    "NEW_MSG_4B9": "navi_segment_4b9", "NEW_MSG_4BE": "navi_profile_4be",
                                    LEGACY_NAVI_SEGMENT_4B5_MSG: "navi_segment_4b5",
                                    LEGACY_NAVI_POSITION_4DE_MSG: "navi_position_4de",
                                    LEGACY_NAVI_PROSHORT_MSG: "navi_proshort_094",
                                    LEGACY_NAVI_PROSHORT_4B7_MSG: "navi_proshort_4b7",
                                    LEGACY_NAVI_RAMP_4B0_MSG: "navi_ramp_4b0", LEGACY_NAVI_STUB_MSG: "navi_stub_09a"})
    self.navi_cache_attrs[LEGACY_NAVI_PROFILE_4B8_MSG] = "navi_profile_4b8"
    self.hda_info_4a3 = None
    self.navi_position_4b4 = None
    self.navi_position_4de = None
    self.navi_segment_4b9 = None
    self.navi_segment_4b5 = None
    self.navi_curve_segment_099 = None
    self.navi_profile_4be = None
    self.navi_profile_4b8 = None
    self.navi_status_380 = None  # A-CAN, not read on this branch
    self.navi_proshort_094 = None
    self.navi_proshort_4b7 = None
    self.navi_ramp_098 = None
    self.navi_ramp_4b0 = None
    self.navi_stub_09a = None
    self.vehicleNaviProshortTimestamp = 0
    self.vehicleNaviProshort4b7Timestamp = 0
    self.vehicleNaviCurveSegmentTimestamp = 0
    self.vehicleNaviRampTimestamp = 0
    self.vehicleNaviRamp4b0Timestamp = 0
    self.vehicleNaviStubTimestamp = 0
    self.vehicleNaviCurves = []
    self.vehicleNaviRampCurves = []
    self.vehicleNaviJunctions = []
    self.vehicleNaviCurveRouteActive = False
    self.vehicleNaviCurveRouteState = 3
    self.vehicleNaviCurvePathIndex = None
    self.ev4Section = None
    self.ev4SectionMismatchNanos = None
    self.pv5_section_start_prev = False
    self.pv5_completed_camera_speed = 0

    distance_time_tenths = _params_int(self.navi_params, "VehicleSpeedCameraDistanceTime", 60)
    self.vehicleSpeedCameraDistanceTime = self._vehicle_speed_camera_distance_time(distance_time_tenths)
    self.vehicleNaviCanControl = self._vehicle_navi_can_control_mode(_params_int(self.navi_params, "VehicleNaviCanControl", 0))
    self.vehicleNaviSchoolZoneControl = _params_bool(self.navi_params, "VehicleNaviSchoolZoneControl", False)
    self.vehicleSpeedCameraParamsCounter = 0
    self.vehicleNaviEvents = []
    self._read_vehicle_navi_curve_params()
    self.speedcam_policy = SpeedcamPolicy()
    self._read_speedcam_params()
    self.vehicleNaviSegmentTimestamp = 0
    self.vehicleNaviSegment4b5Timestamp = 0
    self.vehicleNaviSegment4b5Active = False
    self.vehicleNaviPosition4deSeen = False
    self.vehicleNaviSegment4b5Seen = False
    self.vehicleNaviSegment4b9Seen = False
    self.vehicleNaviGv80HorizonTimestamp = 0
    self.vehicleNaviRoadHorizon = []
    self.vehicleNaviGv80SteerHistory = deque(maxlen=VEHICLE_NAVI_GV80_RESET_STEER_WINDOW_FRAMES)
    self.vehicleNaviGv80FarBumpTargets = deque(maxlen=32)
    self.vehicleNaviProfileTimestamp = 0
    self.vehicleNaviProfile4b8Timestamp = 0
    self.vehicleNaviAvailable = False
    self.vehicleNaviRouteResetTimestamp = 0
    self.vehicleNaviRouteState = 0
    self.vehicleNaviRoutePathIndex = None
    self.vehicleNaviRoadClass = 7
    self.vehicleNaviCameraTarget = None
    self.vehicleNaviCameraStatusEvent = None
    self.vehicleNaviCameraStatusSpeed = 0.0
    self.vehicleNaviCameraStatusTarget = None
    self.vehicleNaviSpeedZoneActive = False
    self.vehicleNaviSpeedZoneSpeed = 0.0
    self.vehicleNaviSchoolZoneActive = False
    self.vehicleNaviSchoolZoneStartDistance = 0.0
    self.vehicleNaviSchoolZoneUsesCameraStatus = False

  # ---- entry point ----
  def vehicle_navi_update(self, cp, ret):
    self.navi_frame += 1
    view = self.navi_view
    view.tick(cp, self.navi_frame * FRAME_NS)
    for name, attr in self.navi_cache_attrs.items():
      if getattr(self, attr) is None and name in view.ts_nanos:
        setattr(self, attr, cp.vl[name])

    # carrot update_canfd: the current warning from HDA info (0x4A3 / 0x364)
    speed_limit_cam = False
    speed_limit = 0.0
    if self.hda_info_4a3 is not None:
      speed_limit = float(self.hda_info_4a3["SPEED_LIMIT"])
      if not self.is_metric:
        speed_limit *= CV.MPH_TO_KPH
      speed_limit = speed_limit if speed_limit < 255 else 0.0
      if int(self.hda_info_4a3["MapSource"]) == 2:
        speed_limit_cam = True
    ret.speedLimit = int(round(speed_limit))
    if self.canfd_wrapped_navi:
      speed_limit_cam = self._update_pv5_camera_warning(view, None)

    distance_time_changed = self._update_vehicle_speed_camera_params()
    warning_active, warning_speed = speed_limit_cam, ret.speedLimit
    speed_limit_cam = self._update_vehicle_navi_events(view, ret, speed_limit_cam, None) or speed_limit_cam
    speed_limit_cam = self._apply_speedcam_policy(ret, speed_limit_cam, warning_active, warning_speed)
    self.update_speed_limit(ret, speed_limit_cam, distance_time_changed)
    ret.totalDistance = self.totalDistance
    # carrot slows for a camera (speedLimit + speedLimitDistance, also a bare warning with its virtual distance) only
    # while its camera control is on; here that is '순정 내비 감속' (VehicleNaviCanControl). The school zone, curve and
    # junction switches alone never slow for cameras.
    if not self.vehicleNaviCanControl:
      ret.speedLimitDistance = 0.

  # ---- params ----
  @staticmethod
  def _vehicle_speed_camera_distance_time(raw_value):
    return min(200, max(10, raw_value)) / 10.0

  @staticmethod
  def _vehicle_navi_can_control_mode(raw_value):
    return min(3, max(0, raw_value))

  def _update_vehicle_speed_camera_params(self):
    self.vehicleSpeedCameraParamsCounter += 1
    if self.vehicleSpeedCameraParamsCounter < VEHICLE_SPEED_CAMERA_PARAM_UPDATE_FRAMES:
      return False

    self.vehicleSpeedCameraParamsCounter = 0
    distance_time_tenths = _params_int(self.navi_params, "VehicleSpeedCameraDistanceTime", 60)
    distance_time = self._vehicle_speed_camera_distance_time(distance_time_tenths)
    changed = distance_time != self.vehicleSpeedCameraDistanceTime
    self.vehicleSpeedCameraDistanceTime = distance_time
    if changed and self.vehicleNaviCameraStatusTarget is not None:
      self.vehicleNaviCameraStatusTarget = self.totalDistance + self.vehicleNaviCameraStatusSpeed * distance_time
    vehicle_navi_can_control = self._vehicle_navi_can_control_mode(_params_int(self.navi_params, "VehicleNaviCanControl", 0))
    if vehicle_navi_can_control != self.vehicleNaviCanControl:
      self.vehicleNaviCanControl = vehicle_navi_can_control
      if not vehicle_navi_can_control:
        self._clear_vehicle_navi_events()
        self._clear_vehicle_navi_speed_zone()
      elif vehicle_navi_can_control >= 2:
        self._clear_vehicle_navi_route_filtered_events()
    vehicle_navi_school_zone_control = _params_bool(self.navi_params, "VehicleNaviSchoolZoneControl", False)
    if vehicle_navi_school_zone_control != self.vehicleNaviSchoolZoneControl:
      self.vehicleNaviSchoolZoneControl = vehicle_navi_school_zone_control
      if not vehicle_navi_school_zone_control:
        self._clear_vehicle_navi_school_zone()
    self._read_vehicle_navi_curve_params()
    self._read_speedcam_params()
    return changed

  def _read_vehicle_navi_curve_params(self):
    raw_factor = _params_int(self.navi_params, "VehicleNaviCurveSpeedFactor", 100)
    if raw_factor <= 0:
      raw_factor = 100
    raw_lower = _params_int(self.navi_params, "AutoCurveSpeedLowerLimit", 30)
    if raw_lower <= 0:
      raw_lower = 30
    raw_decel = _params_int(self.navi_params, "AutoNaviSpeedDecelRate", 120)
    if raw_decel <= 0:
      raw_decel = 120
    raw_ctrl_end = _params_int(self.navi_params, "VehicleNaviCurveCtrlEnd", 3)
    self.vehicleNaviCurveSpeedFactor = min(2.0, max(0.5, raw_factor * 0.01))
    self.vehicleNaviCurveLowerLimit = max(5.0, float(raw_lower))
    self.vehicleNaviCurveDecelRate = max(0.01, raw_decel * 0.01)
    self.vehicleNaviCurveControlEnd = max(0.0, float(raw_ctrl_end))
    self.vehicleNaviRampCurveControl = _params_bool(self.navi_params, "VehicleNaviRampCurveControl", True)

  def _read_speedcam_params(self):
    # carrot: AutoNaviSpeedCtrlMode 3 also decelerates for stock mobile zones (0x4BE kind 3). Not offered here.
    self.speedcamMobileZoneDecel = False
    self.speedcamSectionAvgControl = _params_bool(self.navi_params, "VehicleNaviSectionAvgControl", True)

  def _apply_speedcam_policy(self, ret, speed_limit_cam, warning_active, warning_speed):
    """Suppress a stock camera warning for an ignored mobile zone (carrot without its +/gas skip)."""
    if self.canfd_wrapped_navi or not self.vehicleNaviCanControl:
      self.speedcam_policy.reset_warning()
      return speed_limit_cam
    suppress, _ = self.speedcam_policy.update(warning_active, int(round(warning_speed)), self.totalDistance, False,
                                              self.speedcamMobileZoneDecel, False, False, False)
    return False if suppress else speed_limit_cam

  # ---- carrot carstate.py 1146-2258 ----
  def _clear_vehicle_navi_events(self):
    self.vehicleNaviEvents = []
    self.vehicleNaviCameraTarget = None
    self.vehicleNaviCameraStatusEvent = None
    self.speedcam_policy.clear()
    if hasattr(self, "vehicleNaviGv80FarBumpTargets"):
      self.vehicleNaviGv80FarBumpTargets.clear()

  def _clear_vehicle_navi_curves(self):
    self.vehicleNaviCurves = []
    self.vehicleNaviRampCurves = []
    self.vehicleNaviJunctions = []

  @staticmethod
  def _decode_hyundai_navi_curvature(value):
    """Decode Hyundai CAN-FD PROSHORT ptype=1 10-bit radius code: R ~= 4.4 * |v0 - 511| m (+left / -right)."""
    value = int(value)
    if not 0 <= value < 1023 or value == 511:
      return None
    coded = value - 511
    radius = abs(coded) * VEHICLE_NAVI_CURVE_RADIUS_SCALE
    return (1.0 / radius) if coded > 0 else (-1.0 / radius)

  @staticmethod
  def _decode_vehicle_navi_curve(values):
    if int(values.get("PROSHORT_PROFILE_TYPE", 0)) != 1:
      return None
    offset = int(values.get("PROSHORT_OFFSET", 8191))
    path_index = int(values.get("PROSHORT_PATH_INDEX", 63))
    distance = int(values.get("PROSHORT_DISTANCE", 1023))
    raw_curvature = int(values.get("PROSHORT_VALUE_0", 1023))
    if not 0 <= offset <= VEHICLE_NAVI_CURVE_MAX_DISTANCE or path_index in (0, 63):
      return None
    curvature = VehicleNaviMixin._decode_hyundai_navi_curvature(raw_curvature)
    if curvature is None:
      return None
    return {
      "offset": offset,
      "path_index": path_index,
      "span": distance * VEHICLE_NAVI_CURVE_DISTANCE_FACTOR if 0 <= distance < 1023 else 0.0,
      "curvature": curvature,
      "raw_curvature": raw_curvature,
    }

  @staticmethod
  def _vehicle_navi_curve_reference_speed(curvature):
    if abs(curvature) < 1e-7:
      return 250.0
    return min(250.0, max(5.0, math.sqrt(VEHICLE_NAVI_CURVE_TARGET_LAT_ACCEL / abs(curvature)) * CV.MS_TO_KPH))

  def _add_vehicle_navi_curve(self, target_list, curve, *, is_ramp=False):
    target = self.totalDistance + curve["offset"]
    reference_speed = self._vehicle_navi_curve_reference_speed(curve["curvature"])
    # Ignore isolated sub-10 m turn-node discontinuities on main road, while keeping dense 10 m ramp samples on 0x098.
    short_spot = not is_ramp and 0.0 < curve["span"] < VEHICLE_NAVI_CURVE_SHORT_SPOT_MAX_DISTANCE
    if short_spot and reference_speed <= VEHICLE_NAVI_CURVE_SHORT_SPOT_MAX_SPEED:
      return
    nearest = min(target_list, key=lambda item: abs(item["target"] - target), default=None)
    if nearest is not None and abs(nearest["target"] - target) <= 2.0:
      nearest.update(target=target, span=curve["span"], curvature=curve["curvature"], speed=reference_speed)
    else:
      target_list.append({
        "target": target,
        "span": curve["span"],
        "curvature": curve["curvature"],
        "speed": reference_speed,
      })
    target_list.sort(key=lambda item: item["target"])
    del target_list[VEHICLE_NAVI_MAX_CURVES:]

  @staticmethod
  def _decode_vehicle_navi_junction_zone(values):
    if int(values.get("PROSHORT_PROFILE_TYPE", 31)) != 16:
      return None
    v0 = int(values.get("PROSHORT_VALUE_0", 1023))
    if v0 not in (1, 2):
      return None
    offset = int(values.get("PROSHORT_OFFSET", 8191))
    if not 0 <= offset <= VEHICLE_NAVI_JUNCTION_MAX_DISTANCE:
      return None
    distance = int(values.get("PROSHORT_DISTANCE", 0))
    v1 = int(values.get("PROSHORT_VALUE_1", 0))
    return {
      "offset": offset,
      "path_index": int(values.get("PROSHORT_PATH_INDEX", 63)),
      "type": v0,
      "length": float(max(0, distance)) if 0 <= distance < 1023 else 0.0,
      "lane": (v1 >> 1) if 0 <= v1 < 1023 and (v1 >> 1) <= 255 else 0,
      "side": 0,
      "source": "taper",
    }

  @staticmethod
  def _decode_vehicle_navi_stub(values):
    offset = int(values.get("STUB_OFFSET", 8191))
    if not 0 <= offset <= VEHICLE_NAVI_JUNCTION_MAX_DISTANCE:
      return None
    btype = int(values.get("STUB_BRANCH_TYPE", 0xff))
    if btype not in (VEHICLE_NAVI_STUB_EXIT_BRANCH_TYPE, VEHICLE_NAVI_STUB_MERGE_BRANCH_TYPE):
      return None
    path_index = int(values.get("STUB_PATH_INDEX", 63))
    turn_angle = float(values.get("STUB_TURN_ANGLE", 0.0))
    jtype = 1 if btype == VEHICLE_NAVI_STUB_EXIT_BRANCH_TYPE else 2
    if turn_angle > 0.0:
      side = 2
    elif turn_angle < 0.0:
      side = 1
    else:
      side = 0
    return {
      "offset": offset,
      "path_index": path_index,
      "type": jtype,
      "length": 0.0,
      "lane": 0,
      "side": side,
      "source": "stub",
    }

  def _add_vehicle_navi_junction(self, junction):
    target = self.totalDistance + junction["offset"]
    length = junction["length"]
    end = target + max(30.0 if junction["source"] == "stub" else 0.0, length)
    jtype = junction["type"]
    if junction["source"] == "stub":
      nearby_tapers = [j for j in self.vehicleNaviJunctions
                       if j["type"] == jtype and j["source"] == "taper" and abs(j["start"] - target) <= 350.0]
      if nearby_tapers:
        nearest_taper = min(nearby_tapers, key=lambda j: abs(j["start"] - target))
        if junction["side"] in (1, 2):
          nearest_taper["side"] = junction["side"]
        return
      nearby_stubs = [j for j in self.vehicleNaviJunctions
                      if j["type"] == jtype and j["source"] == "stub" and abs(j["start"] - target) <= 50.0]
      if nearby_stubs:
        nearby_stubs[0].update(start=target, end=end, side=junction["side"] or nearby_stubs[0]["side"])
        return
    else:
      nearby_stubs = [j for j in self.vehicleNaviJunctions
                      if j["type"] == jtype and j["source"] == "stub" and abs(j["start"] - target) <= 350.0]
      inherited_side = next((j["side"] for j in sorted(nearby_stubs, key=lambda item: abs(item["start"] - target))
                             if j["side"] in (1, 2)), 0)
      if nearby_stubs:
        stub_set = set(map(id, nearby_stubs))
        self.vehicleNaviJunctions = [j for j in self.vehicleNaviJunctions if id(j) not in stub_set]
      nearby_tapers = [j for j in self.vehicleNaviJunctions
                       if j["type"] == jtype and j["source"] == "taper" and abs(j["start"] - target) <= 50.0]
      if nearby_tapers:
        nearby_tapers[0].update(
          start=target,
          end=max(nearby_tapers[0]["end"], end),
          lane=junction["lane"] or nearby_tapers[0]["lane"],
          side=inherited_side or nearby_tapers[0]["side"],
        )
        return
      junction = {**junction, "side": inherited_side or junction["side"]}

    self.vehicleNaviJunctions.append({
      "start": target,
      "end": end,
      "type": jtype,
      "side": junction["side"],
      "lane": junction["lane"],
      "source": junction["source"],
    })
    self.vehicleNaviJunctions.sort(key=lambda item: item["start"])
    del self.vehicleNaviJunctions[VEHICLE_NAVI_MAX_JUNCTIONS:]

  def _apply_vehicle_navi_curve_segment(self, segment, timestamp):
    self.vehicleNaviCurveSegmentTimestamp = timestamp
    route = segment["calculated_route"]
    path_index = segment["path_index"]
    if path_index in (0, 63) and route in (0, 1):
      route = 3
    if route == 1:
      if self.vehicleNaviCurveRouteState != 1 or self.vehicleNaviCurvePathIndex != path_index:
        self._clear_vehicle_navi_curves()
      self.vehicleNaviCurveRouteState = 1
      self.vehicleNaviCurveRouteActive = True
      self.vehicleNaviCurvePathIndex = path_index
    elif route == 0:
      if self.vehicleNaviCurveRouteState != 0 or self.vehicleNaviCurvePathIndex != path_index:
        self._clear_vehicle_navi_curves()
      self.vehicleNaviCurveRouteState = 0
      self.vehicleNaviCurveRouteActive = False
      self.vehicleNaviCurvePathIndex = path_index
    elif route == 2:
      self.vehicleNaviRouteResetTimestamp = timestamp
      self.vehicleNaviCurveRouteState = 2
      self.vehicleNaviCurveRouteActive = False
      self.vehicleNaviCurvePathIndex = None
      self._clear_vehicle_navi_curves()
    else:
      self.vehicleNaviRouteResetTimestamp = timestamp
      self.vehicleNaviCurveRouteState = 3
      self.vehicleNaviCurveRouteActive = False
      self.vehicleNaviCurvePathIndex = None
      self._clear_vehicle_navi_curves()

  @staticmethod
  def _decode_ev4_navi_section(values):
    """EV4 0x094 section announcement -> (offset m, length m, limit kph, path index), else None."""
    if int(values.get("PROSHORT_PROFILE_TYPE", 31)) != 16 or int(values.get("PROSHORT_VALUE_0", 1023)) != 0:
      return None
    value_1 = int(values.get("PROSHORT_VALUE_1", 0))
    speed_code = value_1 >> 5
    offset = int(values.get("PROSHORT_OFFSET", 8191))
    length = int(values.get("PROSHORT_DISTANCE", 0)) * EV4_SECTION_DISTANCE_SCALE
    if value_1 & 0x1f or not 7 < speed_code <= 31:  # 35..150 km/h
      return None
    if not 0 < offset <= VEHICLE_NAVI_MAX_EVENT_DISTANCE or length <= 0:
      return None
    return offset, length, (speed_code - 1) * 5, int(values.get("PROSHORT_PATH_INDEX", 0))

  def _consume_vehicle_navi_proshort_values(self, values, timestamp, *, allow_ev4_section=False):
    if timestamp <= self.vehicleNaviRouteResetTimestamp:
      return
    ptype = int(values.get("PROSHORT_PROFILE_TYPE", 0))
    if ptype == 1:
      curve = self._decode_vehicle_navi_curve(values)
      if curve is not None:
        path_matches = self.vehicleNaviCurvePathIndex is None or curve["path_index"] == self.vehicleNaviCurvePathIndex
        if path_matches:
          self._add_vehicle_navi_curve(self.vehicleNaviCurves, curve, is_ramp=False)
    elif ptype == 16:
      junction = self._decode_vehicle_navi_junction_zone(values)
      if junction is not None:
        path_matches = self.vehicleNaviCurvePathIndex is None or junction["path_index"] == self.vehicleNaviCurvePathIndex
        if path_matches:
          self._add_vehicle_navi_junction(junction)
      elif allow_ev4_section and self.canfd_wrapped_navi_full:
        section = self._decode_ev4_navi_section(values)
        if section is not None and self._vehicle_navi_profile_allowed("camera", {"path_index": section[3]}):
          offset, length, speed, _ = section
          start = self.totalDistance + offset
          self.ev4Section = {"start": start, "end": start + length, "speed": speed}
          self.ev4SectionMismatchNanos = None

  def _consume_vehicle_navi_proshort(self, cp):
    if self.navi_proshort_094 is not None and self.navi_proshort_msg in cp.ts_nanos:
      timestamp = self._vehicle_navi_curve_timestamp(cp, self.navi_proshort_msg)
      if timestamp > self.vehicleNaviProshortTimestamp:
        self.vehicleNaviProshortTimestamp = timestamp
        self._consume_vehicle_navi_proshort_values(self.navi_proshort_094, timestamp, allow_ev4_section=True)

    # Alternate 8-byte PROSHORT address (0x4B7, e.g., GV80): same bit layout as 0x4BA/0x094.
    if (self._is_alt_legacy_navi_arch() and
        len(cp.dat.get(0x4B7, b"")) == 8 and self.navi_proshort_4b7 is not None and
        LEGACY_NAVI_PROSHORT_4B7_MSG in cp.ts_nanos):
      timestamp_4b7 = self._vehicle_navi_curve_timestamp(cp, LEGACY_NAVI_PROSHORT_4B7_MSG)
      if timestamp_4b7 > self.vehicleNaviProshort4b7Timestamp:
        self.vehicleNaviProshort4b7Timestamp = timestamp_4b7
        self._consume_vehicle_navi_proshort_values(self.navi_proshort_4b7, timestamp_4b7, allow_ev4_section=False)

  def _consume_vehicle_navi_ramp_and_stub(self, cp):
    if self.navi_ramp_msg is not None and self.navi_ramp_098 is not None and self.navi_ramp_msg in cp.ts_nanos:
      timestamp = self._vehicle_navi_curve_timestamp(cp, self.navi_ramp_msg)
      if timestamp > self.vehicleNaviRampTimestamp:
        self.vehicleNaviRampTimestamp = timestamp
        if timestamp > self.vehicleNaviRouteResetTimestamp:
          curve = self._decode_vehicle_navi_curve(self.navi_ramp_098)
          if curve is not None and curve["path_index"] == 9 and self.vehicleNaviCurvePathIndex == 8:
            self._add_vehicle_navi_curve(self.vehicleNaviRampCurves, curve, is_ramp=True)

    # Alternate 8-byte ramp PROSHORT address (0x4B0, path=9, e.g., GV80): same layout as 0x098.
    if (self._is_alt_legacy_navi_arch() and
        len(cp.dat.get(0x4B0, b"")) == 8 and self.navi_ramp_4b0 is not None and
        LEGACY_NAVI_RAMP_4B0_MSG in cp.ts_nanos):
      timestamp_4b0 = self._vehicle_navi_curve_timestamp(cp, LEGACY_NAVI_RAMP_4B0_MSG)
      if timestamp_4b0 > self.vehicleNaviRamp4b0Timestamp:
        self.vehicleNaviRamp4b0Timestamp = timestamp_4b0
        if timestamp_4b0 > self.vehicleNaviRouteResetTimestamp:
          curve = self._decode_vehicle_navi_curve(self.navi_ramp_4b0)
          if curve is not None and curve["path_index"] == 9 and self.vehicleNaviCurvePathIndex == 8:
            self._add_vehicle_navi_curve(self.vehicleNaviRampCurves, curve, is_ramp=True)

    if self.navi_stub_09a is not None and self.navi_stub_msg in cp.ts_nanos:
      timestamp = self._vehicle_navi_curve_timestamp(cp, self.navi_stub_msg)
      if timestamp > self.vehicleNaviStubTimestamp:
        self.vehicleNaviStubTimestamp = timestamp
        if timestamp > self.vehicleNaviRouteResetTimestamp:
          stub = self._decode_vehicle_navi_stub(self.navi_stub_09a)
          if stub is not None and (self.vehicleNaviCurvePathIndex is None or stub["path_index"] == self.vehicleNaviCurvePathIndex):
            self._add_vehicle_navi_junction(stub)

  def _vehicle_navi_hda_state(self, cp):
    if self.hda_info_4a3 is None or self.hda_info_msg not in cp.ts_nanos:
      return 0, 0, False
    ts = self._vehicle_navi_curve_timestamp(cp, self.hda_info_msg)
    now = getattr(cp, "_last_update_nanos", ts)
    if ts <= 0 or not (0 <= now - ts <= VEHICLE_NAVI_HDA_TIMEOUT_NS):
      return 0, 0, False
    return int(self.hda_info_4a3.get("LinkClass", 0)), int(self.hda_info_4a3.get("Frwinfo", 0)), True

  def _update_vehicle_navi_junction_output(self, ret, link_class, frw_info, hda_fresh):
    self.vehicleNaviJunctions = [j for j in self.vehicleNaviJunctions if j["end"] >= self.totalDistance]
    road_ok = hda_fresh and link_class in VEHICLE_NAVI_CURVE_ALLOWED_LINK_CLASSES
    if road_ok and self.vehicleNaviCurveRouteState in (0, 1):
      candidates = [j for j in self.vehicleNaviJunctions if j["start"] - self.totalDistance <= 600.0]
      if candidates:
        best = min(candidates, key=lambda j: (max(0.0, j["start"] - self.totalDistance), 0 if j["source"] == "taper" else 1))
        ret.vehicleNaviJunctionType = best["type"]
        ret.vehicleNaviJunctionSide = best["side"]
        ret.vehicleNaviJunctionDistance = max(0.0, best["start"] - self.totalDistance)
        ret.vehicleNaviJunctionLane = min(255, max(0, int(best["lane"])))
        return
    if hda_fresh and link_class in VEHICLE_NAVI_CONTROLLED_ACCESS_LINK_CLASSES and frw_info in VEHICLE_NAVI_RAMP_FRWINFO_VALUES:
      ret.vehicleNaviJunctionType = 1
      ret.vehicleNaviJunctionSide = 0
      ret.vehicleNaviJunctionDistance = 500.0
      ret.vehicleNaviJunctionLane = 0

  def _update_vehicle_navi_curve_output(self, ret, link_class, frw_info, hda_fresh):
    self.vehicleNaviCurves = [curve for curve in self.vehicleNaviCurves if curve["target"] >= self.totalDistance]
    self.vehicleNaviRampCurves = [curve for curve in self.vehicleNaviRampCurves if curve["target"] >= self.totalDistance]
    curve_road_allowed = hda_fresh and link_class in VEHICLE_NAVI_CURVE_ALLOWED_LINK_CLASSES
    ret.vehicleNaviCurveRoadAllowed = curve_road_allowed
    ret.vehicleNaviCurveRouteActive = self.vehicleNaviCurveRouteActive
    ret.vehicleNaviCurveRouteState = self.vehicleNaviCurveRouteState
    ret.vehicleNaviFrwInfo = min(255, max(0, int(frw_info))) if curve_road_allowed else 0
    if not curve_road_allowed or self.vehicleNaviCurveRouteState not in (0, 1):
      return

    candidates_raw = [(curve, False) for curve in self.vehicleNaviCurves]
    left_blinker = bool(getattr(ret, "leftBlinker", False))
    right_blinker = bool(getattr(ret, "rightBlinker", False))
    single_blinker = left_blinker != right_blinker
    blinker_side = 1 if left_blinker else (2 if right_blinker else 0)
    upcoming_exits = [j for j in self.vehicleNaviJunctions
                      if j["type"] == 1 and j["end"] >= self.totalDistance and j["start"] - self.totalDistance <= 600.0]
    expected_exit_side = next((j["side"] for j in upcoming_exits if j["side"] in (1, 2)), 0)
    ramp_armed = bool(self.vehicleNaviRampCurveControl and frw_info in VEHICLE_NAVI_RAMP_FRWINFO_VALUES and
                      single_blinker and blinker_side == expected_exit_side)
    if ramp_armed:
      candidates_raw.extend((curve, True) for curve in self.vehicleNaviRampCurves)

    candidates = []
    for curve, is_ramp in candidates_raw:
      if curve["speed"] >= 250.0:
        continue
      distance = curve["target"] - self.totalDistance
      target_speed = max(self.vehicleNaviCurveLowerLimit, curve["speed"] * self.vehicleNaviCurveSpeedFactor)
      safe_speed = target_speed / CV.MS_TO_KPH
      decel_distance = max(0.0, distance - safe_speed * self.vehicleNaviCurveControlEnd)
      preview_speed = math.sqrt(safe_speed ** 2 + 2.0 * self.vehicleNaviCurveDecelRate * decel_distance) * CV.MS_TO_KPH
      candidates.append((preview_speed, distance, target_speed, curve, is_ramp))

    if candidates:
      _, distance, target_speed, curve, is_ramp = min(candidates, key=lambda item: item[0])
      ret.vehicleNaviCurveDistance = distance
      ret.vehicleNaviCurveSpeed = curve["speed"]
      ret.vehicleNaviCurveTargetSpeed = target_speed
      ret.vehicleNaviCurveCurvature = curve["curvature"]
      ret.vehicleNaviCurveIsRamp = is_ramp

  def _clear_vehicle_navi_route_filtered_events(self):
    if self.vehicleNaviCanControl < 2:
      return

    filtered_types = ("bump",) if self.vehicleNaviCanControl == 2 else ("camera", "bump")
    self.vehicleNaviEvents = [event for event in self.vehicleNaviEvents if event["type"] not in filtered_types]
    if self.vehicleNaviCameraStatusEvent is not None and self.vehicleNaviCameraStatusEvent not in self.vehicleNaviEvents:
      self.vehicleNaviCameraStatusEvent = None
      self.vehicleNaviCameraTarget = None
    if self.vehicleNaviCanControl == 3:
      self._clear_vehicle_navi_speed_zone()

  def _clear_vehicle_navi_school_zone(self):
    self.vehicleNaviSchoolZoneActive = False
    self.vehicleNaviSchoolZoneStartDistance = self.totalDistance
    self.vehicleNaviSchoolZoneUsesCameraStatus = False

  def _clear_vehicle_navi_speed_zone(self):
    self.vehicleNaviSpeedZoneActive = False
    self.vehicleNaviSpeedZoneSpeed = 0.0

  def _is_alt_legacy_navi_arch(self):
    # 표준 세그먼트(0x4B9)를 쓰지 않고 대체 POSITION(0x4DE) 또는 세그먼트(0x4B5)를 수신하는 순정내비 여부.
    return (not self.canfd_wrapped_navi and not self.canfd_ev4_navi and
            not self.vehicleNaviSegment4b9Seen and
            (self.vehicleNaviPosition4deSeen or self.vehicleNaviSegment4b5Seen))

  def _gv80_update_road_horizon(self, start_distance, road_class):
    # 0x4B4/0x4B5 호라이즌(전방 구간별 도로등급)에 한 구간을 반영한다.
    if road_class <= 0:
      return
    cover = None
    for entry in self.vehicleNaviRoadHorizon:
      if entry[0] <= self.totalDistance:
        cover = entry
    horizon = [entry for entry in self.vehicleNaviRoadHorizon if entry[0] < start_distance - 15.0]
    if cover is not None and cover not in horizon:
      horizon.append(cover)
    horizon.append((start_distance, road_class))
    horizon.sort(key=lambda entry: entry[0])
    behind = [i for i, entry in enumerate(horizon) if entry[0] <= self.totalDistance]
    if len(behind) > 1:
      horizon = horizon[behind[-1]:]
    if len(horizon) > 32:
      horizon = horizon[:32]
    self.vehicleNaviRoadHorizon = horizon

  def _gv80_current_road_class(self):
    current = None
    for start_distance, road_class in self.vehicleNaviRoadHorizon:
      if start_distance > self.totalDistance:
        break
      current = road_class
    return current

  def _gv80_bump_output_allowed(self):
    # 방지턱 출력 게이트: 생활·이면도로(등급 6)이거나 스쿨존일 때만.
    if self.vehicleNaviSchoolZoneActive:
      return True
    return self._gv80_current_road_class() == 6

  def _gv80_bump_event_allowed(self, event, v_ego, on_controlled_access_road, speed_limit=0.0):
    if self._gv80_bump_output_allowed():
      return True
    if on_controlled_access_road or self._gv80_current_road_class() != 5:
      return False
    if speed_limit >= VEHICLE_NAVI_GV80_FRC5_BUMP_MAX_SPEED_LIMIT:
      return False
    if not event.get("reconfirmed", False):
      return False
    min_offset = event.get("min_offset", event["target"] - self.totalDistance)
    return (v_ego <= VEHICLE_NAVI_GV80_FRC5_BUMP_MAX_SPEED and
            min_offset <= VEHICLE_NAVI_GV80_FRC5_BUMP_MAX_MIN_OFFSET)

  def _gv80_prune_bumps_on_reset(self, road_class_4b4):
    steer_hist = getattr(self, "vehicleNaviGv80SteerHistory", None)
    max_abs_steer = max(steer_hist, default=0.0) if steer_hist else 0.0
    major_road_entry = 1 <= road_class_4b4 <= 4
    if max_abs_steer < VEHICLE_NAVI_GV80_RESET_TURN_STEER_DEG and not major_road_entry:
      return

    keep_ids = set()
    last_kept_target = None
    for event in self.vehicleNaviEvents:
      if event["type"] != "bump":
        continue
      dist = event["target"] - self.totalDistance
      if dist <= VEHICLE_NAVI_GV80_BUMP_RESET_KEEP_DISTANCE:
        keep_ids.add(id(event))
        last_kept_target = event["target"]
      elif (last_kept_target is not None and
            event["target"] - last_kept_target <= VEHICLE_NAVI_GV80_BUMP_PAIR_CHAIN_GAP and
            dist <= VEHICLE_NAVI_GV80_BUMP_PAIR_MAX_KEEP):
        keep_ids.add(id(event))
        last_kept_target = event["target"]

    self.vehicleNaviEvents = [event for event in self.vehicleNaviEvents
                              if event["type"] != "bump" or id(event) in keep_ids]

  def _pv5_navi_message_fresh(self, cp, parser, name, address, size):
    if parser is None:
      return False
    timestamp = self._vehicle_navi_message_timestamp(parser, name)
    age = cp._last_update_nanos - timestamp
    return (timestamp > 0 and 0 <= age <= CANFD_NAVI_STATUS_TIMEOUT_NS and
            not parser.bus_timeout and len(parser.dat.get(address, b"")) == size)

  def _update_pv5_camera_warning(self, cp, cp_alt):
    # A-CAN 0x380 is not read on this branch (cp_alt None): no PV5 camera warning, see the module note.
    event = self.vehicleNaviCameraStatusEvent
    if event is not None and event["target"] <= self.totalDistance:
      self.pv5_completed_camera_speed = event["speed"]
      self.vehicleNaviEvents = [candidate for candidate in self.vehicleNaviEvents if candidate is not event]
      self.vehicleNaviCameraStatusEvent = None

    fresh = (self._pv5_navi_message_fresh(cp, cp, CANFD_HDA_INFO_MSG, 0x364, 16) and
             self._pv5_navi_message_fresh(cp, cp_alt, CANFD_NAVI_STATUS_MSG, 0x380, 24) and
             self.hda_info_4a3 is not None and self.navi_status_380 is not None)
    speed = self.hda_info_4a3["SPEED_LIMIT"] * (1 if self.is_metric else CV.MPH_TO_KPH) if fresh else 0
    map_warning = fresh and int(self.hda_info_4a3["MapSource"]) == 2 and 0 < self.hda_info_4a3["SPEED_LIMIT"] < 255
    previous_speed = self.vehicleNaviCameraStatusSpeed or self.pv5_completed_camera_speed
    if not map_warning or (previous_speed and speed != previous_speed):
      self.vehicleNaviEvents = [candidate for candidate in self.vehicleNaviEvents if candidate["type"] != "camera"]
      self.vehicleNaviCameraStatusEvent = None
      self.vehicleNaviCameraTarget = None
      self.vehicleNaviCameraStatusTarget = None
      self.vehicleNaviCameraStatusSpeed = 0
      profile_event = (self._classify_vehicle_navi_profile(self._decode_vehicle_navi_profile(self.navi_profile_4be))
                       if self.navi_profile_4be is not None else None)
      if profile_event is not None and profile_event[0] == "camera":
        self.vehicleNaviProfileTimestamp = max(self.vehicleNaviProfileTimestamp,
                                               self._vehicle_navi_message_timestamp(cp, self.navi_profile_msg))

    if not fresh:
      return False
    if not map_warning or speed != self.pv5_completed_camera_speed:
      self.pv5_completed_camera_speed = 0
    return map_warning and self.pv5_completed_camera_speed == 0

  def _update_pv5_navi_section(self, cp, cp_alt):
    status_valid = self._pv5_navi_message_fresh(cp, cp_alt, CANFD_NAVI_STATUS_MSG, 0x380, 24)
    hda_valid = self._pv5_navi_message_fresh(cp, cp, CANFD_HDA_INFO_MSG, 0x364, 16)
    if not status_valid or not hda_valid or self.navi_status_380 is None or self.hda_info_4a3 is None:
      self._clear_vehicle_navi_speed_zone()
      self.pv5_section_start_prev = True
      return

    start = bool(self.navi_status_380["SECTION_ALERT"])
    rising = start and not self.pv5_section_start_prev
    self.pv5_section_start_prev = start
    speed = int(self.navi_status_380["SPEED_LIMIT"])
    valid_limit = (30 < speed <= 150 and speed % 5 == 0 and
                   speed == int(self.hda_info_4a3["SPEED_LIMIT"]) and
                   int(self.hda_info_4a3["MapSource"]) == 2)
    if not self.vehicleNaviCanControl or not valid_limit:
      self._clear_vehicle_navi_speed_zone()
      return

    speed_kph = speed if self.is_metric else speed * CV.MPH_TO_KPH
    if self.vehicleNaviSpeedZoneActive and speed_kph != self.vehicleNaviSpeedZoneSpeed:
      self._clear_vehicle_navi_speed_zone()
    if rising:
      self.vehicleNaviSpeedZoneActive = True
      self.vehicleNaviSpeedZoneSpeed = speed_kph

  @staticmethod
  def _vehicle_navi_curve_timestamp(cp, name):
    layouts = {
      CANFD_NAVI_PROSHORT_MSG: (0x094, 32), CANFD_NAVI_RAMP_MSG: (0x098, 16),
      CANFD_NAVI_STUB_MSG: (0x09A, 24), CANFD_NAVI_SEGMENT_MSG: (0x099, 24),
      LEGACY_NAVI_PROSHORT_MSG: (0x4BA, 8), LEGACY_NAVI_PROSHORT_4B7_MSG: (0x4B7, 8),
      LEGACY_NAVI_RAMP_4B0_MSG: (0x4B0, 8), LEGACY_NAVI_STUB_MSG: (0x4BF, 8),
      "NEW_MSG_4B9": (0x4B9, 8), "HDA_INFO_4A3": (0x4A3, 8), CANFD_HDA_INFO_MSG: (0x364, 16),
    }
    address, size = layouts[name]
    if len(cp.dat.get(address, b"")) != size:
      return 0
    stamp = VehicleNaviMixin._vehicle_navi_message_timestamp(cp, name)
    now = getattr(cp, "_last_update_nanos", 0)
    return stamp if stamp > 0 and 0 <= now - stamp <= VEHICLE_NAVI_HDA_TIMEOUT_NS else 0

  @staticmethod
  def _vehicle_navi_message_timestamp(cp, name):
    return max(cp.ts_nanos.get(name, {}).values(), default=0)

  @staticmethod
  def _decode_vehicle_navi_segment(values):
    raw = sum(int(values.get(f"BYTE_{i + 1}", 0)) << (i * 8) for i in range(8))
    return {
      "offset": raw & 0x1fff,
      "path_index": (raw >> 13) & 0x3f,
      "calculated_route": (raw >> 22) & 0x3,
      "functional_road_class": (raw >> 24) & 0x7,
    }

  def _vehicle_navi_is_controlled_access_road(self):
    link_class = int(self.hda_info_4a3.get("LinkClass", 0)) if self.hda_info_4a3 is not None else 0
    return (link_class in VEHICLE_NAVI_CONTROLLED_ACCESS_LINK_CLASSES or
            self.vehicleNaviRoadClass in VEHICLE_NAVI_CONTROLLED_ACCESS_ROAD_CLASSES)

  @staticmethod
  def _decode_vehicle_navi_profile(values):
    return {
      "value": int(values.get("PROLONG_VALUE", 0xffffffff)),
      "offset": int(values.get("PROLONG_OFFSET", 8191)),
      "counter": int(values.get("PROLONG_CYCLIC_COUNTER", 0)),
      "update": int(values.get("PROLONG_UPDATE", 0)),
      "path_index": int(values.get("PROLONG_PATH_INDEX", 0)),
      "profile_type": int(values.get("PROLONG_PROFILE_TYPE", 31)),
    }

  def _vehicle_navi_profile_allowed(self, event_type, profile):
    if not self.vehicleNaviCanControl:
      return False
    # Mode 1 accepts all future profiles. Mode 2 route-gates bumps, and mode 3 route-gates cameras and bumps.
    route_required = (self.vehicleNaviCanControl == 3 or
                      (self.vehicleNaviCanControl == 2 and event_type == "bump"))
    if not route_required:
      return True
    return (self.vehicleNaviRouteState == 1 and
            profile["path_index"] == self.vehicleNaviRoutePathIndex)

  @staticmethod
  def _classify_vehicle_navi_profile(profile):
    if profile["profile_type"] != 16:
      return None

    value = profile["value"]
    if 0 < value <= 0x1ff:
      kind = value & 0xf
      speed_code = value >> 4
      if kind == 7 and profile["offset"] == 0 and 1 < speed_code <= 31:
        return "speed_limit_zone", (speed_code - 1) * 5, kind

    if not 0 < profile["offset"] <= VEHICLE_NAVI_MAX_EVENT_DISTANCE:
      return None
    if value == 6:
      return "bump", 0, 6
    if value == 9:
      return "school_zone", 30, 9

    if not 0 < value <= 0x1ff:
      return None
    kind = value & 0xf
    speed_code = value >> 4
    if kind not in VEHICLE_NAVI_CAMERA_KINDS or not 1 < speed_code <= 31:
      return None
    return "camera", (speed_code - 1) * 5, kind

  def _handle_vehicle_navi_profile(self, values, timestamp, ret, speed_limit_cam, on_controlled_access_road):
    profile = self._decode_vehicle_navi_profile(values)
    if (not self.canfd_wrapped_navi and profile["profile_type"] == 16 and
        timestamp > self.vehicleNaviRouteResetTimestamp):
      self.speedcam_policy.add_preview(profile["value"], profile["offset"], self.totalDistance)
    event = self._classify_vehicle_navi_profile(profile)
    if event is not None and timestamp > self.vehicleNaviRouteResetTimestamp:
      if event[0] == "speed_limit_zone":
        if self.vehicleNaviZoneControlSupported:
          if not self._is_alt_legacy_navi_arch() and self._vehicle_navi_profile_allowed("camera", profile) and event[1] > 30:
            self.vehicleNaviSpeedZoneActive = True
            self.vehicleNaviSpeedZoneSpeed = event[1]
          if self.vehicleNaviSchoolZoneControl:
            # 0x77 describes a generic 30 km/h zone and also appears outside school zones. Only use it for the
            # school cap while 0x4A3 independently confirms an active 30 km/h camera/zone.
            if event[1] == 30 and speed_limit_cam and ret.speedLimit == 30 and not on_controlled_access_road:
              self.vehicleNaviSchoolZoneActive = True
              self.vehicleNaviSchoolZoneStartDistance = self.totalDistance
              self.vehicleNaviSchoolZoneUsesCameraStatus = True
            else:
              self._clear_vehicle_navi_school_zone()
      elif event[0] == "school_zone":
        if (self._is_alt_legacy_navi_arch() and self.vehicleNaviSchoolZoneControl and
            not on_controlled_access_road and self._vehicle_navi_profile_allowed(event[0], profile)):
          self._add_vehicle_navi_event(*event, profile["offset"])
      elif self._vehicle_navi_profile_allowed(event[0], profile) and (not on_controlled_access_road or
                                                                      (event[0] != "bump" and not (event[0] == "camera" and event[1] == 30))):
        self._add_vehicle_navi_event(*event, profile["offset"])

  def _add_vehicle_navi_event(self, event_type, speed, kind, offset):
    target = self.totalDistance + offset
    for event in self.vehicleNaviEvents:
      if event["type"] == event_type and event["speed"] == speed and event["kind"] == kind and abs(event["target"] - target) < 20:
        event["target"] = target
        if event_type == "bump":
          prev_min = event.get("min_offset", offset)
          if offset < prev_min - VEHICLE_NAVI_GV80_BUMP_RECONFIRM_DELTA:
            event["reconfirmed"] = True
          event["min_offset"] = min(prev_min, offset)
        return

    new_event = {"type": event_type, "speed": speed, "kind": kind, "target": target}
    if event_type == "bump":
      new_event["min_offset"] = offset
    self.vehicleNaviEvents.append(new_event)
    self.vehicleNaviEvents.sort(key=lambda event: event["target"])
    self.vehicleNaviEvents = self.vehicleNaviEvents[:VEHICLE_NAVI_MAX_EVENTS]

  def _update_vehicle_navi_events(self, cp, ret, speed_limit_cam, cp_alt=None):
    ret.speedBumpDistance = 0.0
    ret.schoolZoneActive = False
    ret.vehicleNaviActive = False
    ret.vehicleNaviSectionActive = False
    ret.vehicleNaviSpeed = 0.0
    self.vehicleNaviGv80SteerHistory.append(abs(float(ret.steeringAngleDeg)))
    ret.vehicleNaviCurveDistance = 0.0
    ret.vehicleNaviCurveSpeed = 0.0
    ret.vehicleNaviCurveCurvature = 0.0
    ret.vehicleNaviCurveRouteActive = self.vehicleNaviCurveRouteActive
    ret.vehicleNaviCurveRouteState = self.vehicleNaviCurveRouteState
    ret.vehicleNaviCurveTargetSpeed = 0.0
    ret.vehicleNaviCurveIsRamp = False
    ret.vehicleNaviCurveRoadAllowed = False
    ret.vehicleNaviJunctionType = 0
    ret.vehicleNaviJunctionSide = 0
    ret.vehicleNaviJunctionDistance = 0.0
    ret.vehicleNaviJunctionLane = 0
    ret.vehicleNaviFrwInfo = 0
    if self.canfd_wrapped_navi:
      self._update_pv5_navi_section(cp, cp_alt)
    profile_timestamp = self._vehicle_navi_message_timestamp(cp, self.navi_profile_msg)
    profile_4b8_timestamp = 0
    if len(cp.dat.get(0x4b8, b"")) == 8:
      profile_4b8_timestamp = self._vehicle_navi_message_timestamp(cp, LEGACY_NAVI_PROFILE_4B8_MSG)
      profile_timestamp = max(profile_timestamp, profile_4b8_timestamp)
    hda_timestamp = self._vehicle_navi_message_timestamp(cp, self.hda_info_msg) if self.canfd_ev4_navi else 0
    self.vehicleNaviAvailable = self.vehicleNaviAvailable or profile_timestamp > 0 or hda_timestamp > 0 or self.vehicleNaviSpeedZoneActive
    ret.vehicleNaviAvailable = self.vehicleNaviAvailable
    self.vehicleNaviCameraTarget = None

    # Track the current warning independently of future 0x4BE previews.
    camera_status_speed = ret.speedLimit if speed_limit_cam else 0
    if camera_status_speed != self.vehicleNaviCameraStatusSpeed:
      self.vehicleNaviCameraStatusTarget = (self.totalDistance + camera_status_speed * self.vehicleSpeedCameraDistanceTime
                                            if camera_status_speed > 0 else None)
      self.vehicleNaviCameraStatusSpeed = camera_status_speed

    # 0x4B4 is periodic while the stock navigation is running. Its range average speed is zero outside a
    # section-camera zone and valid inside it.
    position_timestamp = self._vehicle_navi_message_timestamp(cp, "NEW_MSG_4B4")
    position_seen = position_timestamp > 0
    position_age = getattr(cp, "_last_update_nanos", position_timestamp) - position_timestamp
    position_recent = position_seen and 0 <= position_age <= VEHICLE_NAVI_POSITION_TIMEOUT_NS
    range_avg_speed = (int(self.navi_position_4b4.get("POS_RANGE_AVG_SPEED", 0))
                       if position_recent and self.navi_position_4b4 is not None else 0)
    range_section_active = 0 < range_avg_speed < 511

    if self.navi_segment_4b9 is not None:
      timestamp = self._vehicle_navi_message_timestamp(cp, self.navi_segment_msg)
      empty_wrapped_segment = self.canfd_ev4_navi and all(
        int(self.navi_segment_4b9.get(f"BYTE_{i + 1}", 0)) == 0xff for i in range(8))
      if timestamp > 0 and not empty_wrapped_segment:
        self.vehicleNaviSegment4b9Seen = True
      if timestamp > self.vehicleNaviSegmentTimestamp and not empty_wrapped_segment:
        self.vehicleNaviSegmentTimestamp = timestamp
        segment = self._decode_vehicle_navi_segment(self.navi_segment_4b9)
        if self._vehicle_navi_curve_timestamp(cp, self.navi_segment_msg):
          self._apply_vehicle_navi_curve_segment(segment, timestamp)
        previous_route_state = self.vehicleNaviRouteState
        previous_path_index = self.vehicleNaviRoutePathIndex
        self.vehicleNaviRouteState = segment["calculated_route"]
        self.vehicleNaviRoutePathIndex = (segment["path_index"]
                                          if segment["calculated_route"] in (0, 1) else None)
        if segment["functional_road_class"] != 7:
          self.vehicleNaviRoadClass = segment["functional_road_class"]
        if segment["calculated_route"] == 2:
          self.vehicleNaviRouteResetTimestamp = timestamp
          self._clear_vehicle_navi_events()
          self._clear_vehicle_navi_speed_zone()
          self._clear_vehicle_navi_school_zone()
        elif (self.vehicleNaviCanControl >= 2 and
              (segment["calculated_route"] != 1 or
               (previous_route_state == 1 and previous_path_index != segment["path_index"]))):
          self._clear_vehicle_navi_route_filtered_events()

    position_4de_recent_valid = False
    range_section_active_4de = False
    if (not self.canfd_wrapped_navi and not self.canfd_ev4_navi and
        len(cp.dat.get(0x4DE, b"")) == 8 and self.navi_position_4de is not None):
      position_4de_timestamp = self._vehicle_navi_message_timestamp(cp, LEGACY_NAVI_POSITION_4DE_MSG)
      if position_4de_timestamp > 0:
        off_4de = int(self.navi_position_4de.get("POS_OFFSET", VEHICLE_NAVI_POSITION_INVALID_OFFSET))
        path_4de = int(self.navi_position_4de.get("POS_PATH_INDEX", 0))
        avg_4de = int(self.navi_position_4de.get("POS_RANGE_AVG_SPEED", VEHICLE_NAVI_POSITION_INVALID_AVG_SPEED))
        frame_valid_4de = (off_4de != VEHICLE_NAVI_POSITION_INVALID_OFFSET and
                           path_4de not in (0, 63) and
                           avg_4de != VEHICLE_NAVI_POSITION_INVALID_AVG_SPEED)
        frame_sentinel_4de = (off_4de == VEHICLE_NAVI_POSITION_INVALID_OFFSET and
                              path_4de == 0 and
                              avg_4de == VEHICLE_NAVI_POSITION_INVALID_AVG_SPEED)
        if (frame_valid_4de or frame_sentinel_4de) and not self.vehicleNaviSegment4b9Seen:
          self.vehicleNaviPosition4deSeen = True
        age_4de = getattr(cp, "_last_update_nanos", position_4de_timestamp) - position_4de_timestamp
        if frame_valid_4de and 0 <= age_4de <= VEHICLE_NAVI_POSITION_TIMEOUT_NS:
          position_4de_recent_valid = True
          range_section_active_4de = 0 < avg_4de < VEHICLE_NAVI_POSITION_INVALID_AVG_SPEED

    if (not self.canfd_wrapped_navi and not self.canfd_ev4_navi and
        not self.vehicleNaviSegment4b9Seen and self.navi_segment_4b5 is not None and
        (len(cp.dat.get(0x4B5, b"")) == 8 or self.vehicleNaviSegment4b5Seen)):
      # 0x4B9가 아니라 0x4B5로 세그먼트를 내보내는 순정내비(예: GV80)
      timestamp_4b5 = (self._vehicle_navi_message_timestamp(cp, LEGACY_NAVI_SEGMENT_4B5_MSG)
                       if len(cp.dat.get(0x4B5, b"")) == 8 else 0)
      if timestamp_4b5 > self.vehicleNaviSegment4b5Timestamp:
        self.vehicleNaviSegment4b5Timestamp = timestamp_4b5
        segment_4b5 = self._decode_vehicle_navi_segment(self.navi_segment_4b5)
        road_class_4b5 = int(self.navi_segment_4b5.get("BYTE_5", 0)) & 0x7
        if (segment_4b5["path_index"] not in (0, 63) and
            segment_4b5["offset"] != VEHICLE_NAVI_POSITION_INVALID_OFFSET and
            road_class_4b5 != 7):
          self.vehicleNaviSegment4b5Seen = True
        if (self.vehicleNaviSegment4b5Seen and segment_4b5["path_index"] not in (0, 63) and
            segment_4b5["offset"] != VEHICLE_NAVI_POSITION_INVALID_OFFSET and road_class_4b5 != 7):
          self._gv80_update_road_horizon(self.totalDistance + segment_4b5["offset"], road_class_4b5)
          guidance_active = bool(int(self.navi_segment_4b5.get("BYTE_5", 0)) & VEHICLE_NAVI_SEGMENT_4B5_ACTIVE_MASK)
          self._apply_vehicle_navi_curve_segment(
            {"calculated_route": 1 if guidance_active else 0, "path_index": segment_4b5["path_index"]},
            timestamp_4b5,
          )
          # 0x4B5 also carries STUB diverge (0x49) / merge (0x01) branch type in byte 3 and turn angle in byte 5.
          dat_4b5 = cp.dat.get(0x4B5, b"")
          if len(dat_4b5) == 8 and timestamp_4b5 > self.vehicleNaviRouteResetTimestamp:
            raw_4b5 = int.from_bytes(dat_4b5, "little")
            stub_4b5 = self._decode_vehicle_navi_stub({
              "STUB_OFFSET": raw_4b5 & 0x1fff,
              "STUB_PATH_INDEX": (raw_4b5 >> 13) & 0x3f,
              "STUB_BRANCH_TYPE": dat_4b5[3],
              "STUB_TURN_ANGLE": int.from_bytes(dat_4b5[5:6], "little", signed=True) * 1.40625,
            })
            if stub_4b5 is not None and (self.vehicleNaviCurvePathIndex is None or stub_4b5["path_index"] == self.vehicleNaviCurvePathIndex):
              self._add_vehicle_navi_junction(stub_4b5)
          if guidance_active:
            self.vehicleNaviSegmentTimestamp = timestamp_4b5
            previous_route_state = self.vehicleNaviRouteState
            previous_path_index = self.vehicleNaviRoutePathIndex
            self.vehicleNaviRouteState = 1
            self.vehicleNaviRoutePathIndex = segment_4b5["path_index"]
            self.vehicleNaviSegment4b5Active = True
            if (self.vehicleNaviCanControl >= 2 and previous_route_state == 1 and
                previous_path_index != self.vehicleNaviRoutePathIndex):
              self._clear_vehicle_navi_route_filtered_events()
          else:
            if self.vehicleNaviSegment4b5Active:
              self.vehicleNaviRouteResetTimestamp = timestamp_4b5
              self.vehicleNaviRouteState = 2
              self.vehicleNaviRoutePathIndex = None
              self._clear_vehicle_navi_events()
              self._clear_vehicle_navi_curves()
              self._clear_vehicle_navi_speed_zone()
              self._clear_vehicle_navi_school_zone()
            self.vehicleNaviSegment4b5Active = False
      elif (self.vehicleNaviSegment4b5Active and
            getattr(cp, "_last_update_nanos", 0) - self.vehicleNaviSegmentTimestamp > VEHICLE_NAVI_SEGMENT_4B5_TIMEOUT_NS):
        # 안내가 끝나면 0x4B5 자체가 끊기는 경우: 스트림 중단도 경로 종료로 본다.
        self.vehicleNaviRouteResetTimestamp = getattr(cp, "_last_update_nanos", 0)
        self.vehicleNaviRouteState = 2
        self.vehicleNaviRoutePathIndex = None
        self.vehicleNaviSegment4b5Active = False
        self._clear_vehicle_navi_events()
        self._clear_vehicle_navi_curves()
        self._clear_vehicle_navi_speed_zone()
        self._clear_vehicle_navi_school_zone()

    alt_navi_arch = self._is_alt_legacy_navi_arch()
    if alt_navi_arch:
      # 0x4B5/0x4DE 계열에서는 0x4B4 bits 21|9 자리가 구간 평균속도가 아니라 도로등급 바이트와 겹친다.
      range_section_active = False
      position_dat = cp.dat.get(0x4B4, b"")
      if len(position_dat) == 8 and position_timestamp > self.vehicleNaviGv80HorizonTimestamp:
        self.vehicleNaviGv80HorizonTimestamp = position_timestamp
        raw_4b4 = int.from_bytes(position_dat, "little")
        path_index_4b4 = (raw_4b4 >> 13) & 0x3f
        road_class_4b4 = position_dat[3] & 0x7
        if path_index_4b4 == 0:
          self.vehicleNaviRoadHorizon = ([(self.totalDistance, road_class_4b4)]
                                         if road_class_4b4 > 0 else [])
          self._gv80_prune_bumps_on_reset(road_class_4b4)
          self.vehicleNaviRouteResetTimestamp = position_timestamp
          self._clear_vehicle_navi_curves()
        elif path_index_4b4 == 8:
          self._gv80_update_road_horizon(self.totalDistance + (raw_4b4 & 0x1fff), road_class_4b4)
          if self.vehicleNaviCurveRouteState not in (0, 1):
            self._apply_vehicle_navi_curve_segment({"calculated_route": 0, "path_index": 8}, position_timestamp)

    if self.canfd_wrapped_navi and self.navi_curve_segment_099 is not None and CANFD_NAVI_SEGMENT_MSG in cp.ts_nanos:
      timestamp = self._vehicle_navi_curve_timestamp(cp, CANFD_NAVI_SEGMENT_MSG)
      if timestamp > self.vehicleNaviCurveSegmentTimestamp and not all(int(self.navi_curve_segment_099.get(f"BYTE_{i + 1}", 0)) == 0xff for i in range(8)):
        self.vehicleNaviCurveSegmentTimestamp = timestamp
        curve_segment = self._decode_vehicle_navi_segment(self.navi_curve_segment_099)
        self._apply_vehicle_navi_curve_segment(curve_segment, timestamp)

    route_age = getattr(cp, "_last_update_nanos", max(profile_timestamp, self.vehicleNaviSegmentTimestamp)) - self.vehicleNaviSegmentTimestamp
    route_owned_by_4b5 = alt_navi_arch and self.vehicleNaviSegment4b5Active
    if (self.vehicleNaviCanControl >= 2 and self.vehicleNaviRouteState == 1 and
        not route_owned_by_4b5 and
        (route_age < 0 or route_age > VEHICLE_NAVI_ROUTE_TIMEOUT_NS)):
      self.vehicleNaviRouteState = 0
      self.vehicleNaviRoutePathIndex = None
      self._clear_vehicle_navi_route_filtered_events()

    curve_route_age = getattr(cp, "_last_update_nanos", 0) - self.vehicleNaviCurveSegmentTimestamp
    curve_route_timeout = VEHICLE_NAVI_SEGMENT_4B5_TIMEOUT_NS if alt_navi_arch else VEHICLE_NAVI_ROUTE_TIMEOUT_NS
    if self.vehicleNaviCurveRouteState in (0, 1) and not 0 <= curve_route_age <= curve_route_timeout:
      self.vehicleNaviCurveRouteState = 3
      self.vehicleNaviCurveRouteActive = False
      self.vehicleNaviCurvePathIndex = None
      self._clear_vehicle_navi_curves()

    self._consume_vehicle_navi_proshort(cp)
    self._consume_vehicle_navi_ramp_and_stub(cp)
    link_class, frw_info, hda_fresh = self._vehicle_navi_hda_state(cp)
    self._update_vehicle_navi_curve_output(ret, link_class, frw_info, hda_fresh)
    self._update_vehicle_navi_junction_output(ret, link_class, frw_info, hda_fresh)

    on_controlled_access_road = self._vehicle_navi_is_controlled_access_road()
    if on_controlled_access_road:
      self._clear_vehicle_navi_school_zone()
    if not (self.vehicleNaviCanControl or self.vehicleNaviSchoolZoneControl):
      return False

    # Both addresses use the same policy. Consume each new profile once and in timestamp order.
    profiles = (
      (self._vehicle_navi_message_timestamp(cp, self.navi_profile_msg), self.navi_profile_4be, "vehicleNaviProfileTimestamp"),
      (profile_4b8_timestamp, self.navi_profile_4b8, "vehicleNaviProfile4b8Timestamp"),
    )
    for timestamp, values, timestamp_attr in sorted(profiles, key=lambda profile: profile[0]):
      if values is not None and timestamp > getattr(self, timestamp_attr):
        setattr(self, timestamp_attr, timestamp)
        self._handle_vehicle_navi_profile(values, timestamp, ret, speed_limit_cam, on_controlled_access_road)

    if alt_navi_arch and position_4de_recent_valid:
      if not range_section_active_4de or not self.vehicleNaviCanControl or 0 < ret.speedLimit <= 30:
        self._clear_vehicle_navi_speed_zone()
      elif 30 < ret.speedLimit < 255:
        self.vehicleNaviSpeedZoneActive = True
        self.vehicleNaviSpeedZoneSpeed = ret.speedLimit
    elif alt_navi_arch:
      # A persistent camera warning alone does not establish a section.
      self._clear_vehicle_navi_speed_zone()
    elif position_seen:
      if not range_section_active or not self.vehicleNaviCanControl or 0 < ret.speedLimit <= 30:
        self._clear_vehicle_navi_speed_zone()
      elif 30 < ret.speedLimit < 255:
        self.vehicleNaviSpeedZoneActive = True
        self.vehicleNaviSpeedZoneSpeed = ret.speedLimit

    self.vehicleNaviEvents = [event for event in self.vehicleNaviEvents
                              if event["target"] >= self.totalDistance - VEHICLE_NAVI_PASSED_EVENT_DISTANCE and
                              (not on_controlled_access_road or
                               (event["type"] != "bump" and not (event["type"] == "camera" and event["speed"] == 30)))]

    status_event = self.vehicleNaviCameraStatusEvent
    if self.canfd_wrapped_navi:
      if status_event is not None and not any(event is status_event for event in self.vehicleNaviEvents):
        status_event = None
      if status_event is None and speed_limit_cam:
        matching_cameras = [event for event in self.vehicleNaviEvents
                            if event["type"] == "camera" and event["speed"] == camera_status_speed and
                            self.totalDistance < event["target"] <=
                            (self.vehicleNaviCameraStatusTarget or self.totalDistance) + VEHICLE_NAVI_CAMERA_MATCH_MARGIN]
        if matching_cameras:
          status_event = matching_cameras[0]
      self.vehicleNaviCameraStatusEvent = status_event
    elif speed_limit_cam:
      if status_event is not None and status_event["speed"] != camera_status_speed:
        self.vehicleNaviEvents = [event for event in self.vehicleNaviEvents if event is not status_event]
        status_event = None
      if status_event is None:
        matching_cameras = [event for event in self.vehicleNaviEvents
                            if event["type"] == "camera" and event["speed"] == camera_status_speed and
                            self.totalDistance - VEHICLE_NAVI_PASSED_EVENT_DISTANCE <= event["target"] <=
                            (self.vehicleNaviCameraStatusTarget or self.totalDistance) + VEHICLE_NAVI_CAMERA_MATCH_MARGIN]
        if matching_cameras:
          status_event = matching_cameras[0]
      self.vehicleNaviCameraStatusEvent = status_event
    elif status_event is not None:
      self.vehicleNaviEvents = [event for event in self.vehicleNaviEvents if event is not status_event]
      self.vehicleNaviCameraStatusEvent = None

    upcoming = [event for event in self.vehicleNaviEvents if event["target"] > self.totalDistance]

    bumps = [event for event in upcoming if event["type"] == "bump"]
    if alt_navi_arch and bumps:
      v_ego = float(getattr(ret, "vEgo", 0.0))
      speed_limit = float(getattr(ret, "speedLimit", 0.0))
      bumps = [event for event in bumps
               if self._gv80_bump_event_allowed(event, v_ego, on_controlled_access_road, speed_limit)]
    if bumps:
      ret.speedBumpDistance = bumps[0]["target"] - self.totalDistance

    if (self.vehicleNaviSpeedZoneActive and not self.canfd_wrapped_navi and
        not (position_seen or position_4de_recent_valid) and not speed_limit_cam):
      self._clear_vehicle_navi_speed_zone()

    if self.vehicleNaviSchoolZoneActive:
      camera_status_ended = (self.vehicleNaviSchoolZoneUsesCameraStatus and
                             (not speed_limit_cam or ret.speedLimit != 30))
      distance_expired = self.totalDistance - self.vehicleNaviSchoolZoneStartDistance >= VEHICLE_NAVI_SCHOOL_ZONE_MAX_DISTANCE
      if camera_status_ended or distance_expired:
        self._clear_vehicle_navi_school_zone()

    school_zone_pre_active = False
    if alt_navi_arch and self.vehicleNaviSchoolZoneControl and not on_controlled_access_road:
      school_zones = [event for event in upcoming if event["type"] == "school_zone"]
      if school_zones and (school_zones[0]["target"] - self.totalDistance) <= VEHICLE_NAVI_SCHOOL_ZONE_PRE_DISTANCE:
        school_zone_pre_active = True

    if self.vehicleNaviSchoolZoneControl and (self.vehicleNaviSchoolZoneActive or school_zone_pre_active) and not on_controlled_access_road:
      ret.schoolZoneActive = True
      ret.speedLimit = 30
      if self.vehicleNaviCanControl:
        ret.vehicleNaviActive = True
        ret.vehicleNaviSpeed = 30
      return False

    section_control_enabled = self.vehicleNaviCanControl and self.vehicleNaviSpeedZoneActive and self.speedcamSectionAvgControl
    section_suppressed = self.vehicleNaviCanControl and self.vehicleNaviSpeedZoneActive and not self.speedcamSectionAvgControl
    if section_control_enabled:
      ret.vehicleNaviActive = True
      ret.vehicleNaviSectionActive = True
      ret.vehicleNaviSpeed = self.vehicleNaviSpeedZoneSpeed

    cameras = [event for event in upcoming if event["type"] == "camera"]
    if section_suppressed:
      matched_cameras = [event for event in cameras if event["speed"] == camera_status_speed]
      camera = matched_cameras[0] if (speed_limit_cam and matched_cameras) else None
    elif self.canfd_wrapped_navi or alt_navi_arch:
      camera = self.vehicleNaviCameraStatusEvent if speed_limit_cam else None
    else:
      camera = self.vehicleNaviCameraStatusEvent if speed_limit_cam else (cameras[0] if cameras else None)
    if camera is not None:
      self.vehicleNaviCameraTarget = camera["target"]
      ret.speedLimit = int(camera["speed"])
      ret.vehicleNaviActive = True
      if ret.vehicleNaviSpeed <= 0:
        ret.vehicleNaviSpeed = camera["speed"]

    if bumps:
      ret.vehicleNaviActive = True

    return camera is not None

  def update_speed_limit(self, ret, speed_limit_cam, distance_time_changed=None):
    if distance_time_changed is None:
      distance_time_changed = self._update_vehicle_speed_camera_params()
    if self._vehicle_navi_is_controlled_access_road() and ret.speedLimit == 30:
      speed_limit_cam = False
    self.totalDistance += ret.vEgo * DT_CTRL
    section_suppressed = self.vehicleNaviCanControl and self.vehicleNaviSpeedZoneActive and not self.speedcamSectionAvgControl
    if section_suppressed:
      # 구간단속 설정 OFF 시 구간 내부에서는 전방 실물 카메라에만 감속하고 통과 직후 즉시 해제한다.
      if ret.speedLimit > 0 and speed_limit_cam and self.vehicleNaviCameraTarget is not None:
        self.speedLimitDistance = self.vehicleNaviCameraTarget
        ret.speedLimitDistance = max(0.0, self.speedLimitDistance - self.totalDistance)
      else:
        self.speedLimitDistance = self.totalDistance
        ret.speedLimitDistance = 0.0
      return
    if ret.speedLimit > 0 and speed_limit_cam and self.vehicleNaviCanControl and self.vehicleNaviCameraTarget is not None:
      self.speedLimitDistance = self.vehicleNaviCameraTarget
      ret.speedLimitDistance = max(1.0 if self.vehicleNaviCameraStatusTarget is not None else 0.0,
                                   self.speedLimitDistance - self.totalDistance)
    elif ret.speedLimit > 0 and speed_limit_cam and self.vehicleNaviCameraStatusTarget is not None:
      # No nearby matching profile: use the current warning's own fallback.
      self.speedLimitDistance = self.vehicleNaviCameraStatusTarget
      ret.speedLimitDistance = max(1.0, self.speedLimitDistance - self.totalDistance)
    elif ret.speedLimit > 0 and speed_limit_cam:
      if distance_time_changed or self.speedLimitDistance <= self.totalDistance:
        self.speedLimitDistance = self.totalDistance + ret.speedLimit * self.vehicleSpeedCameraDistanceTime
      self.speedLimitDistance = max(self.totalDistance + 1, self.speedLimitDistance)
      ret.speedLimitDistance = self.speedLimitDistance - self.totalDistance
    else:
      self.speedLimitDistance = self.totalDistance
      ret.speedLimitDistance = 0.0


class SteeringRateSign:
  """carrot PR #589: 0x125 STEERING_RATE is an unsigned magnitude on this CAN FD layout; take its sign from the angle."""
  def __init__(self):
    self.angle = None
    self.frame = 0
    self.sign = 0

  def update(self, rate, angle, received, frame):
    if not received and frame - self.frame > 15:
      self.angle, self.sign = None, 0
      return 0.0
    if received:
      if self.angle is not None and frame - self.frame <= 15:
        delta = angle - self.angle
        if abs(delta) > 1e-3:
          self.sign = math.copysign(1.0, delta)
      else:
        self.sign = 0
      self.angle, self.frame = angle, frame
    return rate * self.sign


class FdSignalFix:
  """carrot PR #589 signals (OptechFdSignalFix): 0x412 stop lamp, 0x04A IMU yaw rate, signed 0x125 steering rate and
  the 0x1E5 front corner blind-spot indicators. Each optional message is used only while fresh."""
  def __init__(self):
    self.frame = 0
    self.seen = {}  # (parser id, name) -> last frame received
    self.front_bsd_parser = None
    self.steering_rate_sign = SteeringRateSign()

  def _note(self, cp, name):
    got = cp.vl_all.get(name) if cp is not None else None
    if got and any(len(v) for v in got.values()):
      self.seen[(id(cp), name)] = self.frame
      return True
    return False

  def _fresh(self, cp, name):
    last = self.seen.get((id(cp), name))
    return last is not None and self.frame - last <= SIGNAL_FIX_MSGS[name][3]

  def update(self, cp, cp_cam, ret, enable_bsm):
    self.frame += 1
    for name in SIGNAL_FIX_MSGS:
      self._note(cp, name)
    steering_received = self._note(cp, "STEERING_SENSORS")
    if cp_cam is not None:
      self._note(cp_cam, "BLINDSPOTS_FRONT_CORNER_1")

    lamp = self._fresh(cp, "BRAKE_LIGHT_412") and cp.vl["BRAKE_LIGHT_412"]["STOP_LAMP"] == 1
    ret.brakeLights = bool(ret.brakePressed or lamp)
    if self._fresh(cp, "IMU_01_10MS"):
      ret.yawRate = math.radians(cp.vl["IMU_01_10MS"]["IMU_YawRtVal"])
    ret.steeringRateDeg = self.steering_rate_sign.update(cp.vl["STEERING_SENSORS"]["STEERING_RATE"], ret.steeringAngleDeg,
                                                         steering_received, self.frame)
    if enable_bsm:
      if self.front_bsd_parser is None:
        for parser in (cp, cp_cam):
          if parser is not None and (id(parser), "BLINDSPOTS_FRONT_CORNER_1") in self.seen:
            self.front_bsd_parser = parser
            break
      if self.front_bsd_parser is not None:
        # loss of an admitted channel is not evidence of clearance (carrot front_bsd)
        if self._fresh(self.front_bsd_parser, "BLINDSPOTS_FRONT_CORNER_1"):
          values = self.front_bsd_parser.vl["BLINDSPOTS_FRONT_CORNER_1"]
          left, right = values["INDICATOR_LEFT"] != 0, values["INDICATOR_RIGHT"] != 0
        else:
          left, right = True, True
        ret.leftBlindspot = bool(ret.leftBlindspot or left)
        ret.rightBlindspot = bool(ret.rightBlindspot or right)
