#!/usr/bin/env python3
import importlib
import math
from collections import defaultdict, deque

import cereal.messaging as messaging
from cereal import car
from common.numpy_fast import interp
from common.params import Params
from common.realtime import Ratekeeper, Priority, config_realtime_process, sec_since_boot
from selfdrive.controls.lib.radar_helpers import Cluster, Track, RADAR_TO_CAMERA
from selfdrive.swaglog import cloudlog
from selfdrive.carrot.tools.drivelog import diag_write
from third_party.cluster.fastcluster_py import cluster_points_centroid
from selfdrive.hardware import TICI
from common.params import Params

from selfdrive.controls.lib.lane_planner import TRAJECTORY_SIZE
import numpy as np

LEAD_PATH_DREL_MIN = 60 # [m] only care about far away leads
MIN_LANE_PROB = 0.6  # Minimum lanes probability to allow use.

# optech, raw radar tracks only (RadarInterface.new_radar = Mando front radar tracks; the SCC object is already filtered
# by the car's radar). Kia Soul EV SK3 drive 2026-11-24 (dashcam + drive record): in 3-10 km/h traffic on a bridge every
# steel expansion joint came back as a STATIONARY radar point ~5 m ahead while the camera's lead (a car moving ~2 m/s)
# was at 7-9 m. The comma low-speed override took the closer point after one radar frame without any camera check and
# braked at -1.0..-1.2 m/s^2. Two rules from other forks:
# - StarPilot (Honda Bosch raw radar, honda_bosch_a_low_speed_radar_lead_sane): a radar point is a low-speed lead
#   candidate only after RAW_MIN_SEEN_FRAMES frames in a row.
# - carrot-wip moving-lead shield (radar_motion/primary.py _fresh_stationary_blocked, added after a tunnel-reflector
#   FCW; carrot also lists bridge / tunnel / signal-gantry reflections as phantom cases): a stationary point clearly
#   closer than a moving lead in our lane is not taken - neither by the low-speed override nor as the camera lead's
#   radar match - until the camera has put its lead on that point SHIELD_VISION_FRAMES frames in a row. carrot's shield
#   lead must move > 4 m/s; jam leads move 1.5-2.5 m/s, so here it only has to be clearly moving.
# With no lead at all the low-speed override still takes a stationary point (after RAW_MIN_SEEN_FRAMES): carrot-wip
# drops that too, but with openpilot long on raw tracks the car's own FCA is not active, so the safety net stays.
RAW_MIN_SEEN_FRAMES = 3             # StarPilot HONDA_BOSCH_A_LOW_SPEED_MIN_COUNT (20 Hz radar: 0.15 s)
SHIELD_VISION_FRAMES = 3            # carrot FRESH_STATIONARY_VISION_CONTINUITY_FRAMES
SHIELD_STATIONARY_MAX_VLEAD = 1.5   # carrot FRESH_STATIONARY_GATE_MAX_ABS_VLEAD_MPS (reflectors read 0-0.2 m/s)
SHIELD_LEAD_MIN_VLEAD = 1.5         # the shielding lead is moving [m/s] ...
SHIELD_LEAD_MIN_SPEED_GAP = 1.0     # ... and clearly faster than the point [m/s]
SHIELD_MIN_GAP_M = 1.0              # the point is at least this much closer than the lead (carrot handoff margin)
SHIELD_MAX_GAP_M = 40.0             # carrot MOVING_LEAD_SHIELD_MAX_GAP_M: a car far ahead is no shield
SHIELD_LEAD_MAX_Y = 1.0             # carrot MOVING_LEAD_SHIELD_MAX_DPATH_M: the lead is in our lane
VISION_SUPPORT_MAX_Y = 1.25         # carrot: camera lead on the point within 1.25 m sideways ...
VISION_SUPPORT_MIN_DIST_M = 2.0     # ... and max(2 m, 20 %) in distance


def vision_on_track(t, lead_msg):
  """The camera's lead sits on this radar track (distance and side)."""
  cam_d = lead_msg.x[0] - RADAR_TO_CAMERA
  return abs(t.dRel - cam_d) <= max(VISION_SUPPORT_MIN_DIST_M, 0.2 * cam_d) and abs(t.yRel + lead_msg.y[0]) <= VISION_SUPPORT_MAX_Y


