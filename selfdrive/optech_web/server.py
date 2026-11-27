#!/usr/bin/env python3
"""OPTECH 웹 (2026-11-27, optech-hkg selfdrive/optech_web 을 spst에 옮김. 같은 와이파이에서 http://기기IP:7000).

상태 · 지금 화면 · 주행 기록과 녹화 영상 받기 · OPTECH 설정 바꾸기 · 도구 (업데이트, 다시 켜기, 브랜치).
설정 목록은 화면 프로그램(OPTECH 메뉴)이 내보내는 /data/optech_web/settings_meta.json
(selfdrive/ui/qt/offroad/optech_panel.cc exportWebMeta)을 그대로 써서 메뉴와 같은 이름 · 설명 · 범위가 나옵니다.
바꾸기 (설정 · 도구)는 시동이 꺼져 있거나, 기어 P에 오픈파일럿이 꺼져 있을 때만 받습니다.
고급 > '웹 접속'(OptechWebServer)을 끄면 포트를 열지 않고 쉽니다.

optech-hkg와 다른 점 (spst 기반 차이):
- 기기 상태 메시지에 와이파이 주소가 없고 배터리 값이 비어 있어서, 둘 다 기기에서 직접 읽습니다.
- '오픈파일럿만 다시 시작'은 없습니다 (spst에 그 기능이 없음).
- 주행 중 부담을 줄이려고 차 정보는 1초에 한 번, 가장 새 메시지만 읽습니다.
"""
import io
import json
import os
import re
import subprocess
import threading
import time
import zipfile

from flask import Flask, Response, jsonify, request, send_file

import cereal.messaging as messaging
from openpilot.common.params import Params

PORT = 7000
HERE = os.path.dirname(os.path.abspath(__file__))
META = "/data/optech_web/settings_meta.json"
DRIVELOG_DIR = "/data/drivelog"
VIDEO_DIR = "/data/media/0/videos"  # = /storage/emulated/0/videos (selfdrive/ui/qt/screenrecorder)
SH = "/data/openpilot/selfdrive/assets/addon/sh"
GIT_SH = ["/usr/bin/bash", SH + "/optech_git.sh"]
PREV = "/data/optech_prev_commit"
OPTECH_URL = "https://github.com/OPTECH-KR/openpilot.git"
SCREEN_TMP = "/tmp/optech_web_screen.png"
BATT = "/sys/class/power_supply/battery/"
SERVICES = ['deviceState', 'pandaStates', 'carState', 'controlsState', 'carParams']
ALIVE_S = {'deviceState': 3., 'pandaStates': 3., 'carState': 2., 'controlsState': 2.}

app = Flask(__name__)
params = Params()
state = {}
state_lock = threading.Lock()
screen_lock = threading.Lock()


def read_file(path):
  try:
    with open(path) as f:
      return f.read().strip()
  except Exception:
    return ''


def wifi_ip():
  """the address a phone on the same wifi / the device's hotspot opens (not mobile data)"""
  try:
    out = subprocess.run(['ip', '-4', '-o', 'addr', 'show'], capture_output=True, text=True, timeout=3).stdout
  except Exception:
    return ''
  ips = {}
  for line in out.splitlines():
    m = re.match(r'^\d+:\s+(\S+)\s+inet\s+([0-9.]+)/', line)
    if m and m.group(1) != 'lo' and not m.group(1).startswith('rmnet'):
      ips[m.group(1)] = m.group(2)
  return ips.get('wlan0') or next(iter(ips.values()), '')


def battery():
  """percent (-1: the device has no battery, e.g. the comma two) and whether it is charging"""
  if not read_file(BATT + 'present').startswith('1'):
    return -1, False
  try:
    pct = int(read_file(BATT + 'capacity'))
  except ValueError:
    return -1, False
  try:
    charging = int(read_file(BATT + 'current_now')) < 0  # negative while charging (as the HUD reads it)
  except ValueError:
    charging = False
  return pct, charging


