"""comma pedal (gas interceptor) for the cars without SCC: Kia Ray EV and Hyundai Porter II EV (optech-hkg).

Adapted from StarPilot (Kia Ray EV pedal) through optech-hkg. openpilot sends GAS_COMMAND (0x200) to the pedal box, which
passes it to the car as the accelerator pedal; GAS_SENSOR (0x201) carries the driver's own pedal and the box state.
There is no brake actuator: slowing down is the car's regen when the command drops, so stopping or holding still is up
to the driver.

Each car has its own menu switch (OPTECH 시작 tab, under 차종 선택), its own cap and its own DBC:
  Ray EV: StarPilot's Ray calibration (zero command raw 264 / 497).
  Porter II EV: no calibration exists yet; it starts from the Ray values with a lower cap and must be checked on the car.
The panda (board/safety/safety_hyundai.h, FLAG_HYUNDAI_NON_SCC_PEDAL) only lets these commands through in the same ranges.

Carrot's two Ray options (carrot-wip, from the same StarPilot calibration):
  '페달 세게' (RayPedalStrong): carrot PR 570, a 2024 Ray EV owner's fix for weak acceleration: the command DBC has half the
    factor, so the same command is about twice the pedal (command 0.70 = raw 795 / 1572; the panda allows that only with
    FLAG_HYUNDAI_NON_SCC_PEDAL_STRONG).
  '속도 오차 보정' (RayPedalKi): long control with the pedal is a PID on the speed error with Kp 1, Kf 1 and a small Ki
    (owner's candidate 0.05) - this base's longcontrol is the same kind (speed error) as carrot's.
"""
from openpilot.common.numpy_fast import clip, interp
from openpilot.common.params import Params
from openpilot.selfdrive.car.hyundai.values import CAR, HyundaiFlags

PEDAL_DBC = {
  CAR.KIA_RAY_EV: "hyundai_kia_ray_pedal",
  CAR.PORTER_II_EV: "hyundai_porter_pedal",
}
# menu params per car: (pedal on, pedal cap %)
PEDAL_PARAMS = {
  CAR.KIA_RAY_EV: ("RayPedal", "RayPedalMax"),
  CAR.PORTER_II_EV: ("PorterPedal", "PorterPedalMax"),
}
PEDAL_DBC_STRONG = "hyundai_kia_ray_pedal_strong"
STRONG_PARAM = "RayPedalStrong"
KI_PARAM = "RayPedalKi"  # x0.001
KI_DEFAULT = 50
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


def pedal_wanted(candidate, fingerprint) -> bool:
  """the car's menu switch is on and the pedal box answers on the bus (GAS_SENSOR 0x201, 6 bytes)"""
  if candidate not in PEDAL_PARAMS:
    return False
  return Params().get_bool(PEDAL_PARAMS[candidate][0]) and fingerprint[0].get(PEDAL_SENSOR_ADDR) == PEDAL_SENSOR_LEN


def strong_wanted(candidate) -> bool:
  return candidate == CAR.KIA_RAY_EV and Params().get_bool(STRONG_PARAM)


def ray_ki(raw) -> float:
  try:
    v = int(raw)
  except (TypeError, ValueError):
    v = KI_DEFAULT
  return min(max(v, 0), 200) * 0.001


def set_long_tune(ret, candidate) -> None:
  """carrot Ray EV pedal long control: Kp 1, Kf 1 and the Ray menu's Ki (Porter 0.05). Two breakpoints so a single
  breakpoint long tuning menu would not replace it."""
  ki = ray_ki(Params().get(KI_PARAM, encoding="utf8")) if candidate == CAR.KIA_RAY_EV else 0.05
  ret.longitudinalTuning.kpBP = [0., 35.]
  ret.longitudinalTuning.kpV = [1.0, 1.0]
  ret.longitudinalTuning.kiBP = [0., 35.]
  ret.longitudinalTuning.kiV = [ki, ki]
  ret.longitudinalTuning.kf = 1.0


def max_cap(CP) -> float:
  """menu cap (%): Ray 10-70 (default 70), Porter 10-70 (default 40)"""
  if CP.carFingerprint not in PEDAL_PARAMS:
    return 0.5
  default = 70 if CP.carFingerprint == CAR.KIA_RAY_EV else 40
  try:
    v = int(Params().get(PEDAL_PARAMS[CP.carFingerprint][1], encoding="utf8") or default)
  except ValueError:
    v = default
  return min(max(v, 10), 70) / 100.


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


def command_dbc(CP) -> str:
  if CP.flags & HyundaiFlags.NON_SCC_PEDAL_STRONG:
    return PEDAL_DBC_STRONG
  return PEDAL_DBC[CP.carFingerprint]


def next_command(target: float, last: float) -> float:
  if target <= 0.001:
    return 0.0
  return min(clip(target, last - RATE_DOWN, last + RATE_UP), target)


def driver_pressed(gas: float, gas2: float) -> bool:
  """driver's own pedal from GAS_SENSOR (physical values) -> raw tracks above StarPilot's thresholds"""
  track1 = round((gas - _T1_OFFSET) / _T1_FACTOR)
  track2 = round((gas2 - _T2_OFFSET) / _T2_FACTOR)
  return track1 > DRIVER_TRACK1 or track2 > DRIVER_TRACK2
