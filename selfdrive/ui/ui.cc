#include "selfdrive/ui/ui.h"

#include <algorithm>
#include <cassert>
#include <cmath>
#include <functional>
#include <vector>

#include <QtConcurrent>

#include "common/transformations/orientation.hpp"
#include "common/params.h"
#include "common/swaglog.h"
#include "common/util.h"
#include "common/watchdog.h"
#include "system/hardware/hw.h"

#define BACKLIGHT_DT 0.05
#define BACKLIGHT_TS 10.00

// Projects a point in car to space to the corresponding point in full frame
// image space.
static bool calib_frame_to_full_frame(const UIState *s, float in_x, float in_y, float in_z, QPointF *out) {
  const float margin = 500.0f;
  const QRectF clip_region{-margin, -margin, s->fb_w + 2 * margin, s->fb_h + 2 * margin};

  const vec3 pt = (vec3){{in_x, in_y, in_z}};
  const vec3 Ep = matvecmul3(s->scene.wide_cam ? s->scene.view_from_wide_calib : s->scene.view_from_calib, pt);
  const vec3 KEp = matvecmul3(s->scene.wide_cam ? ECAM_INTRINSIC_MATRIX : FCAM_INTRINSIC_MATRIX, Ep);

  // Project.
  QPointF point = s->car_space_transform.map(QPointF{KEp.v[0] / KEp.v[2], KEp.v[1] / KEp.v[2]});
  if (clip_region.contains(point)) {
    *out = point;
    return true;
  }
  return false;
}

int get_path_length_idx(const cereal::XYZTData::Reader &line, const float path_height) {
  const auto line_x = line.getX();
  int max_idx = 0;
  for (int i = 1; i < TRAJECTORY_SIZE && line_x[i] <= path_height; ++i) {
    max_idx = i;
  }
  return max_idx;
}

void update_leads(UIState *s, const cereal::RadarState::Reader &radar_state, const cereal::XYZTData::Reader &line) {
  for (int i = 0; i < 2; ++i) {
    auto lead_data = (i == 0) ? radar_state.getLeadOne() : radar_state.getLeadTwo();
    if (lead_data.getStatus()) {
      float z = line.getZ()[get_path_length_idx(line, lead_data.getDRel())];
      calib_frame_to_full_frame(s, lead_data.getDRel(), -lead_data.getYRel(), z + 1.22, &s->scene.lead_vertices[i]);
    }
  }
}

void update_line_data(const UIState *s, const cereal::XYZTData::Reader &line,
                      float y_off, float z_off, QPolygonF *pvd, int max_idx, bool allow_invert=true) {
  const auto line_x = line.getX(), line_y = line.getY(), line_z = line.getZ();
  QPolygonF left_points, right_points;
  left_points.reserve(max_idx + 1);
  right_points.reserve(max_idx + 1);

  for (int i = 0; i <= max_idx; i++) {
    // highly negative x positions  are drawn above the frame and cause flickering, clip to zy plane of camera
    if (line_x[i] < 0) continue;
    QPointF left, right;
    bool l = calib_frame_to_full_frame(s, line_x[i], line_y[i] - y_off, line_z[i] + z_off, &left);
    bool r = calib_frame_to_full_frame(s, line_x[i], line_y[i] + y_off, line_z[i] + z_off, &right);
    if (l && r) {
      // For wider lines the drawn polygon will "invert" when going over a hill and cause artifacts
      if (!allow_invert && left_points.size() && left.y() > left_points.back().y()) {
        continue;
      }
      left_points.push_back(left);
      right_points.push_front(right);
    }
  }
  *pvd = left_points + right_points;
}

