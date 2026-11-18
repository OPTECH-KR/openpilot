#!/usr/bin/env python3
"""Small text drive log for road tests without a laptop.

Runs while onroad (started by manager) and writes /data/drivelog/<date>-<time>.txt:
  * one status line per second (speed, set speed, engage state, pedals, steering, lead,
    average CPU %, max CPU temp, memory %, free storage GB)
  * an event line right away when engage state or the alert text changes, a fault event appears or clears
    (canError, steerUnavailable, commIssue, radarFault, ...), controlsd lags, or a process stops
  * python process crashes write their traceback to crash-<time>-<name>.txt (selfdrive/manager/process.py)

Only the newest message of each service is read (conflated sockets, 10 checks per second),
so the CPU cost stays small. The newest KEEP_FILES files are kept.

Read later over SSH:  ls /data/drivelog  /  cat /data/drivelog/<file>
"""
import datetime
import os
import time

import cereal.messaging as messaging

LOG_DIR = "/data/drivelog"
KEEP_FILES = 30
SERVICES = ("carState", "controlsState", "carControl", "radarState", "deviceState", "managerState", "carEvents",
            "gpsLocationExternal")

# events that happen in normal driving (buttons, pedals, lane change prompts): not written as faults
NORMAL_EVENTS = {
  "buttonCancel", "buttonEnable", "pcmEnable", "pcmDisable", "pedalPressed", "gasPressedOverride", "steerOverride",
  "preEnableStandstill", "preLaneChangeLeft", "preLaneChangeRight", "laneChange", "resumeRequired",
  "cruisePaused", "cruiseResume", "trafficSignGreen", "trafficSignChanged", "autoHold", "trafficStopping",
  "speedDown", "audioPrompt", "audioRefuse", "stopStop", "audioLaneChange", "audioTurn", "brakeHold",
}
LAG_EVENT_MS = 100  # controlsd frame late by more than this -> event (at most every 10 s)

HEADER = ("# time | v km/h | set | en act lat lon | gas brk str | angle torque | steerCmd accel | "
          "lead d/vrel | cpu% temp mem% freeGB | lag ms | gps fix sats strong cno accm | fdrop% radarlag")


DIAG_FILE = os.path.join(LOG_DIR, "diag.txt")
DIAG_MAX_BYTES = 2_000_000


def diag_write(text):
  """Append one diagnostic line (controlsd: which services made commIssue / radarFault). Only called on a change,
  never raises, and starts over when the file passes DIAG_MAX_BYTES."""
  try:
    os.makedirs(LOG_DIR, exist_ok=True)
    mode = "w" if os.path.isfile(DIAG_FILE) and os.path.getsize(DIAG_FILE) > DIAG_MAX_BYTES else "a"
    with open(DIAG_FILE, mode, encoding="utf8") as f:
      f.write(f"{datetime.datetime.now():%m-%d %H:%M:%S.%f}"[:-3] + f" {text}\n")
  except Exception:  # noqa: BLE001
    pass


def b(x):
  return "1" if x else "0"