# optech ghost guard, Kia Soul EV SK3 only (2026-11-26 18:42, tester dashcam): crawling at 7 km/h on a bridge 8 m behind
# a van, the Mando radar reported a stationary point 1.7 m ahead for under a second - the steel expansion joint across
# the road right in front of the bumper. The low-speed override took it: FCW '브레이크! 충돌 위험' and 7 -> 2 km/h in a
# second. carrot c3-wip runs leadOne with low_speed_override=False altogether; here the safety net stays, but on the Soul
#  1) a stationary point first measured already this close (never seen coming from farther away), while we move, is not
#     taken by the low-speed override until the camera's lead has sat on it SHIELD_VISION_FRAMES frames in a row
#  2) the moving-lead shield also works behind a crawling lead (jam: the van moved 1.6-1.9 m/s, close to 1.5)
GHOST_GUARD_CAR = "KIA SOUL EV (SK3)"  # selfdrive/car/hyundai/values.py CAR.KIA_SOUL_EV_SK3
GHOST_BORN_MAX_D = 5.0                # [m] first measured closer than this: a road-level reflection, not a car we reach
GHOST_MIN_EGO = 0.5                   # [m/s] only while we move (stopped, a point in front keeps us stopped)
CRAWL_LEAD_MIN_VLEAD = 0.5            # [m/s] shielding lead speed on the Soul (default SHIELD_LEAD_MIN_VLEAD 1.5)
CRAWL_LEAD_MIN_SPEED_GAP = 0.5        # [m/s] ... and that much faster than the point (default 1.0)


def near_born_stationary(c, v_ego):
  """Ghost guard 1): c is stationary, all its tracks were first measured within GHOST_BORN_MAX_D, we move, and the
  camera has not confirmed it."""
  return (v_ego > GHOST_MIN_EGO
          and abs(c.vLead) <= SHIELD_STATIONARY_MAX_VLEAD
          and max(t.first_d if t.first_d is not None else t.dRel for t in c.tracks) < GHOST_BORN_MAX_D
          and max(t.vision_frames for t in c.tracks) < SHIELD_VISION_FRAMES)


def shielded_stationary(c, lead, crawl=False):
  """carrot-wip moving-lead shield: c is a stationary radar point clearly closer than lead = (dRel, vLead, yRel) of a
  moving lead in our lane, and the camera has not confirmed c for SHIELD_VISION_FRAMES frames. lead None: no shield.
  crawl (ghost guard 2, Soul only): the lead only has to be crawling."""
  if lead is None:
    return False
  d, v, y = lead
  min_v = CRAWL_LEAD_MIN_VLEAD if crawl else SHIELD_LEAD_MIN_VLEAD
  min_gap = CRAWL_LEAD_MIN_SPEED_GAP if crawl else SHIELD_LEAD_MIN_SPEED_GAP
  return (abs(c.vLead) <= SHIELD_STATIONARY_MAX_VLEAD
          and v >= min_v and v - c.vLead >= min_gap
          and abs(y) <= SHIELD_LEAD_MAX_Y
          and c.dRel + SHIELD_MIN_GAP_M < d <= c.dRel + SHIELD_MAX_GAP_M
          and max(t.vision_frames for t in c.tracks) < SHIELD_VISION_FRAMES)


def raw_seen_enough(c):
  return max(t.seen for t in c.tracks) >= RAW_MIN_SEEN_FRAMES


