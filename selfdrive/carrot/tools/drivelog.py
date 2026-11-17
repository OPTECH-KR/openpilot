#!/usr/bin/env python3
"""Small text drive log for road tests without a laptop.

Runs while onroad (started by manager) and writes /data/drivelog/<date>-<time>.txt:
  * one status line per second (speed, set speed, engage state, pedals, steering, lead,
    average CPU %, max CPU temp, memory %, free storage GB)
  * an event line right away when engage state or the alert text changes, or a process stops

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
SERVICES = ("carState", "controlsState", "carControl", "radarState", "deviceState", "managerState")

HEADER = ("# time | v km/h | set | en act lat lon | gas brk str | angle torque | steerCmd accel | "
          "lead d/vrel | cpu% temp mem% freeGB | lag ms")


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
    self.next_line = time.monotonic()

  def event(self, text):
    self.out.write(f"{datetime.datetime.now():%H:%M:%S} ** {text}\n")

  def step(self):
    for s, sock in self.socks.items():
      msg = messaging.recv_one_or_none(sock)
      if msg is not None:
        self.last[s] = getattr(msg, s)

    cs, ctl, cc = self.last.get("carState"), self.last.get("controlsState"), self.last.get("carControl")

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
    self.out.write(" | ".join(parts) + "\n")


def main():
  os.makedirs(LOG_DIR, exist_ok=True)
  for f in sorted(f for f in os.listdir(LOG_DIR) if f.endswith(".txt"))[:-KEEP_FILES]:
    try:
      os.remove(os.path.join(LOG_DIR, f))
    except OSError:
      pass

  path = os.path.join(LOG_DIR, datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ".txt")
  with open(path, "a", buffering=1, encoding="utf8") as out:
    out.write(HEADER + "\n")
    log = DriveLog(out)
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
