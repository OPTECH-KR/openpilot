import math
import os
from enum import IntEnum
from typing import Dict, Union, Callable, List, Optional

from cereal import log, car
import cereal.messaging as messaging
from common.conversions import Conversions as CV
from common.realtime import DT_CTRL
from selfdrive.locationd.calibrationd import MIN_SPEED_FILTER
from selfdrive.version import get_short_branch

AlertSize = log.ControlsState.AlertSize
AlertStatus = log.ControlsState.AlertStatus
VisualAlert = car.CarControl.HUDControl.VisualAlert
AudibleAlert = car.CarControl.HUDControl.AudibleAlert
EventName = car.CarEvent.EventName


# Alert priorities
class Priority(IntEnum):
  LOWEST = 0
  LOWER = 1
  LOW = 2
  MID = 3
  HIGH = 4
  HIGHEST = 5


# Event types
class ET:
  ENABLE = 'enable'
  PRE_ENABLE = 'preEnable'
  OVERRIDE_LATERAL = 'overrideLateral'
  OVERRIDE_LONGITUDINAL = 'overrideLongitudinal'
  NO_ENTRY = 'noEntry'
  WARNING = 'warning'
  USER_DISABLE = 'userDisable'
  SOFT_DISABLE = 'softDisable'
  IMMEDIATE_DISABLE = 'immediateDisable'
  PERMANENT = 'permanent'


# get event name from enum
EVENT_NAME = {v: k for k, v in EventName.schema.enumerants.items()}


class Events:
  def __init__(self):
    self.events: List[int] = []
    self.static_events: List[int] = []
    self.events_prev = dict.fromkeys(EVENTS.keys(), 0)

  @property
  def names(self) -> List[int]:
    return self.events

  def __len__(self) -> int:
    return len(self.events)

  def add(self, event_name: int, static: bool=False) -> None:
    if static:
      self.static_events.append(event_name)
    self.events.append(event_name)

  def clear(self) -> None:
    self.events_prev = {k: (v + 1 if k in self.events else 0) for k, v in self.events_prev.items()}
    self.events = self.static_events.copy()

  def any(self, event_type: str) -> bool:
    return any(event_type in EVENTS.get(e, {}) for e in self.events)

  def create_alerts(self, event_types: List[str], callback_args=None):
    if callback_args is None:
      callback_args = []

    ret = []
    for e in self.events:
      types = EVENTS[e].keys()
      for et in event_types:
        if et in types:
          alert = EVENTS[e][et]
          if not isinstance(alert, Alert):
            alert = alert(*callback_args)

          if DT_CTRL * (self.events_prev[e] + 1) >= alert.creation_delay:
            alert.alert_type = f"{EVENT_NAME[e]}/{et}"
            alert.event_type = et
            ret.append(alert)
    return ret

  def add_from_msg(self, events):
    for e in events:
      self.events.append(e.name.raw)

  def to_msg(self):
    ret = []
    for event_name in self.events:
      event = car.CarEvent.new_message()
      event.name = event_name
      for event_type in EVENTS.get(event_name, {}):
        setattr(event, event_type, True)
      ret.append(event)
    return ret


class Alert:
  def __init__(self,
               alert_text_1: str,
               alert_text_2: str,
               alert_status: log.ControlsState.AlertStatus,
               alert_size: log.ControlsState.AlertSize,
               priority: Priority,
               visual_alert: car.CarControl.HUDControl.VisualAlert,
               audible_alert: car.CarControl.HUDControl.AudibleAlert,
               duration: float,
               alert_rate: float = 0.,
               creation_delay: float = 0.):

    self.alert_text_1 = alert_text_1
    self.alert_text_2 = alert_text_2
    self.alert_status = alert_status
    self.alert_size = alert_size
    self.priority = priority
    self.visual_alert = visual_alert
    self.audible_alert = audible_alert

    self.duration = int(duration / DT_CTRL)

    self.alert_rate = alert_rate
    self.creation_delay = creation_delay

    self.alert_type = ""
    self.event_type: Optional[str] = None

  def __str__(self) -> str:
    return f"{self.alert_text_1}/{self.alert_text_2} {self.priority} {self.visual_alert} {self.audible_alert}"

  def __gt__(self, alert2) -> bool:
    if not isinstance(alert2, Alert):
      return False
    return self.priority > alert2.priority


class NoEntryAlert(Alert):
  def __init__(self, alert_text_2: str,
               alert_text_1: str = "오픈파일럿을 켤 수 없음",
               visual_alert: car.CarControl.HUDControl.VisualAlert=VisualAlert.none):
    super().__init__(alert_text_1, alert_text_2, AlertStatus.normal,
                     AlertSize.mid, Priority.LOW, visual_alert,
                     AudibleAlert.refuse, 3.)


class NoEntryOneLineAlert(Alert):
  # optech 2026-11-27: the reason alone in one line, without '오픈파일럿을 켤 수 없음' (same sound and time as NoEntryAlert)
  def __init__(self, alert_text_1: str):
    super().__init__(alert_text_1, "", AlertStatus.normal,
                     AlertSize.small, Priority.LOW, VisualAlert.none,
                     AudibleAlert.refuse, 3.)