class DriveLog:
  def __init__(self, out):
    self.out = out
    self.socks = {s: messaging.sub_sock(s, conflate=True) for s in SERVICES}
    self.last = {}
    self.prev_engage = None
    self.prev_alert = ""
    self.dead = set()
    self.events = set()
    self.next_line = time.monotonic()
    self.next_lag_event = 0.
    # GPS (uno uBlox or phone, see GpsSource): satellites from ubloxGnss.measurementReport, which shares the
    # service with other uBlox messages, so it is drained instead of conflated
    self.gnss_sock = messaging.sub_sock("ubloxGnss")
    self.gps_sats = self.gps_strong = self.gps_cno = 0
    self.gnss_t = self.loc_t = -100.
    self.prev_fix = None
    self.gps_ant = None
    # read once a second (not in SERVICES: modelV2 is big, procLog only comes every 2 s)
    self.model_sock = messaging.sub_sock("modelV2", conflate=True)
    self.proc_sock = messaging.sub_sock("procLog", conflate=True)
    self.proc_prev = None  # (time, {pid: (name, cpu seconds)})
    self.next_cpu_event = time.monotonic() + 30.

  def event(self, text):
    self.out.write(f"{datetime.datetime.now():%H:%M:%S} ** {text}\n")

  def step(self):
    for s, sock in self.socks.items():
      msg = messaging.recv_one_or_none(sock)
      if msg is not None:
        self.last[s] = getattr(msg, s)

    cs, ctl, cc = self.last.get("carState"), self.last.get("controlsState"), self.last.get("carControl")

    now = time.monotonic()
    for msg in messaging.drain_sock(self.gnss_sock):
      if msg.ubloxGnss.which() == "measurementReport":
        cnos = sorted((m.cno for m in msg.ubloxGnss.measurementReport.measurements if m.cno > 0), reverse=True)
        self.gps_sats, self.gps_strong = len(cnos), sum(c >= 30 for c in cnos)
        self.gps_cno = sum(cnos[:4]) // len(cnos[:4]) if cnos else 0
        self.gnss_t = now
      elif msg.ubloxGnss.which() == "hwStatus":
        hw = msg.ubloxGnss.hwStatus
        ant = (str(hw.aStatus), str(hw.aPower))
        if ant != self.gps_ant:  # uBlox antenna supervisor: ok / short / open / dontknow
          self.event(f"gps antenna {ant[0]} power {ant[1]} (noise {hw.noisePerMS}, agc {hw.agcCnt}, jam {hw.jamInd})")
          self.gps_ant = ant
    loc = self.last.get("gpsLocationExternal")
    if "gpsLocationExternal" in self.last and loc is not self.last.get("_loc_seen"):
      self.last["_loc_seen"] = loc
      self.loc_t = now
    loc_alive = loc is not None and now - self.loc_t < 3.
    fix = loc_alive and bool(loc.flags & 1)
    if self.prev_fix is not None and fix != self.prev_fix:
      self.event(f"gps fix {'on' if fix else 'lost'} (sats {self.gps_sats}, strong {self.gps_strong}"
                 + (f", acc {loc.accuracy:.0f} m)" if fix else ")"))
    self.prev_fix = fix

    if ctl is not None:
      engage = (ctl.enabled, ctl.active)
      if self.prev_engage is not None and engage != self.prev_engage:
        p = self.prev_engage
        self.event(f"engage {b(p[0])}{b(p[1])} -> {b(engage[0])}{b(engage[1])} ({ctl.alertText1} {ctl.alertText2})")
      self.prev_engage = engage
      alert = f"{ctl.alertText1} {ctl.alertText2}".strip()
      if alert and alert != self.prev_alert:
        self.event(f"alert: {alert}")
      self.prev_alert = alert

    ms = self.last.get("managerState")
    if ms is not None:
      for p in ms.processes:
        down = p.shouldBeRunning and not p.running
        if down and p.name not in self.dead:
          self.event(f"process stopped: {p.name} (exit {p.exitCode})")
          self.dead.add(p.name)
        elif not down and p.name in self.dead:
          self.event(f"process back: {p.name}")
          self.dead.discard(p.name)

    ev = self.last.get("carEvents")
    if ev is not None:
      names = {str(e.name) for e in ev} - NORMAL_EVENTS
      added, cleared = names - self.events, self.events - names
      if added or cleared:
        self.event("events " + " ".join([f"+{n}" for n in sorted(added)] + [f"-{n}" for n in sorted(cleared)]))
      self.events = names

    now = time.monotonic()
    if ctl is not None and ctl.cumLagMs > LAG_EVENT_MS and now >= self.next_lag_event:
      self.event(f"controlsd lag {ctl.cumLagMs:.0f} ms")
      self.next_lag_event = now + 10.

    now = time.monotonic()
    if now < self.next_line or cs is None:
      return
    self.next_line = now + 1.0

    parts = [f"{datetime.datetime.now():%H:%M:%S}", f"{cs.vEgo * 3.6:5.1f}"]
    parts.append(f"{ctl.vCruise:3.0f}" if ctl is not None else "-")
    if ctl is not None and cc is not None:
      parts.append(f"{b(ctl.enabled)} {b(ctl.active)} {b(cc.latActive)} {b(cc.longActive)}")
    else:
      parts.append("- - - -")
    parts.append(f"{b(cs.gasPressed)} {b(cs.brakePressed)} {b(cs.steeringPressed)}")
    parts.append(f"{cs.steeringAngleDeg:6.1f} {cs.steeringTorque:6.0f}")
    parts.append(f"{cc.actuators.steer:5.2f} {cc.actuators.accel:5.2f}" if cc is not None else "- -")
    rs = self.last.get("radarState")
    if rs is not None and rs.leadOne.status:
      parts.append(f"{rs.leadOne.dRel:5.1f} {rs.leadOne.vRel * 3.6:5.1f}")
    else:
      parts.append("- -")
    ds = self.last.get("deviceState")
    if ds is not None:
      cpu = sum(ds.cpuUsagePercent) // len(ds.cpuUsagePercent) if len(ds.cpuUsagePercent) else 0
      temp = max(ds.cpuTempC) if len(ds.cpuTempC) else 0
      st = os.statvfs("/data")
      free_gb = st.f_bavail * st.f_frsize / 1e9
      parts.append(f"{cpu:3d} {temp:4.0f} {ds.memoryUsagePercent:3d} {free_gb:5.1f}")
    else:
      parts.append("- - - -")
    parts.append(f"{ctl.cumLagMs:5.0f}" if ctl is not None else "-")
    if now - self.gnss_t < 3. or loc_alive:
      acc = f"{loc.accuracy:5.0f}" if fix else "    -"
      parts.append(f"{b(fix)} {self.gps_sats:2d} {self.gps_strong:2d} {self.gps_cno:2d} {acc}")
    else:
      parts.append("- - - - -")
    md = messaging.recv_one_or_none(self.model_sock)
    rs_lag = f"{rs.cumLagMs:5.0f}" if rs is not None else "-"
    parts.append((f"{md.modelV2.frameDropPerc:4.1f} " if md is not None else "- ") + rs_lag)
    self.out.write(" | ".join(parts) + "\n")
    self.cpu_top(now)

  def cpu_top(self, now):
    """Every 60 s: the processes using the most CPU since the last snapshot (percent of one core)."""
    pl = messaging.recv_one_or_none(self.proc_sock)
    if pl is None:
      return
    snap = {p.pid: (p.name, p.cpuUser + p.cpuSystem) for p in pl.procLog.procs}
    if self.proc_prev is None:
      self.proc_prev = (now, snap)
      return
    if now >= self.next_cpu_event:
      dt = now - self.proc_prev[0]
      old = self.proc_prev[1]
      use = [(name, (t - old[pid][1]) / dt * 100.) for pid, (name, t) in snap.items() if pid in old and dt > 0]
      top = sorted(use, key=lambda x: -x[1])[:6]
      self.event("cpu top: " + ", ".join(f"{n} {u:.0f}%" for n, u in top))
      self.next_cpu_event = now + 60.
      self.proc_prev = (now, snap)


def main():
  os.makedirs(LOG_DIR, exist_ok=True)
  for prefix in ("2", "crash-"):  # drive logs (<date>-<time>.txt) and crash tracebacks, kept separately
    for f in sorted(f for f in os.listdir(LOG_DIR) if f.startswith(prefix) and f.endswith(".txt"))[:-KEEP_FILES]:
      try:
        os.remove(os.path.join(LOG_DIR, f))
      except OSError:
        pass

  path = os.path.join(LOG_DIR, datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ".txt")
  with open(path, "a", buffering=1, encoding="utf8") as out:
    out.write(HEADER + "\n")
    log = DriveLog(out)
    try:
      from common.params import Params
      log.event("gps source: " + ("phone" if Params().get("GpsSource", encoding="utf8") == "1" else "panda/uno"))
    except Exception:  # noqa: BLE001
      pass
    errors = 0
    while True:
      try:
        log.step()
      except Exception as e:  # noqa: BLE001  (one bad message must not stop the log)
        errors += 1
        if errors <= 5:
          log.event(f"drivelog error: {type(e).__name__}: {e}")
      time.sleep(0.1)


if __name__ == "__main__":
  main()
