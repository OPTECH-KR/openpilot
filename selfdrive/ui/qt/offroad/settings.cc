#include "selfdrive/ui/qt/offroad/settings.h"

#include <cassert>
#include <cmath>
#include <string>

#include <QDebug>

#ifndef QCOM
#include "selfdrive/ui/qt/offroad/networking.h"
#endif

#ifdef ENABLE_MAPS
#include "selfdrive/ui/qt/maps/map_settings.h"
#endif

#include "selfdrive/common/params.h"
#include "selfdrive/common/watchdog.h"
#include "selfdrive/common/util.h"
#include "selfdrive/hardware/hw.h"
#include "selfdrive/ui/qt/widgets/controls.h"
#include "selfdrive/ui/qt/widgets/input.h"
#include "selfdrive/ui/qt/widgets/scrollview.h"
#include "selfdrive/ui/qt/widgets/ssh_keys.h"
#include "selfdrive/ui/qt/widgets/toggle.h"
#include "selfdrive/ui/ui.h"
#include "selfdrive/ui/qt/util.h"
#include "selfdrive/ui/qt/qt_window.h"
#include "selfdrive/ui/qt/widgets/input.h"

#include <QComboBox>
#include <QAbstractItemView>
#include <QScroller>
#include <QListView>
#include <QListWidget>

#include <QProcess> // opkr
#include <QDateTime> // opkr
#include <QTimer> // opkr
#include <QFileInfo> // opkr
#include <QDir>
#include <QElapsedTimer>
#include <QLabel>

TogglesPanel::TogglesPanel(SettingsWindow *parent) : ListWidget(parent) {
  // param, title, desc, icon, confirm
  std::vector<std::tuple<QString, QString, QString, QString>> toggle_defs{
    {
      "OpenpilotEnabledToggle",
      tr("Enable openpilot"),
      tr("Use the openpilot system for adaptive cruise control and lane keep driver assistance. Your attention is required at all times to use this feature. Changing this setting takes effect when the car is powered off."),
      "../assets/offroad/icon_openpilot.png",
    },
    {
      "ExperimentalMode",
      tr("Experimental Mode"),
      "",
      "../assets/img_experimental_white.svg",
    },
    {
      "ExperimentalLongitudinalEnabled",
      tr("openpilot 가감속 제어 (알파)"),
      QString("<b>%1</b><br><br>%2")
      .arg(tr("경고: 이 차의 openpilot 가감속 제어는 알파 단계이며, 자동 긴급 제동(AEB)이 꺼집니다."))
      .arg(tr("이 차에서는 openpilot이 기본적으로 차의 순정 ACC를 사용합니다. 켜면 openpilot 가감속 제어로 바뀝니다. openpilot 가감속 제어(알파)를 켤 때는 실험 모드도 켜는 것을 권장합니다.")),
      "../assets/offroad/icon_speed_limit.png",
    },
    {
      "SccConnectedBus2",
      "롱컨 (Long Control)",
      "롱컨 작업을 마치셨으면 켜 주세요.",
      "../assets/offroad/icon_warning.png",
    },
    {
      "EnableRadarTracks",
      "레이더 트랙 사용",
      "SCC 데이터 대신 레이더 트랙을 사용합니다. (산타페 2022 HEV)",
      "../assets/offroad/icon_warning.png",
    },
    {
      "IsLdwEnabled",
      tr("Enable Lane Departure Warnings"),
      tr("Receive alerts to steer back into the lane when your vehicle drifts over a detected lane line without a turn signal activated while driving over 31 mph (50 km/h)."),
      "../assets/offroad/icon_warning.png",
    },
    {
      "IsMetric",
      tr("Use Metric System"),
      tr("Display speed in km/h instead of mph."),
      "../assets/offroad/icon_metric.png",
    },
    {
      "RecordFront",
      tr("Record and Upload Driver Camera"),
      tr("Upload data from the driver facing camera and help improve the driver monitoring algorithm."),
      "../assets/offroad/icon_monitoring.png",
    },
#ifdef ENABLE_MAPS
    {
      "NavSettingTime24h",
      tr("Show ETA in 24h Format"),
      tr("Use 24h format instead of am/pm"),
      "../assets/offroad/icon_metric.png",
    },
    {
      "NavSettingLeftSide",
      tr("Show Map on Left Side of UI"),
      tr("Show map on left side when in split screen view."),
      "../assets/offroad/icon_road.png",
    },
#endif
  };

  for (auto &[param, title, desc, icon] : toggle_defs) {
    auto toggle = new ParamControl(param, title, desc, icon, this);

    bool locked = false;// params.getBool((param + "Lock").toStdString());
    toggle->setEnabled(!locked);

    addItem(toggle);
    toggles[param.toStdString()] = toggle;
  }

  // Toggles with confirmation dialogs
  toggles["ExperimentalMode"]->setActiveIcon("../assets/img_experimental.svg");
  toggles["ExperimentalMode"]->setConfirmation(true, true);
  toggles["ExperimentalLongitudinalEnabled"]->setConfirmation(true, false);

  connect(toggles["ExperimentalLongitudinalEnabled"], &ToggleControl::toggleFlipped, [=]() {
    updateToggles();
  });
}

void TogglesPanel::expandToggleDescription(const QString &param) {
  toggles[param.toStdString()]->showDescription();
}

void TogglesPanel::showEvent(QShowEvent *event) {
  updateToggles();
}

void TogglesPanel::updateToggles() {
  auto e2e_toggle = toggles["ExperimentalMode"];
  auto op_long_toggle = toggles["ExperimentalLongitudinalEnabled"];
  const QString e2e_description = QString("%1<br>"
                                          "<h4>%2</h4><br>"
                                          "%3<br>"
                                          "<h4>%4</h4><br>"
                                          "%5")
                                  .arg(tr("openpilot은 기본적으로 <b>안정 모드</b>로 주행합니다. 실험 모드는 아직 안정 모드에 넣기 어려운 <b>알파 단계 기능</b>을 켭니다. 실험 기능은 다음과 같습니다:"))
                                  .arg(tr("엔드투엔드 가감속 제어"))
                                  .arg(tr("주행 모델이 가속과 브레이크를 직접 제어합니다. 빨간 신호와 정지 표지판에서 멈추는 것까지 사람이 운전하듯 판단합니다. "
                                       "속도는 주행 모델이 정하기 때문에 크루즈 설정 속도는 최고 속도 제한으로만 쓰입니다. 알파 단계 기능이라 실수가 있을 수 있습니다."))
                                  .arg(tr("새 주행 화면"))
                                  .arg(tr("저속에서는 회전 구간을 더 잘 보여주기 위해 주행 화면이 광각 카메라로 바뀝니다. 오른쪽 위에 실험 모드 로고도 표시됩니다."));

  // experimental mode and openpilot longitudinal (alpha) are set from the 당근파일럿 > 고급 tab
  // (apilot switches acc / blended on its own; experimental mode would force blended all the time)
  const bool show_advanced = false;
  e2e_toggle->setVisible(show_advanced);

  auto cp_bytes = params.get("CarParamsPersistent");
  if (!cp_bytes.empty()) {
    AlignedBuffer aligned_buf;
    capnp::FlatArrayMessageReader cmsg(aligned_buf.align(cp_bytes.data(), cp_bytes.size()));
    cereal::CarParams::Reader CP = cmsg.getRoot<cereal::CarParams>();

    if (!CP.getExperimentalLongitudinalAvailable()) {
      params.remove("ExperimentalLongitudinalEnabled");
    }
    op_long_toggle->setVisible(show_advanced && CP.getExperimentalLongitudinalAvailable());

    const bool op_long = CP.getOpenpilotLongitudinalControl() && !CP.getExperimentalLongitudinalAvailable();
    const bool exp_long_enabled = CP.getExperimentalLongitudinalAvailable() && params.getBool("ExperimentalLongitudinalEnabled");
    if (op_long || exp_long_enabled) {
      // normal description and toggle
      e2e_toggle->setEnabled(true);
      e2e_toggle->setDescription(e2e_description);
    } else {
      // no long for now
      e2e_toggle->setEnabled(false);
      params.remove("ExperimentalMode");

      const QString no_long = tr("이 차는 순정 ACC로 가감속을 제어하므로 지금은 실험 모드를 쓸 수 없습니다.");
      const QString exp_long = tr("실험 모드를 쓰려면 openpilot 가감속 제어(알파)를 켜세요.");
      e2e_toggle->setDescription("<b>" + (CP.getExperimentalLongitudinalAvailable() ? exp_long : no_long) + "</b><br><br>" + e2e_description);
    }

    e2e_toggle->refresh();
  } else {
    e2e_toggle->setDescription(e2e_description);
    op_long_toggle->setVisible(show_advanced);
  }
}

