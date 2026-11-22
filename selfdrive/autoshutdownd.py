#!/usr/bin/env python3

import os
import time
import cereal.messaging as messaging
from common.params import Params



def shutdown():
  os.system('LD_LIBRARY_PATH="" svc power shutdown')


def main():
  # conflate: only the latest deviceState counts (this loop wakes every 5 s, deviceState comes at 2 Hz)
  device_state_sock = messaging.sub_sock('deviceState', conflate=True)
  params = Params()

  off_since = None      # car off after a drive since (monotonic s)
  started_seen = False  # the car was on (onroad) at least once since boot

  while 1:
    msg = messaging.recv_sock(device_state_sock, wait=True)
    now = time.monotonic()
    if msg is not None:
      ds = msg.deviceState

      # (고급 '자동 꺼짐', the 10 min battery shutdown, was removed: the devices in use have no battery;
      # '시동 끈 뒤 꺼짐' covers cars with always-on power)
      # OptechOffShutdown (고급 '시동 끈 뒤 꺼짐', seconds, 0 off; tester feedback): after a drive, once the car is off
      # for this long the device turns itself off, even on the car's power. Only after a drive since boot, so a
      # device turned on at home (no drive) stays on for updates and settings
      if ds.started:
        started_seen = True
        off_since = None
      elif started_seen:
        off_since = off_since or now
      try:
        off_s = int(params.get("OptechOffShutdown", encoding="utf8") or 0)
      except (TypeError, ValueError):
        off_s = 0

      if off_s > 0 and off_since is not None and now - off_since >= off_s:
        print('car off shutdown after', off_s, 's')
        shutdown()

    time.sleep(5)


if __name__ == "__main__":
  main()
