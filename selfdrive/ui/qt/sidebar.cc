#include "selfdrive/ui/qt/sidebar.h"

#include <algorithm>
#include <cmath>

#include <QMouseEvent>

#include "selfdrive/ui/qt/util.h"

void Sidebar::drawMetric(QPainter &p, const QPair<QString, QString> &label, QColor c, int y) {
  const QRect rect = {30, y, 240, 126};

  p.setPen(Qt::NoPen);
  p.setBrush(QBrush(c));
  p.setClipRect(rect.x() + 4, rect.y(), 18, rect.height(), Qt::ClipOperation::ReplaceClip);
  p.drawRoundedRect(QRect(rect.x() + 4, rect.y() + 4, 100, 118), 18, 18);
  p.setClipping(false);

  QPen pen = QPen(QColor(0xff, 0xff, 0xff, 0x55));
  pen.setWidth(2);
  p.setPen(pen);
  p.setBrush(Qt::NoBrush);
  p.drawRoundedRect(rect, 20, 20);

  p.setPen(QColor(0xff, 0xff, 0xff));
  configFont(p, "Inter", 35, "SemiBold");

  QRect label_rect = getTextRect(p, Qt::AlignCenter, label.first);
  label_rect.setWidth(218);
  label_rect.moveLeft(rect.left() + 22);
  label_rect.moveTop(rect.top() + 19);
  p.drawText(label_rect, Qt::AlignCenter, label.first);

  label_rect.moveTop(rect.top() + 65);
  p.drawText(label_rect, Qt::AlignCenter, label.second);
}

Sidebar::Sidebar(QWidget *parent) : QFrame(parent), onroad(false), flag_pressed(false), settings_pressed(false) {
  home_img = loadPixmap("../assets/images/button_home_optech.png", home_btn.size());  // OPTECH owl (was the carrot bunny)
  flag_img = loadPixmap("../assets/images/button_home_optech.png", home_btn.size());  // OPTECH owl while driving too (was the carrot bunny)
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
  setProperty("wifiAddr", deviceState.getWifiIpAddress().cStr());

  // optech (user 2026-11-26, same as optech-spst f8cfca3): the car battery voltage instead of the comma server
  // connection (not used here). Resting 12 V battery: 12.4 V+ good, 12.0-12.4 V low (yellow), below 12.0 V very low
  // (red); engine running 13.5 V+. C2: boardd sends the panda's voltage_pkt (mV)
  ItemStatus connectStatus = {{"전압", "--"}, good_color};
  if (sm.alive("peripheralState")) {
    const float volt = sm["peripheralState"].getPeripheralState().getVoltage() / 1000.f;
    if (volt > 1.f) {
      const QColor c = volt >= 12.4f ? good_color : (volt >= 12.0f ? warning_color : danger_color);
      connectStatus = {{"전압", QString::number(volt, 'f', 1) + "V"}, c};
    }
  }
  setProperty("connectStatus", QVariant::fromValue(connectStatus));

  // optech (same as optech-spst 73f477a): '온도' with the measured temperature, the hottest of CPU / GPU / memory
  // (what thermald's thermal status uses); bar color as before: good white, middle yellow, high red
  float temp = deviceState.getMemoryTempC();
  for (auto t : deviceState.getCpuTempC()) temp = std::max(temp, t);
  for (auto t : deviceState.getGpuTempC()) temp = std::max(temp, t);
  const QString temp_text = QString("%1°C").arg((int)std::round(temp));
  ItemStatus tempStatus = {{"온도", temp_text}, danger_color};
  auto ts = deviceState.getThermalStatus();
  if (ts == cereal::DeviceState::ThermalStatus::GREEN) {
    tempStatus = {{"온도", temp_text}, good_color};
  } else if (ts == cereal::DeviceState::ThermalStatus::YELLOW) {
    tempStatus = {{"온도", temp_text}, warning_color};
  }
  setProperty("tempStatus", QVariant::fromValue(tempStatus));

  // optech (same as optech-spst 73f477a): vehicle / panda only (GPS is on the driving screen)
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
    p.drawEllipse(x, 196, 27, 27);
    x += 37;
  }

  configFont(p, "Inter", 35, "Regular");
  p.setPen(QColor(0xff, 0xff, 0xff));
  const QRect r = QRect(0, 247, event->rect().width(), 50);
  //p.drawText(r, Qt::AlignCenter, net_type);
  if(net_type == network_type[cereal::DeviceState::NetworkType::WIFI])
    p.drawText(r, Qt::AlignCenter, wifi_addr);
  else
    p.drawText(r, Qt::AlignCenter, net_type);

  // metrics
  drawMetric(p, temp_status.first, temp_status.second, 338);
  drawMetric(p, panda_status.first, panda_status.second, 496);
  drawMetric(p, connect_status.first, connect_status.second, 654);
}