# ---------------- live state (its own thread; only the newest message of each, once a second) ----------------
def state_thread():
  socks = {s: messaging.sub_sock(s, conflate=True) for s in SERVICES}
  last = {s: None for s in SERVICES}
  seen = {s: 0. for s in SERVICES}
  car = ''
  ip, ip_t = '', 0.
  while True:
    now = time.monotonic()
    for s, sock in socks.items():
      msg = messaging.recv_one_or_none(sock)
      if msg is not None:
        last[s] = getattr(msg, s)
        seen[s] = now
    alive = {s: last[s] is not None and now - seen[s] < ALIVE_S.get(s, 3.) for s in SERVICES}
    if last['carParams'] is not None:  # sent once in a while, keep the last one
      car = last['carParams'].carFingerprint
    if now - ip_t > 10:
      ip, ip_t = wifi_ip(), now
    pct, charging = battery()
    ds = last['deviceState']
    s = {
      'started': bool(ds.started) if alive['deviceState'] else False,
      'temp': round(max(list(ds.cpuTempC) + [0.0])) if ds is not None else 0,
      'battery': pct,
      'charging': charging,
      'free': round(ds.freeSpacePercent) if ds is not None else 0,
      'ip': ip,
      'device_alive': alive['deviceState'],
    }
    try:
      ps = last['pandaStates']
      s['panda'] = alive['pandaStates'] and len(ps) > 0 and str(ps[0].pandaType) != 'unknown'
    except Exception:
      s['panda'] = False
    cs = last['carState']
    s['car'] = car
    s['car_alive'] = alive['carState']
    s['gear'] = str(cs.gearShifter) if alive['carState'] else ''
    s['speed'] = round(cs.vEgo * 3.6) if alive['carState'] else 0
    s['engaged'] = bool(last['controlsState'].enabled) if alive['controlsState'] else False
    with state_lock:
      state.update(s)
    time.sleep(1.0)


def snapshot():
  with state_lock:
    return dict(state)


def can_change(s=None):
  """car off, or gear P with openpilot off"""
  s = s or snapshot()
  if not s.get('started'):
    return True
  return s.get('car_alive', False) and s.get('gear') == 'park' and not s.get('engaged')


def change_refused():
  return jsonify(ok=False, msg="시동이 켜져 있을 때는 기어를 P에 놓고 오픈파일럿을 꺼야 바꿀 수 있어요."), 409


def pget(key):
  try:
    v = params.get(key)
    return v.decode('utf8', 'replace') if v is not None else ''
  except Exception:
    # not a registered key (e.g. GitCommitRemote, written as a plain file by gitcommit.sh): read the file itself
    try:
      with open('/data/params/d/' + os.path.basename(key), encoding='utf-8', errors='replace') as f:
        return f.read()
    except Exception:
      return ''


def other_branch():
  return 'optech-hkg' if pget('GitBranch').startswith('optech-spst') else 'optech-spst'


_update_cache = {}


