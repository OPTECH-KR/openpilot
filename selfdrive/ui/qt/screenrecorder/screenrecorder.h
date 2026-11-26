#pragma once

#include <QPushButton>
#include <QSoundEffect>

// optech 화면 > '녹화 버튼' (optech-hkg / neokii screen recorder, C2 path): a round REC button on the driving screen.
// Recording uses Android's own `screenrecord` (1280x720, 2 Mbps) into /storage/emulated/0/videos, in 3 minute files.
class ScreenRecorder : public QPushButton {
  Q_OBJECT

public:
  explicit ScreenRecorder(QWidget *parent = nullptr);
  ~ScreenRecorder() override;

  void start(bool sound);
  void stop(bool sound);
  void toggle();
  void updateScreen();  // call at UI_FREQ: blinks while recording and starts the next 3 minute file

protected:
  void paintEvent(QPaintEvent *event) override;

private:
  bool recording = false;
  long long started = 0;
  int frame = 0;
  bool blink_on = false;
  QSoundEffect sound_start, sound_stop;
};
