"""optech 신호등 판단 (2026-11-23): StarPilot's stop light detector (starpilot/controls/lib/
conditional_experimental_mode.py stop_sign_and_light, green light alert in starpilot_events.py) on the C2 model.

The driving model has no traffic light output. Like StarPilot (and apilot's old check_model_stopping) a red light is read
from the model planning to stop: its 10 s path ends well short of where the current speed would take the car. A green
light is the model planning to go again after the car stopped for a red one. StarPilot's refinements over apilot's
one-frame check: speed-dependent filter (more sensitive in town, calmer at speed), on/off hysteresis, a stopped or slow
lead car in front is not a red light unless the model stops before it, no red light while turning with the blinker on,
a short hold so the light does not flicker, nothing above MAX_SPEED.

This only feeds the HUD traffic light and the green light alert. It never controls the car (apilot's own signal stop,
TrafficStopMode, is pinned off by manager.py).
"""
from common.filter_simple import FirstOrderFilter
from common.numpy_fast import interp
from common.realtime import DT_MDL

THRESHOLD = 1. - 1. / 2.718281828459045  # a filter at this value has seen 'true' for about its time constant
MODEL_TIME = 8.0           # StarPilot: PLANNER_TIME (10 s, the model's horizon) - 2
PLANNER_TIME = 10.0
CRUISING_SPEED = 5.0       # m/s; a model path shorter than CRUISING_SPEED * PLANNER_TIME means 'stays stopped'
ON_MARGIN = 2.5            # m: model path this much shorter than the stop threshold -> stopping
OFF_MARGIN = 4.0           # m: ... and back above threshold + this -> not stopping (hysteresis)
HOLD_STRONG_MARGIN = 10.0  # m: a clear stop (or a path below 50 m) keeps the red light HOLD_TIME
HOLD_TIME = 4.0
LEAD_BLOCK_MARGIN = 15.0   # m: a lead closer than the stop threshold + this may be the reason the model stops
MODEL_LEAD_MARGIN = 3.0    # m: the model stops at least this far before the lead -> a light before the lead
MODEL_BRAKE_MIN = 0.5      # m/s^2 the model must plan to brake for 'stops before the lead'
HANDOFF_MAX_LEAD_SPEED = 2.0  # m/s: an already red light stays red behind a lead that has (almost) stopped
MAX_SPEED = 100. / 3.6     # no red light above this (StarPilot 75 mph)
LOW_SPEED_FILTER = 0.35    # s, below 56 km/h
HIGH_SPEED_FILTER = 0.8    # s, from 72 km/h
LIGHT_BOOST_HIGH = 1.2     # longer stop horizon at speed ...
LIGHT_MAX_TIME = 9.0       # ... capped at this
LEAD_CLEAR_LOW, LEAD_CLEAR_HIGH = 0.6, 0.35  # s
SPEED_BP = [0., 56. / 3.6, 72. / 3.6]  # StarPilot's 0 / 35 / 45 mph
TURN_MAX_SPEED = 24. / 3.6
TURN_STEER_DEG = 45.
STOPPED_SPEED = 0.3        # m/s
GREEN_TIME = 0.3           # s the model has to plan to go (after a red-light stop) before it is a green light
GREEN_SHOW_TIME = 3.0      # s the green light stays on the HUD after it turned green (or until the car moves off)

NONE, RED, GREEN = 0, 1, 2


