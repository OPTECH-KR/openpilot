#include "selfdrive/ui/qt/sidebar.h"

#include <QMouseEvent>

#include "common/util.h"
#include "selfdrive/ui/qt/util.h"

// dp - for satellite fmin
#include <algorithm>
#include <cmath>

void Sidebar::drawMetric(QPainter &p, const QPair<QString, QString> &label, QColor c, int y) {
  const QRect rect = {30, y, 240, 126};

  p.setPen(Qt::NoPen);
  p.setBrush(QBrush(c));
  p.setClipRect(rect.x() + 4, rect.y(), 18, rect.height(), Qt::ClipOperation::ReplaceClip);
//  p.drawRoundedRect(QRect(rect.x() + 4, rect.y() + 4, 100, 118), 18, 18);
  p.drawRect(QRect(rect.x() + 4, rect.y() + 4, 100, 118));
  p.setClipping(false);

  QPen pen = QPen(QColor(0xff, 0xff, 0xff, 0x55));
  pen.setWidth(2);
  p.setPen(pen);
  p.setBrush(Qt::NoBrush);
//  p.drawRoundedRect(rect, 20, 20);
  p.drawRect(rect);

  p.setPen(QColor(0xff, 0xff, 0xff));
  p.setFont(InterFont(35, QFont::DemiBold));
  p.drawText(rect.adjusted(22, 0, 0, 0), Qt::AlignCenter, label.first + "\n" + label.second);
}

Sidebar::Sidebar(QWidget *parent) : QFrame(parent), onroad(false), flag_pressed(false), settings_pressed(false) {
  home_img = loadPixmap("../assets/images/button_home_optech.png", home_btn.size());  // OPTECH owl
  flag_img = loadPixmap("../assets/images/button_flag.png", home_btn.size());
  settings_img = loadPixmap("../assets/images/button_settings.png", settings_btn.size(), Qt::IgnoreAspectRatio);

  connect(this, &Sidebar::valueChanged, [=] { update(); });

  setAttribute(Qt::WA_OpaquePaintEvent);
  setSizePolicy(QSizePolicy::Fixed, QSizePolicy::Expanding);
  setFixedWidth(300);

  QObject::connect(uiState(), &UIState::uiUpdate, this, &Sidebar::updateState);

  pm = std::make_unique<PubMaster, const std::initializer_list<const char *>>({"userFlag"});
}

void Sidebar::mousePressEvent(QMouseEvent *event) {
  if (onroad && home_btn.contains(event->pos())) {
    flag_pressed = true;
    update();
  } else if (settings_btn.contains(event->pos())) {
    settings_pressed = true;
    update();
  }
}

void Sidebar::mouseReleaseEvent(QMouseEvent *event) {
  if (flag_pressed || settings_pressed) {
    flag_pressed = settings_pressed = false;
    update();
  }
  if (home_btn.contains(event->pos())) {
    MessageBuilder msg;
    msg.initEvent().initUserFlag();
    pm->send("userFlag", msg);
  } else if (settings_btn.contains(event->pos())) {
    emit openSettings();
  }
}

void Sidebar::offroadTransition(bool offroad) {
  onroad = !offroad;
  update();
}

void Sidebar::updateState(const UIState &s) {
  if (!isVisible()) return;

  auto &sm = *(s.sm);

  auto deviceState = sm["deviceState"].getDeviceState();
  setProperty("netType", network_type[deviceState.getNetworkType()]);
  int strength = (int)deviceState.getNetworkStrength();
  setProperty("netStrength", strength > 0 ? strength + 1 : 0);

  // optech (optech-hkg 2026-11-27): the phone battery under the network type, like the driving screen's battery box,
  // only on a device that has one (C2 has none). spst's thermald leaves batteryPercent empty: the kernel's own files,
  // once a second; current_now is negative while charging
  static const bool has_batt = util::read_file("/sys/class/power_supply/battery/present").rfind("1", 0) == 0;
  if (has_batt && sm.frame % UI_FREQ == 0) {
    const int batt = std::atoi(util::read_file("/sys/class/power_supply/battery/capacity").c_str());
    setProperty("battPercent", batt > 0 && batt <= 100 ? batt : 0);
    setProperty("battCharging", std::atoi(util::read_file("/sys/class/power_supply/battery/current_now").c_str()) < 0);
  }

  // optech: the car battery voltage instead of the comma server connection (not used here).
  // Resting 12 V battery: 12.4 V+ good, 12.0-12.4 V low (yellow), below 12.0 V very low (red); engine running 13.5 V+
  ItemStatus connectStatus = {{"전압", "--"}, good_color};
  if (sm.alive("peripheralState")) {
    const float volt = sm["peripheralState"].getPeripheralState().getVoltage() / 1000.f;
    if (volt > 1.f) {
      const QColor c = volt >= 12.4f ? good_color : (volt >= 12.0f ? warning_color : danger_color);
      connectStatus = {{"전압", QString::number(volt, 'f', 1) + "V"}, c};
    }
  }
  setProperty("connectStatus", QVariant::fromValue(connectStatus));

  // optech: '온도' with the measured temperature (the hottest sensor, what the thermal status uses);
  // bar color as before: good white, middle yellow, high red
  float temp = deviceState.getMaxTempC();
  if (temp <= 0) {
    for (auto t : deviceState.getCpuTempC()) temp = std::max(temp, t);
  }
  const QString temp_text = QString("%1°C").arg((int)std::round(temp));
  ItemStatus tempStatus = {{"온도", temp_text}, danger_color};
  auto ts = deviceState.getThermalStatus();
  if (ts == cereal::DeviceState::ThermalStatus::GREEN) {
    tempStatus = {{"온도", temp_text}, good_color};
  } else if (ts == cereal::DeviceState::ThermalStatus::YELLOW) {
    tempStatus = {{"온도", temp_text}, warning_color};
  }
  setProperty("tempStatus", QVariant::fromValue(tempStatus));

  // optech: vehicle / panda only (GPS goes to the driving screen)
  ItemStatus pandaStatus = {{tr("VEHICLE"), tr("ONLINE")}, good_color};
  if (s.scene.pandaType == cereal::PandaState::PandaType::UNKNOWN) {
    pandaStatus = {{tr("NO"), tr("PANDA")}, danger_color};
  }
  setProperty("pandaStatus", QVariant::fromValue(pandaStatus));
}

