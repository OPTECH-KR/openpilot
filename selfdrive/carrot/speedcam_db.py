"""Built-in Korean speed camera DB lookup (no navigation app needed).

Cameras come from the national standard data (data.go.kr 15028200, see
selfdrive/assets/speedcam/kr_speedcam.csv). Given the GPS position, travel bearing and speed,
SpeedCamFinder returns the camera ahead (limit and distance) or, after passing a section start
camera, the remaining length of the average-speed section.

The data has no usable travel direction per camera, so a camera is matched geometrically:
it must lie ahead within a narrow corridor around the travel direction. A camera for the opposite
direction on the same road can therefore still match; the result is only a slowdown to the
posted limit near that spot.
"""
import math
import os
from collections import defaultdict

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "speedcam", "kr_speedcam.csv")

KIND_POINT, KIND_SECTION_START, KIND_SECTION_END = 0, 1, 2
CELL_DEG = 0.02                 # grid cell, ~2.2 km north-south, ~1.8 km east-west in Korea
M_PER_DEG_LAT = 110540.0
M_PER_DEG_LON_EQ = 111320.0
MIN_SPEED = 2.0                 # m/s, below this the GPS bearing is not trusted
LOOKAHEAD_S = 30.0              # look this many seconds ahead
LOOKAHEAD_MIN, LOOKAHEAD_MAX = 300.0, 1200.0
LATERAL_BASE, LATERAL_GROWTH = 25.0, 0.08    # corridor half width: 25 m + 8 % of the distance ahead
LATERAL_KEEP = 60.0             # a locked camera may drift this far sideways (curves) before it is dropped
PASSED_MARGIN = -15.0           # camera counts as passed once it is this far behind
SECTION_MAX_M = 30000.0


class SpeedCam:
  __slots__ = ("lat", "lon", "limit", "kind", "section_m")

  def __init__(self, lat, lon, limit, kind, section_m):
    self.lat, self.lon, self.limit, self.kind, self.section_m = lat, lon, limit, kind, section_m


class SpeedCamResult:
  __slots__ = ("limit", "dist", "section")

  def __init__(self, limit, dist, section):
    self.limit, self.dist, self.section = limit, dist, section

  def __repr__(self):
    return f"SpeedCamResult(limit={self.limit}, dist={self.dist:.0f}, section={self.section})"


def _cell(lat, lon):
  return int(math.floor(lat / CELL_DEG)), int(math.floor(lon / CELL_DEG))


def load_db(path=DB_PATH):
  cams = []
  with open(path, encoding="utf-8") as f:
    for line in f:
      if not line.strip() or line.startswith("#") or line.startswith("lat,"):
        continue
      lat, lon, limit, kind, section_m = line.strip().split(",")[:5]
      cams.append(SpeedCam(float(lat), float(lon), int(limit), int(kind), float(section_m)))
  return cams


class SpeedCamFinder:
  def __init__(self, cams=None, path=DB_PATH):
    self.cams = cams if cams is not None else load_db(path)
    self.grid = defaultdict(list)
    for c in self.cams:
      self.grid[_cell(c.lat, c.lon)].append(c)
    self.target = None            # camera currently being approached
    self.section_left = 0.0       # remaining section length after passing a section start
    self.section_limit = 0
    self.last_t = None

  def _local(self, cam, lat, lon, bearing_rad):
    """(along, lateral) of the camera in meters, relative to the car and its travel direction."""
    dx = (cam.lon - lon) * M_PER_DEG_LON_EQ * math.cos(math.radians(lat))   # east
    dy = (cam.lat - lat) * M_PER_DEG_LAT                                    # north
    hx, hy = math.sin(bearing_rad), math.cos(bearing_rad)
    return dx * hx + dy * hy, dx * hy - dy * hx

  def _nearby(self, lat, lon):
    ci, cj = _cell(lat, lon)
    for di in (-1, 0, 1):
      for dj in (-1, 0, 1):
        yield from self.grid.get((ci + di, cj + dj), ())

  def reset(self):
    self.target = None
    self.section_left = 0.0
    self.section_limit = 0
    self.last_t = None

  def update(self, lat, lon, bearing_deg, speed, t):
    """Return SpeedCamResult for the camera / section ahead, or None. speed in m/s, t in seconds."""
    dt = 0.0 if self.last_t is None else max(0.0, min(t - self.last_t, 2.0))
    self.last_t = t
    if self.section_left > 0.0:
      self.section_left -= speed * dt

    if speed < MIN_SPEED:
      # bearing unreliable: keep a running section, forget point targets until moving again
      self.target = None
      if self.section_left > 0.0:
        return SpeedCamResult(self.section_limit, self.section_left, True)
      return None

    b = math.radians(bearing_deg)
    lookahead = min(max(speed * LOOKAHEAD_S, LOOKAHEAD_MIN), LOOKAHEAD_MAX)

    # keep the locked camera until it is passed or drifts out of the corridor
    if self.target is not None:
      along, lateral = self._local(self.target, lat, lon, b)
      if along < PASSED_MARGIN:
        if self.target.kind == KIND_SECTION_START:
          self.section_left = min(self.target.section_m, SECTION_MAX_M) + along   # along < 0: already driven
          self.section_limit = self.target.limit
        elif self.target.kind == KIND_SECTION_END:
          self.section_left = 0.0
        self.target = None
      elif abs(lateral) > LATERAL_KEEP or along > lookahead * 1.5:
        self.target = None

    if self.target is None:
      best, best_along = None, None
      for cam in self._nearby(lat, lon):
        along, lateral = self._local(cam, lat, lon, b)
        if not (0.0 < along <= lookahead):
          continue
        if abs(lateral) > LATERAL_BASE + LATERAL_GROWTH * along:
          continue
        if best is None or along < best_along:
          best, best_along = cam, along
      self.target = best

    if self.section_left > 0.0:
      # inside an average-speed section: hold its limit; an end camera ahead just confirms it
      return SpeedCamResult(self.section_limit, self.section_left, True)
    if self.target is not None:
      along, _ = self._local(self.target, lat, lon, b)
      return SpeedCamResult(self.target.limit, max(along, 1.0), False)
    return None