DevicePanel::DevicePanel(SettingsWindow *parent) : ListWidget(parent) {
  setSpacing(50);
  addItem(new LabelControl(tr("동글 ID"), getDongleId().value_or(tr("N/A"))));
  addItem(new LabelControl(tr("시리얼"), params.get("HardwareSerial").c_str()));

  QHBoxLayout *reset_layout = new QHBoxLayout();
  reset_layout->setSpacing(30);

  // reset calibration button
  QPushButton *restart_openpilot_btn = new QPushButton(tr("소프트 재시작"));
  restart_openpilot_btn->setStyleSheet("height: 120px;border-radius: 15px;background-color: #393939;");
  reset_layout->addWidget(restart_openpilot_btn);
  QObject::connect(restart_openpilot_btn, &QPushButton::released, [=]() {
    emit closeSettings();
    QTimer::singleShot(1000, []() {
      Params().putBool("SoftRestartTriggered", true);
    });
  });

  // reset calibration button
  QPushButton *reset_calib_btn = new QPushButton(tr("Reset Calibration"));
  reset_calib_btn->setStyleSheet("height: 120px;border-radius: 15px;background-color: #393939;");
  reset_layout->addWidget(reset_calib_btn);
  QObject::connect(reset_calib_btn, &QPushButton::released, [=]() {
    if (ConfirmationDialog::confirm(tr("캘리브레이션과 학습 값을 초기화할까요?"), tr("Reset"), this)) {
      Params().remove("CalibrationParams");
      Params().remove("LiveParameters");
      emit closeSettings();
      QTimer::singleShot(1000, []() {
        Params().putBool("SoftRestartTriggered", true);
      });
    }
  });

  addItem(reset_layout);

  // offroad-only buttons

  auto dcamBtn = new ButtonControl(tr("Driver Camera"), tr("PREVIEW"),
                                   tr("Preview the driver facing camera to ensure that driver monitoring has good visibility. (vehicle must be off)"));
  connect(dcamBtn, &ButtonControl::clicked, [=]() { emit showDriverView(); });
  addItem(dcamBtn);

  auto resetCalibBtn = new ButtonControl(tr("Reset Calibration"), tr("RESET"), "");
  connect(resetCalibBtn, &ButtonControl::showDescriptionEvent, this, &DevicePanel::updateCalibDescription);
  connect(resetCalibBtn, &ButtonControl::clicked, [&]() {
    if (ConfirmationDialog::confirm(tr("Are you sure you want to reset calibration?"), tr("Reset"), this)) {
      params.remove("CalibrationParams");
      params.remove("LiveTorqueParameters");
    }
  });
  addItem(resetCalibBtn);

  if (!params.getBool("Passive")) {
    auto retrainingBtn = new ButtonControl(tr("Review Training Guide"), tr("REVIEW"), tr("Review the rules, features, and limitations of openpilot"));
    connect(retrainingBtn, &ButtonControl::clicked, [=]() {
      if (ConfirmationDialog::confirm(tr("Are you sure you want to review the training guide?"), tr("Review"), this)) {
        emit reviewTrainingGuide();
      }
    });
    addItem(retrainingBtn);
  }

  if (Hardware::TICI()) {
    auto regulatoryBtn = new ButtonControl(tr("Regulatory"), tr("VIEW"), "");
    connect(regulatoryBtn, &ButtonControl::clicked, [=]() {
      const std::string txt = util::read_file("../assets/offroad/fcc.html");
      ConfirmationDialog::rich(QString::fromStdString(txt), this);
    });
    addItem(regulatoryBtn);
  }

  auto translateBtn = new ButtonControl(tr("Change Language"), tr("CHANGE"), "");
  connect(translateBtn, &ButtonControl::clicked, [=]() {
    QMap<QString, QString> langs = getSupportedLanguages();
    QString selection = MultiOptionDialog::getSelection(tr("Select a language"), langs.keys(), langs.key(uiState()->language), this);
    if (!selection.isEmpty()) {
      // put language setting, exit Qt UI, and trigger fast restart
      Params().put("LanguageSetting", langs[selection].toStdString());
      qApp->exit(18);
      watchdog_kick();
    }
  });
  addItem(translateBtn);

  QObject::connect(uiState(), &UIState::offroadTransition, [=](bool offroad) {
    for (auto btn : findChildren<ButtonControl *>()) {
        //btn->setEnabled(offroad);
        btn->setEnabled(true);
    }
  });

  // power buttons
  QHBoxLayout *power_layout = new QHBoxLayout();
  power_layout->setSpacing(30);

  QPushButton *reboot_btn = new QPushButton(tr("Reboot"));
  reboot_btn->setObjectName("reboot_btn");
  power_layout->addWidget(reboot_btn);
  QObject::connect(reboot_btn, &QPushButton::clicked, this, &DevicePanel::reboot);

  QPushButton *rebuild_btn = new QPushButton(tr("다시 빌드"));
  rebuild_btn->setObjectName("rebuild_btn");
  power_layout->addWidget(rebuild_btn);
  QObject::connect(rebuild_btn, &QPushButton::clicked, [=]() {

    if (ConfirmationDialog::confirm(tr("다시 빌드할까요?"), tr("Reset"), this)) {
      std::system("cd /data/openpilot && scons -c");
      std::system("rm /data/openpilot/.sconsign.dblite");
      std::system("rm /data/openpilot/prebuilt");
      std::system("rm -rf /tmp/scons_cache");
      if (Hardware::TICI())
        std::system("sudo reboot");
      else
        std::system("reboot");
    }
  });

  QPushButton *poweroff_btn = new QPushButton(tr("Power Off"));
  poweroff_btn->setObjectName("poweroff_btn");
  power_layout->addWidget(poweroff_btn);
  QObject::connect(poweroff_btn, &QPushButton::clicked, this, &DevicePanel::poweroff);

  if (!Hardware::PC()) {
    connect(uiState(), &UIState::offroadTransition, poweroff_btn, &QPushButton::setVisible);
  }

  setStyleSheet(R"(
    #reboot_btn { height: 120px; border-radius: 15px; background-color: #393939; }
    #reboot_btn:pressed { background-color: #4a4a4a; }
    #rebuild_btn { height: 120px; border-radius: 15px; background-color: #393939; }
    #rebuild_btn:pressed { background-color: #4a4a4a; }
    #poweroff_btn { height: 120px; border-radius: 15px; background-color: #E22C2C; }
    #poweroff_btn:pressed { background-color: #FF2424; }
  )");
  addItem(power_layout);
}

void DevicePanel::updateCalibDescription() {
  QString desc =
      tr("openpilot requires the device to be mounted within 4° left or right and "
         "within 5° up or 8° down. openpilot is continuously calibrating, resetting is rarely required.");
  std::string calib_bytes = Params().get("CalibrationParams");
  if (!calib_bytes.empty()) {
    try {
      AlignedBuffer aligned_buf;
      capnp::FlatArrayMessageReader cmsg(aligned_buf.align(calib_bytes.data(), calib_bytes.size()));
      auto calib = cmsg.getRoot<cereal::Event>().getLiveCalibration();
      if (calib.getCalStatus() != 0) {
        double pitch = calib.getRpyCalib()[1] * (180 / M_PI);
        double yaw = calib.getRpyCalib()[2] * (180 / M_PI);
        desc += tr(" Your device is pointed %1° %2 and %3° %4.")
                    .arg(QString::number(std::abs(pitch), 'g', 1), pitch > 0 ? tr("down") : tr("up"),
                         QString::number(std::abs(yaw), 'g', 1), yaw > 0 ? tr("left") : tr("right"));
      }
    } catch (kj::Exception) {
      qInfo() << "invalid CalibrationParams";
    }
  }
  qobject_cast<ButtonControl *>(sender())->setDescription(desc);
}