void update_model(UIState *s,
                  const cereal::ModelDataV2::Reader &model,
                  const cereal::UiPlan::Reader &plan) {
  UIScene &scene = s->scene;
  auto plan_position = plan.getPosition();
  if (plan_position.getX().size() < TRAJECTORY_SIZE){
    plan_position = model.getPosition();
  }
  float max_distance = std::clamp(plan_position.getX()[TRAJECTORY_SIZE - 1],
                                  MIN_DRAW_DISTANCE, MAX_DRAW_DISTANCE);

  // update lane lines
  const auto lane_lines = model.getLaneLines();
  const auto lane_line_probs = model.getLaneLineProbs();
  int max_idx = get_path_length_idx(lane_lines[0], max_distance);
  for (int i = 0; i < std::size(scene.lane_line_vertices); i++) {
    scene.lane_line_probs[i] = lane_line_probs[i];
    update_line_data(s, lane_lines[i], 0.025 * scene.lane_line_probs[i], 0, &scene.lane_line_vertices[i], max_idx);
  }

  // update road edges
  const auto road_edges = model.getRoadEdges();
  const auto road_edge_stds = model.getRoadEdgeStds();
  for (int i = 0; i < std::size(scene.road_edge_vertices); i++) {
    scene.road_edge_stds[i] = road_edge_stds[i];
    update_line_data(s, road_edges[i], 0.025, 0, &scene.road_edge_vertices[i], max_idx);
  }

  // update path
  auto lead_one = (*s->sm)["radarState"].getRadarState().getLeadOne();
  if (lead_one.getStatus()) {
    const float lead_d = lead_one.getDRel() * 2.;
    max_distance = std::clamp((float)(lead_d - fmin(lead_d * 0.35, 10.)), 0.0f, max_distance);
  }
  max_idx = get_path_length_idx(plan_position, max_distance);
  update_line_data(s, plan_position, 0.9, 1.22, &scene.track_vertices, max_idx, false);
}
#ifndef QCOM
void update_dmonitoring(UIState *s, const cereal::DriverStateV2::Reader &driverstate, float dm_fade_state, bool is_rhd) {
  UIScene &scene = s->scene;
  const auto driver_orient = is_rhd ? driverstate.getRightDriverData().getFaceOrientation() : driverstate.getLeftDriverData().getFaceOrientation();
  for (int i = 0; i < std::size(scene.driver_pose_vals); i++) {
    float v_this = (i == 0 ? (driver_orient[i] < 0 ? 0.7 : 0.9) : 0.4) * driver_orient[i];
    scene.driver_pose_diff[i] = fabs(scene.driver_pose_vals[i] - v_this);
    scene.driver_pose_vals[i] = 0.8 * v_this + (1 - 0.8) * scene.driver_pose_vals[i];
    scene.driver_pose_sins[i] = sinf(scene.driver_pose_vals[i]*(1.0-dm_fade_state));
    scene.driver_pose_coss[i] = cosf(scene.driver_pose_vals[i]*(1.0-dm_fade_state));
  }

  const mat3 r_xyz = (mat3){{
    scene.driver_pose_coss[1]*scene.driver_pose_coss[2],
    scene.driver_pose_coss[1]*scene.driver_pose_sins[2],
    -scene.driver_pose_sins[1],

    -scene.driver_pose_sins[0]*scene.driver_pose_sins[1]*scene.driver_pose_coss[2] - scene.driver_pose_coss[0]*scene.driver_pose_sins[2],
    -scene.driver_pose_sins[0]*scene.driver_pose_sins[1]*scene.driver_pose_sins[2] + scene.driver_pose_coss[0]*scene.driver_pose_coss[2],
    -scene.driver_pose_sins[0]*scene.driver_pose_coss[1],

    scene.driver_pose_coss[0]*scene.driver_pose_sins[1]*scene.driver_pose_coss[2] - scene.driver_pose_sins[0]*scene.driver_pose_sins[2],
    scene.driver_pose_coss[0]*scene.driver_pose_sins[1]*scene.driver_pose_sins[2] + scene.driver_pose_sins[0]*scene.driver_pose_coss[2],
    scene.driver_pose_coss[0]*scene.driver_pose_coss[1],
  }};

  // transform vertices
  for (int kpi = 0; kpi < std::size(default_face_kpts_3d); kpi++) {
    vec3 kpt_this = default_face_kpts_3d[kpi];
    kpt_this = matvecmul3(r_xyz, kpt_this);
    scene.face_kpts_draw[kpi] = (vec3){{(float)kpt_this.v[0], (float)kpt_this.v[1], (float)(kpt_this.v[2] * (1.0-dm_fade_state) + 8 * dm_fade_state)}};
  }
}
#endif
static void update_sockets(UIState *s) {
  s->sm->update(0);
}