class SoftDisableAlert(Alert):
  def __init__(self, alert_text_2: str):
    super().__init__("즉시 운전하세요", alert_text_2,
                     AlertStatus.userPrompt, AlertSize.full,
                     Priority.MID, VisualAlert.steerRequired,
                     AudibleAlert.warningSoft, 2.),


# less harsh version of SoftDisable, where the condition is user-triggered
class UserSoftDisableAlert(SoftDisableAlert):
  def __init__(self, alert_text_2: str):
    super().__init__(alert_text_2),
    self.alert_text_1 = "오픈파일럿이 꺼집니다"


class ImmediateDisableAlert(Alert):
  def __init__(self, alert_text_2: str):
    super().__init__("즉시 운전하세요", alert_text_2,
                     AlertStatus.critical, AlertSize.full,
                     Priority.HIGHEST, VisualAlert.steerRequired,
                     AudibleAlert.warningImmediate, 4.),


class EngagementAlert(Alert):
  def __init__(self, audible_alert: car.CarControl.HUDControl.AudibleAlert):
    super().__init__("", "",
                     AlertStatus.normal, AlertSize.none,
                     Priority.MID, VisualAlert.none,
                     audible_alert, .2),


class NormalPermanentAlert(Alert):
  def __init__(self, alert_text_1: str, alert_text_2: str = "", duration: float = 0.2, priority: Priority = Priority.LOWER, creation_delay: float = 0.):
    super().__init__(alert_text_1, alert_text_2,
                     AlertStatus.normal, AlertSize.mid if len(alert_text_2) else AlertSize.small,
                     priority, VisualAlert.none, AudibleAlert.none, duration, creation_delay=creation_delay),


class StartupAlert(Alert):
  def __init__(self, alert_text_1: str, alert_text_2: str = "늘 핸들을 잡고 앞을 보세요", alert_status=AlertStatus.normal):
    super().__init__(alert_text_1, alert_text_2,
                     alert_status, AlertSize.mid,
                     Priority.LOWER, VisualAlert.none, AudibleAlert.none, 2.),


# ********** helper functions **********
def get_display_speed(speed_ms: float, metric: bool) -> str:
  speed = int(round(speed_ms * (CV.MS_TO_KPH if metric else CV.MS_TO_MPH)))
  unit = 'km/h' if metric else 'mph'
  return f"{speed} {unit}"


# ********** alert callback functions **********

AlertCallbackType = Callable[[car.CarParams, car.CarState, messaging.SubMaster, bool, int], Alert]


