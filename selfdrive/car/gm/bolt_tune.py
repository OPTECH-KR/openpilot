# Chevrolet Bolt steering tune after StarPilot (firestar5683/StarPilot, opendbc/car/gm/interface.py and
# selfdrive/controls/lib/latcontrol_torque.py), fitted to this base's torque controller:
#  * torque from lateral accel is StarPilot's "sigmoid + linear" curve, with separate left / right weights
#  * StarPilot's Bolt kp / ki / kd / kf overrides are not PID gains there: kp and ki scale the feedforward
#    for left / right turns, kd multiplies the integral gain and kf is a small push near zero lateral accel
#    ("deadzone boost") so the EPS starts to move. Here the feedforward scale and the push are applied to the
#    feedforward call only (friction_compensation=True), the integral gain once in CarParams.
from math import exp, fabs

from openpilot.common.numpy_fast import interp
from openpilot.selfdrive.car.gm.values import CAR, GMFlags
from openpilot.selfdrive.controls.lib.drive_helpers import get_friction
from openpilot.selfdrive.car.interfaces import FRICTION_THRESHOLD

FF_SCALE_BLEND_LAT_ACCEL = 0.05
DEADZONE_BOOST_LAT_ACCEL = 0.15


class BoltTune:
  def __init__(self, siglin, ff_pos, ff_neg, ki_mult, deadzone_boost, torque=None):
    self.siglin = siglin                  # {"left": [a, b, c, d], "right": [...]}
    self.ff_pos = ff_pos                  # feedforward scale, left turns (lateral accel > 0)
    self.ff_neg = ff_neg                  # ... right turns
    self.ki_mult = ki_mult                # integral gain multiplier
    self.deadzone_boost = deadzone_boost
    self.torque = torque                  # (latAccelFactor, friction) when it differs from torque_data


# StarPilot base overrides kp 1.03, ki 1.07, kd 0.93, kf 0.02; 2018+ and 2022-23: ki *= 1.07, kd *= 0.93, kf *= 0.75;
# 2017: ki *= 0.9, kd *= 0.9, kf = 0.026
BOLT_2022_2023 = BoltTune({"left": [2.6531724862969748, 1.1, 0.1919764879840985, 0.0],
                           "right": [2.7031724862969748, 1.0, 0.1469764879840985, 0.0]},
                          1.03, 1.07 * 1.07, 0.93 * 0.93, 0.02 * 0.75)
BOLT_2018_2021 = BoltTune({"left": [1.8, 1.1, 0.27, 0.0], "right": [2.0, 1.0, 0.205, 0.0]},
                          1.03, 1.07 * 1.07, 0.93 * 0.93, 0.02 * 0.75)
BOLT_2017 = BoltTune({"left": [2.15, 1.00, 0.129, 0.0], "right": [2.15, 1.00, 0.145, 0.0]},
                     1.03, 1.07 * 0.9, 0.93 * 0.9, 0.026, torque=(1.2, 0.21))


def get_bolt_tune(CP):
  # optech-spst: only the Bolt EV without ACC; the Bolt EUV 2022-23 keeps this base's (comma) tune that already works
  if CP.carFingerprint == CAR.BOLT_CC:
    return BOLT_2017 if CP.flags & GMFlags.BOLT_2017 else BOLT_2018_2021
  return None


def siglin(lateral_accel, weights):
  a, b, c, d = weights["left" if lateral_accel >= 0 else "right"]
  x = a * lateral_accel
  sig = (1 if x >= 0 else -1) * (1 / (1 + exp(-fabs(x))) - 0.5)
  return sig * b + lateral_accel * c + d


def make_torque_from_lateral_accel(tune):
  def torque_from_lateral_accel(lateral_accel_value, torque_params, lateral_accel_error, lateral_accel_deadzone,
                                friction_compensation):
    torque = siglin(lateral_accel_value, tune.siglin)
    if friction_compensation:  # the feedforward call (the PID error calls pass False)
      torque *= interp(lateral_accel_value, [-FF_SCALE_BLEND_LAT_ACCEL, 0.0, FF_SCALE_BLEND_LAT_ACCEL],
                       [tune.ff_neg, 1.0, tune.ff_pos])
      if tune.deadzone_boost > 0.0 and abs(lateral_accel_value) < DEADZONE_BOOST_LAT_ACCEL:
        boost_scale = interp(abs(lateral_accel_value), [0.0, DEADZONE_BOOST_LAT_ACCEL], [1.0, 0.0])
        torque += (1 if lateral_accel_value > 0 else -1 if lateral_accel_value < 0 else 0) * tune.deadzone_boost * boost_scale
    friction = get_friction(lateral_accel_error, lateral_accel_deadzone, FRICTION_THRESHOLD, torque_params,
                            friction_compensation)
    return float(torque) + friction
  return torque_from_lateral_accel


def apply_bolt_tune(ret, tune):
  """after configure_torque_tune: StarPilot's torque data, integral gain and actuator delay"""
  if tune.torque is not None:
    ret.lateralTuning.torque.latAccelFactor, ret.lateralTuning.torque.friction = tune.torque
  ret.lateralTuning.torque.ki *= tune.ki_mult
  ret.steerActuatorDelay = 0.2
