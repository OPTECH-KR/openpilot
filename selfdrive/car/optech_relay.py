"""optech: panda relay behaviour by car brand.

Hyundai / Kia / Genesis keep this (apilot) panda's relay-on while openpilot is not in control. Every other brand gets
the comma / dragonpilot d2 behaviour: relay off (car <-> camera direct) while the device is off, waiting for ignition
or fingerprinting. boardd reads PandaIdlePassthrough and sends it to the panda with NO_OUTPUT (param bit 0).
(A Bolt EUV stayed offroad with a camera warning on this panda but works on d2.)
"""
from common.params import Params


def is_hkg_car(car):
  """a Hyundai / Kia / Genesis car string of this tree (selfdrive/car/hyundai)"""
  from selfdrive.car.hyundai.values import CAR as HKG_CAR
  return car in {v for k, v in vars(HKG_CAR).items() if not k.startswith("_")}


def set_idle_passthrough(car, params=None):
  """PandaIdlePassthrough: true for a non Hyundai / Kia car"""
  want = not is_hkg_car(car)
  params = params or Params()
  if params.get_bool("PandaIdlePassthrough") != want:
    params.put_bool("PandaIdlePassthrough", want)
  return want
