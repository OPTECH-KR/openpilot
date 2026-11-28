#!/usr/bin/env python3
"""OPTECH 웹 (2026-11-27, 당근처럼 같은 와이파이에서 http://기기IP:7000 으로 들어오는 페이지).

상태 · 지금 화면 · 주행 기록과 녹화 영상 받기 · OPTECH 설정 바꾸기 · 도구 (업데이트, 다시 켜기, 브랜치).
설정 목록은 화면 프로그램이 켜질 때 내보내는 /data/optech_web/settings_meta.json (settings.cc optech_export_web_meta)
을 그대로 써서 메뉴와 같은 이름 · 설명 · 범위가 나옵니다.
바꾸기 (설정 · 도구)는 시동이 꺼져 있거나, 기어 P에 오픈파일럿이 꺼져 있을 때만 받습니다 (소프트웨어 메뉴와 같은 규칙).
고급 > '웹 접속'(OptechWebServer)을 끄면 포트를 열지 않고 쉽니다.
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
from common.params import Params

PORT = 7000
HERE = os.path.dirname(os.path.abspath(__file__))
META = "/data/optech_web/settings_meta.json"
DRIVELOG_DIR = "/data/drivelog"
VIDEO_DIR = "/data/media/0/videos"
SH = "/data/openpilot/selfdrive/assets/addon/sh"
GIT_SH = ["/usr/bin/bash", SH + "/optech_git.sh"]
PREV = "/data/optech_prev_commit"
OPTECH_URL = "https://github.com/OPTECH-KR/openpilot.git"
SCREEN_TMP = "/tmp/optech_web_screen.png"

app = Flask(__name__)
params = Params()
state = {}
state_lock = threading.Lock()
screen_lock = threading.Lock()


# ---------------- live state (one SubMaster in its own thread) ----------------
def state_thread():
  sm = messaging.SubMaster(['deviceState', 'pandaStates', 'carState', 'controlsState', 'carParams'])
  car = ''
  while True:
    sm.update(1000)
    if sm.updated['carParams']:  # sent once in a while, keep the last one
      car = sm['carParams'].carFingerprint
    ds = sm['deviceState']
    s = {
      'started': bool(ds.started),
      'temp': round(max(list(ds.cpuTempC) + [0.0])),
      'battery': int(ds.batteryPercent),
      'charging': ds.batteryCurrent < 0,
      'free': round(ds.freeSpacePercent),
      'ip': ds.wifiIpAddress,
      'device_alive': sm.alive['deviceState'],
    }
    try:
      ps = sm['pandaStates']
      s['panda'] = len(ps) > 0 and str(ps[0].pandaType) != 'unknown'
    except Exception:
      s['panda'] = False
    s['car'] = car
    s['car_alive'] = sm.alive['carState']
    s['gear'] = str(sm['carState'].gearShifter) if s['car_alive'] else ''
    s['speed'] = round(sm['carState'].vEgo * 3.6) if s['car_alive'] else 0
    s['engaged'] = bool(sm['controlsState'].enabled) if sm.alive['controlsState'] else False
    with state_lock:
      state.update(s)


def snapshot():
  with state_lock:
    return dict(state)


def can_change(s=None):
  """the same rule as the 소프트웨어 menu: car off, or gear P with openpilot off"""
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
  local, remote = pget('GitCommit')[:7], pget('GitCommitRemote')[:7]
  s.update({
    'branch': pget('GitBranch'),
    'commit': local,
    'commit_date': pget('GitCommitDate'),
    'remote': remote,
    'update': bool(remote) and remote != local,
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
      # a zip can't hold a time before 1980: z.write() of a file last written while the clock was at 1970 raised
      # ValueError -> 'Internal Server Error' for the whole download (2026-11-28, Soul EV tester; logserver.py had
      # this fix since 11-24). Such a file goes in dated 1980-01-01; one file that can't be read is skipped.
      p = os.path.join(DRIVELOG_DIR, f['name'])
      try:
        t = time.localtime(os.path.getmtime(p))
        info = zipfile.ZipInfo(f['name'], date_time=tuple(t[:6]) if t.tm_year >= 1980 else (1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        with open(p, 'rb') as fh:
          z.writestr(info, fh.read())
      except (OSError, ValueError):
        pass
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


def navi_ctrl(mode):
  """settings.cc navi_ctrl: 내비 연동 방식 -> the AutoNaviSpeedCtrl value '카메라 감속' stores while on"""
  return {1: 3, 2: 2}.get(mode, 1)


def pint(key, default=0):
  try:
    return int(pget(key))
  except ValueError:
    return default


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
    if m and m.group(1) not in vals:  # a condition on a param that is not an item itself (e.g. SelectedCar)
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
    if item.get('special') == 'camDecel':  # '카메라 감속': on stores the value of the chosen 내비 연동 방식
      value = str(navi_ctrl(pint('OptechNaviLinkMode', 1))) if value == '1' else '0'
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
    # like the menu's choice callback: a new 내비 연동 방식 also changes what '카메라 감속' (when on) stores
    if key == 'OptechNaviLinkMode' and pint('AutoNaviSpeedCtrl') > 0:
      params.put('AutoNaviSpeedCtrl', str(navi_ctrl(int(value))))
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
    local, remote = pget('GitCommit')[:7], pget('GitCommitRemote')[:7]
    try:
      changes = open('/tmp/update_changelog.txt', encoding='utf-8').read().strip()
    except Exception:
      changes = ''
    if not remote:
      return jsonify(ok=False, msg="업데이트 서버에 연결하지 못했어요. 와이파이 연결을 확인해 주세요.")
    return jsonify(ok=True, local=local, remote=remote, update=remote != local, changes=changes)

  if not can_change():
    return change_refused()
  if name == 'update':
    background(['/usr/bin/bash', SH + '/gitpull.sh'])
    return jsonify(ok=True, msg="업데이트를 받는 중이에요. 새 버전이 있으면 받은 뒤 자동으로 다시 켜져요 (켤 때 몇 분 빌드).")
  if name == 'reboot':
    background(['/usr/bin/bash', '-c', 'sync; sleep 1; /system/bin/reboot || reboot'])
    return jsonify(ok=True, msg="기기를 다시 켜요. 1~2분 뒤 이 페이지를 새로 고쳐 주세요.")
  if name == 'soft_restart':
    params.put_bool('SoftRestartTriggered', True)
    return jsonify(ok=True, msg="오픈파일럿을 다시 시작해요 (기기는 꺼지지 않아요).")
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
