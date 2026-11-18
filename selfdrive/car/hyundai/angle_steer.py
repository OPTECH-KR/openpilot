"""Hyundai/Kia CAN FD angle steering (LFA2 cars: Ioniq 5 PE, EV6 PE, Ioniq 9, Santa Fe MX5, EV9, ...).

Adapted from StarPilot (firestar5683/StarPilot opendbc_repo, which credits sunnypilot/opendbc's hkg-angle-steering-2025
branch): the car is sent a steering wheel angle plus a torque reduction gain (0..1, how much of the EPS torque the
command may use), instead of a torque.

The angle is limited the same way the red panda safety (panda/board/safety/safety_hyundai_canfd.h) checks it: a simple
vehicle model with a fixed baseline car (Kia Sportage HEV 2026 in StarPilot) and ISO-style lateral accel / jerk limits.
Using the panda's own model here keeps every message inside what the panda lets through.
"""
import math

from common.numpy_fast import clip, interp

DT_CTRL = 0.01

# the panda's baseline vehicle model (keep in sync with HYUNDAI_CANFD_ANGLE_STEERING_PARAMS)
SAFETY_SLIP_FACTOR = -0.0006085930193026732
SAFETY_STEER_RATIO = 13.7
SAFETY_WHEELBASE = 2.756

EARTH_G = 9.81
AVERAGE_ROAD_ROLL = 0.06
MAX_LATERAL_ACCEL = 3.0 + EARTH_G * AVERAGE_ROAD_ROLL  # m/s^2, ISO 11270 accel + road roll
MAX_LATERAL_JERK = 3.0 + EARTH_G * AVERAGE_ROAD_ROLL   # m/s^3, below the ISO 5.0 jerk
MAX_ANGLE_RATE = 5.0      # deg per 10 ms frame, low speed comfort / fault cap
STEER_ANGLE_MAX = 360.0   # deg
# stay a little inside the panda's limits (it rounds its own limits up by one CAN unit)
PANDA_MARGIN = 0.95


def _angle_from_curvature(curvature: float, v: float) -> float:
  curvature_factor = 1. / (1. - SAFETY_SLIP_FACTOR * v * v) / SAFETY_WHEELBASE
  return math.degrees(curvature * SAFETY_STEER_RATIO / curvature_factor)


def max_angle_delta(v_ego_raw: float) -> float:
  """largest angle change per frame (deg) the lateral jerk limit allows at this speed"""
  v = max(v_ego_raw, 1.)
  return min(_angle_from_curvature(MAX_LATERAL_JERK / (v * v), v) * DT_CTRL, MAX_ANGLE_RATE)


def max_angle(v_ego_raw: float) -> float:
  """largest angle (deg) the lateral accel limit allows at this speed"""
  v = max(v_ego_raw, 1.)
  return _angle_from_curvature(MAX_LATERAL_ACCEL / (v * v), v)


def apply_steer_angle_limits(desired: float, last: float, v_ego_raw: float, measured: float, lat_active: bool) -> float:
  if not lat_active:
    # inactive: the panda wants the angle we send to be the angle the wheel is at
    return clip(measured, -STEER_ANGLE_MAX, STEER_ANGLE_MAX)
  delta = max_angle_delta(v_ego_raw) * PANDA_MARGIN
  new = clip(desired, last - delta, last + delta)
  limit = max_angle(v_ego_raw) * PANDA_MARGIN
  new = clip(new, -limit, limit)
  return clip(new, -STEER_ANGLE_MAX, STEER_ANGLE_MAX)


def torque_reduction_gain(steering_torque: float, v_ego: float, lat_active: bool, last_gain: float, max_gain: float = 1.0) -> float:
  """how much EPS torque the angle command may use (0..1). Drops as the driver's own torque grows, so the driver can
  always take over; ramps back slowly (StarPilot compute_torque_reduction_gain). max_gain is the menu cap."""
  if lat_active:
    ceiling = interp(v_ego, [0.5, 1.5], [1.0, 0.85])
    shelf = interp(v_ego, [2.0, 11.0], [0.45, 0.6])
    floor = interp(v_ego, [2.0, 22.0], [0.1, 0.3])
    bp1 = interp(v_ego, [2.0, 11.0], [75.0, 125.0])
    bp2 = interp(v_ego, [2.0, 11.0], [125.0, 150.0])
    bp3 = interp(v_ego, [2.0, 11.0], [175.0, 275.0])
    bp4 = interp(v_ego, [2.0, 22.0], [400.0, 700.0])
    target = interp(abs(steering_torque), [bp1, bp2, bp3, bp4], [ceiling, shelf, shelf, floor])
    target = min(target, max_gain)
  else:
    target = 0.0
  gain = clip(target, last_gain - 0.014, last_gain + 0.004)
  return round(gain / 0.004) * 0.004
