"""Twilsonco's lateral Neural Network FeedForward (NNFF) for the C2.

Ported from carrot c3-wip (opendbc/car/interfaces.py FluxModel + latcontrol_torque.py), which carries the
model files from twilsonco's NNFF work. A model maps
  [v_ego, lateral_accel, friction_input, roll, 3 past + 4 future lateral accels, 3 past + 4 future rolls]
to steer torque for one car platform.
"""
import json
import os

import numpy as np

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "car", "torque_data", "lat_models")


class FluxModel:
  # activation names that are not valid python identifiers
  activation_function_names = {'σ': 'sigmoid'}

  def __init__(self, params_file, zero_bias=False):
    with open(params_file, "r", encoding="utf-8") as f:
      params = json.load(f)

    self.input_size = params["input_size"]
    self.output_size = params["output_size"]
    self.input_mean = np.array(params["input_mean"], dtype=np.float32).T
    self.input_std = np.array(params["input_std"], dtype=np.float32).T
    self.layers = []
    self.friction_override = False

    for layer_params in params["layers"]:
      W = np.array(layer_params[next(key for key in layer_params.keys() if key.endswith('_W'))], dtype=np.float32).T
      b = np.array(layer_params[next(key for key in layer_params.keys() if key.endswith('_b'))], dtype=np.float32).T
      if zero_bias:
        b = np.zeros_like(b)
      activation = layer_params["activation"]
      for k, v in self.activation_function_names.items():
        activation = activation.replace(k, v)
      self.layers.append((W, b, activation))

    self.validate_layers()
    self.check_for_friction_override()

  # activation functions, called by the names stored in the model json
  @staticmethod
  def sigmoid(x):
    return 1 / (1 + np.exp(-x))

  @staticmethod
  def identity(x):
    return x

  def forward(self, x):
    for W, b, activation in self.layers:
      x = getattr(self, activation)(x.dot(W) + b)
    return x

  def evaluate(self, input_array):
    if len(input_array) != self.input_size:
      # 2..4 inputs: simplified evaluation, pad the rest with zeros
      if len(input_array) >= 2:
        input_array = list(input_array) + [0] * (self.input_size - len(input_array))
      else:
        raise ValueError(f"Input array length {len(input_array)} must be length 2 or greater")
    x = (np.array(input_array, dtype=np.float32) - self.input_mean) / self.input_std
    return float(np.asarray(self.forward(x)).reshape(-1)[0])

  def validate_layers(self):
    for _, _, activation in self.layers:
      if not hasattr(self, activation):
        raise ValueError(f"Unknown activation: {activation}")

  def check_for_friction_override(self):
    y = self.evaluate([10.0, 0.0, 0.2])
    self.friction_override = (y < 0.1)


def model_name_for(brand, car_attr_name):
  """C2 CAR attribute name (e.g. SONATA, KIA_NIRO_EV) -> model file name (HYUNDAI_SONATA, KIA_NIRO_EV)."""
  if brand == "hyundai":
    if car_attr_name.startswith(("HYUNDAI_", "KIA_", "GENESIS_")):
      return car_attr_name
    return "HYUNDAI_" + car_attr_name
  return car_attr_name


def find_model_path(brand, car_attr_name, model_dir=MODEL_DIR):
  """Exact name match only: a model trained on another platform must never be used."""
  if not car_attr_name:
    return None
  path = os.path.join(model_dir, model_name_for(brand, car_attr_name) + ".json")
  return path if os.path.isfile(path) else None


def car_attr_name(brand, fingerprint):
  """Reverse lookup of the CAR attribute name for a fingerprint string such as 'HYUNDAI SONATA 2020'."""
  try:
    if brand == "hyundai":
      from openpilot.selfdrive.car.hyundai.values import CAR
    else:
      return None
  except Exception:
    return None
  for member in CAR:  # spst: CAR is a StrEnum
    if member.value == fingerprint:
      return member.name
  return None


def load_model(brand, fingerprint):
  path = find_model_path(brand, car_attr_name(brand, fingerprint))
  return (FluxModel(path), path) if path else (None, None)