void DevicePanel::reboot() {
  if (!uiState()->engaged()) {
    if (ConfirmationDialog::confirm(tr("Are you sure you want to reboot?"), tr("Reboot"), this)) {
      // Check engaged again in case it changed while the dialog was open
      if (!uiState()->engaged()) {
        Params().putBool("DoReboot", true);
      }
    }
  } else {
    ConfirmationDialog::alert(tr("Disengage to Reboot"), this);
  }
}

void DevicePanel::poweroff() {
  if (!uiState()->engaged()) {
    if (ConfirmationDialog::confirm(tr("Are you sure you want to power off?"), tr("Power Off"), this)) {
      // Check engaged again in case it changed while the dialog was open
      if (!uiState()->engaged()) {
        Params().putBool("DoShutdown", true);
      }
    }
  } else {
    ConfirmationDialog::alert(tr("Disengage to Power Off"), this);
  }
}

C2NetworkPanel::C2NetworkPanel(QWidget *parent) : QWidget(parent) {
  QVBoxLayout *layout = new QVBoxLayout(this);
  layout->setContentsMargins(50, 0, 50, 0);

  ListWidget *list = new ListWidget();
  list->setSpacing(30);
  // wifi + tethering buttons
#ifdef QCOM
  auto wifiBtn = new ButtonControl("와이파이 설정", "열기");
  QObject::connect(wifiBtn, &ButtonControl::clicked, [=]() { HardwareEon::launch_wifi(); });
  list->addItem(wifiBtn);

  auto tetheringBtn = new ButtonControl("테더링 설정", "열기");
  QObject::connect(tetheringBtn, &ButtonControl::clicked, [=]() { HardwareEon::launch_tethering(); });
  list->addItem(tetheringBtn);
#endif
  ipaddress = new LabelControl("IP 주소", "");
  list->addItem(ipaddress);

  // SSH key management
  list->addItem(new SshToggle());
  list->addItem(new SshControl());
  layout->addWidget(list);
  layout->addStretch(1);
}

void C2NetworkPanel::showEvent(QShowEvent *event) {
  ipaddress->setText(getIPAddress());
}

QString C2NetworkPanel::getIPAddress() {
  std::string result = util::check_output("ifconfig wlan0");
  if (result.empty()) return "";

  const std::string inetaddrr = "inet addr:";
  std::string::size_type begin = result.find(inetaddrr);
  if (begin == std::string::npos) return "";

  begin += inetaddrr.length();
  std::string::size_type end = result.find(' ', begin);
  if (end == std::string::npos) return "";

  return result.substr(begin, end - begin).c_str();
}

QWidget *network_panel(QWidget *parent) {
#ifdef QCOM
  return new C2NetworkPanel(parent);
#else
  return new Networking(parent);
#endif
}

static QStringList get_list(const char* path)
{
  QStringList stringList;
  QFile textFile(path);
  if(textFile.open(QIODevice::ReadOnly))
  {
      QTextStream textStream(&textFile);
      while (true)
      {
        QString line = textStream.readLine();
        if (line.isNull())
            break;
        else
            stringList.append(line);
      }
  }

  return stringList;
}

void SettingsWindow::showEvent(QShowEvent *event) {
  setCurrentPanel(0);
}

void SettingsWindow::setCurrentPanel(int index, const QString &param) {
  panel_widget->setCurrentIndex(index);
  nav_btns->buttons()[index]->setChecked(true);
  if (!param.isEmpty()) {
    emit expandToggleDescription(param);
  }
}

// Layout follows carrot (C3X) c3-wip selfdrive/ui/qt/offroad/settings.cc:
// round "×" close button, Device / Network / Toggles / Software / CarrotPilot
SettingsWindow::SettingsWindow(QWidget *parent) : QFrame(parent) {

  // setup two main layouts
  sidebar_widget = new QWidget;
  QVBoxLayout *sidebar_layout = new QVBoxLayout(sidebar_widget);
  panel_widget = new QStackedWidget();

  // close button
  QPushButton *close_btn = new QPushButton("×");
  close_btn->setStyleSheet(R"(
    QPushButton {
      font-size: 110px;
      padding-bottom: 16px;
      border-radius: 80px;
      background-color: #292929;
      font-weight: 400;
    }
    QPushButton:pressed {
      background-color: #3B3B3B;
    }
  )");
  close_btn->setFixedSize(160, 160);
  sidebar_layout->addSpacing(30);
  sidebar_layout->addWidget(close_btn, 0, Qt::AlignCenter);
  QObject::connect(close_btn, &QPushButton::clicked, this, &SettingsWindow::closeSettings);

  // setup panels
  DevicePanel *device = new DevicePanel(this);
  QObject::connect(device, &DevicePanel::reviewTrainingGuide, this, &SettingsWindow::reviewTrainingGuide);
  QObject::connect(device, &DevicePanel::showDriverView, this, &SettingsWindow::showDriverView);
  QObject::connect(device, &DevicePanel::closeSettings, this, &SettingsWindow::closeSettings);
  TogglesPanel *toggles = new TogglesPanel(this);
  QObject::connect(this, &SettingsWindow::expandToggleDescription, toggles, &TogglesPanel::expandToggleDescription);

  // index 2 = Toggles (opened directly by the experimental mode button)
  QList<QPair<QString, QWidget *>> panels = {
    {tr("Device"), device},
#ifdef QCOM
    {tr("Network"), new C2NetworkPanel(this)},
#else
    {tr("Network"), new Networking(this)},
#endif
    {tr("Toggles"), toggles},
    {tr("Software"), new SoftwarePanel(this)},
    {"당근파일럿", new CarrotPanel(this)},
  };

#ifdef ENABLE_MAPS
  //auto map_panel = new MapPanel(this);
  //panels.push_back({tr("Navigation"), map_panel});
  //QObject::connect(map_panel, &MapPanel::closeSettings, this, &SettingsWindow::closeSettings);
#endif

  nav_btns = new QButtonGroup(this);
  for (auto &[name, panel] : panels) {
    QPushButton *btn = new QPushButton(name);
    btn->setCheckable(true);
    btn->setChecked(nav_btns->buttons().size() == 0);
    btn->setStyleSheet(R"(
      QPushButton {
        color: grey;
        border: none;
        background: none;
        font-size: 58px;
        font-weight: 500;
      }
      QPushButton:checked {
        color: white;
      }
      QPushButton:pressed {
        color: #ADADAD;
      }
    )");
    btn->setSizePolicy(QSizePolicy::Preferred, QSizePolicy::Expanding);
    nav_btns->addButton(btn);
    sidebar_layout->addWidget(btn, 0, Qt::AlignRight);

    // Network panel handles its own margins; the carrot panel is wide, so keep its sides tight
    const int lr_margin = name == tr("Network") ? 0 : (name == "당근파일럿" ? 15 : 50);
    panel->setContentsMargins(lr_margin, 25, lr_margin, 25);

    ScrollView *panel_frame = new ScrollView(panel, this);
    panel_widget->addWidget(panel_frame);

    QObject::connect(btn, &QPushButton::clicked, [=, w = panel_frame]() {
      btn->setChecked(true);
      panel_widget->setCurrentWidget(w);
    });
  }
  sidebar_layout->setContentsMargins(20, 40, 40, 40);

  // main settings layout, sidebar + main panel
  QHBoxLayout *main_layout = new QHBoxLayout(this);

  sidebar_widget->setFixedWidth(360);
  main_layout->addWidget(sidebar_widget);
  main_layout->addWidget(panel_widget);

  setStyleSheet(R"(
    * {
      color: white;
      font-size: 50px;
    }
    SettingsWindow {
      background-color: black;
    }
    QStackedWidget, ScrollView {
      background-color: #292929;
      border-radius: 30px;
    }
  )");
}



/////////////////////////////////////////////////////////////////////////

// CarrotPilot panel: tab row Start / Cruise / Speed / Tuning / Disp / Path (selected tab green),
// same as carrot c3-wip CarrotPanel. The items are this C2 branch's own apilot/carrot params,
// sorted into carrot's tabs.
// carrot draws these rows without a leading icon
static const char *ROAD_ICON = "";
static const char *SHELL_ICON = "";

// group title inside a tab list
static QLabel *carrot_section(const QString &title) {
  QLabel *label = new QLabel(title);
  label->setStyleSheet("font-size: 42px; font-weight: 600; color: #33ab4c; padding-top: 25px; padding-left: 10px;");
  return label;
}

