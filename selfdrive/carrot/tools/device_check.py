#!/usr/bin/env python3
"""On-device check for the carrot options in apilot-c2 (run on the C2 over SSH).

  cd /data/openpilot && python selfdrive/carrot/tools/device_check.py            # static checks only
  cd /data/openpilot && python selfdrive/carrot/tools/device_check.py --live 60  # + 60 s of live stats

Static: branch/commit, carrot params, imports of every ported module.
Live (openpilot running, ideally while driving): message rates, radarState validity, radard loop lag
(cumLagMs), lead / cut-in fields, and CPU use of radard, plannerd and controlsd.
"""
import argparse
import importlib
import os
import subprocess
import sys
import time

BASEDIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if BASEDIR not in sys.path:
  sys.path.insert(0, BASEDIR)  # run as a file: make `common`, `cereal`, `selfdrive` importable

CARROT_PARAMS = ["AutoCurveSpeedCtrlUse", "CarrotTurnAccel", "CarrotRadar", "CarrotCutInPredecel",
                 "CarrotStoppingLead", "CarrotCutOutRelief", "EnableRadarTracks"]
MODULES = [
  "selfdrive.carrot.curve_speed", "selfdrive.carrot.driving_mode", "selfdrive.carrot.t_follow",
  "selfdrive.carrot.traffic_stop", "selfdrive.carrot.radar.radard_carrot", "selfdrive.carrot.radar_motion",
  "selfdrive.controls.lib.turn_accel", "selfdrive.controls.lib.cutin_predecel",
  "selfdrive.controls.lib.longitudinal_cutout", "selfdrive.controls.lib.longitudinal_stopping_lead",
  "selfdrive.controls.lib.longitudinal_planner", "selfdrive.controls.radard",
]
PROCS = {"radard": "selfdrive.controls.radard", "plannerd": "selfdrive.controls.plannerd",
         "controlsd": "selfdrive.controls.controlsd"}


def section(title):
  print("\n== " + title)


def static_checks():
  section("branch")
  for cmd in (["git", "rev-parse", "--abbrev-ref", "HEAD"], ["git", "log", "-1", "--format=%h %ad %s", "--date=short"]):
    try:
      print("  " + subprocess.check_output(cmd, text=True).strip())
    except Exception as e:  # noqa: BLE001
      print("  git failed:", e)

  section("carrot params (0 = original apilot behavior)")
  from common.params import Params
  params = Params()
  for key in CARROT_PARAMS:
    try:
      value = params.get(key, encoding="utf8")
    except Exception as e:  # noqa: BLE001  (UnknownKeyName = params.cc not rebuilt yet)
      value = f"ERROR {type(e).__name__}: {e}"
    print(f"  {key:22s} {value}")

  section("imports")
  failed = 0
  for name in MODULES:
    t = time.monotonic()
    try:
      importlib.import_module(name)
      print(f"  OK   {name} ({(time.monotonic() - t) * 1000:.0f} ms)")
    except Exception as e:  # noqa: BLE001
      failed += 1
      print(f"  FAIL {name}: {type(e).__name__}: {e}")
  return failed


def find_pids():
  pids = {}
  for pid in os.listdir("/proc"):
    if not pid.isdigit():
      continue
    try:
      with open(f"/proc/{pid}/cmdline", "rb") as f:
        cmd = f.read().replace(b"\0", b" ").decode(errors="ignore")
    except OSError:
      continue
    for name, needle in PROCS.items():
      if needle in cmd or cmd.strip().endswith(name):
        pids.setdefault(name, int(pid))
  return pids


def cpu_ticks(pid):
  with open(f"/proc/{pid}/stat") as f:
    fields = f.read().rsplit(")", 1)[1].split()
  return int(fields[11]) + int(fields[12])  # utime + stime


def live_checks(seconds):
  import cereal.messaging as messaging
  section(f"live stats for {seconds} s")
  pids = find_pids()
  print("  processes:", pids or "none found (is openpilot running?)")
  hz = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
  start_ticks = {n: cpu_ticks(p) for n, p in pids.items()}

  sm = messaging.SubMaster(["radarState", "longitudinalPlan", "carState"])
  counts = {"radarState": 0, "longitudinalPlan": 0}
  valid = lead = radar_lead = cutin_risk = cutin_list = 0
  lag = []
  t0 = time.monotonic()
  while time.monotonic() - t0 < seconds:
    sm.update(100)
    if sm.updated["longitudinalPlan"]:
      counts["longitudinalPlan"] += 1
    if sm.updated["radarState"]:
      counts["radarState"] += 1
      rs = sm["radarState"]
      valid += sm.valid["radarState"]
      lag.append(rs.cumLagMs)
      lead += rs.leadOne.status
      radar_lead += rs.leadOne.status and rs.leadOne.radarTrackId >= 0
      try:
        cutin_risk += rs.leadCutInRisk.status
        cutin_list += len(rs.leadsCutIn) > 0
      except AttributeError:
        pass
  elapsed = time.monotonic() - t0

  n = max(1, counts["radarState"])
  print(f"  radarState        {counts['radarState'] / elapsed:5.1f} Hz (expect ~20), valid {100 * valid / n:5.1f}%")
  print(f"  longitudinalPlan  {counts['longitudinalPlan'] / elapsed:5.1f} Hz (expect ~20)")
  if lag:
    lag_sorted = sorted(lag)
    print(f"  radard cumLagMs   median {lag_sorted[len(lag) // 2]:6.1f}  p95 {lag_sorted[int(len(lag) * .95) - 1]:6.1f}  "
          f"max {lag_sorted[-1]:6.1f}  (positive and growing = radard cannot keep up)")
  print(f"  leadOne status    {100 * lead / n:5.1f}% of frames, with radar track id {100 * radar_lead / n:5.1f}% "
        f"(track ids only with CarrotRadar=1)")
  print(f"  cut-in            risk frames {cutin_risk}, frames with leadsCutIn {cutin_list}")

  section("CPU (% of one core over the window)")
  for name, pid in pids.items():
    try:
      used = (cpu_ticks(pid) - start_ticks[name]) / hz
      print(f"  {name:10s} {100 * used / elapsed:5.1f}%")
    except OSError:
      print(f"  {name:10s} exited during the window (crash/restart? check logs)")


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--live", type=int, default=0, help="seconds of live stats (openpilot must be running)")
  args = parser.parse_args()
  failed = static_checks()
  if args.live > 0:
    live_checks(args.live)
  print("\nRESULT:", "imports OK" if not failed else f"{failed} import failure(s)")


if __name__ == "__main__":
  main()