class OptechSignal:
  def __init__(self):
    self.light_filter = FirstOrderFilter(0., HIGH_SPEED_FILTER, DT_MDL)
    self.lead_clear_filter = FirstOrderFilter(0., LEAD_CLEAR_LOW, DT_MDL)
    self.model_stopping = False
    self.red = False
    self.hold_until = 0.
    self.stopped_for_light = False
    self.go_time = 0.
    self.green_until = 0.
    self.green_event = False  # True for one update when the light turned green while stopped for it
    self.state = NONE
    self.t = 0.

  def reset_red(self):
    self.light_filter.x = 0.
    self.lead_clear_filter.x = 0.
    self.model_stopping = False
    self.red = False
    self.hold_until = 0.

  def update(self, v_ego, model_length, model_accel, standstill, blinker, steering_angle,
             lead_status, lead_dist, lead_speed):
    """v_ego m/s; model_length: modelV2.position.x[-1] (m travelled in the model's 10 s); model_accel: planned
    acceleration now (m/s^2); lead_*: radarState.leadOne. Returns the state (NONE / RED / GREEN)."""
    self.t += DT_MDL
    now = self.t
    self.green_event = False
    model_stopped = model_length < CRUISING_SPEED * PLANNER_TIME
    stopped = standstill or v_ego < STOPPED_SPEED

    if stopped:
      # stopped: red while the model keeps planning to stay, green once it plans to go after a red-light stop
      if self.red or (self.stopped_for_light and model_stopped):
        self.stopped_for_light = True
      if self.stopped_for_light:
        if model_stopped:
          self.go_time = 0.
          self.red = True
        else:
          self.go_time += DT_MDL
          if self.go_time >= GREEN_TIME:
            self.green_event = True
            self.green_until = now + GREEN_SHOW_TIME
            self.stopped_for_light = False
            self.reset_red()
      self.state = GREEN if now < self.green_until else (RED if self.red else NONE)
      return self.state

    self.stopped_for_light = False
    self.go_time = 0.
    if v_ego > 3.:  # moving off: the green light has done its job
      self.green_until = 0.

    # turning with the blinker on at low speed: the model stops for the turn, not for a light
    if blinker and v_ego <= TURN_MAX_SPEED and abs(steering_angle) >= TURN_STEER_DEG:
      self.reset_red()
      self.state = GREEN if now < self.green_until else NONE
      return self.state
    if v_ego > MAX_SPEED:
      self.reset_red()
      self.state = NONE
      return self.state

    self.light_filter.update_alpha(interp(v_ego, SPEED_BP, [LOW_SPEED_FILTER, LOW_SPEED_FILTER, HIGH_SPEED_FILTER]))
    self.lead_clear_filter.update_alpha(interp(v_ego, SPEED_BP, [LEAD_CLEAR_LOW, LEAD_CLEAR_LOW, LEAD_CLEAR_HIGH]))
    boost = interp(v_ego, SPEED_BP, [1., 1., LIGHT_BOOST_HIGH])
    cap = interp(v_ego, SPEED_BP, [0., 0., 1.])
    model_time = MODEL_TIME * boost
    if cap > 0.:
      model_time = min(model_time, LIGHT_MAX_TIME * cap + MODEL_TIME * (1. - cap))
    stop_threshold = max(v_ego * model_time, 0.)
    if self.model_stopping:
      self.model_stopping = model_length < stop_threshold + OFF_MARGIN
    else:
      self.model_stopping = model_length < max(stop_threshold - ON_MARGIN, 0.)

    # a lead car the model may simply be stopping behind
    lead_relevant = lead_status and lead_dist < stop_threshold + LEAD_BLOCK_MARGIN
    target_before_lead = (self.model_stopping and lead_relevant and v_ego > CRUISING_SPEED and
                          model_accel <= -MODEL_BRAKE_MIN and model_length + MODEL_LEAD_MARGIN < lead_dist)
    handoff = lead_relevant and self.red and lead_speed < HANDOFF_MAX_LEAD_SPEED
    if target_before_lead or handoff:
      lead_cleared = True
    else:
      self.lead_clear_filter.update(0. if lead_relevant else 1.)
      lead_cleared = self.lead_clear_filter.x >= THRESHOLD

    self.light_filter.update(1. if (self.model_stopping and lead_cleared) else 0.)
    detector = self.light_filter.x >= THRESHOLD ** 2 and lead_cleared
    if detector and (model_stopped or model_length < max(stop_threshold - HOLD_STRONG_MARGIN, 0.)):
      self.hold_until = now + HOLD_TIME
    hold_ok = (not lead_relevant) or target_before_lead
    self.red = bool(detector or handoff or (hold_ok and now < self.hold_until))
    self.state = GREEN if now < self.green_until else (RED if self.red else NONE)
    return self.state