// Live text for the 'GPS 확인' screen: uses the GPS summary the UI keeps in UIScene (ubloxGnss) plus gpsLocationExternal.
static QString gps_check_text(int elapsed_s) {
  const UIState *s = uiState();
  const SubMaster &sm = *(s->sm);
  const UIScene &scene = s->scene;
  const bool panda = scene.pandaType != cereal::PandaState::PandaType::UNKNOWN;
  const bool gnss_alive = sm.alive("ubloxGnss");
  const bool loc_alive = sm.alive("gpsLocationExternal");
  const auto loc = sm["gpsLocationExternal"].getGpsLocationExternal();
  const bool fixed = loc_alive && (loc.getFlags() & 1);
  const float acc = loc.getAccuracy();

  QString state, color;
  if (!panda) { state = "판다 연결 안 됨"; color = "#AAAAAA"; }
  else if (!gnss_alive) { state = "GPS 신호 없음"; color = "#AAAAAA"; }
  else if (scene.gps_antenna_bad) { state = "안테나 이상"; color = "#FF4040"; }
  else if (!fixed) { state = "위성 찾는 중"; color = "#DACA25"; }
  else if (acc <= 5.0f) { state = "잡힘 (좋음)"; color = "#33DD33"; }
  else if (acc <= 15.0f) { state = "잡힘 (보통)"; color = "#DACA25"; }
  else { state = "잡힘 (약함)"; color = "#DA6F25"; }

  const int cno = scene.gps_cno;
  const int bars = cno >= 35 ? 4 : cno >= 30 ? 3 : cno >= 25 ? 2 : cno >= 20 ? 1 : 0;
  const QString bar_text = QString("<span style='color:%1'>%2</span><span style='color:#555555'>%3</span>")
                             .arg(color, QString("■").repeated(bars), QString("■").repeated(4 - bars));

  QString t = "<h2>GPS 확인</h2>";
  t += QString("<p style='font-size:60px; color:%1'><b>%2</b></p>").arg(color, state);
  t += QString("<p>신호 세기: %1 &nbsp;(%2 dB-Hz)</p>").arg(bar_text).arg(cno);
  t += QString("<p>보이는 위성: %1개 &nbsp;(강한 위성 %2개)</p>").arg(scene.gps_sats).arg(scene.gps_strong);
  if (fixed) {
    t += QString("<p>위치 오차: 약 %1 m</p>").arg(acc, 0, 'f', 0);
    t += QString("<p>위치: %1, %2</p>").arg(loc.getLatitude(), 0, 'f', 5).arg(loc.getLongitude(), 0, 'f', 5);
  } else {
    t += "<p>위치 오차: -</p>";
  }
  t += QString("<p style='color:#888888'>확인 시작 후 %1초</p>").arg(elapsed_s);
  if (!panda) {
    t += "<p>판다(uno 보드)가 연결되지 않았어요. C2에 차량 하네스 전원이 들어와야 GPS가 켜집니다.</p>";
  } else if (!gnss_alive && elapsed_s >= 20) {
    t += "<p>GPS 칩에서 데이터가 오지 않아요. GPS가 없는 판다이거나 GPS 칩이 응답하지 않는 상태일 수 있어요.</p>";
  } else if (!fixed) {
    t += "<p>처음 켜면 위성을 찾는 데 1~3분 걸릴 수 있어요. 하늘이 잘 보이는 곳에서 확인하세요.</p>";
  }
  return t;
}