# optech sticky lead, raw radar tracks only (Soul EV SK3 commute 2026-11-25, dashcam): driving into the low sun / a bright
# tunnel exit the camera lost the car ahead; leadOne jumped to 66-70 m and then was empty for 4-6 s while the radar still
# had the car, openpilot long accelerated to 52 / 84 km/h and the driver had to brake. Above 14.4 km/h radard only uses
# radar points the camera matches. carrot c3-wip get_sticky_track: keep following the radar track that was the
# camera-confirmed lead while it stays measured, physically continuous (Track.update: d 5 m / y 2 m / v 7 m/s jumps end
# it) and inside the model path (0.8 m, beyond 60 m 1.2 m). Here it also wins over a camera lead that jumped far behind
# it or a camera-only lead that is not closer.
STICKY_MIN_SELECTED = 3       # camera-confirmed this many frames first
STICKY_SELECTED_MAX = 40      # carrot STICKY_SELECTED_COUNT_MAX (2 s): only for choosing between candidates
STICKY_MAX_DPATH = 0.8        # carrot STICKY_MAX_DPATH
STICKY_FAR_DREL = 60.0        # carrot STICKY_FAR_DREL
STICKY_MAX_DPATH_FAR = 1.2    # carrot STICKY_MAX_DPATH_FAR
STICKY_KEEP_JUMP_M = 5.0      # a camera match this much farther than the followed car is a jump, not the car
STICKY_VISION_CLOSER_M = 2.0  # a camera-only lead this much closer than the followed car wins (cut-in not on radar)


def get_sticky(clusters, path):
  """The radar point we follow (camera-confirmed lead before), or None. path: model (x, y) lists or None."""
  if path is None:
    return None
  best, best_sel = None, 0
  for c in clusters:
    sel = max(t.selected for t in c.tracks)
    if sel < STICKY_MIN_SELECTED:
      continue
    d_path = c.yRel + interp(c.dRel, path[0], path[1])
    if not (c.measured and 1.0 < c.dRel < 150.0 and
            abs(d_path) <= (STICKY_MAX_DPATH if c.dRel < STICKY_FAR_DREL else STICKY_MAX_DPATH_FAR)):
      for t in c.tracks:
        t.selected = 0  # left our path or lost: not followed any more
      continue
    if best is None or (sel, -c.dRel) > (best_sel, -best.dRel):
      best, best_sel = c, sel
  return best

#LEAD_PLUS_ONE_MIN_REL_DIST_V = [3.0, 6.0] # [m] min distance between lead+1 and lead at low and high distance
#LEAD_PLUS_ONE_MIN_REL_DIST_BP = [0., 100.] # [m] min distance between lead+1 and lead at low and high distance
#LEAD_PLUS_ONE_MAX_YREL_TO_LEAD = 3.0 # [m]

class KalmanParams():
  def __init__(self, dt):
    # Lead Kalman Filter params, calculating K from A, C, Q, R requires the control library.
    # hardcoding a lookup table to compute K for values of radar_ts between 0.01s and 0.2s
    assert dt > .01 and dt < .2, "Radar time step must be between .01s and 0.2s"
    self.A = [[1.0, dt], [0.0, 1.0]]
    self.C = [1.0, 0.0]
    #Q = np.matrix([[10., 0.0], [0.0, 100.]])
    #R = 1e3
    #K = np.matrix([[ 0.05705578], [ 0.03073241]])
    dts = [dt * 0.01 for dt in range(1, 21)]
    K0 = [0.12287673, 0.14556536, 0.16522756, 0.18281627, 0.1988689,  0.21372394,
          0.22761098, 0.24069424, 0.253096,   0.26491023, 0.27621103, 0.28705801,
          0.29750003, 0.30757767, 0.31732515, 0.32677158, 0.33594201, 0.34485814,
          0.35353899, 0.36200124]
    K1 = [0.29666309, 0.29330885, 0.29042818, 0.28787125, 0.28555364, 0.28342219,
          0.28144091, 0.27958406, 0.27783249, 0.27617149, 0.27458948, 0.27307714,
          0.27162685, 0.27023228, 0.26888809, 0.26758976, 0.26633338, 0.26511557,
          0.26393339, 0.26278425]
    self.K = [[interp(dt, dts, K0)], [interp(dt, dts, K1)]]


def laplacian_pdf(x, mu, b):
  b = max(b, 1e-4)
  return math.exp(-abs(x-mu)/b)


