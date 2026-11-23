#include "selfdrive/ui/qt/screenrecorder/screenrecorder.h"

#include <sys/stat.h>
#include <sys/time.h>

#include <cstdio>
#include <cstdlib>
#include <ctime>

#include <QPainter>
#include <QUrl>

#include "selfdrive/ui/ui.h"

static const char *VIDEOS_DIR = "/storage/emulated/0/videos";
static const long long SEGMENT_MS = 3 * 60 * 1000;  // screenrecord stops by itself at 3 minutes

static long long now_ms() {
  struct timeval tv;
  gettimeofday(&tv, nullptr);
  return (long long)tv.tv_sec * 1000 + tv.tv_usec / 1000;
}

ScreenRecorder::ScreenRecorder(QWidget *parent) : QPushButton(parent) {
  const int size = 140;  // as wide as the '차량 주의' mark it sits under
  setFixedSize(size, size);
  setFocusPolicy(Qt::NoFocus);
  QObject::connect(this, &QPushButton::released, this, &ScreenRecorder::toggle);
  sound_start.setSource(QUrl::fromLocalFile("../assets/sounds/start_record.wav"));
  sound_stop.setSource(QUrl::fromLocalFile("../assets/sounds/stop_record.wav"));
  sound_start.setVolume(0.5f);
  sound_stop.setVolume(0.5f);
}

ScreenRecorder::~ScreenRecorder() {
  stop(false);
}

void ScreenRecorder::paintEvent(QPaintEvent *event) {
  QRect r = QRect(0, 0, width(), height()) - QMargins(4, 4, 4, 4);
  QPainter p(this);
  p.setRenderHint(QPainter::Antialiasing);
  p.setPen(QPen(QColor(255, 255, 255, 80), 6));
  p.setBrush(recording ? (blink_on ? QColor(255, 0, 0, 160) : QColor(255, 0, 0, 90)) : QColor(0, 0, 0, 70));
  p.drawEllipse(r);
  QFont f = p.font();
  f.setPixelSize(48);
  f.setBold(true);
  p.setFont(f);
  p.setPen(QColor(255, 255, 255, 220));
  p.drawText(r, Qt::AlignCenter, "REC");
}

void ScreenRecorder::toggle() {
  if (!recording) start(true);
  else stop(true);
}

void ScreenRecorder::start(bool sound) {
  if (recording) return;
  char filename[64];
  time_t t = time(nullptr);
  struct tm tm = *localtime(&t);
  snprintf(filename, sizeof(filename), "%04d%02d%02d-%02d%02d%02d.mp4", tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday,
           tm.tm_hour, tm.tm_min, tm.tm_sec);
  struct stat st = {};
  if (stat(VIDEOS_DIR, &st) == -1) mkdir(VIDEOS_DIR, 0700);
  char cmd[192];
  snprintf(cmd, sizeof(cmd), "screenrecord --size 1280x720 --bit-rate 2000000 %s/%s &", VIDEOS_DIR, filename);
  if (system(cmd) != 0) {}
  recording = true;
  frame = 0;
  started = now_ms();
  update();
  if (sound) sound_start.play();
}

void ScreenRecorder::stop(bool sound) {
  if (!recording) return;
  recording = false;
  if (system("killall -SIGINT screenrecord") != 0) {}
  update();
  if (sound) sound_stop.play();
}

void ScreenRecorder::updateScreen() {
  if (!recording) return;
  if (now_ms() - started > SEGMENT_MS) {
    stop(false);
    start(false);
    return;
  }
  if (frame % (UI_FREQ / 2) == 0) {
    blink_on = (frame % UI_FREQ) < (UI_FREQ / 2);
    update();
  }
  frame++;
}