CarrotPanel::CarrotPanel(QWidget* parent) : QWidget(parent) {
  main_layout = new QStackedLayout(this);
  homeScreen = new QWidget(this);
  carrotLayout = new QVBoxLayout(homeScreen);
  carrotLayout->setMargin(0);

  QHBoxLayout* select_layout = new QHBoxLayout();
  select_layout->setSpacing(10);

  const QStringList tab_names = {"시작", "주행", "속도", "조향", "화면", "고급"};
  for (int i = 0; i < tab_names.size(); i++) {
    QPushButton* tab = new QPushButton(tab_names[i]);
    tab->setObjectName(QString("tab_btn_%1").arg(i));
    QObject::connect(tab, &QPushButton::clicked, this, [this, i]() {
      this->currentCarrotIndex = i;
      this->togglesCarrot(i);
      updateButtonStyles();
    });
    select_layout->addWidget(tab);
  }
  updateButtonStyles();
  carrotLayout->addLayout(select_layout, 0);

  QWidget* toggles = new QWidget();
  QVBoxLayout* toggles_layout = new QVBoxLayout(toggles);

  // ---- 시작: car, hotspot, update ----
  startToggles = new ListWidget(this);
  QString selected = QString::fromStdString(Params().get("SelectedCar"));
  QPushButton* selectCarBtn = new QPushButton(selected.length() ? selected : tr("차종 선택"));
  selectCarBtn->setObjectName("selectCarBtn");
  selectCarBtn->setStyleSheet(R"(
    QPushButton {
      margin-top: 20px; margin-bottom: 20px; padding: 10px; height: 120px; border-radius: 15px;
      color: #FFFFFF; background-color: #2C2CE2;
    }
    QPushButton:pressed {
      background-color: #2424FF;
    }
  )");
  selectCar = new SelectCar(this);
  connect(selectCarBtn, &QPushButton::clicked, [=]() { main_layout->setCurrentWidget(selectCar); });
  connect(selectCar, &SelectCar::backPress, [=]() { main_layout->setCurrentWidget(homeScreen); });
  connect(selectCar, &SelectCar::selectedCar, [=]() {
    QString car = QString::fromStdString(Params().get("SelectedCar"));
    selectCarBtn->setText(car.length() ? car : tr("차종 선택"));
    main_layout->setCurrentWidget(homeScreen);
  });
  startToggles->addItem(selectCarBtn);
  auto gps_btn = new ButtonControl("GPS 확인", "확인", "시동을 걸지 않아도 판다(uno)의 GPS를 켜서 잡힘 여부, 신호 세기, 위성 수, 위치 오차를 실시간으로 보여 줍니다. 창을 닫으면 GPS는 다시 꺼집니다. 차량 하네스 전원이 연결돼 있어야 합니다.");
  QObject::connect(gps_btn, &ButtonControl::clicked, [=]() {
    Params().putBool("GpsCheck", true);  // boardd powers the uBlox while this is set (read about once a second)
    ConfirmationDialog d(gps_check_text(0), "닫기", "", true, this);
    QLabel *label = d.findChild<QLabel *>();
    QElapsedTimer started;
    started.start();
    QTimer refresh;
    QObject::connect(&refresh, &QTimer::timeout, [&]() {
      if (label) label->setText(gps_check_text(started.elapsed() / 1000));
    });
    refresh.start(500);
    d.exec();
    refresh.stop();
    Params().putBool("GpsCheck", false);
  });
  startToggles->addItem(gps_btn);
  startToggles->addItem(new ParamControl("AutoShutdown", "자동 꺼짐", "켜 두면(초록색) 차량이나 충전기 전원 없이 배터리로만 켜져 있고 주행 중이 아닐 때, 약 10분 뒤 기기가 스스로 꺼져 배터리를 보호합니다. 끄면 배터리가 다 닳을 때까지 켜져 있습니다. 주행 중이거나 전원이 연결돼 있으면 이 설정과 상관없이 꺼지지 않습니다.", SHELL_ICON, this));
  startToggles->addItem(new ParamControl("OpkrHotspotOnBoot", "부팅 시 핫스팟 켜기", "켜 두면 기기가 켜질 때 핫스팟(테더링)이 자동으로 켜집니다.", SHELL_ICON, this));
  auto updateBtn = new ButtonControl("업데이트 확인 후 적용", "업데이트");
  QObject::connect(updateBtn, &ButtonControl::clicked, [=]() {
    const char* gitcommit = "/data/openpilot/selfdrive/assets/addon/sh/gitcommit.sh";
    const char* gitpull = "/data/openpilot/selfdrive/assets/addon/sh/gitpull.sh";
    std::system(gitcommit);
    std::system("date -u '+%Y-%m-%dT%H:%M:%S' > /data/params/d/LastUpdateTime");
    QString commit_local = QString::fromStdString(Params().get("GitCommit")).left(7);
    QString commit_remote = QString::fromStdString(Params().get("GitCommitRemote")).left(7);
    if (commit_remote.isEmpty()) {
      ConfirmationDialog::alert("업데이트 서버에 연결하지 못했어요.\n와이파이 연결을 확인해 주세요.", this);
    } else if (commit_local == commit_remote) {
      ConfirmationDialog::alert("이미 최신 버전이에요.\n(" + commit_local + ")", this);
    } else {
      QString changes = QString::fromStdString(util::read_file("/tmp/update_changelog.txt")).trimmed();
      if (changes.isEmpty()) changes = "(바뀐 내용 목록을 불러오지 못했어요)";
      if (ConfirmationDialog::richConfirm("새 업데이트가 있어요. (" + commit_local + " → " + commit_remote + ")\n\n바뀐 내용:\n" + changes +
                                      "\n\n받은 뒤 자동으로 재부팅해요. 업데이트할까요?", "업데이트", this)) {
        std::system(gitpull);
      }
    }
  });
  startToggles->addItem(updateBtn);
  auto tmuxlog_btn = new ButtonControl("오류 로그 (Tmux)", "보기");
  QObject::connect(tmuxlog_btn, &ButtonControl::clicked, [=]() {
    const std::string txt = util::read_file("/data/tmux_error.log");
    ConfirmationDialog::alert(QString::fromStdString(txt), this);
  });

  // ---- 주행: brake / cruise buttons ----
  cruiseToggles = new ListWidget(this);
  cruiseToggles->addItem(carrot_section("브레이크"));
  cruiseToggles->addItem(new ParamControl("AutoResumeFromBrakeRelease", "브레이크 뗀 뒤 자동 재개", "브레이크를 밟으면 조향은 유지하고 가감속만 잠시 운전자에게 넘기며, 브레이크를 떼면 아래 조건에서 다시 openpilot이 가감속합니다. 정차 중: 앞차가 10m 안에 있을 때만. 주행 중: 앞차가 20m보다 멀리 있거나, 앞차 없이 시속 40km 이상일 때 (설정 속도는 '브레이크 재개 속도'를 따름). 신호만 보고 재개하지 않으며, 핸들을 20도 넘게 돌리고 있을 때와 취소 버튼으로 끈 뒤에는 재개하지 않습니다. 끄면 브레이크를 밟을 때마다 버튼으로 다시 켜야 합니다.", SHELL_ICON, this));
  cruiseToggles->addItem(new CValueControl("BrakeResumeSpeedMode", "브레이크 재개 속도", "주행 중 브레이크를 밟았다 떼서 다시 가감속을 맡길 때의 설정 속도입니다. 0:브레이크를 뗀 순간의 속도로 이어 가기, 1:브레이크 밟기 전 설정 속도로 복귀(앞차와 차간은 그대로 지키면서 서서히 가속).", SHELL_ICON, 0, 1, 1));
  cruiseToggles->addItem(new CValueControl("SoftHoldMode", "소프트홀드", "정차 후 브레이크를 떼도 차를 멈춘 상태로 잡아 주는 기능입니다. 0:사용 안 함, 1:사용, 2:SCC와 함께 사용(일부 차량은 전자식 주차 브레이크가 걸릴 수 있음)", ROAD_ICON, 0, 2, 1));
  cruiseToggles->addItem(carrot_section("크루즈 버튼"));
  cruiseToggles->addItem(new CValueControl("LongControlActiveSound", "크루즈 알림음", "크루즈가 켜지고 꺼질 때 나는 알림음 크기입니다. 0:끄기, 1:작게, 2:크게", ROAD_ICON, 0, 2, 1));
  cruiseToggles->addItem(new CValueControl("CruiseSpeedUnit", "버튼 한 번에 바뀌는 속도", "크루즈 속도 버튼을 한 번 누를 때 바뀌는 속도(km/h)입니다.", ROAD_ICON, 1, 20, 1));
  cruiseToggles->addItem(carrot_section("과속카메라 · 방지턱"));
  cruiseToggles->addItem(new CValueControl("AutoNaviSpeedCtrl", "카메라 감속", "과속카메라 앞에서 자동으로 감속합니다. 0:사용 안 함, 1:APM(내비 연동), 2:APM + 순정 내비게이션, 3:NDA", ROAD_ICON, 0, 3, 1));
  cruiseToggles->addItem(new CValueControl("SpeedCamDB", "내장 카메라 DB", "내비 앱 없이 C2 안에 넣어 둔 전국 고정식 단속카메라 목록(공공데이터, 과속·신호과속·구간단속 약 3만 1천 대)과 GPS로 앞쪽 카메라를 찾아 감속합니다. 내비 앱(APM)이 카메라 정보를 보내면 앱 정보를 우선하고, 앱이 회전 안내만 보낼 때(티맵 등)는 내장 DB로 카메라 감속을 합니다. 이동식 카메라와 새로 생긴 카메라는 없고, 반대 차로 카메라에서도 제한속도까지 줄일 수 있습니다. '카메라 감속'이 1 이상이어야 감속합니다. 0:끄기, 1:켜기. 바꾼 뒤 재부팅해야 적용됩니다.", ROAD_ICON, 0, 1, 1));
  cruiseToggles->addItem(new CValueControl("HapticFeedbackWhenSpeedCamera", "카메라 알림", "과속카메라가 가까워질 때 알려 주는 방법입니다. 0:사용 안 함, 1:핸들 진동, 2:계기판 표시, 3:HUD 표시", ROAD_ICON, 0, 3, 1));
  cruiseToggles->addItem(new CValueControl("AutoNaviSpeedBumpSpeed", "방지턱 통과 속도", "과속방지턱을 넘을 때의 속도(km/h)입니다.", ROAD_ICON, 10, 100, 5));

  // ---- 속도: cruise speed, camera / bump, accel ----
  speedToggles = new ListWidget(this);
  speedToggles->addItem(carrot_section("크루즈 속도"));
  speedToggles->addItem(new CValueControl("AutoSyncCruiseSpeedMax", "가속페달 속도 맞춤 상한", "가속페달로 크루즈 설정 속도보다 빨리 달리면, 페달을 뗄 때 설정 속도를 지금 속도로 올려 줍니다. 이 값(km/h)까지만 올립니다. 0:사용 안 함", ROAD_ICON, 0, 200, 10));
  speedToggles->addItem(new CValueControl("AutoSpeedUptoRoadSpeedLimit", "제한속도까지 자동 올림", "앞차를 따라갈 때 도로 제한속도의 이 비율(%)까지 설정 속도를 자동으로 올립니다. 0:사용 안 함, 100:제한속도까지", ROAD_ICON, 0, 200, 10));
  speedToggles->addItem(carrot_section("출발·정지 (출발이 굼뜨거나 정지가 거칠 때)"));
  speedToggles->addItem(new CValueControl("JerkStartLimit", "출발 저크", "정차 후 출발할 때 가속이 얼마나 빨리 붙을지 정합니다(0.1 단위). 높이면 빠르게, 낮추면 부드럽게 출발합니다.", ROAD_ICON, 1, 50, 1));
  speedToggles->addItem(new CValueControl("StartAccelApply", "출발 가속", "정차 후 출발할 때 처음 가속을 몇 % 더 줄지 정합니다. 출발이 굼뜨면 올려 보세요. 0:사용 안 함", ROAD_ICON, 0, 100, 10));
  speedToggles->addItem(new CValueControl("StopAccelApply", "정지 유지 힘", "멈춰 있을 때 브레이크를 얼마나 세게 잡을지 정합니다(%). 정차 중 차가 밀리면 올려 보세요. 0:사용 안 함", ROAD_ICON, 0, 100, 10));
  speedToggles->addItem(new CValueControl("StopDistance", "앞차 뒤 정지 거리", "앞차 뒤에 멈출 때의 거리(cm)입니다. 600이면 약 6m 뒤에 멈춥니다.", ROAD_ICON, 200, 1000, 50));
  speedToggles->addItem(carrot_section("속도별 가속 세기 (가속이 너무 세거나 약할 때)"));
  speedToggles->addItem(new CValueControl("CruiseMaxVals1", "가속: 0km/h", "이 속도에서 낼 수 있는 최대 가속 세기입니다(단위 0.01m/s²). 높이면 더 빠르게 가속하고, 낮추면 부드럽게 가속합니다.", ROAD_ICON, 1, 250, 5));
  speedToggles->addItem(new CValueControl("CruiseMaxVals2", "가속: 40km/h", "이 속도에서 낼 수 있는 최대 가속 세기입니다(단위 0.01m/s²). 높이면 더 빠르게 가속하고, 낮추면 부드럽게 가속합니다.", ROAD_ICON, 1, 250, 5));
  speedToggles->addItem(new CValueControl("CruiseMaxVals3", "가속: 60km/h", "이 속도에서 낼 수 있는 최대 가속 세기입니다(단위 0.01m/s²). 높이면 더 빠르게 가속하고, 낮추면 부드럽게 가속합니다.", ROAD_ICON, 1, 250, 5));
  speedToggles->addItem(new CValueControl("CruiseMaxVals4", "가속: 80km/h", "이 속도에서 낼 수 있는 최대 가속 세기입니다(단위 0.01m/s²). 높이면 더 빠르게 가속하고, 낮추면 부드럽게 가속합니다.", ROAD_ICON, 1, 250, 5));
  speedToggles->addItem(new CValueControl("CruiseMaxVals5", "가속: 110km/h", "이 속도에서 낼 수 있는 최대 가속 세기입니다(단위 0.01m/s²). 높이면 더 빠르게 가속하고, 낮추면 부드럽게 가속합니다.", ROAD_ICON, 1, 250, 5));
  speedToggles->addItem(new CValueControl("CruiseMaxVals6", "가속: 140km/h", "이 속도에서 낼 수 있는 최대 가속 세기입니다(단위 0.01m/s²). 높이면 더 빠르게 가속하고, 낮추면 부드럽게 가속합니다.", ROAD_ICON, 1, 250, 5));

  // ---- 조향: steering and curves ----
  steerToggles = new ListWidget(this);
  steerToggles->addItem(carrot_section("조향"));
  steerToggles->addItem(new CValueControl("PathOffset", "경로 좌우 보정 (쏠릴 때)", "차가 차로 안에서 한쪽으로 치우쳐 달리면 보정합니다. -값:왼쪽으로, +값:오른쪽으로 옮깁니다.", ROAD_ICON, -200, 200, 1));
  steerToggles->addItem(new CValueControl("NNFF", "NNFF 조향 보정", "차종별로 미리 학습된 작은 신경망으로 커브에서 필요한 핸들 힘을 더 정확히 계산합니다(twilsonco NNFF, 당근 c3-wip에서 이식). 현대·기아·제네시스 31개 차종에만 모델이 있고, 모델이 없는 차(K7, 그랜저 IG, 볼트 등)는 켜도 기존 방식 그대로입니다. 토크 조향 차량에서만 동작합니다. 0:끄기, 1:켜기. 바꾼 뒤 재부팅해야 적용됩니다.", ROAD_ICON, 0, 1, 1));
  steerToggles->addItem(new CValueControl("NNFFLite", "NNFF 라이트", "NNFF 모델이 없는 차(K7, 그랜저, 볼트 등)용입니다. 주행 모델이 예상한 앞쪽 커브 변화를 미리 보고, 커브에 들어가거나 나올 때 핸들 마찰 보정을 미리 넣어 늦게 꺾이거나 늦게 풀리는 느낌을 줄입니다. 보정 크기는 기존 마찰 값 안으로 제한됩니다. 모델이 있는 차에서 NNFF를 켜면 NNFF가 우선합니다. 토크 조향 차량에서만 동작합니다. 0:끄기, 1:켜기. 바꾼 뒤 재부팅해야 적용됩니다.", ROAD_ICON, 0, 1, 1));
  steerToggles->addItem(new CValueControl("AutoLaneChangeSpeed", "차선변경 최소 속도", "방향지시등을 켰을 때 자동 차선 변경이 되는 최소 속도(km/h)입니다.", ROAD_ICON, 5, 60, 5));
  steerToggles->addItem(carrot_section("커브"));
  steerToggles->addItem(new CValueControl("AutoCurveSpeedCtrlUse", "커브 자동 감속", "커브를 만나면 미리 속도를 줄입니다. 0:사용 안 함, 1·3:도로 설계 기준(주행 경로의 휘어짐으로 계산), 2:당근 방식(카메라로 앞 커브를 보고 거리에 맞춰 미리 감속)", ROAD_ICON, 0, 3, 1));
  steerToggles->addItem(new CValueControl("AutoCurveSpeedFactor", "커브 감속 비율", "커브 감속 정도입니다(%). 높이면 커브에서 더 빨리 달리고, 낮추면 더 많이 감속합니다.", ROAD_ICON, 50, 300, 1));
  steerToggles->addItem(carrot_section("조향 세부 (커브에서 덜 꺾이거나 너무 꺾일 때)"));
  steerToggles->addItem(new CValueControl("SteerRatioApply", "조향비 고정", "핸들을 돌린 만큼 바퀴가 꺾이는 비율(조향비)을 고정합니다(0.1 단위, 150=15.0). 0:자동 학습값 사용", ROAD_ICON, 0, 300, 2));
  steerToggles->addItem(new CValueControl("LiveSteerRatioApply", "실시간 조향비 적용", "자동으로 학습한 조향비를 몇 %로 쓸지 정합니다. 커브에서 너무 많이 꺾이면(오버스티어) 낮추세요.", ROAD_ICON, 50, 110, 1));
  steerToggles->addItem(new CValueControl("SteerActuatorDelay", "조향 반응 지연 보정", "조향 명령을 보낸 뒤 실제로 핸들이 움직이기까지 걸리는 시간 보정입니다(0.01초 단위). 커브에서 늦게 꺾이면 조금 올려 보세요.", ROAD_ICON, 0, 100, 1));
  auto torqueCustom = new CValueControl("LateralTorqueCustom", "토크 사용자 설정", "토크 조향 값을 직접 정할지 고릅니다. 0:차량 기본값 + 주행하며 자동 학습, 1·2:자동 학습을 끄고 아래 '토크 가속 계수'와 '토크 마찰 계수'를 사용(주행 중 바꿔도 몇 초 안에 적용)", ROAD_ICON, 0, 2, 1);
  steerToggles->addItem(torqueCustom);
  auto torqueAccel = new CValueControl("LateralTorqueAccelFactor", "토크 가속 계수", "토크 조향에서 원하는 회전량을 내는 데 필요한 힘 계수입니다. 커브에서 덜 꺾이면 낮추고, 너무 꺾이면 높이세요. '토크 사용자 설정'이 켜져 있을 때만 적용됩니다.", ROAD_ICON, 1000, 4000, 10);
  steerToggles->addItem(torqueAccel);
  auto torqueFriction = new CValueControl("LateralTorqueFriction", "토크 마찰 계수", "핸들 마찰을 보정하는 값입니다. 직진에서 핸들이 늦게 반응하면 조금 올려 보세요. '토크 사용자 설정'이 켜져 있을 때만 적용됩니다.", ROAD_ICON, 0, 1000, 10);
  steerToggles->addItem(torqueFriction);
  // show the two torque values only while 토크 사용자 설정 is on
  auto showTorqueValues = [=](int v) { torqueAccel->setVisible(v > 0); torqueFriction->setVisible(v > 0); };
  QObject::connect(torqueCustom, &CValueControl::valueChanged, showTorqueValues);
  showTorqueValues(std::atoi(Params().get("LateralTorqueCustom").c_str()));

  // ---- 화면 ----
  dispToggles = new ListWidget(this);
  dispToggles->addItem(new CValueControl("ShowHudMode", "화면 모드", "주행 화면에서 속도 등 정보를 어디에 어떻게 보여줄지 고릅니다. 0:기본, 1:APilot, 2:아래, 3:위, 4:왼쪽, 5:왼쪽 아래, 6:당근(C3X) 스타일 박스", SHELL_ICON, 0, 6, 1));
  dispToggles->addItem(new CValueControl("ScreenAlwaysOn", "화면 항상 켜기", "시동이 꺼져 있을 때 아무것도 만지지 않아도 화면이 꺼지지 않게 합니다. 기본은 30초 뒤 꺼집니다. 켜 두면 차 배터리를 조금 더 쓰고 기기 발열이 늘 수 있습니다. 0:기본(30초 뒤 꺼짐), 1:항상 켜기", SHELL_ICON, 0, 1, 1));
  dispToggles->addItem(new CValueControl("ShowTpms", "타이어 공기압", "타이어 공기압을 주행 화면에 보여줍니다. 0:안 보임, 1:보임", SHELL_ICON, 0, 1, 1));
  dispToggles->addItem(new CValueControl("ShowDateTime", "시간 표시", "주행 화면에 시간과 날짜를 보여줍니다. 0:안 보임, 1:시간+날짜, 2:시간만, 3:날짜만", SHELL_ICON, 0, 3, 1));
  dispToggles->addItem(new CValueControl("ShowGpsInfo", "GPS 상태", "주행 화면 오른쪽 아래에 GPS가 잡혔는지, 신호 세기(막대 4칸), 보이는 위성 수, 위치 오차(m)를 보여줍니다. GPS는 시동이 켜져 있을 때만 동작합니다. 0:안 보임, 1:보임", SHELL_ICON, 0, 1, 1));
  dispToggles->addItem(new CValueControl("ShowDeviceState", "기기 상태", "기기 상태(CPU 온도, 메모리, 저장공간)를 보여줍니다. 0:안 보임, 1:보임", SHELL_ICON, 0, 1, 1));
  dispToggles->addItem(new CValueControl("ShowBlindSpot", "후측방(BSD) 경고", "후측방 감지(BSD) 경고를 화면에 표시합니다. 0:안 보임, 1:보임", SHELL_ICON, 0, 1, 1));
  dispToggles->addItem(new CValueControl("ShowConnInfo", "APM 연결 표시", "내비(APM/NDA) 연결 상태 아이콘을 보여줍니다. 0:안 보임, 1:보임", SHELL_ICON, 0, 1, 1));
  dispToggles->addItem(new CValueControl("ShowDmInfo", "운전자 모니터링", "운전자 모니터링(얼굴 인식) 아이콘을 보여줍니다. 0:안 보임, 1:보임, -1:기능 끄기(재부팅 필요)", SHELL_ICON, -1, 1, 1));

  // ---- 고급: experimental / developer ----
  advancedToggles = new ListWidget(this);
  advancedToggles->addItem(carrot_section("주행 기록"));
  auto drivelog_btn = new ButtonControl("주행 기록 보기", "보기", "주행할 때마다 자동으로 남는 기록입니다. 고른 주행에서 켜짐·꺼짐, 경고, 오류, 프로그램 멈춤을 시간순으로 보여 줍니다. (최근 30번 보관)");
  QObject::connect(drivelog_btn, &ButtonControl::clicked, [=]() {
    const QString dir_path = "/data/drivelog";
    QDir dir(dir_path);
    QStringList files = dir.entryList(QStringList() << "2*.txt", QDir::Files, QDir::Name | QDir::Reversed);
    if (files.isEmpty()) {
      ConfirmationDialog::alert("아직 주행 기록이 없어요.", this);
      return;
    }
    // file name: YYYYmmdd-HHMMSS.txt -> "11/18 08:30 주행"
    QStringList labels;
    for (const QString &f : files) {
      labels << QString("%1/%2 %3:%4 주행").arg(f.mid(4, 2), f.mid(6, 2), f.mid(9, 2), f.mid(11, 2));
    }
    const QString sel = MultiOptionDialog::getSelection("볼 주행을 고르세요", labels, "", this);
    if (sel.isEmpty()) return;
    const int idx = labels.indexOf(sel);
    const QString file = files[idx];

    QString first_time, last_time;
    QStringList events;
    const QStringList lines = QString::fromStdString(util::read_file((dir_path + "/" + file).toStdString())).split('\n');
    for (const QString &line : lines) {
      if (line.isEmpty() || line.startsWith("#")) continue;
      const QString t = line.left(5);  // HH:MM
      if (first_time.isEmpty()) first_time = t;
      last_time = t;
      if (line.contains(" ** ")) events << line.left(8) + "  " + line.mid(line.indexOf(" ** ") + 4);
    }

    // crash tracebacks written during this drive (between this file and the next newer one)
    const QString start = file.left(15);
    const QString end = idx > 0 ? files[idx - 1].left(15) : "99999999-999999";
    QStringList crashes;
    for (const QString &c : dir.entryList(QStringList() << "crash-*.txt", QDir::Files, QDir::Name)) {
      const QString when = c.mid(6, 15);  // crash-YYYYmmdd-HHMMSS-<name>.txt
      if (when >= start && when < end) {
        const QStringList tb = QString::fromStdString(util::read_file((dir_path + "/" + c).toStdString())).trimmed().split('\n');
        const QString name = c.mid(22, c.length() - 22 - 4);
        crashes << c.mid(15, 2) + ":" + c.mid(17, 2) + ":" + c.mid(19, 2) + "  " + name + " : " + tb.last();
      }
    }

    QString text = sel + (first_time.isEmpty() ? "" : " (" + first_time + " ~ " + last_time + ")") + "\n\n";
    if (events.isEmpty() && crashes.isEmpty()) {
      text += "경고나 오류 없이 정상이었어요.";
    } else {
      if (!crashes.isEmpty()) text += "[프로그램 오류]\n" + crashes.join("\n") + "\n\n";
      if (events.size() > 200) {
        text += QString("(앞부분 %1줄 생략)\n").arg(events.size() - 200);
        events = events.mid(events.size() - 200);
      }
      text += events.join("\n");
    }
    ConfirmationDialog d(text, "확인", "", true, this);
    d.exec();
  });
  advancedToggles->addItem(drivelog_btn);
  advancedToggles->addItem(carrot_section("실험 모드"));
  {
    auto op_long = new ParamControl("ExperimentalLongitudinalEnabled", "openpilot 가감속 제어 (알파)", "CAN FD 현대·기아용 롱컨 스위치입니다. 일반 CAN 현대·기아는 이 스위치 대신 토글의 '롱컨'으로 롱컨을 켜지만, 실험 모드 스위치는 이 값이 켜져 있어야 동작합니다. 켜면 자동 긴급 제동(AEB)이 꺼질 수 있습니다.", SHELL_ICON, this);
    op_long->setConfirmation(true, false);
    advancedToggles->addItem(op_long);
    auto e2e = new ParamControl("ExperimentalMode", "실험 모드", "가감속을 항상 주행 모델 주도(blended)로 고정합니다. apilot은 평소 레이더 방식(acc)과 모델 방식을 상황에 따라 자동으로 바꾸고 신호 정지도 자체 기능으로 하므로 보통은 꺼 두는 것을 권장합니다. 롱컨(openpilot 가감속 제어)일 때만 적용됩니다. 알파 단계 기능이라 실수가 있을 수 있습니다.", SHELL_ICON, this);
    e2e->setConfirmation(true, true);
    advancedToggles->addItem(e2e);
  }
  advancedToggles->addItem(carrot_section("개발용"));
  advancedToggles->addItem(new ParamControl("ShowDebugUI", "디버그 정보", "켜 두면 주행 화면에 개발용 상세 정보를 글자로 보여줍니다.", SHELL_ICON, this));
  advancedToggles->addItem(new CValueControl("ShowPlotMode", "디버그 그래프", "개발용 그래프를 보여줍니다. 0:안 보임, 1~5:그래프 종류", SHELL_ICON, 0, 5, 1));
  advancedToggles->addItem(tmuxlog_btn);

  toggles_layout->addWidget(startToggles);
  toggles_layout->addWidget(cruiseToggles);
  toggles_layout->addWidget(speedToggles);
  toggles_layout->addWidget(steerToggles);
  toggles_layout->addWidget(dispToggles);
  toggles_layout->addWidget(advancedToggles);
  ScrollView* toggles_view = new ScrollView(toggles, this);
  carrotLayout->addWidget(toggles_view, 1);

  homeScreen->setLayout(carrotLayout);
  main_layout->addWidget(homeScreen);
  main_layout->addWidget(selectCar);
  main_layout->setCurrentWidget(homeScreen);

  togglesCarrot(0);

}


