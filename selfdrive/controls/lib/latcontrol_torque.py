import math
from collections import deque

import numpy as np

from cereal import log
from openpilot.common.numpy_fast import interp
from openpilot.common.params import Params
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.selfdrive.controls.lib.latcontrol import LatControl
from openpilot.selfdrive.controls.lib.pid import PIDController
from openpilot.selfdrive.controls.lib.vehicle_model import ACCELERATION_DUE_TO_GRAVITY
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N
from openpilot.selfdrive.modeld.constants import ModelConstants

T_IDXS = ModelConstants.T_IDXS

# At higher speeds (25+mph) we can assume:
# Lateral acceleration achieved by a specific car correlates to
# torque applied to the steering rack. It does not correlate to
# wheel slip, or to speed.

# This controller applies torque to achieve desired lateral
# accelerations. To compensate for the low speed effects we
# use a LOW_SPEED_FACTOR in the error. Additionally, there is
# friction in the steering wheel that needs to be overcome to
# move it at all, this is compensated for too.

LOW_SPEED_X = [0, 10, 20, 30]
LOW_SPEED_Y = [15, 13, 10, 5]

# optech 조향 탭 'NNFF 조향 보정' / 'NNFF 라이트' (optech-hkg; twilsonco's lateral neural network feedforward,
# ported from carrot c3-wip). Only with a model for exactly this car (selfdrive/car/torque_data/lat_models)
LAT_PLAN_MIN_IDX = 5


def get_predicted_lateral_jerk(lat_accels, t_diffs):
  return (np.diff(lat_accels) / t_diffs).tolist()


def sign(x):
  return 1.0 if x > 0.0 else (-1.0 if x < 0.0 else 0.0)


def get_lookahead_value(future_vals, current_val):
  if len(future_vals) == 0:
    return current_val
  same_sign_vals = [v for v in future_vals if sign(v) == sign(current_val)]
  # any future value with the opposite sign: the jerk is not deliberate
  if len(same_sign_vals) < len(future_vals):
    return 0.0
  return min(same_sign_vals + [current_val], key=lambda x: abs(x))


def roll_pitch_adjust(roll, pitch):
  # with pitch, part of gravity points along the car instead of across it
  return roll * math.cos(pitch)


