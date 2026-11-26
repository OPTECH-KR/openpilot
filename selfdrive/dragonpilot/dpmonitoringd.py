#!/usr/bin/env python3
# a simple steering only driver monitor module for C2 (dragonpilot, as optech-hkg's 토글 > 운전자 모니터링 '경도 사용')
# No driver camera: any steering, pedal or cruise button use counts as attention; 5 min without any -> warnings.

import gc

import cereal.messaging as messaging
from cereal import car
from openpilot.common.realtime import set_realtime_priority, Ratekeeper, DT_DMON
from openpilot.selfdrive.controls.lib.events import Events
from openpilot.selfdrive.dragonpilot.driver_monitor import DriverStatus

MAX_TERMINAL_ALERTS = 3  # not allowed to engage after 3 terminal alerts
MAX_TERMINAL_DURATION = int(30 / DT_DMON)  # not allowed to engage after 30s of terminal alerts


def dpmonitoringd_thread(sm=None, pm=None):
  rk = Ratekeeper(1. / DT_DMON, print_delay_threshold=None)
  gc.disable()
  set_realtime_priority(2)

  if pm is None:
    pm = messaging.PubMaster(['driverMonitoringState'])

  if sm is None:
    sm = messaging.SubMaster(['carState', 'controlsState'])

  driver_status = DriverStatus()

  v_cruise_last = 0
  driver_engaged = False

  while True:
    sm.update()

    # Get interaction
    if sm.updated['carState']:
      v_cruise = sm['carState'].cruiseState.speed
      driver_engaged = len(sm['carState'].buttonEvents) > 0 or \
                       v_cruise != v_cruise_last or \
                       sm['carState'].steeringPressed or \
                       sm['carState'].gasPressed or \
                       sm['carState'].brakePressed
      v_cruise_last = v_cruise

    events = Events()

    if driver_status.terminal_alert_cnt >= MAX_TERMINAL_ALERTS or \
       driver_status.terminal_time >= MAX_TERMINAL_DURATION:
      events.add(car.CarEvent.EventName.tooDistracted)

    # Update events from driver state
    driver_status.update_events(events, driver_engaged, sm['controlsState'].enabled, sm['carState'].standstill)

    dat = messaging.new_message('driverMonitoringState')
    dat.driverMonitoringState = {
      "events": events.to_msg(),
      "awarenessStatus": driver_status.awareness,
      "isActiveMode": driver_status.awareness <= driver_status.threshold_prompt,
    }
    pm.send('driverMonitoringState', dat)
    rk.keep_time()


def main(sm=None, pm=None):
  dpmonitoringd_thread(sm, pm)


if __name__ == '__main__':
  main()