void CarrotPanel::togglesCarrot(int widgetIndex) {
  startToggles->setVisible(widgetIndex == 0);
  cruiseToggles->setVisible(widgetIndex == 1);
  speedToggles->setVisible(widgetIndex == 2);
  steerToggles->setVisible(widgetIndex == 3);
  dispToggles->setVisible(widgetIndex == 4);
  advancedToggles->setVisible(widgetIndex == 5);
}

void CarrotPanel::updateButtonStyles() {
  QString styleSheet = R"(
      #tab_btn_0, #tab_btn_1, #tab_btn_2, #tab_btn_3, #tab_btn_4, #tab_btn_5 {
        height: 120px; border-radius: 15px; background-color: #393939;
      }
      #tab_btn_0:pressed, #tab_btn_1:pressed, #tab_btn_2:pressed, #tab_btn_3:pressed, #tab_btn_4:pressed, #tab_btn_5:pressed {
        background-color: #4a4a4a;
      }
  )";
  styleSheet += QString("#tab_btn_%1 { background-color: #33ab4c; }").arg(currentCarrotIndex);
  setStyleSheet(styleSheet);
}

// ajouatom
CValueControl::CValueControl(const QString& params, const QString& title, const QString& desc, const QString& icon, int min, int max, int unit/*=1*/) : AbstractControl(title, desc, icon)
{

    m_params = params;
    m_min = min;
    m_max = max;
    m_unit = unit;

    label.setAlignment(Qt::AlignVCenter | Qt::AlignRight);
    label.setStyleSheet("color: #e0e879");
    hlayout->addWidget(&label);

    btnminus.setStyleSheet(R"(
    padding: 0;
    border-radius: 50px;
    font-size: 35px;
    font-weight: 500;
    color: #E4E4E4;
    background-color: #393939;
  )");
    btnplus.setStyleSheet(R"(
    padding: 0;
    border-radius: 50px;
    font-size: 35px;
    font-weight: 500;
    color: #E4E4E4;
    background-color: #393939;
  )");
    btnminus.setFixedSize(110, 100);
    btnplus.setFixedSize(110, 100);
    hlayout->addWidget(&btnminus);
    hlayout->addWidget(&btnplus);

    QObject::connect(&btnminus, &QPushButton::released, [=]() {
        auto str = QString::fromStdString(Params().get(m_params.toStdString()));
        int value = str.toInt();
        value = value - m_unit;
        if (value < m_min) {
            value = m_min;
        }
        else {
        }

        //UIScene& scene = uiState()->scene;//QUIState::ui_state.scene;
        //scene.scr.autoFocus = value;
        QString values = QString::number(value);
        Params().put(m_params.toStdString(), values.toStdString());
        refresh();
    });

    QObject::connect(&btnplus, &QPushButton::released, [=]() {
        auto str = QString::fromStdString(Params().get(m_params.toStdString()));
        int value = str.toInt();
        value = value + m_unit;
        if (value > m_max) {
            value = m_max;
        }
        else {
        }

        //UIScene& scene = uiState()->scene;//QUIState::ui_state.scene;
        //scene.scr.autoFocus = value;
        QString values = QString::number(value);
        Params().put(m_params.toStdString(), values.toStdString());
        refresh();
    });
    refresh();
}
TimeZoneSelectCombo::TimeZoneSelectCombo() : AbstractControl("TZ", "", "../assets/offroad/icon_shell.png") 
{
  combobox.setStyleSheet(R"(
    subcontrol-origin: padding;
    subcontrol-position: top left;
    selection-background-color: #111;
    selection-color: yellow;
    color: white;
    background-color: #393939;
    border-style: solid;
    border: 0px solid #1e1e1e;
    border-radius: 0;
    width: 100px;
  )");

  combobox.addItem(tr("시간대를 선택하세요"));
  QFile timezonelistfile("/data/openpilot/selfdrive/assets/addon/param/TimeZone");
  if (timezonelistfile.open(QIODevice::ReadOnly)) {
    QTextStream timezonename(&timezonelistfile);
    while (!timezonename.atEnd()) {
      QString line = timezonename.readLine();
      combobox.addItem(line);
    }
    timezonelistfile.close();
  }

  combobox.setFixedWidth(950);

  btn.setStyleSheet(R"(
    padding: 0;
    border-radius: 50px;
    font-size: 35px;
    font-weight: 500;
    color: #E4E4E4;
    background-color: #393939;
  )");

  btn.setFixedSize(150, 100);

  QObject::connect(&btn, &QPushButton::clicked, [=]() {
    if (btn.text() == tr("해제")) {
      if (ConfirmationDialog::confirm(tr("기본값으로 되돌릴까요?"), tr("Reboot"), this)) {
        params.put("OPKRTimeZone", "UTC");
        combobox.setCurrentIndex(0);
        refresh();
      }
    }
  });

  //combobox.view()->setVerticalScrollBarPolicy(Qt::ScrollBarAsNeeded);

  hlayout->addWidget(&combobox, Qt::AlignLeft);
  hlayout->addWidget(&btn, Qt::AlignRight);

  QObject::connect(&combobox, static_cast<void(QComboBox::*)(int)>(&QComboBox::activated), [=](int index)
  {
    combobox.itemData(combobox.currentIndex());
    QString str = combobox.currentText();
    if (combobox.currentIndex() != 0) {
      if (ConfirmationDialog::confirm(tr("확인을 누르면 시간대를 다음으로 설정합니다:") + "\n" + str, tr("Reboot"), this)) {
        params.put("OPKRTimeZone", str.toStdString());
      }
    }
    refresh();
  });
  refresh();
}