class LatControlTorque(LatControl):
  def __init__(self, CP, CI):
    super().__init__(CP, CI)
    self.torque_params = CP.lateralTuning.torque
    self.pid = PIDController(self.torque_params.kp, self.torque_params.ki,
                             k_f=self.torque_params.kf, pos_limit=self.steer_max, neg_limit=-self.steer_max)
    self.torque_from_lateral_accel = CI.torque_from_lateral_accel()
    self.use_steering_angle = self.torque_params.useSteeringAngle
    self.steering_angle_deadzone_deg = self.torque_params.steeringAngleDeadzoneDeg

    # NNFF: only when switched on and a model exists for exactly this car (read at start)
    params = Params()
    self.nn_model = None
    self.nn_model_path = None
    if params.get_bool("NNFF"):
      try:
        from openpilot.selfdrive.controls.lib.nnff import load_model
        self.nn_model, self.nn_model_path = load_model(CP.carName, CP.carFingerprint)
      except Exception as e:
        print("NNFF load failed:", e)
        self.nn_model = None
    self.use_nnff = self.nn_model is not None
    # NNFF Lite: no model, only the look-ahead of the planned lateral jerk added to the friction compensation
    self.use_nnff_lite = not self.use_nnff and params.get_bool("NNFFLite")
    print("NNFF:", self.nn_model_path if self.use_nnff else ("lite" if self.use_nnff_lite else "off"))

    if self.use_nnff or self.use_nnff_lite:
      # look ahead to the planned lateral jerk to see whether the current jerk is deliberate
      self.friction_look_ahead_v = [1.4, 2.0]
      self.friction_look_ahead_bp = [9.0, 30.0]
      self.lat_jerk_friction_factor = 0.4
      self.lat_accel_friction_factor = 0.7
      self.t_diffs = np.diff(T_IDXS)
      self.desired_lat_jerk_time = CP.steerActuatorDelay + 0.3

    if self.use_nnff:
      self.pitch = FirstOrderFilter(0.0, 0.5, 0.01)
      self.nn_friction_override = self.nn_model.friction_override
      self.nn_time_offset = CP.steerActuatorDelay + 0.2
      self.nn_future_times = [t + self.nn_time_offset for t in (0.3, 0.6, 1.0, 1.5)]
      self.past_times = [-0.3, -0.2, -0.1]
      history_check_frames = [int(abs(t) * 100) for t in self.past_times]
      self.history_frame_offsets = [history_check_frames[0] - f for f in history_check_frames]
      self.lateral_accel_desired_deque = deque(maxlen=history_check_frames[0])
      self.roll_deque = deque(maxlen=history_check_frames[0])
      self.past_future_len = len(self.past_times) + len(self.nn_future_times)

  def update_live_torque_params(self, latAccelFactor, latAccelOffset, friction):
    self.torque_params.latAccelFactor = latAccelFactor
    self.torque_params.latAccelOffset = latAccelOffset
    self.torque_params.friction = friction

  def update(self, active, CS, VM, params, last_actuators, steer_limited, desired_curvature, desired_curvature_rate, llk,
             model_data=None):
    pid_log = log.ControlsState.LateralTorqueState.new_message()

    if not active:
      output_torque = 0.0
      pid_log.active = False
    else:
      actual_lateral_jerk = 0.0
      if self.use_steering_angle:
        actual_curvature = -VM.calc_curvature(math.radians(CS.steeringAngleDeg - params.angleOffsetDeg), CS.vEgo, params.roll)
        curvature_deadzone = abs(VM.calc_curvature(math.radians(self.steering_angle_deadzone_deg), CS.vEgo, 0.0))
        if self.use_nnff:
          actual_curvature_rate = -VM.calc_curvature(math.radians(CS.steeringRateDeg), CS.vEgo, 0.0)
          actual_lateral_jerk = actual_curvature_rate * CS.vEgo ** 2
      else:
        actual_curvature_vm = -VM.calc_curvature(math.radians(CS.steeringAngleDeg - params.angleOffsetDeg), CS.vEgo, params.roll)
        actual_curvature_llk = llk.angularVelocityCalibrated.value[2] / CS.vEgo
        actual_curvature = interp(CS.vEgo, [2.0, 5.0], [actual_curvature_vm, actual_curvature_llk])
        curvature_deadzone = 0.0
      desired_lateral_accel = desired_curvature * CS.vEgo ** 2

      # desired rate is the desired rate of change in the setpoint, not the absolute desired curvature
      # desired_lateral_jerk = desired_curvature_rate * CS.vEgo ** 2
      actual_lateral_accel = actual_curvature * CS.vEgo ** 2
      lateral_accel_deadzone = curvature_deadzone * CS.vEgo ** 2

      low_speed_factor = interp(CS.vEgo, LOW_SPEED_X, LOW_SPEED_Y)**2
      setpoint = desired_lateral_accel + low_speed_factor * desired_curvature
      measurement = actual_lateral_accel + low_speed_factor * actual_curvature
      gravity_adjusted_lateral_accel = desired_lateral_accel - params.roll * ACCELERATION_DUE_TO_GRAVITY

      plan_good = (model_data is not None and len(model_data.acceleration.y) == len(T_IDXS) and
                   len(model_data.orientation.x) >= CONTROL_N)
      model_good = self.use_nnff and plan_good
      lite_good = self.use_nnff_lite and plan_good
      if model_good:
        ff, pid_log.error = self._nnff(CS, params, llk, model_data, desired_lateral_accel, setpoint, measurement,
                                       actual_lateral_jerk, lateral_accel_deadzone)
      else:
        torque_from_setpoint = self.torque_from_lateral_accel(setpoint, self.torque_params, setpoint,
                                                       lateral_accel_deadzone, friction_compensation=False)
        torque_from_measurement = self.torque_from_lateral_accel(measurement, self.torque_params, measurement,
                                                       lateral_accel_deadzone, friction_compensation=False)
        pid_log.error = torque_from_setpoint - torque_from_measurement
        friction_input = desired_lateral_accel - actual_lateral_accel
        if lite_good:
          # NNFF Lite: the feedforward friction also sees the planned jerk ahead, bounded by the car's friction
          lookahead_lateral_jerk = self._lookahead_lateral_jerk(CS, list(model_data.acceleration.y), desired_lateral_accel)
          friction_input += self.lat_jerk_friction_factor * lookahead_lateral_jerk
        ff = self.torque_from_lateral_accel(gravity_adjusted_lateral_accel, self.torque_params, friction_input,
                                            lateral_accel_deadzone, friction_compensation=True)

      freeze_integrator = steer_limited or CS.steeringPressed or CS.vEgo < 5
      output_torque = self.pid.update(pid_log.error,
                                      feedforward=ff,
                                      speed=CS.vEgo,
                                      freeze_integrator=freeze_integrator)

      pid_log.active = True
      pid_log.p = self.pid.p
      pid_log.i = self.pid.i
      pid_log.d = self.pid.d
      pid_log.f = self.pid.f
      pid_log.output = -output_torque
      pid_log.actualLateralAccel = actual_lateral_accel
      pid_log.desiredLateralAccel = desired_lateral_accel
      pid_log.saturated = self._check_saturation(self.steer_max - abs(output_torque) < 1e-3, CS, steer_limited)

    # TODO left is positive in this convention
    return -output_torque, 0.0, pid_log

  def _lookahead_lateral_jerk(self, CS, acc_y, desired_lateral_accel):
    """Planned lateral jerk that persists over the look-ahead window (0 when it changes sign = not deliberate)."""
    lookahead = interp(CS.vEgo, self.friction_look_ahead_bp, self.friction_look_ahead_v)
    friction_upper_idx = next((i for i, t in enumerate(T_IDXS) if t > lookahead), 16)
    predicted_lateral_jerk = get_predicted_lateral_jerk(acc_y, self.t_diffs)
    desired_lateral_jerk = (interp(self.desired_lat_jerk_time, T_IDXS, acc_y) - desired_lateral_accel) / self.desired_lat_jerk_time
    return get_lookahead_value(predicted_lateral_jerk[LAT_PLAN_MIN_IDX:friction_upper_idx], desired_lateral_jerk)

  def _nnff(self, CS, params, llk, model_data, desired_lateral_accel, setpoint, measurement, actual_lateral_jerk,
            lateral_accel_deadzone):
    """Feedforward and PID error from the NN model (optech-hkg / carrot c3-wip LatControlTorque, NNFF branch)."""
    acc_y = list(model_data.acceleration.y)

    lookahead_lateral_jerk = self._lookahead_lateral_jerk(CS, acc_y, desired_lateral_accel)
    lat_accel_friction_factor = self.lat_accel_friction_factor
    if self.use_steering_angle or lookahead_lateral_jerk == 0.0:
      lookahead_lateral_jerk = 0.0
      actual_lateral_jerk = 0.0
      lat_accel_friction_factor = 1.0
    lateral_jerk_setpoint = self.lat_jerk_friction_factor * lookahead_lateral_jerk
    lateral_jerk_measurement = self.lat_jerk_friction_factor * actual_lateral_jerk

    # roll (road bank) adjusted by pitch
    pitch = 0.0
    roll = params.roll
    try:
      if len(llk.orientationNED.value) > 1:
        pitch = self.pitch.update(llk.orientationNED.value[1])
        roll = roll_pitch_adjust(roll, pitch)
    except Exception:
      pass
    self.roll_deque.append(roll)
    self.lateral_accel_desired_deque.append(desired_lateral_accel)

    # past and future values; future times stretched by the longitudinal acceleration
    rot_x, rot_y = list(model_data.orientation.x), list(model_data.orientation.y)
    adjusted_future_times = [t + 0.5 * CS.aEgo * (t / max(CS.vEgo, 1.0)) for t in self.nn_future_times]
    past_rolls = [self.roll_deque[min(len(self.roll_deque) - 1, i)] for i in self.history_frame_offsets]
    future_rolls = [roll_pitch_adjust(interp(t, T_IDXS, rot_x) + roll, interp(t, T_IDXS, rot_y) + pitch) for t in adjusted_future_times]
    past_lateral_accels_desired = [self.lateral_accel_desired_deque[min(len(self.lateral_accel_desired_deque) - 1, i)]
                                   for i in self.history_frame_offsets]
    future_planned_lateral_accels = [interp(t, T_IDXS, acc_y) for t in adjusted_future_times]

    # error response
    nnff_setpoint_input = [CS.vEgo, setpoint, lateral_jerk_setpoint, roll] + [setpoint] * self.past_future_len + past_rolls + future_rolls
    nnff_measurement_input = [CS.vEgo, measurement, lateral_jerk_measurement, roll] + [measurement] * self.past_future_len + past_rolls + future_rolls
    error = float(self.nn_model.evaluate(nnff_setpoint_input) - self.nn_model.evaluate(nnff_measurement_input))
    error_blend_factor = interp(abs(desired_lateral_accel), [1.0, 2.0], [0.0, 1.0])
    if error_blend_factor > 0.0:  # stronger error response at high lateral acceleration
      torque_from_error = self.nn_model.evaluate([CS.vEgo, setpoint - measurement, lateral_jerk_setpoint - lateral_jerk_measurement, 0.0])
      if sign(error) == sign(torque_from_error) and abs(error) < abs(torque_from_error):
        error = error * (1.0 - error_blend_factor) + torque_from_error * error_blend_factor

    # feedforward
    friction_input = lat_accel_friction_factor * (setpoint - measurement) + self.lat_jerk_friction_factor * lookahead_lateral_jerk
    nn_input = [CS.vEgo, desired_lateral_accel, friction_input, roll] + past_lateral_accels_desired + future_planned_lateral_accels + past_rolls + future_rolls
    ff = self.nn_model.evaluate(nn_input)

    # cars whose model has a weak friction response get the classic friction term on top
    if self.nn_friction_override:
      error += self.torque_from_lateral_accel(0.0, self.torque_params, friction_input, lateral_accel_deadzone,
                                              friction_compensation=True)
    return ff, error