def soft_disable_alert(alert_text_2: str) -> AlertCallbackType:
  def func(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
    if soft_disable_time < int(0.5 / DT_CTRL):
      return ImmediateDisableAlert(alert_text_2)
    return SoftDisableAlert(alert_text_2)
  return func

def user_soft_disable_alert(alert_text_2: str) -> AlertCallbackType:
  def func(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
    if soft_disable_time < int(0.5 / DT_CTRL):
      return ImmediateDisableAlert(alert_text_2)
    return UserSoftDisableAlert(alert_text_2)
  return func

def startup_master_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  branch = get_short_branch("")  # Ensure get_short_branch is cached to avoid lags on startup
  if "REPLAY" in os.environ:
    branch = "replay"

  return StartupAlert("주의: 시험하지 않은 버전입니다", branch, alert_status=AlertStatus.userPrompt)

def below_engage_speed_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  return NoEntryAlert(f"{get_display_speed(CP.minEnableSpeed, metric)} 미만에서는 켤 수 없음")


def below_steer_speed_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  return Alert(
    f"{get_display_speed(CP.minSteerSpeed, metric)} 미만에서는 조향 안 됨",
    "",
    AlertStatus.userPrompt, AlertSize.small,
    Priority.MID, VisualAlert.steerRequired, AudibleAlert.prompt, 0.4)


def calibration_incomplete_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  return Alert(
    "Calibration in Progress: %d%%" % sm['liveCalibration'].calPerc,
    f"Drive Above {get_display_speed(MIN_SPEED_FILTER, metric)}",
    AlertStatus.normal, AlertSize.mid,
    Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .2)


def no_gps_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  return Alert(
    "GPS 수신 약함",
    "하늘이 보이는데도 이러면 기기 고장",
    AlertStatus.normal, AlertSize.mid,
    Priority.LOWER, VisualAlert.none, AudibleAlert.none, .2, creation_delay=300.)

# *** debug alerts ***

def out_of_space_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  full_perc = round(100. - sm['deviceState'].freeSpacePercent)
  return NormalPermanentAlert("저장 공간 부족", f"{full_perc}% 사용 중")


def posenet_invalid_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  mdl = sm['modelV2'].velocity.x[0] if len(sm['modelV2'].velocity.x) else math.nan
  err = CS.vEgo - mdl
  msg = f"속도 오차 {err:.1f} m/s"
  return NoEntryAlert(msg, alert_text_1="영상 속도 추정 이상")


def process_not_running_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  not_running = [p.name for p in sm['managerState'].processes if not p.running and p.shouldBeRunning]
  msg = ', '.join(not_running)
  return NoEntryAlert(msg, alert_text_1="프로그램 일부가 멈춤")


def comm_issue_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  bs = [s for s in sm.data.keys() if not sm.all_checks([s, ])]
  msg = ', '.join(bs[:4])  # can't fit too many on one line
  return NoEntryAlert(msg, alert_text_1="기기 내부 통신 문제")


def camera_malfunction_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  all_cams = ('roadCameraState', 'driverCameraState', 'wideRoadCameraState')
  bad_cams = [s.replace('State', '') for s in all_cams if s in sm.data.keys() and not sm.all_checks([s, ])]
  return NormalPermanentAlert("Camera Malfunction", ', '.join(bad_cams))


def calibration_invalid_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  rpy = sm['liveCalibration'].rpyCalib
  yaw = math.degrees(rpy[2] if len(rpy) == 3 else math.nan)
  pitch = math.degrees(rpy[1] if len(rpy) == 3 else math.nan)
  angles = f"위아래 {pitch:.1f}도, 좌우 {yaw:.1f}도"
  return NormalPermanentAlert("캘리브레이션 실패", angles)


def overheat_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  cpu = max(sm['deviceState'].cpuTempC, default=0.)
  gpu = max(sm['deviceState'].gpuTempC, default=0.)
  temp = max((cpu, gpu, sm['deviceState'].memoryTempC))
  return NormalPermanentAlert("기기 과열", f"{temp:.0f}도")


def low_memory_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  return NormalPermanentAlert("메모리 부족", f"{sm['deviceState'].memoryUsagePercent}% 사용")


def high_cpu_usage_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  x = max(sm['deviceState'].cpuUsagePercent, default=0.)
  return NormalPermanentAlert("처리 부하 높음", f"{x}% 사용")


def modeld_lagging_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  return NormalPermanentAlert("주행 판단 지연", f"화면 {sm['modelV2'].frameDropPerc:.1f}% 누락")


def wrong_car_mode_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  text = "크루즈 모드 꺼짐"
  if CP.carName == "honda":
    text = "메인 스위치 꺼짐"
  return NoEntryAlert(text)


def joystick_alert(CP: car.CarParams, CS: car.CarState, sm: messaging.SubMaster, metric: bool, soft_disable_time: int) -> Alert:
  axes = sm['testJoystick'].axes
  gb, steer = list(axes)[:2] if len(axes) else (0., 0.)
  vals = f"가속 {round(gb * 100.)}%, 조향 {round(steer * 100.)}%"
  return NormalPermanentAlert("조이스틱 모드", vals)



EVENTS: Dict[int, Dict[str, Union[Alert, AlertCallbackType]]] = {
  # ********** events with no alerts **********

  EventName.stockFcw: {},

  # ********** events only containing alerts displayed in all states **********

  EventName.joystickDebug: {
    ET.WARNING: joystick_alert,
    ET.PERMANENT: NormalPermanentAlert("조이스틱 모드"),
  },

  EventName.controlsInitializing: {
    ET.NO_ENTRY: NoEntryAlert("시스템 준비 중"),
  },

  EventName.startup: {
    ET.PERMANENT: StartupAlert("언제든 직접 운전할 준비를 하세요")
  },

  EventName.startupMaster: {
    ET.PERMANENT: startup_master_alert,
  },

  # Car is recognized, but marked as dashcam only
  EventName.startupNoControl: {
    ET.PERMANENT: StartupAlert("Dashcam mode", "Always keep hands on wheel and eyes on road"),
  },

  # Car is not recognized
  EventName.startupNoCar: {
    ET.PERMANENT: StartupAlert("Dashcam mode for unsupported car", "Always keep hands on wheel and eyes on road"),
  },

  EventName.startupNoFw: {
    ET.PERMANENT: StartupAlert("차종을 알 수 없음",
                               "전원 연결을 확인하세요",
                               alert_status=AlertStatus.userPrompt),
  },

  EventName.dashcamMode: {
    ET.PERMANENT: NormalPermanentAlert("Dashcam Mode",
                                       priority=Priority.LOWEST),
  },

  EventName.invalidLkasSetting: {
    ET.PERMANENT: NormalPermanentAlert("차량 차로 유지 기능이 켜져 있음",
                                       "차량 차로 유지 기능을 끄고 켜세요"),
  },

  EventName.cruiseMismatch: {
    #ET.PERMANENT: ImmediateDisableAlert("오픈파일럿이 크루즈를 끄지 못함"),
  },

  # openpilot doesn't recognize the car. This switches openpilot into a
  # read-only mode. This can be solved by adding your fingerprint.
  # See https://github.com/commaai/openpilot/wiki/Fingerprinting for more information
  EventName.carUnrecognized: {
    ET.PERMANENT: NormalPermanentAlert("Dashcam Mode",
                                       "Car Unrecognized",
                                       priority=Priority.LOWEST),
  },

  EventName.stockAeb: {
    ET.PERMANENT: Alert(
      "브레이크!",
      "차량 긴급 제동: 충돌 위험",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGHEST, VisualAlert.fcw, AudibleAlert.none, 2.),
    ET.NO_ENTRY: NoEntryAlert("차량 긴급 제동: 충돌 위험"),
  },

  EventName.fcw: {
    ET.PERMANENT: Alert(
      "브레이크!",
      "충돌 위험",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGHEST, VisualAlert.fcw, AudibleAlert.stopStop, 2.),
  },

  EventName.ldw: {
    ET.PERMANENT: Alert(
      "차로 이탈",
      "",
      AlertStatus.userPrompt, AlertSize.small,
      Priority.LOW, VisualAlert.ldw, AudibleAlert.prompt, 3.),
  },

  # ********** events only containing alerts that display while engaged **********

  # openpilot tries to learn certain parameters about your car by observing
  # how the car behaves to steering inputs from both human and openpilot driving.
  # This includes:
  # - steer ratio: gear ratio of the steering rack. Steering angle divided by tire angle
  # - tire stiffness: how much grip your tires have
  # - angle offset: most steering angle sensors are offset and measure a non zero angle when driving straight
  # This alert is thrown when any of these values exceed a sanity check. This can be caused by
  # bad alignment or bad sensor data. If this happens consistently consider creating an issue on GitHub
  EventName.vehicleModelInvalid: {
    ET.NO_ENTRY: NoEntryAlert("차량 값 학습 실패"),
    ET.SOFT_DISABLE: soft_disable_alert("차량 값 학습 실패"),
  },

  EventName.steerTempUnavailableSilent: {
    ET.WARNING: Alert(
      "조향 일시 중단",
      "",
      AlertStatus.userPrompt, AlertSize.small,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.none, 1.),
  },

  EventName.preDriverDistracted: {
    ET.WARNING: Alert(
      "앞을 보세요",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .1),
  },

  EventName.promptDriverDistracted: {
    ET.WARNING: Alert(
      "앞을 보세요",
      "운전자 주의 분산",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.MID, VisualAlert.steerRequired, AudibleAlert.promptDistracted, .1),
  },

  EventName.driverDistracted: {
    ET.WARNING: Alert(
      "즉시 운전하세요",
      "운전자 주의 분산",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGH, VisualAlert.steerRequired, AudibleAlert.warningImmediate, .1),
  },

  EventName.preDriverUnresponsive: {
    ET.WARNING: Alert(
      "핸들을 잡으세요: 얼굴이 안 보입니다",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.none, .1, alert_rate=0.75),
  },

  EventName.promptDriverUnresponsive: {
    ET.WARNING: Alert(
      "핸들을 잡으세요",
      "운전자 반응 없음",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.MID, VisualAlert.steerRequired, AudibleAlert.promptDistracted, .1),
  },

  EventName.driverUnresponsive: {
    ET.WARNING: Alert(
      "즉시 운전하세요",
      "운전자 반응 없음",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGH, VisualAlert.steerRequired, AudibleAlert.warningImmediate, .1),
  },

  EventName.manualRestart: {
    ET.WARNING: Alert(
      "직접 운전하세요",
      "직접 운전을 이어 가세요",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .2),
  },

  EventName.resumeRequired: {
    ET.WARNING: Alert(
      "정지",
      "출발하려면 RES 버튼을 누르세요",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .2),
  },

  EventName.belowSteerSpeed: {
    ET.WARNING: below_steer_speed_alert,
  },

  EventName.preLaneChangeLeft: {
    ET.WARNING: Alert(
      "안전하면 핸들을 왼쪽으로 살짝 밀어 차로 변경",
      "",
      AlertStatus.normal, AlertSize.none,
      #Priority.LOW, VisualAlert.none, AudibleAlert.none, .1, alert_rate=0.75),
      Priority.LOW, VisualAlert.none, AudibleAlert.prompt, .1),
  },

  EventName.preLaneChangeRight: {
    ET.WARNING: Alert(
      "안전하면 핸들을 오른쪽으로 살짝 밀어 차로 변경",
      "",
      AlertStatus.normal, AlertSize.none,
      #Priority.LOW, VisualAlert.none, AudibleAlert.none, .1, alert_rate=0.75),
      Priority.LOW, VisualAlert.none, AudibleAlert.prompt, .1),
  },

  EventName.laneChangeBlocked: {
    ET.WARNING: Alert(
      "옆 차로에 차량 또는 도로 끝",
      "",
      AlertStatus.userPrompt, AlertSize.none,
      #Priority.LOW, VisualAlert.none, AudibleAlert.prompt, .1),
      Priority.LOW, VisualAlert.none, AudibleAlert.bsdWarning, .1),
  },

  EventName.laneChangeRoadEdge: {
    ET.WARNING: Alert(
      "옆 차로에 차량 또는 도로 끝",
      "",
      AlertStatus.userPrompt, AlertSize.none,
      #Priority.LOW, VisualAlert.none, AudibleAlert.prompt, .1),
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .1),
  },
  

  EventName.laneChange: {
    ET.WARNING: Alert(
      "차로 변경 중",
      "",
      AlertStatus.normal, AlertSize.none,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .1),
  },

  EventName.steerSaturated: {
    ET.WARNING: Alert(
      "직접 운전하세요",
      "커브가 조향 한계를 넘습니다",
      AlertStatus.userPrompt, AlertSize.none,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.none, 1.),
  },

  # Thrown when the fan is driven at >50% but is not rotating
  EventName.fanMalfunction: {
    ET.PERMANENT: NormalPermanentAlert("냉각 팬 고장", "기기 고장 가능성"),
  },

  # Camera is not outputting frames
  EventName.cameraMalfunction: {
    ET.PERMANENT: camera_malfunction_alert,
    ET.SOFT_DISABLE: soft_disable_alert("Camera Malfunction"),
    ET.NO_ENTRY: NoEntryAlert("Camera Malfunction: Reboot Your Device"),
  },
  # Camera framerate too low
  EventName.cameraFrameRate: {
    ET.PERMANENT: NormalPermanentAlert("Camera Frame Rate Low", "Reboot your Device"),
    ET.SOFT_DISABLE: soft_disable_alert("Camera Frame Rate Low"),
    ET.NO_ENTRY: NoEntryAlert("Camera Frame Rate Low: Reboot Your Device"),
  },

  # Unused
  EventName.gpsMalfunction: {
    ET.PERMANENT: NormalPermanentAlert("GPS 고장", "기기 고장 가능성"),
  },

  # When the GPS position and localizer diverge the localizer is reset to the
  # current GPS position. This alert is thrown when the localizer is reset
  # more often than expected.
  EventName.localizerMalfunction: {
    # ET.PERMANENT: NormalPermanentAlert("센서 고장", "Hardware Malfunction"),
  },

  # ********** events that affect controls state transitions **********

  EventName.pcmEnable: {
    ET.ENABLE: EngagementAlert(AudibleAlert.engage),
  },

  EventName.buttonEnable: {
    ET.ENABLE: EngagementAlert(AudibleAlert.engage),
  },

  EventName.pcmDisable: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
  },

  EventName.buttonCancel: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
    ET.NO_ENTRY: NoEntryAlert("취소 버튼 눌림"),
  },

  EventName.brakeHold: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
    ET.NO_ENTRY: NoEntryOneLineAlert("오토 홀드"),
  },

  EventName.parkBrake: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
    ET.NO_ENTRY: NoEntryOneLineAlert("주차 브레이크"),
  },

  EventName.pedalPressed: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
    ET.NO_ENTRY: NoEntryAlert("페달 밟음",
                              visual_alert=VisualAlert.brakePressed),
  },

  EventName.preEnableStandstill: {
    ET.PRE_ENABLE: Alert(
      "브레이크에서 발을 떼고 켜세요",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .1, creation_delay=1.),
  },

  EventName.gasPressedOverride: {
    ET.OVERRIDE_LONGITUDINAL: Alert(
      "",
      "",
      AlertStatus.normal, AlertSize.none,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .1),
  },

  EventName.steerOverride: {
    ET.OVERRIDE_LATERAL: Alert(
      "",
      "",
      AlertStatus.normal, AlertSize.none,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .1),
  },

  EventName.wrongCarMode: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
    ET.NO_ENTRY: wrong_car_mode_alert,
  },

  EventName.resumeBlocked: {
    ET.NO_ENTRY: NoEntryAlert("SET 버튼을 눌러 켜세요"),
  },

  EventName.wrongCruiseMode: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
    ET.NO_ENTRY: NoEntryAlert("크루즈 꺼짐"),
  },

  EventName.steerTempUnavailable: {
    ET.SOFT_DISABLE: soft_disable_alert("조향 일시 중단"),
    ET.NO_ENTRY: NoEntryAlert("조향 일시 중단"),
  },

  EventName.steerTimeLimit: {
    ET.SOFT_DISABLE: soft_disable_alert("차량 조향 시간 한도"),
    ET.NO_ENTRY: NoEntryAlert("차량 조향 시간 한도"),
  },

  EventName.outOfSpace: {
    ET.PERMANENT: out_of_space_alert,
    ET.NO_ENTRY: NoEntryAlert("저장 공간 부족"),
  },

  EventName.belowEngageSpeed: {
    ET.NO_ENTRY: below_engage_speed_alert,
  },

  EventName.sensorDataInvalid: {
    ET.PERMANENT: Alert(
      "센서 값 이상",
      "기기를 단단히 고정하세요",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, .2, creation_delay=1.),
    ET.NO_ENTRY: NoEntryAlert("센서 값 이상"),
    ET.SOFT_DISABLE: soft_disable_alert("센서 값 이상"),
  },

  EventName.noGps: {
    ET.PERMANENT: no_gps_alert,
  },

  EventName.soundsUnavailable: {
    ET.PERMANENT: NormalPermanentAlert("스피커를 찾을 수 없음", "기기를 다시 켜세요"),
    ET.NO_ENTRY: NoEntryAlert("스피커를 찾을 수 없음"),
  },

  EventName.tooDistracted: {
    ET.NO_ENTRY: NoEntryAlert("주의 분산이 너무 많아 켤 수 없습니다"),
  },

  EventName.overheat: {
    ET.PERMANENT: overheat_alert,
    ET.SOFT_DISABLE: soft_disable_alert("기기 과열"),
    ET.NO_ENTRY: NoEntryAlert("기기 과열"),
  },

  EventName.wrongGear: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
    #ET.SOFT_DISABLE: user_soft_disable_alert("기어가 D가 아닙니다"),
    ET.NO_ENTRY: NoEntryAlert("기어가 D가 아닙니다"),
  },

  # This alert is thrown when the calibration angles are outside of the acceptable range.
  # For example if the device is pointed too much to the left or the right.
  # Usually this can only be solved by removing the mount from the windshield completely,
  # and attaching while making sure the device is pointed straight forward and is level.
  # See https://comma.ai/setup for more information
  EventName.calibrationInvalid: {
    ET.PERMANENT: calibration_invalid_alert,
    ET.SOFT_DISABLE: soft_disable_alert("캘리브레이션 오류: 기기를 다시 달아 주세요"),
    ET.NO_ENTRY: NoEntryAlert("캘리브레이션 오류: 기기를 다시 달아 주세요"),
  },

  EventName.calibrationIncomplete: {
    ET.PERMANENT: calibration_incomplete_alert,
    ET.SOFT_DISABLE: soft_disable_alert("Calibration in Progress"),
    ET.NO_ENTRY: NoEntryAlert("Calibration in Progress", alert_text_1="openpilot Unavailable"),
  },

  EventName.doorOpen: {
    ET.USER_DISABLE: user_soft_disable_alert("문 열림"),
    ET.NO_ENTRY: NoEntryAlert("문 열림"),
  },

  EventName.seatbeltNotLatched: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
    #ET.SOFT_DISABLE: user_soft_disable_alert("안전벨트 풀림"),
    ET.NO_ENTRY: NoEntryAlert("안전벨트 풀림"),
  },

  EventName.espDisabled: {
    ET.SOFT_DISABLE: soft_disable_alert("Electronic Stability Control Disabled"),
    ET.NO_ENTRY: NoEntryAlert("Electronic Stability Control Disabled"),
  },

  EventName.lowBattery: {
    ET.SOFT_DISABLE: soft_disable_alert("배터리 부족"),
    ET.NO_ENTRY: NoEntryAlert("배터리 부족"),
  },

  # Different openpilot services communicate between each other at a certain
  # interval. If communication does not follow the regular schedule this alert
  # is thrown. This can mean a service crashed, did not broadcast a message for
  # ten times the regular interval, or the average interval is more than 10% too high.
  EventName.commIssue: {
    ET.SOFT_DISABLE: soft_disable_alert("기기 내부 통신 문제"),
    ET.NO_ENTRY: comm_issue_alert,
  },
  EventName.commIssueAvgFreq: {
    ET.SOFT_DISABLE: soft_disable_alert("기기 내부 통신 느림"),
    ET.NO_ENTRY: NoEntryAlert("기기 내부 통신 느림"),
  },

  EventName.controlsdLagging: {
    ET.SOFT_DISABLE: soft_disable_alert("제어 지연"),
    ET.NO_ENTRY: NoEntryAlert("제어 지연: 기기를 다시 켜세요"),
  },

  # Thrown when manager detects a service exited unexpectedly while driving
  EventName.processNotRunning: {
    ET.NO_ENTRY: process_not_running_alert,
    ET.SOFT_DISABLE: soft_disable_alert("프로그램 일부가 멈춤"),
  },

  EventName.radarFault: {
    ET.SOFT_DISABLE: soft_disable_alert("레이더 오류: 시동을 다시 거세요"),
    ET.NO_ENTRY: NoEntryAlert("레이더 오류: 시동을 다시 거세요"),
  },

  # Every frame from the camera should be processed by the model. If modeld
  # is not processing frames fast enough they have to be dropped. This alert is
  # thrown when over 20% of frames are dropped.
  EventName.modeldLagging: {
    ET.SOFT_DISABLE: soft_disable_alert("주행 판단 지연"),
    ET.NO_ENTRY: NoEntryAlert("주행 판단 지연"),
    ET.PERMANENT: modeld_lagging_alert,
  },

  # Besides predicting the path, lane lines and lead car data the model also
  # predicts the current velocity and rotation speed of the car. If the model is
  # very uncertain about the current velocity while the car is moving, this
  # usually means the model has trouble understanding the scene. This is used
  # as a heuristic to warn the driver.
  EventName.posenetInvalid: {
    ET.SOFT_DISABLE: soft_disable_alert("영상 속도 추정 이상"),
    ET.NO_ENTRY: posenet_invalid_alert,
  },

  # When the localizer detects an acceleration of more than 40 m/s^2 (~4G) we
  # alert the driver the device might have fallen from the windshield.
  EventName.deviceFalling: {
    ET.SOFT_DISABLE: soft_disable_alert("기기가 거치대에서 떨어짐"),
    ET.NO_ENTRY: NoEntryAlert("기기가 거치대에서 떨어짐"),
  },

  EventName.lowMemory: {
    ET.SOFT_DISABLE: soft_disable_alert("메모리 부족: 기기를 다시 켜세요"),
    ET.PERMANENT: low_memory_alert,
    ET.NO_ENTRY: NoEntryAlert("메모리 부족: 기기를 다시 켜세요"),
  },

  EventName.highCpuUsage: {
    #ET.SOFT_DISABLE: soft_disable_alert("시스템 고장: 기기를 다시 켜세요"),
    #ET.PERMANENT: NormalPermanentAlert("시스템 고장", "기기를 다시 켜세요"),
    ET.NO_ENTRY: high_cpu_usage_alert,
  },

  EventName.accFaulted: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("크루즈 장치 오류: 시동을 다시 거세요"),
    ET.PERMANENT: NormalPermanentAlert("크루즈 장치 오류: 시동을 다시 걸어야 켜집니다"),
    ET.NO_ENTRY: NoEntryAlert("크루즈 장치 오류: 시동을 다시 거세요"),
  },

  EventName.controlsMismatch: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("제어 판단 불일치"),
    ET.NO_ENTRY: NoEntryAlert("제어 판단 불일치"),
  },

  EventName.roadCameraError: {
    ET.PERMANENT: NormalPermanentAlert("앞 카메라 신호 오류",
                                       duration=1.,
                                       creation_delay=30.),
  },

  EventName.wideRoadCameraError: {
    ET.PERMANENT: NormalPermanentAlert("광각 카메라 신호 오류",
                                       duration=1.,
                                       creation_delay=30.),
  },

  EventName.driverCameraError: {
    ET.PERMANENT: NormalPermanentAlert("운전자 카메라 신호 오류",
                                       duration=1.,
                                       creation_delay=30.),
  },

  # Sometimes the USB stack on the device can get into a bad state
  # causing the connection to the panda to be lost
  EventName.usbError: {
    ET.SOFT_DISABLE: soft_disable_alert("USB 오류: 기기를 다시 켜세요"),
    ET.PERMANENT: NormalPermanentAlert("USB 오류: 기기를 다시 켜세요", ""),
    ET.NO_ENTRY: NoEntryAlert("USB 오류: 기기를 다시 켜세요"),
  },

  # This alert can be thrown for the following reasons:
  # - No CAN data received at all
  # - CAN data is received, but some message are not received at the right frequency
  # If you're not writing a new car port, this is usually cause by faulty wiring
  EventName.canError: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("차량 통신 오류"),
    ET.PERMANENT: Alert(
      "차량 통신 오류: 연결을 확인하세요",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 1., creation_delay=1.),
    ET.NO_ENTRY: NoEntryAlert("차량 통신 오류: 연결을 확인하세요"),
  },

  EventName.canBusMissing: {
    #ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("차량 통신 끊김"),
    #ET.PERMANENT: Alert(
    #  "CAN Bus Disconnected: Likely Faulty Cable",
    #  "",
    #  AlertStatus.normal, AlertSize.small,
    #  Priority.LOW, VisualAlert.none, AudibleAlert.none, 1., creation_delay=1.),
    #ET.NO_ENTRY: NoEntryAlert("차량 통신 끊김: 연결을 확인하세요"),
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.disengage),
    #ET.SOFT_DISABLE: user_soft_disable_alert("기어가 D가 아닙니다"),
    ET.NO_ENTRY: NoEntryAlert("차량 통신 끊김"),

  },

  EventName.steerUnavailable: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("차로 유지 장치 오류: 시동을 다시 거세요"),
    ET.PERMANENT: NormalPermanentAlert("차로 유지 장치 오류: 시동을 다시 걸어야 켜집니다"),
    ET.NO_ENTRY: NoEntryAlert("차로 유지 장치 오류: 시동을 다시 거세요"),
  },

  EventName.brakeUnavailable: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("크루즈 장치 오류: 시동을 다시 거세요"),
    ET.PERMANENT: NormalPermanentAlert("크루즈 장치 오류: 시동을 다시 걸어야 켜집니다"),
    ET.NO_ENTRY: NoEntryAlert("크루즈 장치 오류: 시동을 다시 거세요"),
  },

  EventName.reverseGear: {
    ET.PERMANENT: Alert(
      "후진\n기어",
      "",
      AlertStatus.normal, AlertSize.full,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .2, creation_delay=0.5),
    ET.SOFT_DISABLE: SoftDisableAlert("후진 기어"),
    ET.NO_ENTRY: NoEntryAlert("후진 기어"),
  },

  # On cars that use stock ACC the car can decide to cancel ACC for various reasons.
  # When this happens we can no long control the car so the user needs to be warned immediately.
  EventName.cruiseDisabled: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("크루즈 꺼짐"),
  },

  # For planning the trajectory Model Predictive Control (MPC) is used. This is
  # an optimization algorithm that is not guaranteed to find a feasible solution.
  # If no solution is found or the solution has a very high cost this alert is thrown.
  EventName.plannerError: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("주행 계획 계산 오류"),
    ET.NO_ENTRY: NoEntryAlert("주행 계획 계산 오류"),
  },

  # When the relay in the harness box opens the CAN bus between the LKAS camera
  # and the rest of the car is separated. When messages from the LKAS camera
  # are received on the car side this usually means the relay hasn't opened correctly
  # and this alert is thrown.
  EventName.relayMalfunction: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("Harness Relay Malfunction"),
    ET.PERMANENT: NormalPermanentAlert("Harness Relay Malfunction", "Check Hardware"),
    ET.NO_ENTRY: NoEntryAlert("Harness Relay Malfunction"),
  },

  EventName.speedTooLow: {
    ET.IMMEDIATE_DISABLE: Alert(
      "오픈파일럿 취소됨",
      "속도가 너무 낮습니다",
      AlertStatus.normal, AlertSize.mid,
      Priority.HIGH, VisualAlert.none, AudibleAlert.disengage, 3.),
  },

  # When the car is driving faster than most cars in the training data, the model outputs can be unpredictable.
  EventName.speedTooHigh: {
    ET.WARNING: Alert(
      "속도가 너무 높습니다",
      "이 속도에서는 판단이 불확실합니다",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.HIGH, VisualAlert.steerRequired, AudibleAlert.promptRepeat, 4.),
    ET.NO_ENTRY: NoEntryAlert("속도를 줄여야 켜집니다"),
  },

  EventName.lowSpeedLockout: {
    ET.PERMANENT: NormalPermanentAlert("크루즈 장치 오류: 시동을 다시 걸어야 켜집니다"),
    ET.NO_ENTRY: NoEntryAlert("크루즈 장치 오류: 시동을 다시 거세요"),
  },

  EventName.lkasDisabled: {
    ET.PERMANENT: NormalPermanentAlert("차로 유지 기능을 켜야 쓸 수 있습니다"),
    ET.NO_ENTRY: NoEntryAlert("차로 유지 기능 꺼짐"),
  },
  EventName.cruisePaused: {
    ET.WARNING: EngagementAlert(AudibleAlert.longDisengaged),
  },
  EventName.cruiseResume: {
    ET.WARNING: EngagementAlert(AudibleAlert.longEngaged),
  },
  EventName.trafficSignGreen: {
    # optech '초록불 알림' (cruise_helper, optech_signal.py): stopped for a red light, the light turned green
    ET.WARNING: Alert(
      "초록불로 바뀌었어요",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.trafficSignGreen, 3.),
    #ET.WARNING: Alert(
    #  "출발합니다.",
    #  "",
    #  AlertStatus.normal, AlertSize.small,
    #  Priority.LOW, VisualAlert.none, AudibleAlert.trafficSignGreen, 3.),
  },
  EventName.trafficSignChanged: {
    ET.WARNING: Alert(
      "신호가바뀌었어요.",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.trafficSignChanged, 3.),
  },
  EventName.autoHold: {
    ET.WARNING: Alert(
      "소프트 오토홀드",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.autoHold, 3.),
  },
  EventName.trafficError: {
     ET.WARNING: EngagementAlert(AudibleAlert.trafficError),
  },
  EventName.audioPrompt: {
     ET.WARNING: EngagementAlert(AudibleAlert.prompt),
  },
  EventName.audioRefuse: {
     ET.WARNING: EngagementAlert(AudibleAlert.refuse),
  },
  EventName.trafficStopping: {
    ET.WARNING: EngagementAlert(AudibleAlert.stopping),
    #ET.WARNING: Alert(
    #  "신호 감속정지중입니다.",
    #  "",
    #  AlertStatus.normal, AlertSize.small,
    #  Priority.LOW, VisualAlert.none, AudibleAlert.stopping, 3.),
  },
  EventName.speedDown: {
     ET.WARNING: EngagementAlert(AudibleAlert.speedDown),
  },
  EventName.stopStop: {
     ET.WARNING: EngagementAlert(AudibleAlert.stopStop),
  },
  EventName.audioLaneChange: {
     ET.WARNING: EngagementAlert(AudibleAlert.laneChange),
  },
  EventName.audioTurn: {
     ET.WARNING: EngagementAlert(AudibleAlert.audioTurn),
  },

}