void TimeZoneSelectCombo::refresh() {
  QString selected_timezonename = QString::fromStdString(params.get("OPKRTimeZone"));
  int index = combobox.findText(selected_timezonename);
  if (index >= 0) combobox.setCurrentIndex(index);
  if (selected_timezonename.length()) {
    btn.setEnabled(true);
    btn.setText(tr("해제"));
  } else {
    btn.setEnabled(false);
    btn.setText(tr("설정"));
  }
}

void CValueControl::refresh()
{
    QString value = QString::fromStdString(Params().get(m_params.toStdString()));
    label.setText(value);
    emit valueChanged(value.toInt());
    btnminus.setText("－");
    btnplus.setText("＋");
}

GitHash::GitHash() : AbstractControl("커밋(로컬/리모트)", "", "") {

    QString lhash = QString::fromStdString(Params().get("GitCommit").substr(0, 10));
    QString rhash = QString::fromStdString(Params().get("GitCommitRemote").substr(0, 10));
    hlayout->addStretch(2);

    local_hash.setText(QString::fromStdString(Params().get("GitCommit").substr(0, 10)));
    remote_hash.setText(QString::fromStdString(Params().get("GitCommitRemote").substr(0, 10)));
    local_hash.setAlignment(Qt::AlignVCenter);
    remote_hash.setAlignment(Qt::AlignVCenter);
    local_hash.setStyleSheet("color: #aaaaaa");
    if (lhash == rhash) {
        remote_hash.setStyleSheet("color: #aaaaaa");
    }
    else {
        remote_hash.setStyleSheet("color: #0099ff");
    }
    hlayout->addWidget(&local_hash);
    hlayout->addWidget(&remote_hash);
}
SelectCar::SelectCar(QWidget* parent): QWidget(parent) {

  QVBoxLayout* main_layout = new QVBoxLayout(this);
  main_layout->setMargin(20);
  main_layout->setSpacing(20);

  // Back button
  QPushButton* back = new QPushButton(tr("Back"));
  back->setObjectName("back_btn");
  back->setFixedSize(500, 100);
  connect(back, &QPushButton::clicked, [=]() { emit backPress(); });
  main_layout->addWidget(back, 0, Qt::AlignLeft);

  QListWidget* list = new QListWidget(this);
  list->setStyleSheet("QListView {padding: 40px; background-color: #393939; border-radius: 15px; height: 140px;} QListView::item{height: 100px}");
  //list->setAttribute(Qt::WA_AcceptTouchEvents, true);
  QScroller::grabGesture(list->viewport(), QScroller::LeftMouseButtonGesture);
  list->setVerticalScrollMode(QAbstractItemView::ScrollPerPixel);

  list->addItem(tr("[ 선택 안 함 ]"));

  QStringList items = get_list("/data/params/d/SupportedCars");
  QStringList items_gm = get_list("/data/params/d/SupportedCars_gm");
  list->addItems(items);
  list->addItems(items_gm);
  list->setCurrentRow(0);

  QString selected = QString::fromStdString(Params().get("SelectedCar"));

  int index = 0;
  for(QString item : items) {
    if(selected == item) {
        list->setCurrentRow(index + 1);
        break;
    }
    index++;
  }

  QObject::connect(list, QOverload<QListWidgetItem*>::of(&QListWidget::itemClicked),
    [=](QListWidgetItem* item){

    if(list->currentRow() == 0)
        Params().remove("SelectedCar");
    else
        Params().put("SelectedCar", list->currentItem()->text().toStdString());

    emit selectedCar();
    });

  main_layout->addWidget(list);
}
