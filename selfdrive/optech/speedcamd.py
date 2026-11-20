#!/usr/bin/env python3
"""OPTECH speed camera daemon (same idea as optech-hkg's built-in camera DB).

Finds the Korean fixed speed camera ahead from the GPS position (selfdrive/optech/speedcam_db.py) and
publishes optechSpeedCam: the camera limit, the distance to it and the speed the car should drive now.
The slowdown profile is the one optech-hkg uses (road_speed_limiter.get_max_speed): it starts
OptechCamDecelStart seconds before the camera, reaches limit x OptechCamSafetyFactor % at
OptechCamDecelEnd seconds before it, and holds the limit inside an average-speed section.
The planner only uses targetSpeed when OptechSpeedCamDecel is on and openpilot controls the speed.
"""
import time

import cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.selfdrive.optech.speedcam_db import SpeedCamFinder

MIN_LIMIT, MAX_LIMIT = 10, 120  # km/h; other values in the data are ignored
GPS_MAX_ACCURACY = 50.0  # m


class SlowdownProfile:
  def __init__(self):
    self.slowing_down = False
    self.started_dist = 0.0

  def reset(self):
    self.slowing_down = False

  def target(self, v_ego, limit, dist, section, start_s, end_s, factor):
    """km/h the car should drive now (0 = no slowdown). v_ego in m/s, dist in m."""
    if not (MIN_LIMIT <= limit <= MAX_LIMIT) or dist <= 0:
      self.slowing_down = False
      return 0.0
    if section:
      self.slowing_down = True
      return limit * factor

    cur_kph = v_ego * 3.6
    diff_speed = cur_kph - limit * factor
    starting_dist = v_ego * start_s
    safe_dist = v_ego * end_s
    if not (self.slowing_down or dist < starting_dist):
      return 0.0
    if not self.slowing_down:
      self.started_dist = dist
      self.slowing_down = True

    td = self.started_dist - safe_dist
    d = dist - safe_dist
    pp = (d / td) ** 0.6 if d > 0. and td > 0. and diff_speed > 0. else 0.
    return limit * factor + pp * max(diff_speed, 0.)


def main():
  params = Params()
  finder = SpeedCamFinder()
  profile = SlowdownProfile()
  sm = messaging.SubMaster(['gpsLocationExternal', 'carState'])
  pm = messaging.PubMaster(['optechSpeedCam'])
  rk = Ratekeeper(5, print_delay_threshold=None)

  start_s, end_s, factor = 22., 6., 1.05
  frame = 0
  while True:
    sm.update(0)
    if frame % 25 == 0:  # settings every 5 s
      try:
        start_s = float(params.get("OptechCamDecelStart", encoding="utf8") or 22)
        end_s = float(params.get("OptechCamDecelEnd", encoding="utf8") or 6)
        factor = float(params.get("OptechCamSafetyFactor", encoding="utf8") or 105) / 100.
      except (TypeError, ValueError):
        pass
    frame += 1

    cam = None
    gps = sm['gpsLocationExternal']
    if sm.alive['gpsLocationExternal'] and (gps.flags & 1) and 0 < gps.accuracy < GPS_MAX_ACCURACY:
      try:
        cam = finder.update(gps.latitude, gps.longitude, gps.bearingDeg, gps.speed, time.monotonic())
      except Exception:
        finder.reset()
    else:
      finder.reset()

    msg = messaging.new_message('optechSpeedCam')
    out = msg.optechSpeedCam
    if cam is not None:
      target = profile.target(sm['carState'].vEgo, cam.limit, cam.dist, cam.section, start_s, end_s, factor)
      out.camLimit = int(cam.limit)
      out.camDist = float(cam.dist)
      out.section = bool(cam.section)
      out.targetSpeed = float(target)
      out.active = target > 0
    else:
      profile.reset()
    pm.send('optechSpeedCam', msg)
    rk.keep_time()


if __name__ == "__main__":
  main()