// optech 주행 화면 'GPS 상태' (optech-hkg update_gps): satellites, strong ones and the mean of the 4 best signals
static void update_gps(const SubMaster &sm, UIScene &scene) {
  if (!sm.alive("ubloxGnss")) {
    scene.gps_sats = scene.gps_strong = scene.gps_cno = 0;
    scene.gps_antenna_bad = false;
    return;
  }
  if (!sm.updated("ubloxGnss")) return;
  const auto gnss = sm["ubloxGnss"].getUbloxGnss();
  if (gnss.which() == cereal::UbloxGnss::MEASUREMENT_REPORT) {
    std::vector<int> cnos;
    for (const auto &meas : gnss.getMeasurementReport().getMeasurements()) {
      if (meas.getCno() > 0) cnos.push_back(meas.getCno());
    }
    std::sort(cnos.begin(), cnos.end(), std::greater<int>());
    const int top = std::min<int>(4, cnos.size());
    int sum = 0;
    for (int i = 0; i < top; i++) sum += cnos[i];
    scene.gps_sats = cnos.size();
    scene.gps_strong = std::count_if(cnos.begin(), cnos.end(), [](int c) { return c >= 30; });
    scene.gps_cno = top > 0 ? sum / top : 0;
  } else if (gnss.which() == cereal::UbloxGnss::HW_STATUS) {
    const auto ant = gnss.getHwStatus().getAStatus();
    scene.gps_antenna_bad = ant == cereal::UbloxGnss::HwStatus::AntennaSupervisorState::SHORT ||
                            ant == cereal::UbloxGnss::HwStatus::AntennaSupervisorState::OPEN;
  }
}

// optech 주행 화면 '레이더 물체' (optech-hkg ui_draw_radar_info): every radar track on the screen with its own speed
static void update_radar_points(UIState *s) {
  const SubMaster &sm = *(s->sm);
  UIScene &scene = s->scene;
  scene.radar_points.clear();
  if (!sm.alive("liveTracks")) return;
  const auto line = sm["modelV2"].getModelV2().getPosition();
  const float v_ego = sm["carState"].getCarState().getVEgo();
  for (const auto &t : sm["liveTracks"].getLiveTracks()) {
    const float d = t.getDRel();
    if (d < 2.f || d > 150.f) continue;
    float z = 0.f;
    if (line.getX().size() > 0) z = line.getZ()[get_path_length_idx(line, d)];
    QPointF pt;
    if (!calib_frame_to_full_frame(s, d, -t.getYRel(), z + 1.22, &pt)) continue;
    const float v = v_ego + t.getVRel();
    const int kind = v < -1.f ? 1 : std::abs(v) < 1.f ? 2 : 0;
    scene.radar_points.push_back({pt, v, t.getYRel(), kind});
  }
}

