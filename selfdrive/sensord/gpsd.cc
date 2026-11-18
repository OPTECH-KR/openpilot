// Phone built-in GPS (LePro3 / OnePlus3 msm8996 on EON and C2) through the Android GPS HAL, for pandas without a uBlox.
// Runs only with GpsSource=1 ('GPS 종류: 폰 내장 GPS', process_config.py); ubloxd is disabled then, so this is the
// only publisher of:
//   gpsLocationExternal: same message ubloxd sends, so locationd, the speed camera DB and the UI work unchanged
//   ubloxGnss.measurementReport: satellites seen with cno = HAL snr (dB-Hz), only for the UI GPS summary
// The engine runs only while onroad or while the 'GPS 확인' screen is open (GpsCheck), to save battery.
// Based on commaai/openpilot v0.7.10 selfdrive/sensord/gpsd.cc.
#include <pthread.h>
#include <sys/resource.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <mutex>

#include <hardware/gps.h>

#include "cereal/messaging/messaging.h"
#include "selfdrive/common/params.h"
#include "selfdrive/common/swaglog.h"
#include "selfdrive/common/util.h"

ExitHandler do_exit;

namespace {

PubMaster *pm = nullptr;
std::mutex pm_lock;  // HAL callbacks may come from different HAL threads
const GpsInterface *gps_iface = nullptr;

void send(const char *name, MessageBuilder &msg) {
  std::lock_guard<std::mutex> lk(pm_lock);
  if (pm) pm->send(name, msg);
}

void location_cb(GpsLocation *location) {
  MessageBuilder msg;
  auto loc = msg.initEvent().initGpsLocationExternal();
  const bool has_fix = location->flags & GPS_LOCATION_HAS_LAT_LONG;
  const float speed = (location->flags & GPS_LOCATION_HAS_SPEED) ? location->speed : 0.0f;
  const float bearing = (location->flags & GPS_LOCATION_HAS_BEARING) ? location->bearing : 0.0f;
  const float acc = (location->flags & GPS_LOCATION_HAS_ACCURACY) ? location->accuracy : 100.0f;
  loc.setSource(cereal::GpsLocationData::SensorSource::ANDROID);
  loc.setFlags(has_fix ? 1 : 0);  // bit 0 = valid fix, like ublox NAV-PVT gnssFixOK
  loc.setLatitude(location->latitude);
  loc.setLongitude(location->longitude);
  loc.setAltitude(location->altitude);
  loc.setSpeed(speed);
  loc.setBearingDeg(bearing);
  loc.setAccuracy(acc);
  loc.setUnixTimestampMillis(location->timestamp);
  const float rad = bearing * M_PI / 180.0f;
  float vned[] = {speed * cosf(rad), speed * sinf(rad), 0.0f};
  loc.setVNED(vned);
  // the HAL has no vertical/speed/bearing accuracy: rough values so locationd's sanity checks accept the fix
  loc.setVerticalAccuracy(acc * 1.5f);
  loc.setSpeedAccuracy(1.0f);
  loc.setBearingAccuracyDeg(speed > 2.0f ? 10.0f : 180.0f);
  send("gpsLocationExternal", msg);
}

void sv_status_cb(GpsSvStatus *sv_status) {
  const int num = std::max(0, std::min<int>(sv_status->num_svs, GPS_MAX_SVS));
  MessageBuilder msg;
  auto mr = msg.initEvent().initUbloxGnss().initMeasurementReport();
  mr.setNumMeas(num);
  auto meas = mr.initMeasurements(num);
  for (int i = 0; i < num; i++) {
    meas[i].setSvId(sv_status->sv_list[i].prn);
    meas[i].setCno(std::max(0, std::min(255, (int)lroundf(sv_status->sv_list[i].snr))));
  }
  send("ubloxGnss", msg);
}

void status_cb(GpsStatus *status) { LOGD("gpsd status %d", status->status); }
void nmea_cb(GpsUtcTime, const char *, int) {}
void set_capabilities_cb(uint32_t capabilities) { LOGD("gpsd capabilities %08x", capabilities); }
void acquire_wakelock_cb() {}
void release_wakelock_cb() {}
void request_utc_time_cb() {}

pthread_t create_thread_cb(const char *name, void (*start)(void *), void *arg) {
  LOG("gpsd creating thread: %s", name);
  pthread_t thread;
  pthread_create(&thread, nullptr, (void *(*)(void *))start, arg);
  return thread;
}

GpsCallbacks gps_callbacks = {
  sizeof(GpsCallbacks), location_cb, status_cb, sv_status_cb, nmea_cb, set_capabilities_cb,
  acquire_wakelock_cb, release_wakelock_cb, create_thread_cb, request_utc_time_cb,
};

bool gps_init() {
  hw_module_t *module = nullptr;
  if (hw_get_module(GPS_HARDWARE_MODULE_ID, (hw_module_t const **)&module) != 0 || module == nullptr) {
    LOGE("gpsd: no GPS HAL module");
    return false;
  }
  hw_device_t *device = nullptr;
  module->methods->open(module, GPS_HARDWARE_MODULE_ID, &device);
  if (device == nullptr) {
    LOGE("gpsd: GPS HAL open failed");
    return false;
  }
  gps_device_t *gps_device = (gps_device_t *)device;
  gps_iface = gps_device->get_gps_interface(gps_device);
  if (gps_iface == nullptr || gps_iface->init(&gps_callbacks) != 0) {
    LOGE("gpsd: GPS HAL init failed");
    return false;
  }
  gps_iface->set_position_mode(GPS_POSITION_MODE_STANDALONE, GPS_POSITION_RECURRENCE_PERIODIC, 100, 0, 0);
  return true;
}

}  // namespace

int main() {
  setpriority(PRIO_PROCESS, 0, -13);
  pm = new PubMaster({"gpsLocationExternal", "ubloxGnss"});
  if (!gps_init()) {
    // keep running so manager does not restart it in a loop
    while (!do_exit) util::sleep_for(1000);
    return 0;
  }

  Params params;
  bool running = false;
  while (!do_exit) {
    const bool want = params.getBool("IsOnroad") || params.getBool("GpsCheck");
    if (want && !running) {
      LOGW("gpsd: starting phone GPS");
      gps_iface->start();
      running = true;
    } else if (!want && running) {
      LOGW("gpsd: stopping phone GPS");
      gps_iface->stop();
      running = false;
    }
    util::sleep_for(1000);
  }

  if (running) gps_iface->stop();
  gps_iface->cleanup();
  std::lock_guard<std::mutex> lk(pm_lock);
  delete pm;
  pm = nullptr;
  return 0;
}
