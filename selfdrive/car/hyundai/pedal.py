"""comma pedal (gas interceptor) for the cars without SCC: Kia Ray EV and Hyundai Porter II EV.

Adapted from StarPilot (firestar5683/StarPilot, Kia Ray EV pedal). openpilot sends GAS_COMMAND (0x200) to the pedal box,
which passes it to the car as the accelerator pedal; GAS_SENSOR (0x201) carries the driver's own pedal and the box state.
There is no brake actuator: slowing down is the car's regen when the command drops, so stopping or holding still is up
to the driver.

Each car has its own menu switch, its own cap and its own DBC (the pedal command scaling is per car):
  Ray EV: StarPilot's Ray calibration (zero command raw 264 / 497).
  Porter II EV: no calibration exists yet; it starts from the Ray values with a lower cap and must be checked on the car.
The red panda / uno safety (panda/board/safety/safety_hyundai.h) only lets these commands through in the same ranges.
"""
from common.numpy_fast import clip, interp
from selfdrive.car.hyundai.values import CAR

PEDAL_DBC = {
  CAR.KIA_RAY_EV: "hyundai_kia_ray_pedal",
  CAR.PORTER_II_EV: "hyundai_porter_pedal",
}
# menu params per car: (pedal on, pedal cap %, speed buttons when the pedal is off)
PEDAL_PARAMS = {
  CAR.KIA_RAY_EV: ("RayPedal", "RayPedalMax", "RaySpeedButtons"),
  CAR.PORTER_II_EV: ("PorterPedal", "PorterPedalMax", "PorterSpeedButtons"),
}
PEDAL_SENSOR_ADDR = 0x201
PEDAL_SENSOR_LEN = 6

# StarPilot Ray EV pedal model
CAP_SPEED_BP = [0.0, 12.0, 20.0, 25.0]
CAP_V = [0.55, 0.55, 0.65, 0.70]
OFFSET_SPEED_BP = [0.0, 2.0, 4.0, 8.0, 12.0, 16.0, 20.0, 25.0]
OFFSET_V = [0.08, 0.13, 0.20, 0.32, 0.42, 0.51, 0.565, 0.60]
ACCEL_GAIN = 0.22
DECEL_GAIN = 0.55
RATE_UP = 0.02    # per command (25 Hz)
RATE_DOWN = 0.06
OVERSPEED_CUTOFF = 0.5    # m/s above the set speed: no pedal
TAPER_BELOW_TARGET = 0.75  # m/s below the set speed: ease off
COMMAND_MAX = 0.70        # what the panda allows (raw 530)

# driver pedal pressed: raw tracks above these (StarPilot, Ray pedal firmware)
DRIVER_TRACK1 = 272
DRIVER_TRACK2 = 513
# GAS_SENSOR scaling in the pedal DBCs (raw = (value - offset) / factor)
_T1_FACTOR, _T1_OFFSET = 0.672, -177.408
_T2_FACTOR, _T2_OFFSET = 0.332, -165.004


def pedal_target(accel: float, v_ego: float, set_speed: float, max_cap: float = COMMAND_MAX) -> float:
  """pedal command 0..max_cap for the wanted accel (StarPilot get_ray_pedal_target with a menu cap)"""
  if set_speed < 1.0:
    return 0.0
  speed_error = set_speed - v_ego
  if speed_error <= -OVERSPEED_CUTOFF:
    return 0.0
  offset = interp(v_ego, OFFSET_SPEED_BP, OFFSET_V)
  cap = min(interp(v_ego, CAP_SPEED_BP, CAP_V), max_cap, COMMAND_MAX)
  gain = DECEL_GAIN if accel < 0.0 else ACCEL_GAIN
  target = clip(offset + accel * gain, 0.0, cap)
  if speed_error < 0.0:
    target *= clip(0.65 * (1.0 + speed_error / OVERSPEED_CUTOFF), 0.0, 1.0)
  elif speed_error < TAPER_BELOW_TARGET:
    target *= 0.65 + 0.35 * speed_error / TAPER_BELOW_TARGET
  return target


def next_command(target: float, last: float) -> float:
  if target <= 0.001:
    return 0.0
  return min(clip(target, last - RATE_DOWN, last + RATE_UP), target)


def driver_pressed(gas: float, gas2: float) -> bool:
  """driver's own pedal from GAS_SENSOR (physical values) -> raw tracks above StarPilot's thresholds"""
  track1 = round((gas - _T1_OFFSET) / _T1_FACTOR)
  track2 = round((gas2 - _T2_OFFSET) / _T2_FACTOR)
  return track1 > DRIVER_TRACK1 or track2 > DRIVER_TRACK2
