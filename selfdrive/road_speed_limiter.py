import json
import os
import random

import select
import threading
import time
import socket
import fcntl
import struct
from threading import Thread
from cereal import messaging, log
from common.numpy_fast import clip
from common.realtime import sec_since_boot
from common.conversions import Conversions as CV
from common.params import Params

CAMERA_SPEED_FACTOR = 1.05


class Port:
  BROADCAST_PORT = 2899
  RECEIVE_PORT = 2843
  LOCATION_PORT = BROADCAST_PORT
  # optech 2026-11-25: carrot protocol (carrotpilot carrot_man.py): the device announces itself on 7705 with its ip and
  # receive port, the phone app (CarrotNavi = Tmap with carrot code, TmapNda) then sends Tmap SDK JSON to 7706 -
  # the same keys (nTBTTurnType, nSdiType, nRoadLimitSpeed ...) this file already reads from APM's "apilot" object
  CARROT_BROADCAST_PORT = 7705
  CARROT_RECEIVE_PORT = 7706


def get_if_addr(ifname, request):
  """IPv4 of a network interface: request 0x8915 = SIOCGIFADDR (own address), 0x8919 = SIOCGIFBRDADDR (broadcast)."""
  try:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
      return socket.inet_ntoa(fcntl.ioctl(s.fileno(), request, struct.pack('256s', ifname.encode('utf-8')))[20:24])
  except Exception:
    return None