static void update_state(UIState *s) {
  SubMaster &sm = *(s->sm);
  UIScene &scene = s->scene;

  update_gps(sm, scene);
  if (sm.updated("liveTracks")) update_radar_points(s);
  if (sm.updated("controlsStateExt")) {
    const auto ext = sm["controlsStateExt"].getControlsStateExt();
    scene.tpms[0] = ext.getTpmsFl(); scene.tpms[1] = ext.getTpmsFr();
    scene.tpms[2] = ext.getTpmsRl(); scene.tpms[3] = ext.getTpmsRr();
    scene.traffic_state = ext.getTrafficState();
  }

  if (sm.updated("liveCalibration")) {
    auto live_calib = sm["liveCalibration"].getLiveCalibration();
    auto rpy_list = live_calib.getRpyCalib();
    auto wfde_list = live_calib.getWideFromDeviceEuler();
    Eigen::Vector3d rpy;
    Eigen::Vector3d wfde;
    if (rpy_list.size() == 3) rpy << rpy_list[0], rpy_list[1], rpy_list[2];
    if (wfde_list.size() == 3) wfde << wfde_list[0], wfde_list[1], wfde_list[2];
    Eigen::Matrix3d device_from_calib = euler2rot(rpy);
    #ifndef QCOM
    Eigen::Matrix3d wide_from_device = euler2rot(wfde);
    #endif
    Eigen::Matrix3d view_from_device;
    view_from_device << 0,1,0,
                        0,0,1,
                        1,0,0;
    Eigen::Matrix3d view_from_calib = view_from_device * device_from_calib;
    #ifndef QCOM
    Eigen::Matrix3d view_from_wide_calib = view_from_device * wide_from_device * device_from_calib;
    #endif
    for (int i = 0; i < 3; i++) {
      for (int j = 0; j < 3; j++) {
        scene.view_from_calib.v[i*3 + j] = view_from_calib(i,j);
        #ifndef QCOM
        scene.view_from_wide_calib.v[i*3 + j] = view_from_wide_calib(i,j);
        #endif
      }
    }
    scene.calibration_valid = live_calib.getCalStatus() == cereal::LiveCalibrationData::Status::CALIBRATED;
    #ifndef QCOM
    scene.calibration_wide_valid = wfde_list.size() == 3;
    #endif
  }
  if (sm.updated("pandaStates")) {
    auto pandaStates = sm["pandaStates"].getPandaStates();
    if (pandaStates.size() > 0) {
      scene.pandaType = pandaStates[0].getPandaType();

      if (scene.pandaType != cereal::PandaState::PandaType::UNKNOWN) {
        scene.ignition = false;
        for (const auto& pandaState : pandaStates) {
          scene.ignition |= pandaState.getIgnitionLine() || pandaState.getIgnitionCan();
        }
      }
    }
  } else if ((s->sm->frame - s->sm->rcv_frame("pandaStates")) > 5*UI_FREQ) {
    scene.pandaType = cereal::PandaState::PandaType::UNKNOWN;
  }
  if (sm.updated("carParams")) {
    scene.longitudinal_control = sm["carParams"].getCarParams().getOpenpilotLongitudinalControl();
  }
  #ifndef QCOM
  if (sm.updated("wideRoadCameraState")) {
    auto cam_state = sm["wideRoadCameraState"].getWideRoadCameraState();
    float scale = (cam_state.getSensor() == cereal::FrameData::ImageSensor::AR0231) ? 6.0f : 1.0f;
    scene.light_sensor = std::max(100.0f - scale * cam_state.getExposureValPercent(), 0.0f);
  }
  #else
  if (!scene.started && sm.updated("sensorEvents")) {
    for (auto sensor : sm["sensorEvents"].getSensorEvents()) {
      if (sensor.which() == cereal::SensorEventData::ACCELERATION) {
        auto accel = sensor.getAcceleration().getV();
        if (accel.totalSize().wordCount) { // TODO: sometimes empty lists are received. Figure out why
          scene.accel_sensor = accel[2];
        }
      } else if (sensor.which() == cereal::SensorEventData::GYRO_UNCALIBRATED) {
        auto gyro = sensor.getGyroUncalibrated().getV();
        if (gyro.totalSize().wordCount) {
          scene.gyro_sensor = gyro[1];
        }
      }
    }
  }
  if (sm.updated("roadCameraState")) {
    auto camera_state = sm["roadCameraState"].getRoadCameraState();

    float max_lines = 5408;
    float max_gain = 1.0;
    float max_ev = max_lines * max_gain;

    float ev = camera_state.getGain() * float(camera_state.getIntegLines());

    // Scale to 0% to 100%
    scene.light_sensor = 100.0 * std::clamp<float>(1.0 - (ev / max_ev), 0.0, 1.0);
  }
  #endif
  scene.started = sm["deviceState"].getDeviceState().getStarted() && scene.ignition;
  scene.lat_active = sm["carControl"].getCarControl().getLatActive();
  scene.alka_active = sm["controlsStateExt"].getControlsStateExt().getAlkaActive();
  scene.alka_enabled = sm["controlsStateExt"].getControlsStateExt().getAlkaEnabled();
  if (scene.started && sm.updated("carControl")) {
    auto car_control = sm["carControl"].getCarControl();
    if (car_control.getLongActive()) {
      scene.dpAccel = car_control.getActuatorsOutput().getAccel();
    } else {
      scene.dpAccel = 0.0;
    }
  }
}