def match_vision_to_cluster(v_ego, lead, clusters):
  # match vision point to best statistical cluster match
  offset_vision_dist = lead.x[0] - RADAR_TO_CAMERA

  def prob(c):
    prob_d = laplacian_pdf(c.dRel, offset_vision_dist, lead.xStd[0])
    prob_y = laplacian_pdf(c.yRel, -lead.y[0], lead.yStd[0])
    prob_v = laplacian_pdf(c.vRel + v_ego, lead.v[0], lead.vStd[0])

    # This is isn't exactly right, but good heuristic
    return prob_d * prob_y * prob_v

  cluster = max(clusters, key=prob)

  # if no 'sane' match is found return -1
  # stationary radar points can be false positives
  #dist_sane = abs(cluster.dRel - offset_vision_dist) < max([(offset_vision_dist)*.25, 5.0])
  dist_sane = abs(cluster.dRel - offset_vision_dist) < max([(offset_vision_dist)*.35, 5.0])
  vel_sane = (abs(cluster.vRel + v_ego - lead.v[0]) < 10) or (v_ego + cluster.vRel > 3)
  if dist_sane and vel_sane:
    return cluster
  else:
    return None

def get_path_adjacent_leads(v_ego, md, lane_width, clusters):
  if len(clusters) == 0:
    return [[],[],[]]
  
  if md is not None and lane_width > 0. and len(md.laneLines) == 4 and len(md.laneLines[1].x) == TRAJECTORY_SIZE:
    # get centerline approximation using one or both lanelines
    ll_x = md.laneLines[1].x  # left and right ll x is the same
    lll_y = np.array(md.laneLines[1].y)
    rll_y = np.array(md.laneLines[2].y)
    l_prob = md.laneLineProbs[1]
    r_prob = md.laneLineProbs[2]

    # Find path from lanes as the average center lane only if min probability on both lanes is above threshold.
    if l_prob > MIN_LANE_PROB and r_prob > MIN_LANE_PROB:
      c_y = (lll_y + rll_y) / 2.
    elif l_prob > MIN_LANE_PROB:
      c_y = lll_y + (lane_width / 2)
    elif r_prob > MIN_LANE_PROB:
      c_y = rll_y - (lane_width / 2)
    else:
      c_y = None
  else:
    c_y = None
  
  if md is not None or len(md.position.x) == TRAJECTORY_SIZE or md.position.x[-1] > LEAD_PATH_DREL_MIN:
    md_y = md.position.y
    md_x = md.position.x
  else:
    md_y = None
  
  leads_left = {}
  leads_center = {}
  leads_right = {}
  half_lane_width = lane_width / 2
  for c in clusters:
    if md_y is not None and c.dRel <= md_x[-1] or (c_y is not None and md_x[-1] - c.dRel < ll_x[-1] - c.dRel):
      dPath = -c.yRel - interp(c.dRel, md_x, md_y)
      checkSource = 'modelPath'
    elif c_y is not None:
      dPath = -c.yRel - interp(c.dRel, ll_x, c_y.tolist())
      checkSource = 'modelLaneLines'
    else:
      dPath = -c.yRel
      checkSource = 'lowSpeedOverride'
      
    source = 'vision' if c.dRel > 145. else 'radar'
    
    #ld = c.get_RadarState(source=source, checkSource=checkSource)
    ld = c.get_RadarState()
    ld["dPath"] = dPath
    ld["vLat"] = math.sqrt((10*dPath)**2 + c.dRel**2)
    if abs(dPath) < half_lane_width and ld["vLeadK"] > -1.: # want to still get stopped leads, so put in wiggle-room for radar noise
      leads_center[abs(dPath)] = ld
    elif dPath < 0.:
      leads_left[abs(dPath)] = ld
    else:
      leads_right[abs(dPath)] = ld
  
  ll,lr = [[l[k] for k in sorted(list(l.keys()))] for l in [leads_left,leads_right]]
  lc = sorted(leads_center.values(), key=lambda c:c["dRel"])
  return [ll,lc,lr]

