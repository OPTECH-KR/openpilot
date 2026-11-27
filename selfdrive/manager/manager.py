#!/usr/bin/env python3
import datetime
import os
import signal
import subprocess
import sys
import traceback
from typing import List, Tuple, Union

from cereal import log
import cereal.messaging as messaging
import openpilot.selfdrive.sentry as sentry
from openpilot.common.basedir import BASEDIR
from openpilot.common.params import Params, ParamKeyType
from openpilot.common.text_window import TextWindow
from openpilot.selfdrive.boardd.set_time import set_time
from openpilot.system.hardware import HARDWARE, PC
from openpilot.selfdrive.manager.helpers import unblock_stdout, write_onroad_params
from openpilot.selfdrive.manager.process import ensure_running
from openpilot.selfdrive.manager.process_config import managed_processes
from openpilot.selfdrive.athena.registration import register, UNREGISTERED_DONGLE_ID
from openpilot.system.swaglog import cloudlog, add_file_handler
from openpilot.system.version import is_dirty, get_commit, get_version, get_origin, get_short_branch, \
                           get_normalized_origin, terms_version, training_version, \
                           is_tested_branch, is_release_branch
import json
from openpilot.selfdrive.car.fingerprints import all_known_cars, all_legacy_fingerprint_cars


def optech_navi_link_migrate(params) -> None:
  """optech 2026-11-25 (same as optech-hkg): 내비 연동 방식 (OptechNaviLinkMode) names the phone app now: 0 사용 안 함,
  1 TmapNda (NDA 843 + carrot 7706), 2 당근내비 (carrot 7706). It was 0 내비 안 씀 / 1 APM / 2 APM + 순정 / 3 NDA, and
  APM (APilotMan + Mappy) is no longer received. Old values move once, like optech-hkg's: 3 NDA -> 1, 1 APM and
  2 APM + 순정 -> 2, 0 stays. spst has no AutoNaviSpeedCtrl to tell an old 1 from a new 1, so OptechNaviLinkVer "2"
  marks a device that has the new meaning (a new install gets it before the defaults are written: nothing to move)."""
  if params.get("OptechNaviLinkVer", encoding="utf8") == "2":
    return
  old = params.get("OptechNaviLinkMode", encoding="utf8")
  if old is not None:
    try:
      new = {0: 0, 1: 2, 2: 2, 3: 1}.get(int(old), 1)
    except ValueError:
      new = 1  # a broken value: the new default
    params.put("OptechNaviLinkMode", str(new))
  params.put("OptechNaviLinkVer", "2")


