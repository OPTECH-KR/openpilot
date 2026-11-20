#!/usr/bin/env python3
"""Car signal check while the device waits for ignition (optech).

A remote tester's Bolt EUV stayed offroad while the car was READY. This shows, on the offroad home screen, what the
panda actually hears, so a photo tells us why: harness orientation, ignition line / CAN ignition, how many CAN
messages each bus carries, and the GM ignition messages 0x160 (this panda's CAN ignition) and 0x1F1 (newer comma).

Only while offroad, and only after car CAN has been seen for a while with no ignition (a parked, sleeping car sends
nothing, so normal users never see it). Onroad it closes its socket and sleeps.
"""
import time

import cereal.messaging as messaging
from common.params import Params
from selfdrive.controls.lib.alertmanager import set_offroad_alert

ALERT = "Offroad_OptechCanDiag"
WINDOW = 3.0       # s of CAN per sample
SHOW_AFTER = 15.0  # s of car CAN without ignition before the message shows
HARNESS = {"notConnected": "연결 안 됨", "normal": "정상", "flipped": "뒤집힘"}


def sample(sock, seconds):
  """addresses seen per bus, and the GM ignition messages (bus, ignition on?)"""
  seen = {}
  gm_160 = gm_1f1 = None
  end = time.monotonic() + seconds
  while time.monotonic() < end:
    for m in messaging.drain_sock(sock, wait_for_one=True):
      for c in m.can:
        if c.src >= 128:  # panda's own sent messages
          continue
        seen.setdefault(c.src, set()).add(c.address)
        if c.address == 0x160 and len(c.dat) == 5:
          gm_160 = (c.src, int.from_bytes(c.dat[:4], "big") != 0)
        elif c.address == 0x1F1 and len(c.dat) == 8:
          gm_1f1 = (c.src, (c.dat[0] & 0x2) != 0)
  return seen, gm_160, gm_1f1


def describe(seen, gm_160, gm_1f1, ps):
  def gm(v):
    return "없음" if v is None else f"bus{v[0]} {'켜짐' if v[1] else '꺼짐'}"
  buses = ", ".join(f"bus{b} {len(a)}종" for b, a in sorted(seen.items())) or "없음"
  if ps is None:
    panda = "판다 상태 없음"
  else:
    panda = (f"하네스 {HARNESS.get(str(ps.harnessStatus), str(ps.harnessStatus))}, "
             f"시동선 {'켜짐' if ps.ignitionLine else '꺼짐'}, CAN 시동 {'켜짐' if ps.ignitionCan else '꺼짐'}")
  return f"\n{panda}\n차 신호: {buses}\nGM 시동 메시지 0x160: {gm(gm_160)} / 0x1F1: {gm(gm_1f1)}"


def main():
  params = Params()
  sm = messaging.SubMaster(["pandaStates"])
  sock = None
  shown = False
  traffic_since = None
  while True:
    if params.get_bool("IsOnroad"):
      if sock is not None:
        del sock
        sock = None
      if shown:
        set_offroad_alert(ALERT, False)
        shown = False
      traffic_since = None
      time.sleep(5.)
      continue

    if sock is None:
      sock = messaging.sub_sock("can", timeout=100)
    seen, gm_160, gm_1f1 = sample(sock, WINDOW)
    sm.update(0)
    ps = sm["pandaStates"][0] if sm.rcv_frame["pandaStates"] > 0 and len(sm["pandaStates"]) > 0 else None
    ignition = ps is not None and (ps.ignitionLine or ps.ignitionCan)

    if seen and not ignition:
      traffic_since = traffic_since or time.monotonic()
      if time.monotonic() - traffic_since > SHOW_AFTER:
        set_offroad_alert(ALERT, True, describe(seen, gm_160, gm_1f1, ps))
        shown = True
    else:
      traffic_since = None
      if shown:
        set_offroad_alert(ALERT, False)
        shown = False
    time.sleep(2.)


if __name__ == "__main__":
  main()