void Sidebar::paintEvent(QPaintEvent *event) {
  QPainter p(this);
  p.setPen(Qt::NoPen);
  p.setRenderHint(QPainter::Antialiasing);

  p.fillRect(rect(), QColor(57, 57, 57));

  // buttons
  p.setOpacity(settings_pressed ? 0.65 : 1.0);
  p.drawPixmap(settings_btn.x(), settings_btn.y(), settings_img);
  p.setOpacity(onroad && flag_pressed ? 0.65 : 1.0);
  p.drawPixmap(home_btn.x(), home_btn.y(), onroad ? flag_img : home_img);
  p.setOpacity(1.0);

  // network
  int x = 58;
  const QColor gray(0x54, 0x54, 0x54);
  for (int i = 0; i < 5; ++i) {
    p.setBrush(i < net_strength ? Qt::white : gray);
    p.drawRect(x, 196, 27, 27);
//    p.drawEllipse(x, 196, 27, 27);
    x += 37;
  }

  p.setFont(InterFont(35));
  p.setPen(QColor(0xff, 0xff, 0xff));
  const QRect r = QRect(50, 247, 100, 50);
  p.drawText(r, Qt::AlignCenter, net_type);

  // optech (optech-hkg 2026-11-27): phone battery under the network type - a battery picture filled to the level
  // (green, orange under 30 %, red under 15 %, a yellow bolt while charging) and the %; the metrics move 50 down to
  // make room (they still end above the home button)
  int my = 0;
  if (batt_percent > 0) {
    my = 50;
    const int bw = 62, bh = 30, nub = 6, by = 307, gap = 14;
    p.setFont(InterFont(33, QFont::DemiBold));
    const QString t = QString("%1%").arg(batt_percent);
    const int tw = p.fontMetrics().boundingRect(t).width();
    const int bx = (width() - (bw + nub + gap + tw)) / 2;
    const QColor level = batt_percent < 15 ? QColor(226, 75, 74) : batt_percent < 30 ? QColor(245, 160, 50) : QColor(120, 220, 90);
    p.setPen(QPen(Qt::white, 3));
    p.setBrush(Qt::NoBrush);
    p.drawRoundedRect(QRect(bx, by, bw, bh), 6, 6);
    p.setPen(Qt::NoPen);
    p.setBrush(Qt::white);
    p.drawRect(QRect(bx + bw + 1, by + bh / 2 - 6, nub, 12));
    p.setBrush(level);
    p.drawRoundedRect(QRect(bx + 5, by + 5, std::max(2, (bw - 10) * batt_percent / 100), bh - 10), 3, 3);
    if (batt_charging) {
      const int cx = bx + bw / 2, cy = by + bh / 2;
      const QPoint bolt[] = {{cx + 4, cy - 12}, {cx - 8, cy + 2}, {cx - 1, cy + 2}, {cx - 4, cy + 12},
                             {cx + 8, cy - 2}, {cx + 1, cy - 2}};
      p.setPen(QPen(QColor(40, 40, 40), 2));
      p.setBrush(QColor(255, 214, 0));
      p.drawPolygon(bolt, 6);
      p.setPen(Qt::NoPen);
    }
    p.setPen(Qt::white);
    p.drawText(QRect(bx + bw + nub + gap, by - 10, tw + 6, bh + 20), Qt::AlignLeft | Qt::AlignVCenter, t);
  }

  // metrics
  drawMetric(p, temp_status.first, temp_status.second, 338 + my);
  drawMetric(p, panda_status.first, panda_status.second, 496 + my);
  drawMetric(p, connect_status.first, connect_status.second, 654 + my);
}