def manager_init() -> None:
  # update system time from panda
  set_time(cloudlog)

  # save boot log
  subprocess.call("./bootlog", cwd=os.path.join(BASEDIR, "selfdrive/loggerd"))

  params = Params()
  params.clear_all(ParamKeyType.CLEAR_ON_MANAGER_START)
  params.clear_all(ParamKeyType.CLEAR_ON_ONROAD_TRANSITION)
  params.clear_all(ParamKeyType.CLEAR_ON_OFFROAD_TRANSITION)

  default_params: List[Tuple[str, Union[str, bytes]]] = [
    ("CompletedTrainingVersion", "0"),
    ("DisengageOnAccelerator", "0"),
    ("GsmMetered", "1"),
    ("HasAcceptedTerms", "0"),
    ("LanguageSetting", "main_ko"),
    ("OpenpilotEnabledToggle", "1"),
    ("LongitudinalPersonality", str(log.LongitudinalPersonality.standard)),
    ("DisableUpdates", "1"),
    ("dp_no_gps_ctrl", "0"),
    ("dp_no_fan_ctrl", "0"),
    ("dp_logging", "1"),
    ("dp_0813", "0"),  # optech 2026-11-23: new 0.8.16 model by default (실험 모드, openpilot 가감속, 카메라 감속 need it)
    ("dp_lat_controller", "0"),

    # dp addition
    ("dp_alka", "0"),
    ("dp_mapd", "0"),
    ("dp_lat_lane_priority_mode", "0"),
    ("dp_device_auto_shutdown", "0"),
    ("dp_device_auto_shutdown_in", "30"),
    ("dp_toyota_sng", "0"),
    ("dp_toyota_enhanced_bsm", "0"),
    ("dp_toyota_auto_lock", "0"),
    ("dp_toyota_auto_unlock", "0"),
    ("dp_device_audible_alert_mode", "0"),
    ("dp_device_disable_temp_check", "0"),
    ("dp_car_dashcam_mode_removal", "0"),
    ("dp_device_enable_comma_registration", "0"),
    ("dp_long_accel_profile", "0"),
    ("OptechHud", "1"),
    ("OptechShowDeviceState", "0"),
    ("OptechSpeedCam", "0"),
    ("OptechSpeedCamDecel", "0"),
    ("OptechCamDecelStart", "22"),
    ("OptechCamDecelEnd", "6"),
    ("OptechCamSafetyFactor", "105"),
    ("BoltPedal", "0"),
    ("BoltPedalMax", "100"),
    ("BoltYear2017", "0"),
    ("ShowDmInfo", "0"),
    ("dp_long_use_df_tune", "0"),
    ("dp_long_de2e", "0"),
    ("dp_mapd_vision_turn_control", "0"),
    ("dp_hkg_min_steer_speed_bypass", "0"),
    ("OptechCruiseSetCurrent", "1"),
    ("dp_lat_lane_priority_mode_speed_based", "0"),
    ("dp_long_use_krkeegen_tune", "0"),
    ("dp_toyota_zss", "0"),
    ("dp_long_accel_btn", "0"),
    ("dp_long_personality_btn", "0"),
    ("dp_lat_lane_change_assist_speed", "20"),
    # optech-hkg menu items (same keys and first values as optech-hkg)
    ("OptechLdwsCar", "0"),             # 토글 > LDWS 차량 (LKAS11 CF_Lkas_LdwsOpt_USM = 3)
    ("OptechSettingsTimeout", "180"),   # 화면 > 화면 유지 시간 (seconds, -1 항상)
    ("OptechDriveDim", "0"),            # 화면 > 주행 중 밝기 (%, 0 off)
    ("OpkrHotspotOnBoot", "0"),         # 고급 > 부팅 시 핫스팟 켜기
    ("OptechLatMethod", "0"),           # 조향 > 조향 방식 (0 기본, 1 PID, 2 INDI, 3 LQR) and their values
    ("OptechPidKp", "25"),
    ("OptechPidKi", "40"),
    ("OptechPidKf", "7"),
    ("OptechIndiInner", "35"),
    ("OptechIndiOuter", "20"),
    ("OptechIndiTime", "14"),
    ("OptechIndiAct", "20"),
    ("OptechLqrScale", "1500"),
    ("OptechLqrKi", "16"),
    ("OptechLqrDcGain", "265"),
    ("SteerRatioApply", "0"),           # 조향 > 조향 세부 (0.1 units, 0 = learned value)
    ("LiveSteerRatioApply", "100"),     # % of the learned steer ratio
    ("SteerActuatorDelay", "0"),        # 0.01 s, 0 = the car's own value
    ("LateralTorqueCustom", "0"),
    ("LateralTorqueAccelFactor", "2500"),
    ("LateralTorqueFriction", "100"),
    # optech-hkg stage 2 (same first values as optech-hkg)
    ("OptechNaviLinkMode", "1"),            # 주행 > 과속카메라 > 내비 연동 방식 (0 사용 안 함, 1 TmapNda, 2 당근내비)
    ("HapticFeedbackWhenSpeedCamera", "0"), # 과속 단속 알림 (0 off, 1 핸들 진동, 2 계기판, 3 화면)
    ("OptechSignalEnable", "1"),            # 주행 > 신호등 > 신호등 사용
    ("OptechGreenAlert", "1"),              # 주행 > 신호등 > 초록불 알림
    ("ShowTpms", "1"),
    ("ShowGpsInfo", "1"),
    ("ShowBlindSpot", "1"),
    ("ShowRadarInfo", "1"),
    ("ShowConnInfo", "1"),
    ("OptechShowRecordBtn", "0"),
    ("OptechWebServer", "1"),  # 고급 > 웹 접속 (selfdrive/optech_web/server.py, port 7000)
    ("PathOffset", "0"),
    ("NNFF", "0"),
    ("NNFFLite", "0"),
    ("JerkStartLimit", "10"),
    ("StartAccelApply", "0"),
    ("StopAccelApply", "0"),
    ("StopDistance", "600"),
    # optech: Ray EV / Porter II EV (no SCC) comma pedal, under 차종 선택 when that car is chosen (optech-hkg)
    ("RayPedal", "0"),
    ("RayPedalMax", "70"),
    ("RayPedalStrong", "0"),
    ("RayPedalKi", "50"),
    ("PorterPedal", "0"),
    ("PorterPedalMax", "40"),
  ]
  if not PC:
    default_params.append(("LastUpdateTime", datetime.datetime.utcnow().isoformat().encode('utf8')))

  # optech: settings that replaced dragonpilot ones keep the old choice the first time
  if params.get("OptechDmMode") is None:  # 토글 > 운전자 모니터링: 0 기본 사용, 1 경도 사용, 2 사용 안 함
    params.put("OptechDmMode", "2" if params.get_bool("dp_device_no_ir_ctrl") else "0")
  if params.get("OptechOffShutdown") is None:  # 고급 > 시동 끈 뒤 꺼짐 (seconds, 0 off)
    off_s = 0
    if params.get_bool("dp_device_auto_shutdown"):
      try:
        mins = int(params.get("dp_device_auto_shutdown_in", encoding="utf8") or 0)
      except ValueError:
        mins = 0
      off_s = min((30, 60, 180, 300, 600), key=lambda s: abs(s - mins * 60))
    params.put("OptechOffShutdown", str(off_s))
  params.put_bool("OptechHud", True)  # the OPTECH 주행 화면 is always on, as on optech-hkg (no menu item)
  optech_navi_link_migrate(params)  # before the defaults: a new install has no old 내비 연동 방식 to move

  params.put("dp_car_list", get_support_car_list())

  if params.get_bool("RecordFrontLock"):
    params.put_bool("RecordFront", True)

  # set unset params
  for k, v in default_params:
    if params.get(k) is None:
      params.put(k, v)

  # is this dashcam?
  if os.getenv("PASSIVE") is not None:
    params.put_bool("Passive", bool(int(os.getenv("PASSIVE", "0"))))

  if params.get("Passive") is None:
    raise Exception("Passive must be set to continue")

  # Create folders needed for msgq
  try:
    os.mkdir("/dev/shm")
  except FileExistsError:
    pass
  except PermissionError:
    print("WARNING: failed to make /dev/shm")

  # set version params
  params.put("Version", get_version())
  params.put("TermsVersion", terms_version)
  params.put("TrainingVersion", training_version)
  params.put("GitCommit", get_commit(default=""))
  # optech: release date of the code (Korea time), shown as 브랜치 커밋 on the software page
  try:
    commit_date = subprocess.check_output(["git", "log", "-1", "--format=%cd", "--date=format-local:%Y-%m-%d %H:%M:%S"],
                                          cwd=BASEDIR, encoding="utf8", stderr=subprocess.DEVNULL,
                                          env=dict(os.environ, TZ="KST-9")).strip()
  except Exception:
    commit_date = ""
  params.put("GitCommitDate", commit_date)
  params.put("GitBranch", get_short_branch(default=""))
  params.put("GitRemote", get_origin(default=""))
  params.put_bool("IsTestedBranch", is_tested_branch())
  params.put_bool("IsReleaseBranch", is_release_branch())

  # set dongle id
  reg_res = register(show_spinner=True)
  if reg_res:
    dongle_id = reg_res
  else:
    serial = params.get("HardwareSerial")
    raise Exception(f"Registration failed for device {serial}")
  os.environ['DONGLE_ID'] = dongle_id  # Needed for swaglog

  if not is_dirty():
    os.environ['CLEAN'] = '1'

  # init logging
  sentry.init(sentry.SentryProject.SELFDRIVE)
  cloudlog.bind_global(dongle_id=dongle_id,
                       version=get_version(),
                       origin=get_normalized_origin(),
                       branch=get_short_branch(),
                       commit=get_commit(),
                       dirty=is_dirty(),
                       device=HARDWARE.get_device_type())


