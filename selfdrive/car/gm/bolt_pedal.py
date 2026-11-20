# Chevrolet Bolt EV 2017-21 without ACC: comma pedal model, after StarPilot (firestar5683/StarPilot,
# opendbc/car/gm/carcontroller.py, the pedal-long Bolts without the regen paddle press).
# Only on with the "BoltPedal" toggle (Bolt EV settings page) and the pedal seen on the bus (0x201).
# The car is in L (one pedal) mode: no pedal is regen braking, so slowing down is letting the pedal up.
from openpilot.common.numpy_fast import interp, clip

PEDAL_PARAM = "BoltPedal"
PEDAL_MAX_PARAM = "BoltPedalMax"  # percent of full pedal, on top of StarPilot's own speed cap
PEDAL_MAX_DEFAULT = 100           # StarPilot as is
PEDAL_MAX_RANGE = (20, 100)
YEAR_2017_PARAM = "BoltYear2017"  # 2017 Bolt EV: its own steering tune and limits

# StarPilot get_pid_accel_limits for BOLT_PEDAL_LONG_CARS
ACCEL_MIN_BP = [0.0, 1.5, 4.0, 8.0, 15.0, 30.0]
ACCEL_MIN_V = [-0.93, -1.28, -1.98, -2.58, -2.86, -2.95]
ACCEL_MAX_BP = [0.0, 1.5, 4.0, 8.0, 15.0]
ACCEL_MAX_V = [0.54, 0.74, 1.03, 1.46, 2.0]  # last = CarControllerParams.ACCEL_MAX


def pedal_max(raw):
  try:
    v = int(raw)
  except (TypeError, ValueError):
    v = PEDAL_MAX_DEFAULT
  return clip(v, *PEDAL_MAX_RANGE) / 100.


def accel_limits(v_ego):
  return interp(v_ego, ACCEL_MIN_BP, ACCEL_MIN_V), interp(v_ego, ACCEL_MAX_BP, ACCEL_MAX_V)


def target_pedal(accel, v_ego):
  """pedal 0..1 for the wanted accel (StarPilot, no regen paddle press)"""
  accel_gain = interp(v_ego, [0.0, 3.0, 8.0, 20.0], [0.47, 0.52, 0.57, 0.61])
  pedal_offset = interp(v_ego, [0.0, 1.0, 3.0, 6.0, 15.0, 30.0], [0.085, 0.11, 0.17, 0.23, 0.235, 0.23])

  # tiny planner sign flaps around zero: keep the creep-speed pedal stable
  pedal_accel = 0.0 if abs(accel) < 0.04 else accel
  if pedal_accel >= 0.0:
    small_cmd_scale = interp(abs(pedal_accel), [0.0, 0.35, 0.8, 1.5, 2.5], [0.58, 0.68, 0.82, 0.93, 1.0])
  else:
    small_cmd_scale = interp(abs(pedal_accel), [0.0, 0.35, 0.8, 1.5, 2.5], [0.44, 0.54, 0.70, 0.89, 1.0])
  accel_cmd = pedal_accel * small_cmd_scale
  if pedal_accel < -2.0:
    accel_cmd *= interp(abs(pedal_accel), [2.0, 2.5, 3.0], [1.0, 1.03, 1.06])
  raw_pedal = clip(pedal_offset + accel_cmd * accel_gain, 0.0, 1.0)

  speed_cap = interp(v_ego, [0.0, 1.0, 2.5, 4.5, 6.0, 8.0, 12.0], [0.20, 0.235, 0.29, 0.365, 0.52, 0.78, 1.0])
  return clip(raw_pedal, 0.0, speed_cap)


def pedal_command(accel, v_ego, steady, active_last, max_pedal):
  """returns (pedal 0..max_pedal, new steady); active_last False = first frame after engaging: jump to the target"""
  target = min(target_pedal(accel, v_ego), max_pedal)
  if not active_last:
    pedal = target
  else:
    # rate limits: faster when the planner wants more, gentler for small comfort changes at speed
    urgency = clip(abs(accel) / 2.0, 0.0, 1.0)
    rate_up = interp(v_ego, [0.0, 3.0, 8.0, 20.0], [0.007, 0.012, 0.022, 0.036]) + 0.011 * urgency
    if accel > 0.0 and v_ego > 6.0:
      rate_up *= interp(abs(accel), [0.0, 0.12, 0.25, 0.45, 0.8], [0.55, 0.58, 0.68, 0.82, 1.0])
    if accel > 1.2:
      rate_up += interp(v_ego, [0.0, 4.0, 12.0, 25.0], [0.006, 0.005, 0.003, 0.002])
    rate_down = interp(v_ego, [0.0, 3.0, 8.0, 20.0], [0.008, 0.014, 0.026, 0.045]) + 0.015 * urgency
    pedal = clip(target, steady - rate_down, steady + rate_up)
  return pedal, pedal
