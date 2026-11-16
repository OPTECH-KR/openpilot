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
      "SCC 모듈 BUS2 연결",
      "",
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
    {
      "DisengageOnAccelerator",
      tr("Disengage on Accelerator Pedal"),
      tr("When enabled, pressing the accelerator pedal will disengage openpilot."),
      "../assets/offroad/icon_disengage_on_accelerator.svg",
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
                                  .arg(tr("🌮 엔드투엔드 가감속 제어 🌮"))
                                  .arg(tr("Let the driving model control the gas and brakes. openpilot will drive as it thinks a human would, including stopping for red lights and stop signs. "
                                       "Since the driving model decides the speed to drive, the set speed will only act as an upper bound. This is an alpha quality feature; mistakes should be expected."))
                                  .arg(tr("새 주행 화면"))
                                  .arg(tr("저속에서는 회전 구간을 더 잘 보여주기 위해 주행 화면이 광각 카메라로 바뀝니다. 오른쪽 위에 실험 모드 로고도 표시됩니다."));

  auto cp_bytes = params.get("CarParamsPersistent");
  if (!cp_bytes.empty()) {
    AlignedBuffer aligned_buf;
    capnp::FlatArrayMessageReader cmsg(aligned_buf.align(cp_bytes.data(), cp_bytes.size()));
    cereal::CarParams::Reader CP = cmsg.getRoot<cereal::CarParams>();

    if (!CP.getExperimentalLongitudinalAvailable()) {
      params.remove("ExperimentalLongitudinalEnabled");
    }
    op_long_toggle->setVisible(CP.getExperimentalLongitudinalAvailable());

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
    op_long_toggle->setVisible(true);
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

CarrotPanel::CarrotPanel(QWidget* parent) : QWidget(parent) {
  main_layout = new QStackedLayout(this);
  homeScreen = new QWidget(this);
  carrotLayout = new QVBoxLayout(homeScreen);
  carrotLayout->setMargin(0);

  QHBoxLayout* select_layout = new QHBoxLayout();
  select_layout->setSpacing(10);

  const QStringList tab_names = {"시작", "크루즈", "속도", "튜닝", "화면", "경로"};
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

  // ---- Start: car, engage / auto cruise, carrot radar, system ----
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
  startToggles->addItem(new CValueControl("EnableAutoEngage", "자동 인게이지", "시동 후 조건이 되면 openpilot을 자동으로 켭니다. 0:사용 안 함, 1:자동으로 켜지만 크루즈는 꺼진 상태, 2:자동으로 켜고 크루즈도 켬", SHELL_ICON, 0, 2, 1));
  startToggles->addItem(new ParamControl("KeepEngage", "인게이지 유지 모드", "켜 두면 기어를 D가 아닌 곳(P, N 등)으로 바꿔도 openpilot이 꺼지지 않고 유지됩니다.", SHELL_ICON, this));
  startToggles->addItem(new CValueControl("SoftHoldMode", "소프트홀드(1)", "정차 후 브레이크를 떼도 차를 멈춘 상태로 잡아 주는 기능입니다. 0:사용 안 함, 1:사용, 2:SCC와 함께 사용(일부 차량은 전자식 주차 브레이크가 걸릴 수 있음)", ROAD_ICON, 0, 2, 1));
  startToggles->addItem(new CValueControl("CruiseOnDist", "크루즈: 앞차 접근 시 자동 ON 거리(0cm)", "가속·브레이크 페달을 밟지 않은 채 앞차와 이 거리보다 가까워지면 크루즈를 자동으로 켭니다(단위 cm). 0:사용 안 함, -값:크루즈는 켜지 않고 경고만", ROAD_ICON, -500, 500, 50));
  startToggles->addItem(new CValueControl("AutoResumeFromGas", "가속페달 크루즈 ON: 사용", "가속페달로 크루즈를 켜는 기능입니다. 1:가속페달을 떼면 자동으로 크루즈 ON, 2:가속페달을 60% 이상 밟아도 크루즈 ON", ROAD_ICON, 0, 2, 1));
  startToggles->addItem(new CValueControl("AutoResumeFromGasSpeed", "가속페달 크루즈 ON: 속도(30)", "가속페달로 크루즈를 켤 때 필요한 최소 속도입니다(km/h). 이 속도보다 빠를 때만 켜집니다.", ROAD_ICON, 20, 140, 5));
  startToggles->addItem(new CValueControl("AutoResumeFromGasSpeedMode", "가속페달 크루즈 ON: 설정 속도(0)", "가속페달로 크루즈가 켜질 때 설정 속도를 무엇으로 할지 고릅니다. 0:지금 속도, 1:이전에 쓰던 속도, 2:앞차 속도, 3:60m 이상 직진이면 이전 속도", ROAD_ICON, 0, 3, 1));
  startToggles->addItem(new CValueControl("AutoCancelFromGasMode", "가속페달 크루즈 OFF: 모드", "느리게 달릴 때(가속페달 크루즈 ON 속도 이하) 크루즈를 끄는 조건입니다. 0:끄지 않음, 1:항상 끔, 2:앞차가 없을 때만 끔", ROAD_ICON, 0, 140, 1));
  startToggles->addItem(new ParamControl("AutoResumeFromBrakeRelease", "브레이크 크루즈 ON: 사용", "켜 두면 브레이크를 밟았다가 뗄 때 조건이 맞으면 크루즈가 다시 켜집니다. 아래 '브레이크 크루즈 ON' 항목들이 그 조건입니다.", ROAD_ICON, this));
  startToggles->addItem(new CValueControl("AutoResumeFromBrakeReleaseDist", "브레이크 크루즈 ON: 주행 중 앞차 거리(20)", "주행 중 브레이크를 뗐을 때, 앞차가 이 거리(m)보다 멀리 있으면 크루즈를 다시 켭니다. 0:사용 안 함", ROAD_ICON, 0, 80, 5));
  startToggles->addItem(new ParamControl("AutoResumeFromBrakeReleaseLeadCar", "브레이크 크루즈 ON: 정차 중 앞차", "켜 두면 정차 중 브레이크를 뗐을 때 10m 안에 앞차가 있으면 크루즈를 다시 켭니다.", ROAD_ICON, this));
  startToggles->addItem(new CValueControl("AutoResumeFromBrakeCarSpeed", "브레이크 크루즈 ON: 주행 중 속도(40)", "앞차가 없을 때, 브레이크를 뗀 순간 내 속도가 이 값(km/h)보다 빠르면 크루즈를 다시 켭니다. 0:사용 안 함", ROAD_ICON, 0, 80, 5));
  startToggles->addItem(new ParamControl("AutoResumeFromBrakeReleaseTrafficSign", "브레이크 크루즈 ON: 주행 중 신호 감지", "켜 두면 주행 중 브레이크를 뗐을 때 신호등이 보이면 크루즈를 다시 켭니다.", ROAD_ICON, this));
  startToggles->addItem(new CValueControl("MixRadarInfo", "SCC 레이더 정보 혼합", "앞차 거리·속도를 정할 때 SCC 레이더 값과 카메라(비전) 값을 섞어 씁니다. 0:사용 안 함, 1:사용", SHELL_ICON, 0, 1, 1));
  startToggles->addItem(new CValueControl("CarrotRadar", "레이더: 당근 앞차 선택(0)", "앞차를 고르는 방식입니다(현대·기아). 0:기존 apilot 방식, 1:당근 방식(옆 차선 차가 끼어들 위험도 함께 계산). 바꾼 뒤 재부팅해야 적용됩니다.", ROAD_ICON, 0, 1, 1));
  startToggles->addItem(new CValueControl("CarrotCutInPredecel", "레이더: 당근 끼어들기 사전감속(0)", "옆 차선 차가 끼어들 것 같으면 미리 살짝 감속합니다(최대 -0.25~-0.65m/s²). '레이더: 당근 앞차 선택'이 1일 때만 동작합니다.", ROAD_ICON, 0, 1, 1));
  startToggles->addItem(new CValueControl("CarrotStoppingLead", "레이더: 당근 정차 앞차 필터(0)", "정차 중 앞차가 멈춰 있는데 레이더 잡음 때문에 출발한 것으로 잘못 아는 것을 막습니다. 앞차가 실제로 0.15m 이상 멀어져야 출발로 판단합니다. '레이더: 당근 앞차 선택'이 1일 때만 동작합니다.", ROAD_ICON, 0, 1, 1));
  startToggles->addItem(new CValueControl("CarrotCutOutRelief", "레이더: 당근 앞차 빠짐 여유(0)", "앞차가 차선을 빠져나가는 것이 확실하면 불필요하게 감속하지 않도록 차간 여유를 조금(최대 0.5초/8m) 줄입니다. CAN FD 레이더 전용이라 지금 C2 레이더(만도/SCC)에서는 동작하지 않습니다.", ROAD_ICON, 0, 1, 1));
  startToggles->addItem(new CValueControl("LongControlActiveSound", "크루즈 알림음", "크루즈가 켜지고 꺼질 때 나는 알림음 크기입니다. 0:끄기, 1:작게, 2:크게", ROAD_ICON, 0, 2, 1));
  startToggles->addItem(new ParamControl("OpkrHotspotOnBoot", "부팅 시 핫스팟 켜기", "켜 두면 기기가 켜질 때 핫스팟(테더링)이 자동으로 켜집니다.", SHELL_ICON, this));
  startToggles->addItem(new ParamControl("CustomMapbox", "맵박스 토큰 입력", "PC나 휴대폰에서 http://기기IP:8082 에 접속해 맵박스 토큰을 입력하면 자동으로 켜집니다. 끄면 입력한 토큰이 지워집니다.", ROAD_ICON, this));
  auto updateBtn = new ButtonControl("업데이트 확인 후 적용", "업데이트");
  QObject::connect(updateBtn, &ButtonControl::clicked, [=]() {
    const char* gitcommit = "/data/openpilot/selfdrive/assets/addon/sh/gitcommit.sh";
    const char* gitpull = "/data/openpilot/selfdrive/assets/addon/sh/gitpull.sh";
    std::system(gitcommit);
    std::system("date '+%F %T' > /data/params/d/LastUpdateTime");
    QString desc = "";
    QString commit_local = QString::fromStdString(Params().get("GitCommit").substr(0, 7));
    QString commit_remote = QString::fromStdString(Params().get("GitCommitRemote").substr(0, 7));
    desc += QString("(Local/Remote): %1/%2\n").arg(commit_local, commit_remote);
    desc += (commit_local == commit_remote) ? QString("No Update exist.") : QString("Update exist.");
    if (ConfirmationDialog::alert(desc, this)) {
      std::system("cd /data/openpilot; rm -f prebuilt");
      std::system(gitpull);
    }
  });
  startToggles->addItem(updateBtn);
  startToggles->addItem(new CPrebuiltToggle());
  auto tmuxlog_btn = new ButtonControl("오류 로그 (Tmux)", "보기");
  QObject::connect(tmuxlog_btn, &ButtonControl::clicked, [=]() {
    const std::string txt = util::read_file("/data/tmux_error.log");
    ConfirmationDialog::alert(QString::fromStdString(txt), this);
  });
  startToggles->addItem(tmuxlog_btn);

  // ---- Cruise: buttons, cruise speed, gap, drive mode, traffic stop ----
  cruiseToggles = new ListWidget(this);
  cruiseToggles->addItem(new CValueControl("CruiseButtonMode", "버튼: 크루즈 속도 모드", "핸들의 크루즈 속도 버튼이 동작하는 방식입니다. 0:순정과 같음, 1~4:사용자 방식(짧게/길게 누를 때 올리고 내리는 폭이 다름)", ROAD_ICON, 0, 4, 1));
  cruiseToggles->addItem(new CValueControl("CruiseSpeedUnit", "버튼: 크루즈 속도 단위", "크루즈 속도 버튼을 한 번 누를 때 바뀌는 속도(km/h)입니다.", ROAD_ICON, 1, 20, 1));
  cruiseToggles->addItem(new CValueControl("CruiseSpeedMin", "크루즈 속도: 하한(10)", "크루즈 설정 속도의 최저값(km/h)입니다. 이보다 낮게 내려가지 않습니다.", ROAD_ICON, 5, 50, 1));
  cruiseToggles->addItem(new CValueControl("CruiseControlMode", "크루즈: 연비 제어(4km/h)", "연비를 위해 크루즈 설정 속도보다 이만큼(km/h) 잠깐 더 빨리 달렸다가 관성으로 줄이는 방식입니다. 0:사용 안 함", ROAD_ICON, 0, 10, 1));
  cruiseToggles->addItem(new CValueControl("AutoSyncCruiseSpeedMax", "크루즈: 자동 속도 동기화 상한(120km/h)", "가속페달로 크루즈 설정 속도보다 빨리 달리면, 페달을 뗄 때 설정 속도를 지금 속도로 올려 줍니다. 이 값(km/h)까지만 올립니다. 0:사용 안 함", ROAD_ICON, 0, 200, 10));
  cruiseToggles->addItem(new CValueControl("AutoSpeedUptoRoadSpeedLimit", "크루즈: 자동 속도 올림(100%)", "앞차를 따라갈 때 도로 제한속도의 이 비율(%)까지 설정 속도를 자동으로 올립니다. 0:사용 안 함, 100:제한속도까지", ROAD_ICON, 0, 200, 10));
  cruiseToggles->addItem(new CValueControl("AutoSpeedAdjustWithLeadCar", "크루즈: 앞차 속도 + 옵셋(+0)", "설정 속도를 앞차 속도보다 이만큼(km/h) 높게 맞춥니다. 거의 쓰지 않는 기능입니다. 0:사용 안 함", ROAD_ICON, 0, 100, 5));
  cruiseToggles->addItem(new CValueControl("TFollowGap1", "차간 1단계: 시간 간격 (110)x0.01초", "차간 1단계(가장 가까움)의 앞차와 시간 간격입니다(0.01초 단위, 110=1.1초). 크면 더 멀리 따라갑니다.", ROAD_ICON, 90, 300, 5));
  cruiseToggles->addItem(new CValueControl("TFollowGap2", "차간 2단계: 시간 간격 (120)x0.01초", "차간 2단계의 앞차와 시간 간격입니다(0.01초 단위, 120=1.2초). 크면 더 멀리 따라갑니다.", ROAD_ICON, 90, 300, 5));
  cruiseToggles->addItem(new CValueControl("TFollowGap3", "차간 3단계: 시간 간격 (140)x0.01초", "차간 3단계의 앞차와 시간 간격입니다(0.01초 단위, 140=1.4초). 크면 더 멀리 따라갑니다.", ROAD_ICON, 90, 300, 5));
  cruiseToggles->addItem(new CValueControl("TFollowGap4", "차간 4단계: 시간 간격 (160)x0.01초", "차간 4단계(가장 멂)의 앞차와 시간 간격입니다(0.01초 단위, 160=1.6초). 크면 더 멀리 따라갑니다.", ROAD_ICON, 90, 300, 5));
  cruiseToggles->addItem(new ParamControl("ApplyLongDynamicCost", "차간: 다이나믹 제어(0)", "켜 두면 앞차 속도 변화에 더 빨리 반응해서 차간 거리를 일정하게 유지하려고 합니다. 대신 가감속이 조금 더 잦을 수 있습니다.", ROAD_ICON, this));
  cruiseToggles->addItem(new CValueControl("TFollowSpeedRatio", "차간: 속도별 보정(110%)", "속도가 빠를수록 차간을 더 벌립니다. 100km/h에서 차간 시간 간격에 이 비율(%)을 곱합니다(110이면 10% 더 멀리). 100:속도와 관계없이 같음", ROAD_ICON, 100, 300, 5));
  cruiseToggles->addItem(new CValueControl("InitMyDrivingMode", "주행 모드: 부팅 시(3)", "기기를 켰을 때 시작하는 주행 모드입니다. 1:연비(부드러운 가속), 2:안전(넉넉한 차간), 3:일반, 4:고속(빠른 반응), 5:자동", ROAD_ICON, 1, 5, 1));
  cruiseToggles->addItem(new CValueControl("MyEcoModeFactor", "주행 모드: 연비 가속 비율(80%)", "연비 모드에서 가속 세기를 일반 모드의 몇 %로 줄일지 정합니다. 낮을수록 더 부드럽게 가속합니다.", ROAD_ICON, 10, 95, 5));
  cruiseToggles->addItem(new CValueControl("MySafeModeFactor", "주행 모드: 안전 비율(80%)", "안전 모드에서 가속, 정지 거리, 감속, 차간을 일반 모드 대비 얼마나 여유 있게 할지 정합니다(%). 낮을수록 더 조심스럽게 달립니다.", ROAD_ICON, 10, 90, 10));
  cruiseToggles->addItem(new CValueControl("TrafficStopMode", "정지: 신호 정지 모드(1)", "빨간 신호를 보고 정지선 앞에서 멈추는 기능입니다. 0:사용 안 함, 1:사용, 2:APilot 방식", ROAD_ICON, 0, 2, 1));
  cruiseToggles->addItem(new CValueControl("TrafficStopAccel", "정지: 감속률(80%)", "신호를 보고 멈출 때 감속 세기(%)입니다. 낮을수록 더 일찍부터 천천히 줄입니다.", ROAD_ICON, 10, 120, 10));
  cruiseToggles->addItem(new CValueControl("ApplyModelDistOrder", "정지: 감속 모델(30)", "신호에서 멈출 때 주행 모델이 예측한 정지 거리를 어느 시점 값으로 쓸지 정합니다. 숫자가 작을수록 미리 감속하고 부드럽게 멈춥니다.", ROAD_ICON, 1, 32, 1));
  cruiseToggles->addItem(new CValueControl("TrafficStopAdjustRatio", "정지: 정지선 보정 비율(90)", "주행 모델이 예측한 정지선 거리에 곱하는 보정 비율(%)입니다. 시험용이니 보통은 그대로 두세요.", ROAD_ICON, 0, 200, 1));
  cruiseToggles->addItem(new CValueControl("TrafficStopDistanceAdjust", "정지: 정지선 거리 보정(200cm)", "신호에서 멈추는 위치를 앞뒤로 옮깁니다(cm). +값이면 정지선에 더 가까이, -값이면 더 멀리 멈춥니다.", ROAD_ICON, -1000, 1000, 10));

  // ---- Speed: curve, speed camera / bump, auto turn ----
  speedToggles = new ListWidget(this);
  speedToggles->addItem(new CValueControl("AutoCurveSpeedCtrlUse", "커브: 자동 감속(1)", "커브를 만나면 미리 속도를 줄입니다. 0:사용 안 함, 1·3:도로 설계 기준(주행 경로의 휘어짐으로 계산), 2:당근 방식(카메라로 앞 커브를 보고 거리에 맞춰 미리 감속)", ROAD_ICON, 0, 3, 1));
  speedToggles->addItem(new CValueControl("CarrotTurnAccel", "커브: 당근 가속 제한(0)", "커브에서 가속을 얼마나 제한할지 정하는 방식입니다. 0:기존(지금 조향각 기준), 1:당근(주행 경로 3초 앞의 휘어짐 기준, 커브 들어가기 전에 미리 가속을 줄임)", ROAD_ICON, 0, 1, 1));
  speedToggles->addItem(new CValueControl("AutoCurveSpeedFactor", "커브: 자동 감속 비율(100%)", "커브 감속 정도입니다(%). 높이면 커브에서 더 빨리 달리고, 낮추면 더 많이 감속합니다.", ROAD_ICON, 50, 300, 1));
  speedToggles->addItem(new CValueControl("AutoCurveSpeedFactorIn", "커브: 진입 비율(10%)", "커브에 들어가는 순간 감속을 얼마나 더할지 정합니다(%). 높이면 커브 입구에서 더 많이 줄입니다.", ROAD_ICON, 0, 300, 1));
  speedToggles->addItem(new CValueControl("AutoNaviSpeedCtrl", "과속카메라: 감속 사용(2)", "과속카메라 앞에서 자동으로 감속합니다. 0:사용 안 함, 1:APM(내비 연동), 2:APM + 순정 내비게이션, 3:NDA", ROAD_ICON, 0, 3, 1));
  speedToggles->addItem(new CValueControl("AutoNaviSpeedCtrlMode", "과속카메라: 감속 방식(1)", "과속카메라 감속을 계산하는 방식입니다. 0:기존 방식, 1:APILOT 방식", ROAD_ICON, 0, 1, 1));
  speedToggles->addItem(new CValueControl("AutoNaviSpeedCtrlStart", "과속카메라: 감속 시작(22초)", "과속카메라 몇 초 전부터 감속을 시작할지 정합니다. 크면 더 멀리서부터 줄입니다.", ROAD_ICON, 10, 50, 1));
  speedToggles->addItem(new CValueControl("AutoNaviSpeedCtrlEnd", "과속카메라: 감속 완료(6초)", "과속카메라 몇 초 전까지 감속을 끝낼지 정합니다. 크면 카메라보다 더 일찍 제한속도에 맞춥니다.", ROAD_ICON, 3, 20, 1));
  speedToggles->addItem(new CValueControl("AutoNaviSpeedDecelRate", "과속카메라: 감속률 x0.01m/s^2(80)", "과속카메라 앞 감속 세기입니다(0.01m/s² 단위). 낮으면 더 멀리서부터 부드럽게 줄입니다.", ROAD_ICON, 10, 200, 10));
  speedToggles->addItem(new CValueControl("AutoNaviSpeedSafetyFactor", "과속카메라: 안전 계수(105%)", "과속카메라 제한속도에 곱하는 비율(%)입니다. 105면 제한속도의 105%까지 허용하고, 낮추면 더 여유 있게 줄입니다.", ROAD_ICON, 80, 120, 1));
  speedToggles->addItem(new CValueControl("AutoNaviSpeedBumpDist", "방지턱: 거리(10m)", "과속방지턱 몇 m 앞에서 아래 방지턱 속도까지 줄일지 정합니다.", ROAD_ICON, 1, 50, 1));
  speedToggles->addItem(new CValueControl("AutoNaviSpeedBumpSpeed", "방지턱: 속도(35km/h)", "과속방지턱을 넘을 때의 속도(km/h)입니다.", ROAD_ICON, 10, 100, 5));
  speedToggles->addItem(new CValueControl("HapticFeedbackWhenSpeedCamera", "과속카메라: 알림 방식", "과속카메라가 가까워질 때 알려 주는 방법입니다. 0:사용 안 함, 1:핸들 진동, 2:계기판 표시, 3:HUD 표시", ROAD_ICON, 0, 3, 1));
  speedToggles->addItem(new CValueControl("AutoTurnControl", "자동 턴: NOO 도우미(0)", "내비 안내에 맞춰 차로 변경과 회전을 도와줍니다(NOO). 0:사용 안 함, 1:외부 내비 연동만, 2:자동 차로 변경, 3:자동 속도 조절", ROAD_ICON, 0, 3, 1));
  speedToggles->addItem(new CValueControl("AutoTurnControlSpeedLaneChange", "자동 턴: 차로변경 속도(60)", "내비 안내로 자동 차로 변경을 할 수 있는 최소 속도(km/h)입니다. 0:사용 안 함", ROAD_ICON, 0, 100, 10));
  speedToggles->addItem(new CValueControl("AutoTurnControlSpeedTurn", "자동 턴: 턴 속도(20)", "내비 안내로 회전(좌·우회전)할 때 줄일 속도(km/h)입니다. 0:사용 안 함", ROAD_ICON, 0, 100, 5));
  speedToggles->addItem(new CValueControl("AutoTurnControlTurnEnd", "자동 턴: 턴 제어 거리시간(3)", "회전 지점 몇 초 전부터 회전 속도 제어를 할지 정합니다(거리 = 속도 x 시간).", ROAD_ICON, 0, 30, 1));

  // ---- Tuning: lateral, longitudinal, accel table ----
  latLongToggles = new ListWidget(this);
  latLongToggles->addItem(new CValueControl("UseLaneLineSpeed", "레인모드 전환 속도(0)", "이 속도(km/h) 이상에서는 차선을 보고 달리는 '레인모드'로 바뀌고, 그보다 느리면 차선 없이 경로를 따라가는 '레인리스'로 달립니다. 0:항상 레인리스", ROAD_ICON, 0, 200, 10));
  latLongToggles->addItem(new CValueControl("AutoLaneChangeSpeed", "차선변경: 최소 속도(30)", "방향지시등을 켰을 때 자동 차선 변경이 되는 최소 속도(km/h)입니다.", ROAD_ICON, 5, 60, 5));
  latLongToggles->addItem(new CValueControl("PathOffset", "조향: 경로 좌우 보정", "차가 차로 안에서 한쪽으로 치우쳐 달리면 보정합니다. -값:왼쪽으로, +값:오른쪽으로 옮깁니다.", ROAD_ICON, -200, 200, 1));
  latLongToggles->addItem(new CValueControl("SteerRatioApply", "조향: 조향비 고정(0x0.1)", "핸들을 돌린 만큼 바퀴가 꺾이는 비율(조향비)을 고정합니다(0.1 단위, 150=15.0). 0:자동 학습값 사용", ROAD_ICON, 0, 300, 2));
  latLongToggles->addItem(new CValueControl("LiveSteerRatioApply", "조향: 실시간 조향비 적용(100)", "자동으로 학습한 조향비를 몇 %로 쓸지 정합니다. 커브에서 너무 많이 꺾이면(오버스티어) 낮추세요.", ROAD_ICON, 50, 110, 1));
  latLongToggles->addItem(new CValueControl("SteerActuatorDelay", "조향: 액추에이터 지연(30)", "조향 명령을 보낸 뒤 실제로 핸들이 움직이기까지 걸리는 시간 보정입니다(0.01초 단위). 커브에서 늦게 꺾이면 조금 올려 보세요.", ROAD_ICON, 0, 100, 1));
  latLongToggles->addItem(new CValueControl("SteeringRateCost", "조향: 조향 속도 비용(700)", "핸들을 얼마나 천천히 돌리게 할지 정합니다. 높이면 부드럽지만 반응이 느리고, 낮추면 빠르지만 흔들릴 수 있습니다.", ROAD_ICON, 0, 2000, 10));
  latLongToggles->addItem(new CValueControl("PathCostApply", "조향: 경로 비용 적용(100)", "계획한 경로를 얼마나 정확히 따라갈지 정합니다(%). 높이면 경로에 더 딱 붙고, 낮추면 더 여유 있게 따라갑니다.", ROAD_ICON, 0, 200, 5));
  latLongToggles->addItem(new CValueControl("LateralAccelCost", "조향: 횡가속 비용(0)", "커브에서 옆으로 쏠리는 힘(횡가속)을 얼마나 줄이려 할지 정합니다. 높이면 쏠림이 적어지지만 경로를 덜 정확히 따라갈 수 있습니다.", ROAD_ICON, 0, 300, 1));
  latLongToggles->addItem(new CValueControl("LateralMotionCost", "조향: 횡움직임 비용(11)", "옆으로 움직이는 동작을 얼마나 아낄지 정합니다. 높이면 덜 움직이고 부드럽지만 반응이 느려집니다.", ROAD_ICON, 0, 50, 1));
  latLongToggles->addItem(new CValueControl("LateralJerkCost", "조향: 횡저크 비용(4)", "조향이 갑자기 바뀌는 것(저크)을 얼마나 막을지 정합니다. 높이면 부드럽지만 반응이 느려집니다.", ROAD_ICON, 0, 50, 1));
  latLongToggles->addItem(new CValueControl("LateralTorqueCustom", "조향: 토크 사용자 설정(0)", "토크 조향 값을 직접 정할지 고릅니다. 0:차량 기본값, 1~2:아래 '토크 가속 계수'와 '토크 마찰 계수'를 사용", ROAD_ICON, 0, 2, 1));
  latLongToggles->addItem(new CValueControl("LateralTorqueAccelFactor", "조향: 토크 가속 계수(2500)", "토크 조향에서 원하는 회전량을 내는 데 필요한 힘 계수입니다. 커브에서 덜 꺾이면 낮추고, 너무 꺾이면 높이세요. '토크 사용자 설정'이 켜져 있을 때만 적용됩니다.", ROAD_ICON, 1000, 4000, 10));
  latLongToggles->addItem(new CValueControl("LateralTorqueFriction", "조향: 토크 마찰 계수(100)", "핸들 마찰을 보정하는 값입니다. 직진에서 핸들이 늦게 반응하면 조금 올려 보세요. '토크 사용자 설정'이 켜져 있을 때만 적용됩니다.", ROAD_ICON, 0, 1000, 10));
  latLongToggles->addItem(new CValueControl("SteerDeltaUp", "조향: 토크 증가 속도(3)", "조향 힘을 한 번에 얼마나 빨리 올릴 수 있는지 정합니다. 높이면 빨리 꺾지만 거칠어질 수 있습니다.", ROAD_ICON, 1, 20, 1));
  latLongToggles->addItem(new CValueControl("SteerDeltaDown", "조향: 토크 감소 속도(7)", "조향 힘을 한 번에 얼마나 빨리 줄일 수 있는지 정합니다.", ROAD_ICON, 1, 20, 1));
  latLongToggles->addItem(new CValueControl("LongitudinalTuningKpV", "가감속: P 게인(100)", "가감속 제어가 목표 속도와의 차이에 얼마나 세게 반응할지 정합니다. 시험용이니 잘 모르면 그대로 두세요.", ROAD_ICON, 50, 150, 1));
  latLongToggles->addItem(new CValueControl("LongitudinalTuningKiV", "가감속: I 게인(200)", "가감속 제어가 쌓인 오차를 얼마나 보정할지 정합니다. 시험용이니 잘 모르면 그대로 두세요.", ROAD_ICON, 0, 2000, 5));
  latLongToggles->addItem(new CValueControl("LongitudinalTuningKf", "가감속: 피드포워드 게인(200)", "목표 가속을 미리 반영하는 정도입니다. 시험용이니 잘 모르면 그대로 두세요.", ROAD_ICON, 0, 200, 1));
  latLongToggles->addItem(new CValueControl("JerkStartLimit", "가감속: 출발 저크(10)x0.1", "정차 후 출발할 때 가속이 얼마나 빨리 붙을지 정합니다(0.1 단위). 높이면 빠르게, 낮추면 부드럽게 출발합니다.", ROAD_ICON, 1, 50, 1));
  latLongToggles->addItem(new CValueControl("StartAccelApply", "가감속: 출발 가속 2.0x(0%)", "정차 후 출발할 때 처음 가속을 몇 % 더 줄지 정합니다. 출발이 굼뜨면 올려 보세요. 0:사용 안 함", ROAD_ICON, 0, 100, 10));
  latLongToggles->addItem(new CValueControl("StopAccelApply", "가감속: 정지 유지 -2.0x(30%)", "멈춰 있을 때 브레이크를 얼마나 세게 잡을지 정합니다(%). 정차 중 차가 밀리면 올려 보세요. 0:사용 안 함", ROAD_ICON, 0, 100, 10));
  latLongToggles->addItem(new CValueControl("StopDistance", "가감속: 앞차 정지 거리(600cm)", "앞차 뒤에 멈출 때의 거리(cm)입니다. 600이면 약 6m 뒤에 멈춥니다.", ROAD_ICON, 200, 1000, 50));
  latLongToggles->addItem(new CValueControl("CruiseMaxVals1", "가속: 0km/h(160)", "이 속도에서 낼 수 있는 최대 가속 세기입니다(단위 0.01m/s²). 높이면 더 빠르게 가속하고, 낮추면 부드럽게 가속합니다.", ROAD_ICON, 1, 250, 5));
  latLongToggles->addItem(new CValueControl("CruiseMaxVals2", "가속: 40km/h(120)", "이 속도에서 낼 수 있는 최대 가속 세기입니다(단위 0.01m/s²). 높이면 더 빠르게 가속하고, 낮추면 부드럽게 가속합니다.", ROAD_ICON, 1, 250, 5));
  latLongToggles->addItem(new CValueControl("CruiseMaxVals3", "가속: 60km/h(100)", "이 속도에서 낼 수 있는 최대 가속 세기입니다(단위 0.01m/s²). 높이면 더 빠르게 가속하고, 낮추면 부드럽게 가속합니다.", ROAD_ICON, 1, 250, 5));
  latLongToggles->addItem(new CValueControl("CruiseMaxVals4", "가속: 80km/h(80)", "이 속도에서 낼 수 있는 최대 가속 세기입니다(단위 0.01m/s²). 높이면 더 빠르게 가속하고, 낮추면 부드럽게 가속합니다.", ROAD_ICON, 1, 250, 5));
  latLongToggles->addItem(new CValueControl("CruiseMaxVals5", "가속: 110km/h(70)", "이 속도에서 낼 수 있는 최대 가속 세기입니다(단위 0.01m/s²). 높이면 더 빠르게 가속하고, 낮추면 부드럽게 가속합니다.", ROAD_ICON, 1, 250, 5));
  latLongToggles->addItem(new CValueControl("CruiseMaxVals6", "가속: 140km/h(60)", "이 속도에서 낼 수 있는 최대 가속 세기입니다(단위 0.01m/s²). 높이면 더 빠르게 가속하고, 낮추면 부드럽게 가속합니다.", ROAD_ICON, 1, 250, 5));
  latLongToggles->addItem(new CValueControl("MaxAngleFrames", "최대 조향각 프레임(89)", "핸들을 크게 돌린 상태가 몇 프레임 이어지면 조향 힘을 잠깐 끊을지 정합니다(현대차 조향 각도 제한). 계기판에 조향 오류가 뜨면 85~87로 낮추세요. 기본 89", ROAD_ICON, 80, 100, 1));

  // ---- Disp: onroad display ----
  dispToggles = new ListWidget(this);
  dispToggles->addItem(new CValueControl("ShowHudMode", "화면 모드", "주행 화면에서 속도 등 정보를 어디에 어떻게 보여줄지 고릅니다. 0:기본, 1:APilot, 2:아래, 3:위, 4:왼쪽, 5:왼쪽 아래, 6:당근(C3X) 스타일 박스", SHELL_ICON, 0, 6, 1));
  dispToggles->addItem(new ParamControl("ShowDebugUI", "디버그 정보", "켜 두면 주행 화면에 개발용 상세 정보를 글자로 보여줍니다.", SHELL_ICON, this));
  dispToggles->addItem(new CValueControl("ShowTpms", "타이어 공기압 정보", "타이어 공기압을 주행 화면에 보여줍니다. 0:안 보임, 1:보임", SHELL_ICON, 0, 1, 1));
  dispToggles->addItem(new CValueControl("ShowDateTime", "시간 정보", "주행 화면에 시간과 날짜를 보여줍니다. 0:안 보임, 1:시간+날짜, 2:시간만, 3:날짜만", SHELL_ICON, 0, 3, 1));
  dispToggles->addItem(new CValueControl("ShowPathEnd", "경로 끝 표시", "주행 경로 끝에 표시를 그립니다. 0:안 보임, 1~2:보임", SHELL_ICON, 0, 2, 1));
  dispToggles->addItem(new CValueControl("ShowDeviceState", "기기 상태", "기기 상태(CPU 온도, 메모리, 저장공간)를 보여줍니다. 0:안 보임, 1:보임", SHELL_ICON, 0, 1, 1));
  dispToggles->addItem(new CValueControl("ShowLaneInfo", "차선 정보", "차선을 얼마나 그릴지 고릅니다. -1:안 그림, 0:경로만, 1:경로+차선, 2:경로+차선+도로 가장자리", SHELL_ICON, -1, 2, 1));
  dispToggles->addItem(new CValueControl("ShowRadarInfo", "레이더 정보", "레이더가 잡은 차들을 화면에 표시합니다. 0:안 보임, 1:보임, 2:상대 위치까지, 3:멈춘 차까지", SHELL_ICON, 0, 3, 1));
  dispToggles->addItem(new CValueControl("ShowPlotMode", "디버그 그래프", "개발용 그래프를 보여줍니다. 0:안 보임, 1~5:그래프 종류", SHELL_ICON, 0, 5, 1));
  dispToggles->addItem(new CValueControl("ShowSteerRotate", "핸들 회전", "핸들 아이콘이 실제 핸들처럼 돌아가게 합니다. 0:고정, 1:회전", SHELL_ICON, 0, 1, 1));
  dispToggles->addItem(new CValueControl("ShowAccelRpm", "가속도 미터", "가속도 막대를 보여줍니다. 0:안 보임, 1:가속도, 2:가속도+엔진(모터) 회전수", SHELL_ICON, 0, 2, 1));
  dispToggles->addItem(new CValueControl("ShowSteerMode", "핸들 표시 모드", "핸들 아이콘 모양을 고릅니다. 0:검정, 1:컬러, 2:안 보임", SHELL_ICON, 0, 2, 1));
  dispToggles->addItem(new CValueControl("ShowConnInfo", "APM 연결 표시", "내비(APM/NDA) 연결 상태 아이콘을 보여줍니다. 0:안 보임, 1:보임", SHELL_ICON, 0, 1, 1));
  dispToggles->addItem(new CValueControl("ShowBlindSpot", "후측방(BSD) 정보", "후측방 감지(BSD) 경고를 화면에 표시합니다. 0:안 보임, 1:보임", SHELL_ICON, 0, 1, 1));
  dispToggles->addItem(new CValueControl("ShowGapInfo", "차간 정보", "차간 단계와 주행 모드를 앞차 표시 옆에 보여줍니다. -1:모두 끔, 0:간단히, 1:보임", SHELL_ICON, -1, 1, 1));
  dispToggles->addItem(new CValueControl("ShowDmInfo", "운전자 모니터링 정보", "운전자 모니터링(얼굴 인식) 아이콘을 보여줍니다. 0:안 보임, 1:보임, -1:기능 끄기(재부팅 필요)", SHELL_ICON, -1, 1, 1));

  // ---- Path: path drawing ----
  pathToggles = new ListWidget(this);
  pathToggles->addItem(new CValueControl("ShowZOffset", "경로 높이 보정(170)", "화면에 그리는 주행 경로의 높이를 맞춥니다. +값:아래로, -값:위로. 경로가 도로에서 떠 보이면 조절하세요.", SHELL_ICON, -300, 300, 10));
  pathToggles->addItem(new CValueControl("ShowPathModeCruiseOff", "경로 모양: 크루즈 OFF", "주행 경로를 화면에 어떤 모양으로 그릴지 고릅니다. 0:기본, 1~2:사각형, 3~4:화살표(^^), 5~6:사각형, 7~8:화살표(^^), 9~12:부드러운 화살표 (크루즈가 꺼져 있을 때)", SHELL_ICON, 0, 15, 1));
  pathToggles->addItem(new CValueControl("ShowPathColorCruiseOff", "경로 색: 크루즈 OFF", "주행 경로 색을 고릅니다. 0:빨강, 1:주황, 2:노랑, 3:초록, 4:파랑, 5:남색, 6:보라, 7:갈색, 8:흰색, 9:검정. 10을 더하면(예: 13) 테두리만 그립니다. (크루즈가 꺼져 있을 때)", SHELL_ICON, 0, 19, 1));
  pathToggles->addItem(new CValueControl("ShowPathMode", "경로 모양: 레인리스", "주행 경로를 화면에 어떤 모양으로 그릴지 고릅니다. 0:기본, 1~2:사각형, 3~4:화살표(^^), 5~6:사각형, 7~8:화살표(^^), 9~12:부드러운 화살표 (레인리스로 달릴 때)", SHELL_ICON, 0, 15, 1));
  pathToggles->addItem(new CValueControl("ShowPathColor", "경로 색: 레인리스", "주행 경로 색을 고릅니다. 0:빨강, 1:주황, 2:노랑, 3:초록, 4:파랑, 5:남색, 6:보라, 7:갈색, 8:흰색, 9:검정. 10을 더하면(예: 13) 테두리만 그립니다. (레인리스로 달릴 때)", SHELL_ICON, 0, 19, 1));
  pathToggles->addItem(new CValueControl("ShowPathModeLane", "경로 모양: 레인모드", "주행 경로를 화면에 어떤 모양으로 그릴지 고릅니다. 0:기본, 1~2:사각형, 3~4:화살표(^^), 5~6:사각형, 7~8:화살표(^^), 9~12:부드러운 화살표 (레인모드로 달릴 때)", SHELL_ICON, 0, 15, 1));
  pathToggles->addItem(new CValueControl("ShowPathColorLane", "경로 색: 레인모드", "주행 경로 색을 고릅니다. 0:빨강, 1:주황, 2:노랑, 3:초록, 4:파랑, 5:남색, 6:보라, 7:갈색, 8:흰색, 9:검정. 10을 더하면(예: 13) 테두리만 그립니다. (레인모드로 달릴 때)", SHELL_ICON, 0, 19, 1));
  pathToggles->addItem(new CValueControl("ShowPathWidth", "경로 폭 비율(100%)", "화면에 그리는 주행 경로의 폭(%)입니다. 100이 기본 폭입니다.", SHELL_ICON, 10, 200, 10));

  toggles_layout->addWidget(cruiseToggles);
  toggles_layout->addWidget(latLongToggles);
  toggles_layout->addWidget(dispToggles);
  toggles_layout->addWidget(pathToggles);
  toggles_layout->addWidget(startToggles);
  toggles_layout->addWidget(speedToggles);
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
  latLongToggles->setVisible(widgetIndex == 3);
  dispToggles->setVisible(widgetIndex == 4);
  pathToggles->setVisible(widgetIndex == 5);
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
    label.setText(QString::fromStdString(Params().get(m_params.toStdString())));
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