def manager_prepare() -> None:
  for p in managed_processes.values():
    p.prepare()


def manager_cleanup() -> None:
  # send signals to kill all procs
  for p in managed_processes.values():
    p.stop(block=False)

  # ensure all are killed
  for p in managed_processes.values():
    p.stop(block=True)

  cloudlog.info("everything is dead")


def manager_thread() -> None:
  cloudlog.bind(daemon="manager")
  cloudlog.info("manager start")
  cloudlog.info({"environ": os.environ})

  params = Params()

  ignore: List[str] = []
  if params.get("DongleId", encoding='utf8') in (None, UNREGISTERED_DONGLE_ID):
    ignore += ["manage_athenad", "uploader"]
  if os.getenv("NOBOARD") is not None:
    ignore.append("pandad")

  if not params.get_bool("dp_logging"):
    ignore += ["logcatd", "proclogd", "loggerd"]
  ignore += [x for x in os.getenv("BLOCK", "").split(",") if len(x) > 0]

  if not params.get_bool("dp_mapd"):
    ignore += ["mapd", "gpxd"]

  if params.get_bool("dp_no_gps_ctrl"):
    ignore += ["ubloxd", "gpx_uploader", "gpxd", "mapd"]

  sm = messaging.SubMaster(['deviceState', 'carParams'], poll=['deviceState'])
  pm = messaging.PubMaster(['managerState'])

  write_onroad_params(False, params)
  ensure_running(managed_processes.values(), False, params=params, CP=sm['carParams'], not_run=ignore)

  started_prev = False

  while True:
    sm.update()

    started = sm['deviceState'].started

    if started and not started_prev:
      params.clear_all(ParamKeyType.CLEAR_ON_ONROAD_TRANSITION)
    elif not started and started_prev:
      params.clear_all(ParamKeyType.CLEAR_ON_OFFROAD_TRANSITION)

    # update onroad params, which drives boardd's safety setter thread
    if started != started_prev:
      write_onroad_params(started, params)

    started_prev = started

    ensure_running(managed_processes.values(), started, params=params, CP=sm['carParams'], not_run=ignore)

    running = ' '.join("%s%s\u001b[0m" % ("\u001b[32m" if p.proc.is_alive() else "\u001b[31m", p.name)
                       for p in managed_processes.values() if p.proc)
    print(running)
    cloudlog.debug(running)

    # send managerState
    msg = messaging.new_message('managerState')
    msg.managerState.processes = [p.get_process_state_msg() for p in managed_processes.values()]
    pm.send('managerState', msg)

    # Exit main loop when uninstall/shutdown/reboot is needed
    shutdown = False
    for param in ("DoUninstall", "DoShutdown", "DoReboot", "dp_reset_conf"):
      if params.get_bool(param):
        if param == "dp_reset_conf":
          os.system("rm -fr /data/params/d/dp_*")
        shutdown = True
        params.put("LastManagerExitReason", f"{param} {datetime.datetime.now()}")
        cloudlog.warning(f"Shutting down manager - {param} set")

    if shutdown:
      break