def get_lead(v_ego, ready, clusters, lead_msg, model_v_ego, low_speed_override=True, mixRadarInfo=0, raw_tracks=False,
             blocked=None, sticky_path=None, sticky_used=None, ghost_guard=False, low_log=None):
  # optech raw radar tracks: stationary points shielded by the camera's moving lead may not be its radar match
  # (blocked collects them for the diag log). ghost_guard: Soul EV SK3 rules above (raw tracks only), low_log collects
  # what the low-speed override did for the diag log
  ghost_guard = ghost_guard and raw_tracks
  match_clusters = clusters
  if raw_tracks and ready and lead_msg.prob > .5:
    cam = (lead_msg.x[0] - RADAR_TO_CAMERA, lead_msg.v[0], -lead_msg.y[0])
    match_clusters = [c for c in clusters if not shielded_stationary(c, cam, crawl=ghost_guard)]
    if blocked is not None:
      blocked += [(c, cam) for c in clusters if c not in match_clusters]

  # Determine leads, this is where the essential logic happens
  if len(match_clusters) > 0 and ready and lead_msg.prob > .5:
    cluster = match_vision_to_cluster(v_ego, lead_msg, match_clusters)
  else:
    cluster = None

  # optech sticky lead (raw tracks, leadOne only: sticky_path given)
  if raw_tracks and sticky_path is not None:
    sticky = get_sticky(clusters, sticky_path)
    use_sticky = False
    if sticky is not None and sticky is not cluster:
      if cluster is not None:
        use_sticky = cluster.dRel > sticky.dRel + STICKY_KEEP_JUMP_M  # the camera's lead jumped far behind it
      else:
        vision_d = lead_msg.x[0] - RADAR_TO_CAMERA if (ready and lead_msg.prob > .5) else None
        use_sticky = vision_d is None or vision_d >= sticky.dRel - STICKY_VISION_CLOSER_M
    if use_sticky:
      if sticky_used is not None:
        sticky_used.append((sticky, None if cluster is None else cluster.dRel,
                            lead_msg.x[0] - RADAR_TO_CAMERA if lead_msg.prob > .5 else None))
      cluster = sticky
    elif cluster is not None:
      # the camera confirmed this radar point as the lead: it becomes the one to follow
      for c in clusters:
        for t in c.tracks:
          t.selected = min(t.selected + 1, STICKY_SELECTED_MAX) if c is cluster else 0

  lead_dict = {'status': False}
  if cluster is not None:
    lead_dict = cluster.get_RadarState2(lead_msg.prob, lead_msg, mixRadarInfo)
  elif (cluster is None) and ready and (lead_msg.prob > .5):
    lead_dict = Cluster().get_RadarState_from_vision(lead_msg, v_ego, model_v_ego)

  if low_speed_override:
    low_speed_clusters = [c for c in clusters if c.potential_low_speed_lead(v_ego)]
    if raw_tracks:
      # StarPilot: seen RAW_MIN_SEEN_FRAMES in a row; carrot-wip: not a stationary point short of a moving lead
      shield = (lead_dict['dRel'], lead_dict['vLead'], lead_dict['yRel']) if lead_dict['status'] else None
      candidates = [c for c in low_speed_clusters if raw_seen_enough(c)]
      if blocked is not None and shield is not None:
        blocked += [(c, shield) for c in candidates if shielded_stationary(c, shield, crawl=ghost_guard)]
      low_speed_clusters = [c for c in candidates if not shielded_stationary(c, shield, crawl=ghost_guard)]
      if ghost_guard:
        ghosts = [c for c in low_speed_clusters if near_born_stationary(c, v_ego)]
        if low_log is not None:
          low_log += [("ghost", c, shield) for c in ghosts if not lead_dict['status'] or c.dRel < lead_dict['dRel']]
        low_speed_clusters = [c for c in low_speed_clusters if c not in ghosts]
    if len(low_speed_clusters) > 0:
      closest_cluster = min(low_speed_clusters, key=lambda c: c.dRel)

      # Only choose new cluster if it is actually closer than the previous one
      if (not lead_dict['status']) or (closest_cluster.dRel < lead_dict['dRel']):
        if low_log is not None and ghost_guard:
          low_log.append(("took", closest_cluster, (lead_dict['dRel'], lead_dict['vLead'], lead_dict['yRel'])
                          if lead_dict['status'] else None))
        lead_dict = closest_cluster.get_RadarState2(lead_msg.prob, lead_msg, mixRadarInfo)

  return lead_dict


