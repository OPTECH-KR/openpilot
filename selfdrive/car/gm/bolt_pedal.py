# Chevrolet Bolt EV 2017-21 without ACC: comma pedal model, after ds5ajd/openpilot 0814 (selfdrive/car/gm/carcontroller.py)
# Only on with the "BoltPedal" toggle (Bolt EV settings page) and the pedal seen on the bus (0x201).
import math

from common.conversions import Conversions as CV
from common.numpy_fast import interp, clip

PEDAL_PARAM = "BoltPedal"
PEDAL_MAX_PARAM = "BoltPedalMax"  # percent of full pedal, 20..60
PEDAL_MAX_DEFAULT = 33            # ds5ajd pedalMaxValue 0.331
PEDAL_MAX_RANGE = (20, 60)


def pedal_max(raw):
  try:
    v = int(raw)
  except (TypeError, ValueError):
    v = PEDAL_MAX_DEFAULT
  return clip(v, *PEDAL_MAX_RANGE) / 100.


def coast_point(v_ego):
  # pedal that holds the speed in L (one pedal) mode, rising with speed
  return interp(v_ego, [0.2 * CV.KPH_TO_MS, 0.7 * CV.KPH_TO_MS, 1.5 * CV.KPH_TO_MS, 3.0 * CV.KPH_TO_MS, 6.0 * CV.KPH_TO_MS,
                        9.0 * CV.KPH_TO_MS, 18.0 * CV.KPH_TO_MS, 85.0 * CV.KPH_TO_MS, 100.0 * CV.KPH_TO_MS],
                [0.006, 0.02, 0.04, 0.05, 0.07, 0.11, 0.14, 0.175, 0.2125])


def hysteresis(target, steady, gap):
  # don't change the pedal for small oscillations within gap
  if math.isclose(target, 0.0):
    steady = 0.
  elif target > steady + gap:
    steady = target - gap
  elif target < steady - gap:
    steady = target + gap
  return steady, steady


def pedal_command(accel, v_ego, steady, max_pedal):
  """returns (pedal 0..max_pedal, new steady)"""
  const = coast_point(v_ego)
  target = clip(interp(accel, [-0.875, 0.0, 0.3], [0.0, const, const + 0.025]) + (accel - const) / 8.0, 0., 1.)
  gap = interp(v_ego, [40.0 * CV.KPH_TO_MS, 100.0 * CV.KPH_TO_MS], [0.01, 0.0055])
  final, steady = hysteresis(target, steady, gap)
  return clip(final, 0., max_pedal), steady