void ui_update_params(UIState *s) {
  auto params = Params();
  s->scene.is_metric = params.getBool("IsMetric");
  s->scene.map_on_left = params.getBool("NavSettingLeftSide");
  s->scene.dp_long_personality_btn = params.getBool("dp_long_personality_btn");
  s->scene.dp_long_accel_btn = params.getBool("dp_long_accel_btn");
}

void UIState::updateStatus() {
  if (scene.started && sm->updated("controlsState")) {
    auto controls_state = (*sm)["controlsState"].getControlsState();
    auto state = controls_state.getState();
    if (state == cereal::ControlsState::OpenpilotState::PRE_ENABLED || state == cereal::ControlsState::OpenpilotState::OVERRIDING) {
      status = STATUS_OVERRIDE;
    } else {
      status = controls_state.getEnabled() ? STATUS_ENGAGED : STATUS_DISENGAGED;
    }
  }

  // Handle onroad/offroad transition
  if (scene.started != started_prev || sm->frame == 1) {
    if (scene.started) {
      status = STATUS_DISENGAGED;
      scene.started_frame = sm->frame;
    }
    started_prev = scene.started;
    emit offroadTransition(!scene.started);
  }
}

UIState::UIState(QObject *parent) : QObject(parent) {
  sm = std::make_unique<SubMaster, const std::initializer_list<const char *>>({
    "modelV2", "controlsState", "liveCalibration", "radarState", "deviceState", "roadCameraState",
    "pandaStates", "carParams", "driverMonitoringState", "carState", "liveLocationKalman", "driverStateV2",
    "wideRoadCameraState", "managerState", "navInstruction", "navRoute", "uiPlan",
    // legacy - eon/c2, for touch
    "sensorEvents",
    // dp - for alka detection
    "carControl", "controlsStateExt",
    // dp - for mapd
    "liveMapData",
    // dp - for lane priority mode
    "lateralPlan",
    // dp - for e2e/acc detection
    "longitudinalPlanExt",
    // dp - for gps accuracy in sidebar
    "gpsLocationExternal",
    // optech - speed camera ahead
    "optechSpeedCam",
    // optech - car battery voltage in the sidebar
    "peripheralState",
    // optech 주행 화면 (optech-hkg): navigation app link, radar objects, GPS satellites
    "roadLimitSpeed", "liveTracks", "ubloxGnss",
  });

  Params params;
  prime_type = std::atoi(params.get("PrimeType").c_str());
  language = QString::fromStdString(params.get("LanguageSetting"));

  // update timer
  timer = new QTimer(this);
  QObject::connect(timer, &QTimer::timeout, this, &UIState::update);
  timer->start(1000 / UI_FREQ);
}

void UIState::update() {
  update_sockets(this);
  update_state(this);
  updateStatus();

  if (sm->frame % UI_FREQ == 0) {
    watchdog_kick(nanos_since_boot());
    // optech 화면 탭 (optech-hkg): read once a second, also while the car is off
    Params params;
    const std::string keep = params.get("OptechSettingsTimeout");
    settings_timeout_s = keep.empty() ? 180 : std::atoi(keep.c_str());
    drive_dim = std::atoi(params.get("OptechDriveDim").c_str());
  }
  emit uiUpdate(*this);
}

void UIState::setPrimeType(int type) {
  if (type != prime_type) {
    prime_type = type;
    Params().put("PrimeType", std::to_string(prime_type));
    emit primeTypeChanged(prime_type);
  }
}

Device::Device(QObject *parent) : brightness_filter(BACKLIGHT_OFFROAD, BACKLIGHT_TS, BACKLIGHT_DT), QObject(parent) {
  setAwake(true);
  resetInteractiveTimeout();

  QObject::connect(uiState(), &UIState::uiUpdate, this, &Device::update);
}

void Device::update(const UIState &s) {
  if (idle_frames < 1000000) idle_frames++;
  updateBrightness(s);
  updateWakefulness(s);
}

void Device::setAwake(bool on) {
  if (on != awake) {
    awake = on;
    Hardware::set_display_power(awake);
    LOGD("setting display power %d", awake);
    emit displayPowerChanged(awake);
  }
}

