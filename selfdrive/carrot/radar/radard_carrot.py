"""carrot dPath RadarD adapted to the C2 radard loop.

Selected in selfdrive/controls/radard.py with the CarrotRadar param. C2 keeps its own
RadarInterface (Mando front radar tracks or the SCC11 object) and its radar-timed loop;
this class only replaces the lead selection:

- enrich each C2 radar point with what carrot's RadarInterface adds (radarSource, vLead,
  filtered yRel/yvRel and aLead/jLead from carrot's per-track MyTrack observer),
- run carrot's DPathRadarController against the latest modelV2,
- fill radarState with carrot's leads, including leadsCutIn / leadCutInRisk.

Differences from carrot-wip's radard_dpath: yaw rate comes from C2's liveLocationKalman
(device frame, same sign convention as carrot's livePose), there are no corner radars,
and the radar-to-model time offset uses the radar frame's arrival time.
"""
from __future__ import annotations

import math
from typing import Any, Dict

from cereal import car
from selfdrive.carrot.radar.radar_tracks import MyTrack
from selfdrive.carrot.radar_motion import DPathRadarController
from selfdrive.carrot.radar_motion.coordinates import device_yaw_to_radar

PRODUCTION_CUT_IN_SENSITIVITY = 3  # carrot-wip radard_dpath value
EMPTY_LEAD = {
  "dRel": 0.0, "yRel": 0.0, "vRel": 0.0, "aRel": 0.0, "vLead": 0.0, "aLead": 0.0, "dPath": 0.0, "vLat": 0.0,
  "vLeadK": 0.0, "aLeadK": 0.0, "fcw": False, "status": False, "aLeadTau": 0.0, "modelProb": 0.0, "radar": False,
  "radarTrackId": -1, "jLead": 0.0, "score": 0.0, "cutOutTime": 0.0, "cutOutConfidence": 0.0,
}


def empty_lead() -> Dict[str, Any]:
  return EMPTY_LEAD.copy()


def c2_radar_track_mode(new_radar: bool) -> int:
  """carrot EnableRadarTracks semantics for the two C2 Hyundai radar sources.

  1 = front radar tracks only (C2 reads RADAR_TRACK_5xx), 0 = SCC object only (SCC11).
  """
  return 1 if new_radar else 0


def yaw_rate_from_llk(llk: Any) -> float:
  """Yaw rate for carrot's radar frame from C2 liveLocationKalman (0 when not trustworthy)."""
  try:
    av = llk.angularVelocityDevice
    if av.valid and llk.inputsOK and llk.sensorsOK and len(av.value) == 3:
      return device_yaw_to_radar(float(av.value[2]))
  except (AttributeError, IndexError, TypeError, ValueError):
    pass
  return 0.0


def model_measurement_time_s(model: Any, model_log_mono_time: int) -> float:
  """Camera exposure time (timestampEof), not model publication time, as carrot does."""
  eof = int(getattr(model, "timestampEof", 0) or 0)
  return float(eof if eof > 0 else model_log_mono_time) * 1e-9


class CarrotRadarD:
  def __init__(self, CP: Any, new_radar: bool) -> None:
    self.source = "frontRadar" if new_radar else "scc"
    self.dt = float(CP.radarTimeStep) if CP.radarTimeStep > 0 else 0.05
    self.tracks: Dict[int, MyTrack] = {}
    self.controller = DPathRadarController(
      prefer_corner_radar=False,
      enable_radar_tracks=c2_radar_track_mode(new_radar),
      cut_in_sensitivity=PRODUCTION_CUT_IN_SENSITIVITY,
      front_radar_measurement_delay_s=0.0,  # carrot's Hyundai radarDelay is 0 as well
      production_live_tracks=True,
    )

  def enrich(self, rr: Any, v_ego: float, a_ego: float) -> Any:
    """Copy C2 radar points into carrot's richer RadarPoint and run the per-track observer."""
    out = car.RadarData.new_message()
    points = out.init("points", len(rr.points))
    tracks: Dict[int, MyTrack] = {}
    for dst, src in zip(points, rr.points):
      track_id = int(src.trackId)
      dst.trackId = track_id
      dst.measured = bool(src.measured)
      dst.dRel, dst.yRel, dst.vRel = float(src.dRel), float(src.yRel), float(src.vRel)
      dst.aRel = float(src.aRel)
      dst.yvRel = float(src.yvRel) if math.isfinite(src.yvRel) else 0.0  # carrot uses 0.0, C2 RI sends NaN
      dst.radarSource = self.source
      dst.vLead = dst.vRel + v_ego
      track = self.tracks.get(track_id)
      if track is None:
        track = MyTrack(track_id, dst, self.dt)
      track.update(dst, a_ego)
      track.write_acceleration(dst)
      dst.yRel, dst.yvRel = float(track.yRel), float(track.yvRel)
      tracks[track_id] = track
    self.tracks = tracks
    return out.as_reader() if hasattr(out, "as_reader") else out

  @staticmethod
  def _yaw_rate(sm: Any) -> float:
    try:
      return yaw_rate_from_llk(sm["liveLocationKalman"])
    except KeyError:  # a caller-provided SubMaster without locationd
      return 0.0

  def update(self, sm: Any, rr: Any, radar_time_s: float, radar_state: Any) -> None:
    car_state = sm["carState"]
    rich = self.enrich(rr, float(car_state.vEgo), float(car_state.aEgo))
    model_time_s = model_measurement_time_s(sm["modelV2"], sm.logMonoTime["modelV2"])
    output = self.controller.update(
      time_s=model_time_s if model_time_s > 0.0 else radar_time_s,
      v_ego=float(car_state.vEgo),
      radar_points=rich.points,
      model=sm["modelV2"],
      yaw_rate_rad_s=self._yaw_rate(sm),
      radar_to_model_time_s=(model_time_s - radar_time_s) if model_time_s > 0.0 else 0.0,
    )
    radar_state.leadOne = output.lead_one or empty_lead()
    radar_state.leadTwo = output.lead_two or empty_lead()
    radar_state.leadLeft = output.lead_left or empty_lead()
    radar_state.leadRight = output.lead_right or empty_lead()
    radar_state.leadsLeft = output.leads_left
    radar_state.leadsCenter = output.leads_center
    radar_state.leadsRight = output.leads_right
    radar_state.leadsCutIn = output.leads_cutin
    radar_state.leadCutInRisk = output.lead_cutin_risk or empty_lead()
    radar_state.leadsLeft2 = output.leads_left2
    radar_state.leadsRight2 = output.leads_right2
