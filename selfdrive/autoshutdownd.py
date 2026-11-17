#!/usr/bin/env python3

import os
import time
import cereal.messaging as messaging
from common.params import Params


def main():

  shutdown_at = 60*10
  shutdown_count = 0
  device_state_sock = messaging.sub_sock('deviceState')
  params = Params()

  while 1:
    msg = messaging.recv_sock(device_state_sock, wait=True)
    if msg is not None:
      # AutoShutdown (시작 탭 '자동 꺼짐'): off keeps the device on while it runs on its battery
      if not msg.deviceState.usbOnline and not msg.deviceState.started and params.get_bool("AutoShutdown"):
        shutdown_count += 5
      else:
        shutdown_count = 0
    else:
      shutdown_count = 0

    print('current', shutdown_count, 'shutdown_at', shutdown_at)

    if shutdown_count >= shutdown_at > 0:
      os.system('LD_LIBRARY_PATH="" svc power shutdown')

    time.sleep(5)


if __name__ == "__main__":
  main()