class RadarD():
  def __init__(self, radar_ts, delay=0, raw_tracks=False, ghost_guard=False):
    self.current_time = 0
    self.raw_tracks = raw_tracks  # optech: Mando front radar tracks (lead shield + seen-3-frames rule)
    self.ghost_guard = ghost_guard and raw_tracks  # optech: Soul EV SK3 only (GHOST_GUARD_CAR)
    self.last_block_log = 0.
    self.last_sticky_log = 0.
    self.last_low_log = 0.

    self.tracks = defaultdict(dict)
    self.kalman_params = KalmanParams(radar_ts)

    # v_ego
    self.v_ego = 0.
    self.v_ego_hist = deque([0], maxlen=delay+1)

    self.ready = False
    self.showRadarInfo = False
    self.mixRadarInfo = 0

  def update(self, sm, rr):
    self.showRadarInfo = int(Params().get("ShowRadarInfo"))
    self.mixRadarInfo = int(Params().get("MixRadarInfo"))

    self.current_time = 1e-9*max(sm.logMonoTime.values())

    if sm.updated['carState']:
      self.v_ego = sm['carState'].vEgo
      self.v_ego_hist.append(self.v_ego)
    if sm.updated['modelV2']:
      self.ready = True

    ar_pts = {}
    for pt in rr.points:
      ar_pts[pt.trackId] = [pt.dRel, pt.yRel, pt.vRel, pt.measured]

    # *** remove missing points from meta data ***
    for ids in list(self.tracks.keys()):
      if ids not in ar_pts:
        self.tracks.pop(ids, None)

    # *** compute the tracks ***
    for ids in ar_pts:
      rpt = ar_pts[ids]

      # align v_ego by a fixed time to align it with the radar measurement
      v_lead = rpt[2] + self.v_ego_hist[0]

      # create the track if it doesn't exist or it's a new track
      if ids not in self.tracks:
        self.tracks[ids] = Track(v_lead, self.kalman_params)
      self.tracks[ids].update(rpt[0], rpt[1], rpt[2], v_lead, rpt[3])

    idens = list(sorted(self.tracks.keys()))
    track_pts = [self.tracks[iden].get_key_for_cluster() for iden in idens]

    # If we have multiple points, cluster them
    if len(track_pts) > 1:
      cluster_idxs = cluster_points_centroid(track_pts, 2.5)
      clusters = [None] * (max(cluster_idxs) + 1)

      for idx in range(len(track_pts)):
        cluster_i = cluster_idxs[idx]
        if clusters[cluster_i] is None:
          clusters[cluster_i] = Cluster()
        clusters[cluster_i].add(self.tracks[idens[idx]])
    elif len(track_pts) == 1:
      # FIXME: cluster_point_centroid hangs forever if len(track_pts) == 1
      cluster_idxs = [0]
      clusters = [Cluster()]
      clusters[0].add(self.tracks[idens[0]])
    else:
      clusters = []

    # if a new point, reset accel to the rest of the cluster
    for idx in range(len(track_pts)):
      if self.tracks[idens[idx]].cnt <= 1:
        aLeadK = clusters[cluster_idxs[idx]].aLeadK
        aLeadTau = clusters[cluster_idxs[idx]].aLeadTau
        self.tracks[idens[idx]].reset_a_lead(aLeadK, aLeadTau)

    # *** publish radarState ***
    dat = messaging.new_message('radarState')
    dat.valid = sm.all_checks() and len(rr.errors) == 0
    radarState = dat.radarState
    radarState.mdMonoTime = sm.logMonoTime['modelV2']
    radarState.radarErrors = list(rr.errors)
    radarState.carStateMonoTime = sm.logMonoTime['carState']

    if len(sm['modelV2'].temporalPose.trans):
      model_v_ego = sm['modelV2'].temporalPose.trans[0]
    else:
      model_v_ego = self.v_ego
    leads_v3 = sm['modelV2'].leadsV3
    if len(leads_v3) > 1:
      blocked = []
      if self.raw_tracks:
        # frames in a row the camera's lead sat on each radar track (the shield lets a point through after 3)
        cam_lead = self.ready and leads_v3[0].prob > .5
        for t in self.tracks.values():
          t.vision_frames = t.vision_frames + 1 if cam_lead and vision_on_track(t, leads_v3[0]) else 0
      # model path for the sticky lead (capnp lists: list() before use, they can't be sliced on the device)
      pos = sm['modelV2'].position
      path = (list(pos.x), list(pos.y)) if self.ready and len(pos.x) == TRAJECTORY_SIZE else None
      sticky_used = []
      low_log = []
      radarState.leadOne = get_lead(self.v_ego, self.ready, clusters, leads_v3[0], model_v_ego, low_speed_override=True, mixRadarInfo=self.mixRadarInfo,
                                    raw_tracks=self.raw_tracks, blocked=blocked, sticky_path=path, sticky_used=sticky_used,
                                    ghost_guard=self.ghost_guard, low_log=low_log)
      if low_log and self.current_time - self.last_low_log >= 1.0:
        # ghost guard 3): why the low-speed override took a radar point, or which one it ignored as a ghost
        self.last_low_log = self.current_time
        what, c, lead = low_log[0]
        t = max(c.tracks, key=lambda t: t.seen)
        first = max(tr.first_d if tr.first_d is not None else tr.dRel for tr in c.tracks)
        lead_txt = "none" if lead is None else "d=%.1f v=%.1f y=%.1f" % lead
        diag_write(f"radar low-speed {'ghost ignored' if what == 'ghost' else 'took point'}: d={c.dRel:.1f} y={c.yRel:.1f} "
                   f"v={c.vLead:.1f} first_d={first:.1f} seen={t.seen} cam={t.vision_frames} (lead {lead_txt}, "
                   f"ego {self.v_ego:.1f} m/s)")
      if sticky_used and self.current_time - self.last_sticky_log >= 1.0:
        self.last_sticky_log = self.current_time
        c, match_d, cam_d = sticky_used[0]
        cam = "none" if cam_d is None else "%.1f" % cam_d
        match = "none" if match_d is None else "%.1f" % match_d
        diag_write(f"radar sticky: kept the followed car d={c.dRel:.1f} v={c.vLead:.1f} (camera lead {cam}, "
                   f"its radar match {match}, ego {self.v_ego:.1f} m/s)")
      radarState.leadTwo = get_lead(self.v_ego, self.ready, clusters, leads_v3[1], model_v_ego, low_speed_override=False, mixRadarInfo=self.mixRadarInfo,
                                    raw_tracks=self.raw_tracks)
      blocked = [b for b in blocked if abs(b[0].yRel) < 1.5]  # log only points in our lane (not guard rails)
      if blocked and self.current_time - self.last_block_log >= 1.0:
        self.last_block_log = self.current_time
        c, (d, v, _) = blocked[0]
        diag_write(f"radar shield: stationary point ignored d={c.dRel:.1f} v={c.vLead:.1f} (lead d={d:.1f} v={v:.1f}, ego {self.v_ego:.1f} m/s)")

      if self.ready and self.showRadarInfo: #self.extended_radar_enabled and self.ready:
        ll,lc,lr = get_path_adjacent_leads(self.v_ego, sm['modelV2'], sm['lateralPlan'].laneWidth, clusters)
        #try:
        #  if abs(sm['carState'].steeringAngleDeg) < 15 and radarState.leadOne.status and radarState.leadOne.modelProb > 0.5:
        #    check_dist = interp(radarState.leadOne.dRel, LEAD_PLUS_ONE_MIN_REL_DIST_BP, LEAD_PLUS_ONE_MIN_REL_DIST_V)
        #    lc = [l for l in lc if l["dRel"] > radarState.leadOne.dRel + check_dist and abs(l["yRel"] - radarState.leadOne.yRel) <= LEAD_PLUS_ONE_MAX_YREL_TO_LEAD]
        #    if len(lc) > 0: # get the lead+1 car
        #      radarState.leadOnePlus = self.lead_one_plus_lr.update(lc[0], use_v_lat=self.extended_radar_enabled)
        #except AttributeError:
        #  lc = []
        #  self.lead_one_plus_lr.reset()
        radarState.leadsLeft = list(ll)
        radarState.leadsCenter = list(lc)
        radarState.leadsRight = list(lr)

    return dat