// optech '화면 유지 시간' (화면 탭, optech-hkg): untouched, the settings window stays open and the screen stays on with
// the car off this long (-1 '항상': never). A value not in the menu (0) counts as 3 minutes
static int keepSeconds() {
  const int s = uiState()->settings_timeout_s;
  return s == 0 ? 180 : s;
}

bool Device::keepApplies() const {
  return settings_open || !ignition_on;
}

void Device::resetInteractiveTimeout(int timeout) {
  idle_frames = 0;  // '주행 중 밝기': a touch brings the brightness back
  if (timeout == -1) {
    const int keep_s = keepSeconds();
    timeout = (keep_s > 0 && keepApplies()) ? keep_s : (ignition_on ? 10 : 30);
  }
  interactive_timeout = timeout * UI_FREQ;
}

void Device::updateBrightness(const UIState &s) {
  float clipped_brightness = offroad_brightness;
  if (s.scene.started) {
    clipped_brightness = s.scene.light_sensor;

    // CIE 1931 - https://www.photonstophotos.net/GeneralTopics/Exposure/Psychometric_Lightness_and_Gamma.htm
    if (clipped_brightness <= 8) {
      clipped_brightness = (clipped_brightness / 903.3);
    } else {
      clipped_brightness = std::pow((clipped_brightness + 16.0) / 116.0, 3.0);
    }

    // Scale back to 10% to 100%
    clipped_brightness = std::clamp(100.0f * clipped_brightness, 10.0f, 100.0f);
  }

  // optech '주행 중 밝기' (화면 탭, optech-hkg): while driving, after 30 s without a touch fade down to this %
  // (never brighter than the auto brightness). A touch or a warning brings it back at once
  const auto cs = (*s.sm)["controlsState"].getControlsState();
  const bool alerting = cs.getAlertSize() != cereal::ControlsState::AlertSize::NONE &&
                        cs.getAlertStatus() != cereal::ControlsState::AlertStatus::NORMAL;
  const bool want_dim = s.scene.started && s.drive_dim > 0 && idle_frames >= 30 * UI_FREQ && !alerting;
  if (want_dim) {
    clipped_brightness = std::min(clipped_brightness, (float)s.drive_dim);
  } else if (dimmed) {
    brightness_filter.reset(clipped_brightness);
  }
  dimmed = want_dim;

  int brightness = brightness_filter.update(clipped_brightness);
  if (!awake) {
    brightness = 0;
  }

  if (brightness != last_brightness) {
    if (!brightness_future.isRunning()) {
      brightness_future = QtConcurrent::run(Hardware::set_brightness, brightness);
      last_brightness = brightness;
    }
  }
}
#ifdef QCOM
bool Device::motionTriggered(const UIState &s) {
  static float accel_prev = 0;
  static float gyro_prev = 0;

  bool accel_trigger = abs(s.scene.accel_sensor - accel_prev) > 0.2;
  bool gyro_trigger = abs(s.scene.gyro_sensor - gyro_prev) > 0.15;

  gyro_prev = s.scene.gyro_sensor;
  accel_prev = (accel_prev * (accel_samples - 1) + s.scene.accel_sensor) / accel_samples;

  return (!awake && accel_trigger && gyro_trigger);
}
#endif

void Device::updateWakefulness(const UIState &s) {
  bool ignition_just_turned_off = !s.scene.ignition && ignition_on;
  ignition_on = s.scene.ignition;

  #ifdef QCOM
  if (ignition_just_turned_off || motionTriggered(s)) {
  #else
  if (ignition_just_turned_off) {
  #endif
    resetInteractiveTimeout();
  } else if (keepSeconds() < 0 && keepApplies()) {
    // '화면 유지 시간: 항상': never time out (and do not fire interactiveTimeout, which closes the settings window)
    if (interactive_timeout <= 0) interactive_timeout = 1;
  } else if (interactive_timeout > 0 && --interactive_timeout == 0) {
    emit interactiveTimeout();
  }

  setAwake(s.scene.ignition || interactive_timeout > 0);
}

UIState *uiState() {
  static UIState ui_state;
  return &ui_state;
}

Device *device() {
  static Device _device;
  return &_device;
}