def main() -> None:
  prepare_only = os.getenv("PREPAREONLY") is not None

  manager_init()

  # Start UI early so prepare can happen in the background
  if not prepare_only:
    managed_processes['ui'].start()

  manager_prepare()

  if prepare_only:
    return

  # SystemExit on sigterm
  signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(1))

  try:
    manager_thread()
  except Exception:
    traceback.print_exc()
    sentry.capture_exception()
  finally:
    manager_cleanup()

  params = Params()
  if params.get_bool("DoUninstall"):
    cloudlog.warning("uninstalling")
    HARDWARE.uninstall()
  elif params.get_bool("DoReboot"):
    cloudlog.warning("reboot")
    HARDWARE.reboot()
  elif params.get_bool("DoShutdown"):
    cloudlog.warning("shutdown")
    HARDWARE.shutdown()


def get_support_car_list():
  cars = dict({"cars": []})
  list = []
  for car in all_known_cars():
    list.append(str(car))

  for car in all_legacy_fingerprint_cars():
    name = str(car)
    if name not in list:
      list.append(name)

  # optech: also the cars without fingerprints (only chosen by hand, e.g. GM ... NO ACC, Trax 2024, Suburban 2016)
  try:
    from openpilot.selfdrive.car.interfaces import get_interface_attr
    for brand_models in get_interface_attr("CAR").values():
      if brand_models is None:
        continue
      for model in brand_models:
        name = str(model.value if hasattr(model, "value") else model)
        if name not in list:
          list.append(name)
  except Exception:
    cloudlog.exception("optech: could not list every car model")
  cars["cars"] = sorted(list)

  # optech: Hyundai / Kia / Genesis menu (normal CAN cars only) = brand, then model family, then year, names like optech-hkg
  try:
    from openpilot.selfdrive.car.hyundai.car_menu import hkg_menu
    cars["hkg_menu"] = hkg_menu()
  except Exception:
    cloudlog.exception("optech: could not make the Hyundai / Kia / Genesis menu")
  return json.dumps(cars)


if __name__ == "__main__":
  unblock_stdout()

  try:
    main()
  except Exception:
    add_file_handler(cloudlog)
    cloudlog.exception("Manager failed to start")

    try:
      managed_processes['ui'].stop()
    except Exception:
      pass

    # Show last 3 lines of traceback
    error = traceback.format_exc(-3)
    error = "Manager failed to start\n\n" + error
    with TextWindow(error) as t:
      t.wait_for_exit()

    raise

  # manual exit because we are forked
  sys.exit(0)