def make_carrot_radard(CP, RI):
  """carrot dPath lead selection when CarrotRadar=1 on a Hyundai/Kia; otherwise None (apilot RadarD)."""
  try:
    enabled = int(Params().get("CarrotRadar", encoding="utf8") or 0) == 1
  except Exception:
    enabled = False
  if not enabled:
    return None
  if CP.carName != "hyundai":
    cloudlog.warning("CarrotRadar needs the Hyundai radar interface; using apilot radard for %s", CP.carName)
    return None
  from selfdrive.carrot.radar.radard_carrot import CarrotRadarD
  new_radar = bool(getattr(RI, "new_radar", False))
  cloudlog.info("radard: carrot dPath lead selection (%s)", "front radar tracks" if new_radar else "SCC object")
  return CarrotRadarD(CP, new_radar)


# fuses camera and radar data for best lead detection
def radard_thread(sm=None, pm=None, can_sock=None):
  config_realtime_process(5 if TICI else 2, Priority.CTRL_LOW)

  # wait for stats about the car to come in from controls
  cloudlog.info("radard is waiting for CarParams")
  CP = car.CarParams.from_bytes(Params().get("CarParams", block=True))
  cloudlog.info("radard got CarParams")

  # import the radar from the fingerprint
  cloudlog.info("radard is importing %s", CP.carName)
  RadarInterface = importlib.import_module(f'selfdrive.car.{CP.carName}.radar_interface').RadarInterface

  # *** setup messaging
  if can_sock is None:
    can_sock = messaging.sub_sock('can')
  RI = RadarInterface(CP)
  CRD = make_carrot_radard(CP, RI)

  if sm is None:
    services = ['modelV2', 'carState', 'lateralPlan']
    # carrot lead selection also wants yaw rate; subscribe only then so apilot's all_checks() is unchanged
    extra = ['liveLocationKalman'] if CRD is not None else []
    sm = messaging.SubMaster(services + extra, ignore_alive=extra, ignore_avg_freq=services + extra)  # Can't check average frequency, since radar determines timing
  if pm is None:
    pm = messaging.PubMaster(['radarState', 'liveTracks'])

  rk = Ratekeeper(1.0 / CP.radarTimeStep, print_delay_threshold=None)
  raw_tracks = bool(getattr(RI, "new_radar", False))
  ghost_guard = raw_tracks and CP.carFingerprint == GHOST_GUARD_CAR
  RD = RadarD(CP.radarTimeStep, RI.delay, raw_tracks=raw_tracks, ghost_guard=ghost_guard)
  if ghost_guard:
    diag_write(f"radar ghost guard on ({CP.carFingerprint}): near-born stationary points and crawling-lead shield")
  last_diag = None

  while 1:
    can_strings = messaging.drain_sock_raw(can_sock, wait_for_one=True)
    radar_time_s = sec_since_boot()
    rr = RI.update(can_strings)

    if rr is None:
      continue

    sm.update(0)

    if CRD is not None:
      dat = messaging.new_message('radarState')
      dat.valid = sm.all_checks(['modelV2', 'carState']) and len(rr.errors) == 0
      radarState = dat.radarState
      radarState.mdMonoTime = sm.logMonoTime['modelV2']
      radarState.radarErrors = list(rr.errors)
      radarState.carStateMonoTime = sm.logMonoTime['carState']
      CRD.update(sm, rr, radar_time_s, radarState)
    else:
      dat = RD.update(sm, rr)
    dat.radarState.cumLagMs = -rk.remaining*1000.

    # diagnostics for radarFault / commIssue: which radard input made radarState invalid (only on a change)
    diag = None if dat.valid else (sorted(s for s, v in sm.valid.items() if not v),
                                   sorted(s for s, a in sm.alive.items() if not a), list(rr.errors))
    if diag != last_diag:
      if diag is not None:
        diag_write(f"radard invalid: inputs_invalid={diag[0]} not_alive={diag[1]} radar_errors={diag[2]}")
      last_diag = diag

    pm.send('radarState', dat)

    # *** publish tracks for UI debugging (keep last) ***
    tracks = CRD.tracks if CRD is not None else RD.tracks
    dat = messaging.new_message('liveTracks', len(tracks))

    for cnt, ids in enumerate(sorted(tracks.keys())):
      dat.liveTracks[cnt] = {
        "trackId": ids,
        "dRel": float(tracks[ids].dRel),
        "yRel": float(tracks[ids].yRel),
        "vRel": float(tracks[ids].vRel),
      }
    pm.send('liveTracks', dat)

    #rk.monitor_time()
    rk.keep_time()


def main(sm=None, pm=None, can_sock=None):
  radard_thread(sm, pm, can_sock)


if __name__ == "__main__":
  main()