class RoadLimitSpeedServer:
  def __init__(self):
    self.json_road_limit = None
    self.json_apilot = None
    self.active = 0
    self.active_apilot = 0
    self.last_updated = 0
    self.last_updated_apilot = 0
    self.last_updated_active = 0
    self.last_exception = None
    self.lock = threading.Lock()
    self.remote_addr = None

    self.remote_gps_addr = None
    self.last_time_location = 0
    self.carrot_addr = None       # phone app that sent carrot-protocol data (7706)
    self.carrot_updated = 0.
    self.sock_updated = 0.        # last packet from an NDA (843) app, for roadLimitSpeed.naviSource
    self.json_carrot = None
    self.cmd_ignored = False
    # optech 2026-11-25: APM (APilotMan, UDP 7707 / beacon 7708) is no longer received (user: APilotMan + Mappy can't
    # be used any more). Only NDA (843 / beacon 2899) uses the app socket, in 내비 연동 방식 1 (AutoNaviSpeedCtrl 3)
    self.nda = int(Params().get("AutoNaviSpeedCtrl")) == 3

    broadcast = Thread(target=self.broadcast_thread, args=[])
    broadcast.setDaemon(True)
    broadcast.start()

    self.gps_sm = messaging.SubMaster(['gpsLocationExternal'], poll=['gpsLocationExternal'])
    self.gps_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    self.gps_event = threading.Event()
    gps_thread = Thread(target=self.gps_thread, args=[])
    gps_thread.setDaemon(True)
    gps_thread.start()

  def gps_thread(self):
    try:
      period = 1.0
      wait_time = period
      i = 0.
      frame = 1
      start_time = sec_since_boot()
      while True:
        self.gps_event.wait(wait_time)
        self.gps_timer()

        now = sec_since_boot()
        error = (frame * period - (now - start_time))
        i += error * 0.1
        wait_time = period + error * 0.5 + i
        wait_time = clip(wait_time, 0.8, 1.0)
        frame += 1

    except:
      pass

  def gps_timer(self):
    try:
      if self.remote_gps_addr is not None:
        self.gps_sm.update(0)
        if self.gps_sm.updated['gpsLocationExternal']:
          location = self.gps_sm['gpsLocationExternal']

          if location.accuracy < 10.:
            json_location = json.dumps({"location": [
              location.latitude,
              location.longitude,
              location.altitude,
              location.speed,
              location.bearingDeg,
              location.accuracy,
              # optech 2026-11-26: was location.timestamp, a field this cereal does not have (GpsLocationData @7 is
              # unixTimestampMillis): the AttributeError was caught below, so the GPS never reached the app.
              # TmapNda asks for it (request_gps) and uses it for its openpilot GPS state and the parked spot.
              location.unixTimestampMillis,
              # location.source,
              # location.vNED,
              location.verticalAccuracy,
              location.bearingAccuracyDeg,
              location.speedAccuracy,
            ]})

            address = (self.remote_gps_addr[0], Port.LOCATION_PORT)
            self.gps_socket.sendto(json_location.encode(), address)
    except:
      self.remote_gps_addr = None

  def get_broadcast_address(self):
    try:
      s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
      ip = fcntl.ioctl(
        s.fileno(),
        0x8919,
        struct.pack('256s', 'wlan0'.encode('utf-8'))
      )[20:24]

      return socket.inet_ntoa(ip)
    except:
      return None

  def broadcast_thread(self):

    broadcast_address = None
    frame = 0

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
      try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        while True:

          try:

            if broadcast_address is None or frame % 10 == 0:
              broadcast_address = self.get_broadcast_address()

            print('broadcast_address', broadcast_address)

            if broadcast_address is not None and self.nda:   # NDA beacon only (the APM one is gone)
              address = (broadcast_address, Port.BROADCAST_PORT)
              sock.sendto('EON:ROAD_LIMIT_SERVICE:v1'.encode(), address)
          except:
            pass

          time.sleep(5.)
          frame += 1

      except:
        pass

  def start_carrot(self):
    t = Thread(target=self.carrot_broadcast_thread, args=[])
    t.setDaemon(True)
    t.start()

  def carrot_message(self, ip):
    """What carrot_man.make_send_message announces; CarrotNavi reads ip / port (and navi_debug / active_mode)."""
    try:
      onroad = Params().get_bool("IsOnroad")
    except Exception:
      onroad = False
    return json.dumps({"Carrot2": "OPTECH C2", "IsOnroad": onroad, "ip": ip, "port": Port.CARROT_RECEIVE_PORT,
                       "navi_debug": 0, "active_mode": 0, "active": False, "xState": 0, "trafficState": 0})

  def carrot_broadcast_thread(self):
    """Announce this device on 7705 once a second, like carrot_man.broadcast_version_info: to the phone that sends
    carrot data, else to the Wi-Fi broadcast address (wlan0; hotspot), else to 255.255.255.255."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
      try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
      except Exception:
        pass
      while True:
        try:
          ip = get_if_addr('wlan0', 0x8915) or get_if_addr('ap0', 0x8915)
          if ip is not None:
            phone = self.carrot_addr if sec_since_boot() - self.carrot_updated < 10. else None
            targets = [phone[0]] if phone is not None else \
                      [a for a in (get_if_addr('wlan0', 0x8919), get_if_addr('ap0', 0x8919), '255.255.255.255') if a]
            msg = self.carrot_message(ip).encode()
            for t in targets:
              try:
                sock.sendto(msg, (t, Port.CARROT_BROADCAST_PORT))
              except Exception:
                pass
        except Exception:
          pass
        time.sleep(1.)

  def carrot_recv(self, sock):
    """A carrot-protocol packet (7706): top-level Tmap SDK keys, used as the "apilot" object."""
    data, addr = sock.recvfrom(4096)
    json_obj = json.loads(data.decode())
    if not isinstance(json_obj, dict):
      return
    if self.carrot_addr is None or self.carrot_addr[0] != addr[0]:
      print("carrot navi app:", addr)
    self.carrot_addr = addr
    self.carrot_updated = sec_since_boot()
    try:
      self.lock.acquire()
      self.json_carrot = json_obj
    finally:
      self.lock.release()

  def get_tmap_val(self, key, default=None):
    """Tmap SDK keys (nTBTTurnType, nSdiType ...): from the carrot-protocol app while it sends (kept apart from
    APM's messages so the two do not overwrite each other), else from APM's / NDA's "apilot" object."""
    if self.json_carrot is not None and sec_since_boot() - self.carrot_updated < 6.:
      return self.get_json_val(self.json_carrot, key, default)
    return self.get_apilot_val(key, default)

  def navi_source(self):
    """roadLimitSpeed.naviSource, by the port the data came in on (user 2026-11-25: show which link is on, not
    APM / APN): 1 carrot (7706) while it sends - its Tmap values are the ones used -, else 2 NDA (843) while that app
    sends, else 0. 6 s like the other timeouts in this file. (3 was APM, no longer received.)"""
    now = sec_since_boot()
    if self.json_carrot is not None and now - self.carrot_updated < 6.:
      return 1
    if now - self.sock_updated < 6.:
      return 2
    return 0

  def send_sdp(self, sock):
    """Tell the NDA app that sent data where this device is (every second)."""
    if sock is None or not self.nda:
      return
    try:
      sock.sendto('EON:ROAD_LIMIT_SERVICE:v1'.encode(), (self.remote_addr[0], Port.BROADCAST_PORT))
    except:
      pass

  def udp_recv(self, sock, wait_time, carrot_sock=None):
    """sock: the NDA app socket (843), None when NDA is not used; carrot_sock: 7706."""
    ret = False
    try:
      socks = [s for s in (sock, carrot_sock) if s is not None]
      if not socks:
        time.sleep(wait_time)
        return False
      ready = select.select(socks, [], [], wait_time)
      ret = bool(ready[0])
      if ret and carrot_sock is not None and carrot_sock in ready[0]:
        try:
          self.carrot_recv(carrot_sock)
        except Exception as e:
          print("carrot recv error:", e)
        if sock is None or sock not in ready[0]:
          return True
      if ret:
        data, self.remote_addr = sock.recvfrom(2048)
        json_obj = json.loads(data.decode())
        self.sock_updated = sec_since_boot()
        #print(json_obj)

        if 'cmd' in json_obj:
          # optech 2026-11-25: no longer run it. Any device on the same Wi-Fi could send {"cmd": "..."} and get a
          # root shell command run on the C2 (apilot / neokii code, os.system). Ignored, noted once in the log.
          if not self.cmd_ignored:
            self.cmd_ignored = True
            print("road_speed_limiter: ignored a remote 'cmd' from", self.remote_addr)
          ret = False

        if 'request_gps' in json_obj:
          try:
            if json_obj['request_gps'] == 1:
              self.remote_gps_addr = self.remote_addr
            else:
              self.remote_gps_addr = None
            ret = False
          except:
            pass

        if 'echo' in json_obj:
          try:
            echo = json.dumps(json_obj["echo"])
            sock.sendto(echo.encode(), (self.remote_addr[0], Port.BROADCAST_PORT))
            ret = False
          except:
            pass

        try:
          self.lock.acquire()
          try:
            if 'active' in json_obj:
              self.active = json_obj['active']
              self.last_updated_active = sec_since_boot()
          except:
            pass

          if 'road_limit' in json_obj:
            self.json_road_limit = json_obj['road_limit']
            self.last_updated = sec_since_boot()

          if 'apilot' in json_obj:
            self.json_apilot = json_obj['apilot']
            self.last_updated_apilot = sec_since_boot()

        finally:
          self.lock.release()

    except:

      try:
        self.lock.acquire()
        self.json_road_limit = None
      finally:
        self.lock.release()

    return ret

  def check(self):
    now = sec_since_boot()
    if now - self.last_updated > 6.:
      try:
        self.lock.acquire()
        self.json_road_limit = None
      finally:
        self.lock.release()

    if now - self.last_updated_apilot > 6.:
      try:
        self.lock.acquire()
        self.json_apilot = None
      finally:
        self.lock.release()

    if now - self.last_updated_active > 6.:
      self.active = 0
    if now - self.last_updated_apilot > 6.:
      self.active_apilot = 0


  def get_limit_val(self, key, default=None):
    return self.get_json_val(self.json_road_limit, key, default)

  def get_apilot_val(self, key, default=None):
    return self.get_json_val(self.json_apilot, key, default)


  def get_json_val(self, json, key, default=None):

    try:
      if json is None:
        return default

      if key in json:
        return json[key]

    except:
      pass

    return default


def main():
  server = RoadLimitSpeedServer()
  roadLimitSpeed = messaging.pub_sock('roadLimitSpeed')

  sock_carState = messaging.sub_sock("carState")
  carState = None
  CS = None

  xTurnInfo = -1
  xDistToTurn = -1
  xSpdDist = -1
  xSpdLimit = -1
  xSignType = -1
  xRoadSignType = -1
  xRoadLimitSpeed = -1
  xRoadName = ""

  xBumpDistance = 0
  xTurnInfo_prev = xTurnInfo
  sdiDebugText = ""

  sdi_valid_count = 0
  apm_valid_count = 0
  sdiType = -1

  totalDistance = 0.0
  mappyMode = True
  mappyMode_valid = False

  nTBTTurnType = -1
  nSdiType = -1
  nSdiDist = -1
  nSdiSpeedLimit = -1
  nSdiPlusType = -1
  nSdiPlusDist = -1
  nSdiPlusSpeedLimit = -1
  nSdiBlockType = -1
  nSdiBlockSpeed = -1
  nSdiBlockDist = -1
  nTBTDist = -1
  nRoadLimitSpeed = -1
  
  # built-in speed camera DB (used while no navigation app sends camera data)
  speedcam = None
  speedcam_sm = None
  if Params().get_bool("SpeedCamDB"):
    try:
      from selfdrive.carrot.speedcam_db import SpeedCamFinder
      speedcam = SpeedCamFinder()
      speedcam_sm = messaging.SubMaster(['gpsLocationExternal'])
      print("speedcam DB loaded:", len(speedcam.cams), "cameras")
    except Exception as e:
      print("speedcam DB load failed:", e)
      speedcam = None

  prev_recvTime = sec_since_boot()
  # optech: 내비 연동 방식 0 = no navigation app: ignore what an app sends, cameras only from the built-in DB
  try:
    navi_off = int(Params().get("OptechNaviLinkMode") or 1) == 0
  except (TypeError, ValueError):
    navi_off = False
  # optech 2026-11-25: 0.2 s for NDA too (it was 1.0): 내비 연동 방식 1 TmapNda runs as NDA, and with 1.0 the built-in
  # camera DB and the distances were recomputed only once a second while no app sends
  sockWaitTime = 0.2
  send_time = sec_since_boot()

  with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
    try:
      # the NDA app socket (843, else 2843) only in 내비 연동 방식 1 (AutoNaviSpeedCtrl 3). optech 2026-11-25: the APM
      # port 7707 is no longer opened (APilotMan + Mappy can't be used any more; it was also where a remote 'cmd' came in)
      app_sock = None
      if server.nda and not navi_off:
        print("AutoNaviSpeed == 3")
        try:
          sock.bind(('0.0.0.0', 843))
        except:
          sock.bind(('0.0.0.0', Port.RECEIVE_PORT))
        sock.setblocking(False)
        app_sock = sock

      # optech: carrot protocol (CarrotNavi / TmapNda) next to NDA, whenever a navigation app is in use
      carrot_sock = None
      if not navi_off:
        try:
          carrot_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
          carrot_sock.bind(('0.0.0.0', Port.CARROT_RECEIVE_PORT))
          carrot_sock.setblocking(False)
          server.start_carrot()
          print("carrot navi link on", Port.CARROT_RECEIVE_PORT)
        except Exception as e:
          print("carrot navi link off:", e)
          carrot_sock = None

      while True:

        if navi_off:
          time.sleep(sockWaitTime)
          ret = False
        else:
          ret = server.udp_recv(app_sock, sockWaitTime, carrot_sock)

        try:
          carState = messaging.recv_sock(sock_carState, wait=False)
          if carState is not None:
            CS = carState.carState
        except:
          pass

        #print(Port.RECEIVE_PORT)

        dat = messaging.new_message()
        dat.init('roadLimitSpeed')
        dat.roadLimitSpeed.active = server.active
        dat.roadLimitSpeed.naviSource = 0 if navi_off else server.navi_source()
        dat.roadLimitSpeed.roadLimitSpeed = server.get_limit_val("road_limit_speed", 0)
        dat.roadLimitSpeed.isHighway = server.get_limit_val("is_highway", False)
        dat.roadLimitSpeed.camType = server.get_limit_val("cam_type", 0)
        dat.roadLimitSpeed.camLimitSpeedLeftDist = server.get_limit_val("cam_limit_speed_left_dist", 0)
        dat.roadLimitSpeed.camLimitSpeed = server.get_limit_val("cam_limit_speed", 0)
        dat.roadLimitSpeed.sectionLimitSpeed = server.get_limit_val("section_limit_speed", 0)
        dat.roadLimitSpeed.sectionLeftDist = server.get_limit_val("section_left_dist", 0)
        dat.roadLimitSpeed.sectionAvgSpeed = server.get_limit_val("section_avg_speed", 0)
        dat.roadLimitSpeed.sectionLeftTime = server.get_limit_val("section_left_time", 0)
        dat.roadLimitSpeed.sectionAdjustSpeed = server.get_limit_val("section_adjust_speed", False)
        dat.roadLimitSpeed.camSpeedFactor = server.get_limit_val("cam_speed_factor", CAMERA_SPEED_FACTOR)

        atype = server.get_apilot_val("type")
        value = server.get_apilot_val("value")
        atype = "none" if atype is None else atype
        value = "-1" if value is None else value
        try:
          value_int = int(value)
        except:
          value_int = -100

        xCmd = server.get_apilot_val("apilot_cmd")
        xArg = server.get_apilot_val("apilot_arg")
        xIndex = value_int

        now = sec_since_boot()
        if ret:
          prev_recvTime = now

        #print(atype, value)
        delta_dist = 0.0
        if CS is not None:
          delta_dist = CS.totalDistance - totalDistance
          totalDistance = CS.totalDistance
          if CS.gasPressed:
            xBumpDistance = -1
            if xSignType == 124:
              xSignType = -1
        apm_valid = True
        if atype == 'none':
          apm_valid = False
        elif atype == 'opkrturninfo':
          mappyMode_valid = True
          xTurnInfo = value_int
        elif atype == 'opkrdistancetoturn':
          xDistToTurn = value_int
        elif atype == 'opkrspddist':
          xSpdDist = value_int
        elif atype == 'opkr-spddist':
          pass
        elif atype == 'opkrspdlimit':
          mappyMode_valid = True
          xSpdLimit = value_int
        elif atype == 'opkr-spdlimit':
          pass
        elif atype == 'opkrsigntype':
          xSignType = value_int
        elif atype == 'opkr-signtype':
          pass
        elif atype == 'opkrroadsigntype':
          xRoadSignType = value_int
        elif atype == 'opkrroadlimitspeed':
          xRoadLimitSpeed = value_int
        elif atype == 'opkrwazecurrentspd':
          pass
        elif atype == 'opkrwazeroadname':
          xRoadName = value
        elif atype == 'opkrwazenavsign':
          mappyMode_valid = True
          if value == '2131230983': # 목적지
            xTurnInfo = -1
          elif value == '2131230988': # turnLeft
            xTurnInfo = 1
          elif value == '2131230989': # turnRight
            xTurnInfo = 2
          elif value == '2131230985': 
            xTurnInfo = 4
          else:
            xTurnInfo = value_int
          xTurnInfo_prev = xTurnInfo
        elif atype == 'opkrwazenavdist':
          xDistToTurn = value_int
          if xTurnInfo<0:
            xTurnInfo = xTurnInfo_prev
        elif atype == 'opkrwazeroadspdlimit':
          mappyMode_valid = True
          xRoadLimitSpeed = value_int
        elif atype == 'opkrwazealertdist':
          pass
        elif atype == 'opkrwazereportid':
          pass
        elif atype == 'apilotman':
          server.active_apilot = 1
          xIndex = value_int
        else:
          print("unknown{}={}".format(atype, value))
        #dat.roadLimitSpeed.xRoadName = apilot_val['opkrroadname']['value']

        #for 띠맵
        if ret or now - prev_recvTime > 2.0: # 수신값이 있거나, 2.0초가 지난경우 데이터를 초기화함.
          nTBTTurnType = nSdiType = nSdiSpeedLimit = nSdiPlusType = nSdiPlusSpeedLimit = nSdiBlockType = -1
          nSdiBlockSpeed = nRoadLimitSpeed = -1

        nSdiDist -= delta_dist
        nSdiPlusDist -= delta_dist
        nSdiBlockDist -= delta_dist
        nTBTDist -= delta_dist

        if xSpdLimit >= 0:
          xSpdDist -= delta_dist
          if xSpdDist < 0:
            xSpdLimit = -1

        if True: #xTurnInfo >= 0:
          xDistToTurn -= delta_dist
          if xDistToTurn < 0:
            xTurnInfo = -1

        #print("I:{:.1f},{:.1f},{:.1f},{:.2f}".format(nSdiDist, nSdiPlusDist, nTBTDist, delta_dist))

        if ret:
          # optech: Tmap keys from the carrot-protocol app first (get_tmap_val); a value an app sends as text, null or
          # "12.0" keeps the previous value instead of stopping this loop
          def tv(key, cur, conv=int):
            try:
              return conv(float(server.get_tmap_val(key, cur)))
            except (TypeError, ValueError):
              return cur
          nTBTTurnType = tv("nTBTTurnType", nTBTTurnType)
          nSdiType = tv("nSdiType", nSdiType)
          nSdiDist = tv("nSdiDist", nSdiDist, float)
          nSdiSpeedLimit = tv("nSdiSpeedLimit", nSdiSpeedLimit)
          nSdiPlusType = tv("nSdiPlusType", nSdiPlusType)
          nSdiPlusDist = tv("nSdiPlusDist", nSdiPlusDist, float)
          nSdiPlusSpeedLimit = tv("nSdiPlusSpeedLimit", nSdiPlusSpeedLimit)
          nSdiBlockType = tv("nSdiBlockType", nSdiBlockType)
          nSdiBlockSpeed = tv("nSdiBlockSpeed", nSdiBlockSpeed)
          nSdiBlockDist = tv("nSdiBlockDist", nSdiBlockDist, float)
          nTBTDist = tv("nTBTDist", nTBTDist, float)
          nRoadLimitSpeed = tv("nRoadLimitSpeed", nRoadLimitSpeed)

        #print("O:{:.1f},{:.1f},{:.1f},{:.2f}".format(nSdiDist, nSdiPlusDist, nTBTDist, delta_dist))

        sdiDebugText = ":"
        if nSdiType >= 0:
          sdiDebugText += "S-{}/{}/{} ".format(nSdiType, int(nSdiDist), nSdiSpeedLimit)
        if nSdiPlusType >= 0:
          sdiDebugText += "P-{}/{}/{} ".format(nSdiPlusType, int(nSdiPlusDist), nSdiPlusSpeedLimit)
        if nSdiBlockType >= 0:
          sdiDebugText += "B-{}/{}/{} ".format(nSdiBlockType, int(nSdiBlockDist), nSdiBlockSpeed)
        if nTBTTurnType >= 0:
          sdiDebugText += "T-{}/{} ".format(nTBTTurnType, int(nTBTDist))
        #if ret:
        #  print(sdiDebugText)

        if nTBTTurnType in [12, 16]:
          xTurnInfo = 1  # turn left
        elif nTBTTurnType in [13, 19]:
          xTurnInfo = 2  # turn right
        elif nTBTTurnType in [7, 44, 17, 75, 102, 105, 112, 115, 76, 118]: # left lanechange
        #elif nTBTTurnType in [7, 17, 102, 105, 112, 115, 76, 118]: # left lanechange
          xTurnInfo = 3  # slight left
        elif nTBTTurnType in [6, 43, 73, 74, 101, 104, 111, 114, 123, 124, 117]: # right lanechange
        #elif nTBTTurnType in [6, 43, 73, 74, 101, 104, 111, 114]: # right lanechange
          xTurnInfo = 4  # slight right
        elif nTBTTurnType in [14, 131, 132, 133, 134, 135, 136, 137, 138, 139, 140, 141, 142]:
          xTurnInfo = 5 # speed down
        elif nTBTTurnType >= 0:
          xTurnInfo = -1
        if nTBTDist > 0 and xTurnInfo >= 0:
          xDistToTurn = nTBTDist
        sdi_valid = True if nRoadLimitSpeed >= 0 or nTBTTurnType > 0 or nSdiType >= 0 else False
        if nRoadLimitSpeed > 0:
          if nRoadLimitSpeed >= 200:
            nRoadLimitSpeed = (nRoadLimitSpeed - 20) / 10
          xRoadLimitSpeed = nRoadLimitSpeed
        #sdiType: 
        # 0: speedLimit, 1: speedLimitPos, 2:SpeedBlockStartPos, 3: SpeedBlockEndPos, 4:SpeedBlockMidPos, 
        # 5: Tail, 6: SignalAccidentPos, 7: SpeedLimitDangerous, 8:BoxSpeedLimit, 9: BusLane, 
        # 10:ChangerRoadPos, 11:RoadControlPos, 12: IntruderArea, 13: TrafficInfoCollectPos, 14:CctvArea
        # 15:OverloadDangerousArea, 16:LoadBadControlPos, 17:ParkingControlPos, 18:OnewayArea, 19:RailwayCrossing
        # 20:SchoolZoneStart, 21:SchoolZoneEnd, 22:SpeedBump, 23:LpgStation, 24:TunnelArea, 
        # 25:ServiceArea
        # 66:ChangableSpeedBlockStartPos, 67:ChangableSpeedBlockEndPos
        if nSdiType in [0,1,2,3,4,7,8] and nSdiSpeedLimit > 0: # SpeedLimitPos, nSdiSection: 2,
          xSpdLimit = nSdiSpeedLimit
          xSpdDist = nSdiDist
          sdiType = nSdiType
          if sdiType == 4: ## 구간단속
            xSpdDist = nSdiBlockDist if nSdiBlockDist > 0 else 80
          elif sdiType == 7: ##이동식카메라?
            xSpdLimit = xSpdDist = -1
        elif nSdiPlusType == 22 or nSdiType == 22: # SpeedBump
          xSpdLimit = 35
          xSpdDist = nSdiPlusDist if nSdiPlusType == 22 else nSdiDist
          sdiType = 22
        elif sdi_valid and nSdiSpeedLimit <= 0 and not mappyMode: # 데이터는 수신되었으나, sdi 수신이 없으면, 감속중 다른곳으로 빠진경우... 초기화...
          xSpdLimit = xSpdDist = sdiType = -1

        if sdiType >= 0:
          dat.roadLimitSpeed.camType = sdiType

        szPosRoadName = str(server.get_tmap_val("szPosRoadName", "") or "")
        if len(szPosRoadName) > 0:
          xRoadName = szPosRoadName

        sdi_valid_count -= 1
        if sdi_valid:
          sdi_valid_count = 10
        apm_valid_count -= 1
        if apm_valid:
          apm_valid_count = 10

        if xBumpDistance > 0:
          xBumpDistance -= delta_dist
          if xBumpDistance <= 0 and xSignType == 124:
            xSignType = -1
          else:
            dat.roadLimitSpeed.camType = 22 # bump

        if xSignType == 124: ##사고방지턱
          if xBumpDistance <= 0:
            xBumpDistance = 110
        else:
          xBumpDistance = -1

        if sdi_valid_count > 0:
          dat.roadLimitSpeed.active = 200 + server.active
          mappyMode = False
        elif apm_valid_count > 0 and mappyMode_valid:
          dat.roadLimitSpeed.active = 200 + server.active
        elif apm_valid_count > 0:
          dat.roadLimitSpeed.active = 100 + server.active
        else:
          xSpdDist = xBumpDistance = xSpdLimit = -1
          mappyMode_valid = False
        #print(dat.roadLimitSpeed.active)
        #print("turn={},{}".format(xTurnInfo, xDistToTurn))
        dat.roadLimitSpeed.xTurnInfo = int(xTurnInfo)
        dat.roadLimitSpeed.xDistToTurn = int(xDistToTurn)
        dat.roadLimitSpeed.xSpdDist = int(xSpdDist) if xBumpDistance <= 0 else int(xBumpDistance)
        dat.roadLimitSpeed.xSpdLimit = int(xSpdLimit) if xBumpDistance <= 0 else 35 # 속도는 추후조절해야함. 일단 35
        dat.roadLimitSpeed.xSignType = int(xSignType) if xBumpDistance <= 0 else 22
        # built-in camera DB fills the camera fields whenever the navigation app (if any) gives no camera,
        # e.g. APM connected with Tmap/Waze that only send turn-by-turn
        if speedcam is not None and not (xSpdLimit > 0 and xSpdDist > 0):
          cam = None
          try:
            speedcam_sm.update(0)
            gps = speedcam_sm['gpsLocationExternal']
            if speedcam_sm.alive['gpsLocationExternal'] and (gps.flags & 1) and 0 < gps.accuracy < 50:
              cam = speedcam.update(gps.latitude, gps.longitude, gps.bearingDeg, gps.speed, now)
            else:
              speedcam.reset()
          except Exception as e:
            print("speedcam error:", e)
            speedcam.reset()
          if cam is not None and xBumpDistance <= 0:
            dat.roadLimitSpeed.xSpdLimit = int(cam.limit)
            dat.roadLimitSpeed.xSpdDist = int(cam.dist)
            # section: camType 4 / xSignType 165 make the planners hold the limit instead of a point decel
            dat.roadLimitSpeed.camType = 4 if cam.section else 1
            dat.roadLimitSpeed.xSignType = 165 if cam.section else 1

        dat.roadLimitSpeed.xRoadSignType = int(xRoadSignType)
        dat.roadLimitSpeed.xRoadLimitSpeed = int(xRoadLimitSpeed)
        if xRoadLimitSpeed > 0:
          dat.roadLimitSpeed.roadLimitSpeed = int(xRoadLimitSpeed)
        dat.roadLimitSpeed.xRoadName = xRoadName + sdiDebugText

        dat.roadLimitSpeed.xCmd = "" if xCmd is None else xCmd
        dat.roadLimitSpeed.xArg = "" if xArg is None else xArg
        dat.roadLimitSpeed.xIndex = xIndex

        roadLimitSpeed.send(dat.to_bytes())
        if now - send_time > 1.0:
          server.send_sdp(app_sock)
          send_time = now
        server.check()
        #time.sleep(0.03)

    except Exception as e:
      print(e)
      server.last_exception = e


class RoadSpeedLimiter:
  def __init__(self):
    self.slowing_down = False
    self.started_dist = 0
    self.session_limit = False

    self.sock = messaging.sub_sock("roadLimitSpeed")
    self.roadLimitSpeed = None
    self.autoNaviSpeedCtrlStart = 22
    self.autoNaviSpeedCtrlEnd = 6
    self.autoNaviSpeedBumpDist = 10
    self.autoNaviSpeedBumpSpeed = 30
    self.autoNaviSpeedSafetyFactor = 1.05

  def recv(self):
    try:
      dat = messaging.recv_sock(self.sock, wait=False)
      if dat is not None:
        self.roadLimitSpeed = dat.roadLimitSpeed
    except:
      pass

  def get_active(self):
    self.recv()
    if self.roadLimitSpeed is not None:
      return self.roadLimitSpeed.active % 100
    return 0

  def get_max_speed(self, CS, cluster_speed, is_metric, apNaviSpeed, apNaviDistance):

    log = ""
    self.recv()

    if self.roadLimitSpeed is None:
      return 0, 0, 0, False, ""

    try:
      road_limit_speed = self.roadLimitSpeed.roadLimitSpeed
      is_highway = self.roadLimitSpeed.isHighway

      cam_type = int(self.roadLimitSpeed.camType)

      cam_limit_speed_left_dist = self.roadLimitSpeed.camLimitSpeedLeftDist
      cam_limit_speed = self.roadLimitSpeed.camLimitSpeed

      if apNaviSpeed > 0 and apNaviDistance > 0:
        cam_limit_speed = apNaviSpeed
        cam_limit_speed_left_dist = apNaviDistance
        cam_type = 1000
      elif self.roadLimitSpeed.xSpdLimit > 0 and self.roadLimitSpeed.xSpdDist > 0:
        cam_limit_speed_left_dist = self.roadLimitSpeed.xSpdDist
        cam_limit_speed = self.roadLimitSpeed.xSpdLimit
        self.session_limit = True if (self.roadLimitSpeed.xSignType == 165) or (cam_limit_speed_left_dist > 3000) or cam_type==4 else False
        #log = "limit={:.1f},{:.1f}".format(self.roadLimitSpeed.xSpdLimit, self.roadLimitSpeed.xSpdDist)

        self.session_limit = False if cam_limit_speed_left_dist < 50 else self.session_limit

      # optech (user 2026-11-27): the CAN car's own navigation (HDA Navi_HU, interface.py) is not used any more.
      hda_limit_active = False
      # optech-hkg-fd 2026-11-28: the CAN FD stock navigation (selfdrive/car/hyundai/vehicle_navi.py, its OPTECH
      # switches) only while no phone navigation is linked and nothing above gave a camera - school zone, section,
      # camera, speed bump, the order carrot_serv uses. Its 1 m distance means "at / inside it: hold the limit".
      vn_cam = cam_limit_speed is not None and cam_limit_speed > 0 and cam_limit_speed_left_dist is not None and cam_limit_speed_left_dist > 0
      if not vn_cam and not (self.roadLimitSpeed.active > 0):
        if getattr(CS, "schoolZoneActive", False):
          cam_limit_speed, cam_limit_speed_left_dist, cam_type = 30, 1, 4
          hda_limit_active = True
        elif getattr(CS, "vehicleNaviSectionActive", False) and getattr(CS, "vehicleNaviSpeed", 0) > 0:
          cam_limit_speed = int(round(CS.vehicleNaviSpeed))
          cam_limit_speed_left_dist = CS.speedLimitDistance if CS.speedLimitDistance > 1 else 1
          cam_type = 4
          hda_limit_active = True
        elif CS.speedLimit > 0 and CS.speedLimitDistance > 0:
          cam_limit_speed = CS.speedLimit
          cam_limit_speed_left_dist = CS.speedLimitDistance
          hda_limit_active = True
        elif getattr(CS, "vehicleNaviActive", False) and getattr(CS, "speedBumpDistance", 0) > 0:
          cam_limit_speed = self.autoNaviSpeedBumpSpeed
          cam_limit_speed_left_dist = CS.speedBumpDistance
          cam_type = 22
          hda_limit_active = True
        if hda_limit_active:
          self.session_limit = cam_type == 4
          log = "VNAVI={:.0f},{:.0f},type={}".format(float(cam_limit_speed), float(cam_limit_speed_left_dist), cam_type)

      section_limit_speed = self.roadLimitSpeed.sectionLimitSpeed
      section_left_dist = self.roadLimitSpeed.sectionLeftDist
      section_avg_speed = self.roadLimitSpeed.sectionAvgSpeed
      section_left_time = self.roadLimitSpeed.sectionLeftTime
      section_adjust_speed = self.roadLimitSpeed.sectionAdjustSpeed

      #camSpeedFactor = clip(self.roadLimitSpeed.camSpeedFactor, 1.0, 1.1)
      camSpeedFactor = self.autoNaviSpeedSafetyFactor 

      if False and is_highway is not None:
        if is_highway:
          MIN_LIMIT = 40
          MAX_LIMIT = 120
        else:
          MIN_LIMIT = 20
          MAX_LIMIT = 100
      else:
        MIN_LIMIT = 10
        MAX_LIMIT = 120

      if cam_type == 22:  # speed bump
        MIN_LIMIT = 10
        cam_speed_limit = self.autoNaviSpeedBumpSpeed

      if cam_limit_speed_left_dist is not None and cam_limit_speed is not None and cam_limit_speed_left_dist > 0:

        v_ego = cluster_speed * (CV.KPH_TO_MS if is_metric else CV.MPH_TO_MS)
        diff_speed = cluster_speed - (cam_limit_speed * camSpeedFactor)
        #cam_limit_speed_ms = cam_limit_speed * (CV.KPH_TO_MS if is_metric else CV.MPH_TO_MS)

        #starting_dist = v_ego * 30.
        starting_dist = v_ego * self.autoNaviSpeedCtrlStart

        if cam_type == 1000:
          starting_dist = v_ego * 15
          safe_dist = 80
        elif cam_type == 22:
          starting_dist = v_ego * 10 #6
          safe_dist = self.autoNaviSpeedBumpDist #v_ego * 0.5 # speed bump
        else:
          safe_dist = v_ego * self.autoNaviSpeedCtrlEnd

        if not hda_limit_active:
          log = "SPDCTRL({})={:.0f}<{:.0f}<{:.0f},type={},{:.0f}".format(self.slowing_down, safe_dist, cam_limit_speed_left_dist, starting_dist, cam_type, self.started_dist)

        if MIN_LIMIT <= cam_limit_speed <= MAX_LIMIT and (self.slowing_down or cam_limit_speed_left_dist < starting_dist or self.session_limit):
          if not self.slowing_down:
            self.started_dist = cam_limit_speed_left_dist
            self.slowing_down = True
            first_started = True
          else:
            first_started = False

          td = self.started_dist - safe_dist
          d = cam_limit_speed_left_dist - safe_dist

          if d > 0. and td > 0. and diff_speed > 0. and (section_left_dist is None or section_left_dist < 10 or cam_type == 2) and not self.session_limit:
            pp = (d / td) ** 0.6
          else:
            pp = 0

          return cam_limit_speed * camSpeedFactor + int(pp * diff_speed), \
                 cam_limit_speed, cam_limit_speed_left_dist, first_started, log

        self.slowing_down = False
        return 0, cam_limit_speed, cam_limit_speed_left_dist, False, log

      elif section_left_dist is not None and section_limit_speed is not None and section_left_dist > 0:
        if MIN_LIMIT <= section_limit_speed <= MAX_LIMIT:

          if not self.slowing_down:
            self.slowing_down = True
            first_started = True
          else:
            first_started = False

          speed_diff = 0
          if section_adjust_speed is not None and section_adjust_speed:
            speed_diff = (section_limit_speed - section_avg_speed) / 2.

          return section_limit_speed * camSpeedFactor + speed_diff, section_limit_speed, section_left_dist, first_started, log

        self.slowing_down = False
        return 0, section_limit_speed, section_left_dist, False, log

    except Exception as e:
      log = "Ex: " + str(e)
      pass

    self.slowing_down = False
    return 0, 0, 0, False, log


road_speed_limiter = None


def road_speed_limiter_get_active():
  global road_speed_limiter
  if road_speed_limiter is None:
    road_speed_limiter = RoadSpeedLimiter()

  return road_speed_limiter.get_active()


def road_speed_limiter_get_max_speed(cluster_speed, is_metric):
  global road_speed_limiter
  if road_speed_limiter is None:
    road_speed_limiter = RoadSpeedLimiter()

  return road_speed_limiter.get_max_speed(cluster_speed, is_metric)


def get_road_speed_limiter():
  global road_speed_limiter
  if road_speed_limiter is None:
    road_speed_limiter = RoadSpeedLimiter()
  return road_speed_limiter


if __name__ == "__main__":
  main()