def has_update(local, remote):
  """a newer version waits: GitCommitRemote (left by the last check) differs from this version and is not already in
  it - an old check (e.g. from before an update by hand) would otherwise say '새 버전 있음' for an older version"""
  local, remote = local.strip(), remote.strip()
  if not remote or remote[:7] == local[:7]:
    return False
  if (local, remote) not in _update_cache:
    try:
      r = subprocess.run(['git', '-C', '/data/openpilot', 'merge-base', '--is-ancestor', remote, 'HEAD'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
      _update_cache[(local, remote)] = r.returncode != 0  # 0: remote is already part of this version
    except Exception:
      _update_cache[(local, remote)] = True
  return _update_cache[(local, remote)]


# ---------------- pages ----------------
@app.route('/')
def index():
  return send_file(os.path.join(HERE, 'index.html'))


@app.route('/api/status')
def api_status():
  s = snapshot()
  try:
    up = int(float(open('/proc/uptime').read().split()[0]))
  except Exception:
    up = 0
  prev = ''
  try:
    p = open(PREV).read().split()
    if len(p) >= 2:
      prev = f"{p[0]} ({p[1][:7]})"
  except Exception:
    pass
  local_full, remote_full = pget('GitCommit'), pget('GitCommitRemote')
  update = has_update(local_full, remote_full)
  s.update({
    'branch': pget('GitBranch'),
    'commit': local_full[:7],
    'commit_date': pget('GitCommitDate'),
    'remote': remote_full[:7],
    'update': update,
    'uptime': up,
    'can_change': can_change(s),
    'other_branch': other_branch(),
    'prev': prev,
  })
  return jsonify(s)


@app.route('/api/screen')
def api_screen():
  """what the device screen shows now, as a small JPEG (PNG if PIL is missing)"""
  with screen_lock:
    try:
      subprocess.run(['/system/bin/screencap', '-p', SCREEN_TMP], env=dict(os.environ, LD_LIBRARY_PATH=''),
                     timeout=10, check=True)
    except Exception:
      return Response("화면을 찍지 못했어요", status=500)
    try:
      from PIL import Image
      img = Image.open(SCREEN_TMP).convert('RGB')
      img.thumbnail((1280, 1280))
      buf = io.BytesIO()
      img.save(buf, 'JPEG', quality=80)
      buf.seek(0)
      return send_file(buf, mimetype='image/jpeg', max_age=0)
    except Exception:
      return send_file(SCREEN_TMP, mimetype='image/png', max_age=0)


def list_dir(d, ext):
  out = []
  try:
    for n in os.listdir(d):
      p = os.path.join(d, n)
      if n.endswith(ext) and os.path.isfile(p):
        st = os.stat(p)
        out.append({'name': n, 'size': st.st_size, 'mtime': int(st.st_mtime)})
  except FileNotFoundError:
    pass
  return sorted(out, key=lambda f: f['mtime'], reverse=True)


@app.route('/api/files')
def api_files():
  return jsonify(drivelog=list_dir(DRIVELOG_DIR, '.txt'), videos=list_dir(VIDEO_DIR, '.mp4'))


def safe_path(d, name):
  if not name or name != os.path.basename(name) or name.startswith('.'):
    return None
  p = os.path.join(d, name)
  return p if os.path.isfile(p) else None


@app.route('/files/drivelog/<name>')
def file_drivelog(name):
  p = safe_path(DRIVELOG_DIR, name)
  return send_file(p, as_attachment=True) if p else (Response("없는 파일이에요", status=404))


@app.route('/files/drivelog.zip')
def file_drivelog_zip():
  buf = io.BytesIO()
  with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
    for f in list_dir(DRIVELOG_DIR, '.txt'):
      z.write(os.path.join(DRIVELOG_DIR, f['name']), f['name'])
  buf.seek(0)
  return send_file(buf, mimetype='application/zip', as_attachment=True,
                   download_name=time.strftime('drivelog_%Y%m%d_%H%M.zip'))


@app.route('/files/videos/<name>')
def file_video(name):
  p = safe_path(VIDEO_DIR, name)
  if not p:
    return Response("없는 파일이에요", status=404)
  return send_file(p, mimetype='video/mp4', conditional=True, as_attachment=request.args.get('dl') == '1')


# ---------------- settings ----------------
def load_meta():
  try:
    with open(META, encoding='utf-8') as f:
      return json.load(f)
  except Exception:
    return None


SHOW_IF = re.compile(r'^([A-Za-z0-9_]+)(==|=|>)(.*)$')


@app.route('/api/settings')
def api_settings():
  meta = load_meta()
  if meta is None:
    return jsonify(ok=False, msg="설정 목록이 아직 없어요. 화면 프로그램이 켜지면 만들어집니다.", items=[])
  vals = {}
  for it in meta:
    if it.get('key'):
      it['value'] = vals[it['key']] = pget(it['key'])
    m = SHOW_IF.match(it.get('showIf', ''))
    if m and m.group(1) not in vals:  # a condition on a param that is not an item itself (e.g. OptechDmMode)
      vals[m.group(1)] = pget(m.group(1))
  return jsonify(ok=True, items=meta, vals=vals, can_change=can_change())


@app.route('/api/settings', methods=['POST'])
def api_settings_set():
  if not can_change():
    return change_refused()
  body = request.get_json(force=True, silent=True) or {}
  key, value = str(body.get('key', '')), str(body.get('value', ''))
  item = next((it for it in (load_meta() or []) if key and it.get('key') == key), None)
  if item is None:
    return jsonify(ok=False, msg="메뉴에 없는 설정이에요."), 400
  t = item['type']
  if t == 'toggle':
    if value not in ('0', '1'):
      return jsonify(ok=False, msg="켜기/끄기 값이 아니에요."), 400
  elif t == 'number':
    try:
      n = int(value)
    except ValueError:
      return jsonify(ok=False, msg="숫자가 아니에요."), 400
    if not item['min'] <= n <= item['max']:
      return jsonify(ok=False, msg=f"{item['min']} ~ {item['max']} 사이로 넣어 주세요."), 400
    value = str(n)
  elif t == 'choice':
    if value not in item['values']:
      return jsonify(ok=False, msg="고를 수 없는 값이에요."), 400
  else:
    return jsonify(ok=False, msg="바꿀 수 없는 항목이에요."), 400
  try:
    params.put(key, value)
    # what the menu also writes when it changes these (optech_panel.cc)
    special = item.get('special', '')
    if special == 'latMethod':  # '조향 방식' replaces the dragonpilot switch
      params.put('dp_lat_controller', '0')
    elif special == 'offShutdown':  # '시동 끈 뒤 꺼짐' replaces the dragonpilot auto shutdown
      params.put_bool('dp_device_auto_shutdown', False)
  except Exception as e:
    return jsonify(ok=False, msg=f"저장하지 못했어요 ({e})"), 500
  return jsonify(ok=True, reboot=bool(item.get('reboot')))


# ---------------- tools ----------------
def background(cmd):
  subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


@app.route('/api/tool/<name>', methods=['POST'])
def api_tool(name):
  body = request.get_json(force=True, silent=True) or {}
  if name == 'check':
    try:
      subprocess.run(['/usr/bin/bash', SH + '/gitcommit.sh'], timeout=90, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
    except Exception:
      pass
    local, remote = pget('GitCommit'), pget('GitCommitRemote')
    try:
      changes = open('/tmp/update_changelog.txt', encoding='utf-8').read().strip()
    except Exception:
      changes = ''
    if not remote.strip():
      return jsonify(ok=False, msg="업데이트 서버에 연결하지 못했어요. 와이파이 연결을 확인해 주세요.")
    return jsonify(ok=True, local=local[:7], remote=remote[:7], update=has_update(local, remote), changes=changes)

  if not can_change():
    return change_refused()
  if name == 'update':
    background(['/usr/bin/bash', SH + '/gitpull.sh'])
    return jsonify(ok=True, msg="업데이트를 받는 중이에요. 새 버전이 있으면 받은 뒤 자동으로 다시 켜져요 (켤 때 몇 분 빌드).")
  if name == 'reboot':
    background(['/usr/bin/bash', '-c', 'sync; sleep 1; /system/bin/reboot || reboot'])
    return jsonify(ok=True, msg="기기를 다시 켜요. 1~2분 뒤 이 페이지를 새로 고쳐 주세요.")
  if name == 'reset':
    background(GIT_SH + ['reset'])
    return jsonify(ok=True, msg="바뀐 프로그램 파일을 되돌리고 다시 켜요.")
  if name == 'restore':
    if not os.path.isfile(PREV):
      return jsonify(ok=False, msg="되돌릴 이전 버전이 없어요. 업데이트나 브랜치 바꾸기를 한 뒤에 쓸 수 있어요.")
    background(GIT_SH + ['restore'])
    return jsonify(ok=True, msg="이전 버전으로 되돌리고 다시 켜요 (켤 때 몇 분 빌드).")
  if name == 'branch':
    if body.get('choice') == 'other':
      url, br = OPTECH_URL, other_branch()
    else:
      gid, repo, br = (str(body.get(k, '')).strip() for k in ('id', 'repo', 'branch'))
      if repo.endswith('.git'):
        repo = repo[:-4]
      ok_name, ok_branch = re.compile(r'^[A-Za-z0-9._-]+$'), re.compile(r'^[A-Za-z0-9._/-]+$')
      if not (ok_name.match(gid) and ok_name.match(repo) and ok_branch.match(br)):
        return jsonify(ok=False, msg="영문, 숫자와 . _ - 만 쓸 수 있어요 (브랜치는 / 도).")
      url = f"https://github.com/{gid}/{repo}.git"
    found = subprocess.run(GIT_SH + ['check', url, br], timeout=40).returncode == 0
    if not found:
      return jsonify(ok=False, msg=f"브랜치를 찾지 못했어요: {url} -b {br}. 주소와 와이파이 연결을 확인해 주세요.")
    background(GIT_SH + ['switch', url, br])
    return jsonify(ok=True, msg=f"{br} 브랜치를 받는 중이에요. 받은 뒤 자동으로 다시 켜져요 (켤 때 몇 분 빌드).")
  return jsonify(ok=False, msg="모르는 도구예요."), 404


def main():
  if not params.get_bool('OptechWebServer'):
    while True:  # turned off in 고급 > 웹 접속: stay idle (the manager would restart a process that exits)
      time.sleep(3600)
  try:
    os.nice(10)  # never compete with the driving processes
  except Exception:
    pass
  threading.Thread(target=state_thread, daemon=True).start()
  import logging
  logging.getLogger('werkzeug').setLevel(logging.WARNING)
  app.run(host='0.0.0.0', port=PORT, threaded=True, use_reloader=False)


if __name__ == '__main__':
  main()
