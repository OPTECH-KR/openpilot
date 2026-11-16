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
      tr("openpilot Longitudinal Control (Alpha)"),
      QString("<b>%1</b><br><br>%2")
      .arg(tr("WARNING: openpilot longitudinal control is in alpha for this car and will disable Automatic Emergency Braking (AEB)."))
      .arg(tr("On this car, openpilot defaults to the car's built-in ACC instead of openpilot's longitudinal control. Enable this to switch to openpilot longitudinal control. Enabling Experimental mode is recommended when enabling openpilot longitudinal control alpha.")),
      "../assets/offroad/icon_speed_limit.png",
    },
    {
      "SccConnectedBus2",
      "SCC Module connected BUS2",
      "",
      "../assets/offroad/icon_warning.png",
    },
    {
      "EnableRadarTracks",
      "EnableRadarTracks",
      "Using RadarTracks instead of SCC data. SANTAFE2022HEV",
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
                                  .arg(tr("openpilot defaults to driving in <b>chill mode</b>. Experimental mode enables <b>alpha-level features</b> that aren't ready for chill mode. Experimental features are listed below:"))
                                  .arg(tr("🌮 End-to-End Longitudinal Control 🌮"))
                                  .arg(tr("Let the driving model control the gas and brakes. openpilot will drive as it thinks a human would, including stopping for red lights and stop signs. "
                                       "Since the driving model decides the speed to drive, the set speed will only act as an upper bound. This is an alpha quality feature; mistakes should be expected."))
                                  .arg(tr("New Driving Visualization"))
                                  .arg(tr("The driving visualization will transition to the road-facing wide-angle camera at low speeds to better show some turns. The Experimental mode logo will also be shown in the top right corner."));

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

      const QString no_long = tr("Experimental mode is currently unavailable on this car, since the car's stock ACC is used for longitudinal control.");
      const QString exp_long = tr("Enable experimental longitudinal control to allow experimental mode.");
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
  addItem(new LabelControl(tr("Dongle ID"), getDongleId().value_or(tr("N/A"))));
  addItem(new LabelControl(tr("Serial"), params.get("HardwareSerial").c_str()));

  QHBoxLayout *reset_layout = new QHBoxLayout();
  reset_layout->setSpacing(30);

  // reset calibration button
  QPushButton *restart_openpilot_btn = new QPushButton(tr("Soft restart"));
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
    if (ConfirmationDialog::confirm(tr("Are you sure you want to reset calibration and live params?"), tr("Reset"), this)) {
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

  QPushButton *rebuild_btn = new QPushButton(tr("Rebuild"));
  rebuild_btn->setObjectName("rebuild_btn");
  power_layout->addWidget(rebuild_btn);
  QObject::connect(rebuild_btn, &QPushButton::clicked, [=]() {

    if (ConfirmationDialog::confirm(tr("Are you sure you want to rebuild?"), tr("Reset"), this)) {
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
  auto wifiBtn = new ButtonControl("Wi-Fi Settings", "OPEN");
  QObject::connect(wifiBtn, &ButtonControl::clicked, [=]() { HardwareEon::launch_wifi(); });
  list->addItem(wifiBtn);

  auto tetheringBtn = new ButtonControl("Tethering Settings", "OPEN");
  QObject::connect(tetheringBtn, &ButtonControl::clicked, [=]() { HardwareEon::launch_tethering(); });
  list->addItem(tetheringBtn);
#endif
  ipaddress = new LabelControl("IP Address", "");
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
      font-size: 140px;
      padding-bottom: 20px;
      border-radius: 100px;
      background-color: #292929;
      font-weight: 400;
    }
    QPushButton:pressed {
      background-color: #3B3B3B;
    }
  )");
  close_btn->setFixedSize(200, 200);
  sidebar_layout->addSpacing(45);
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
    {"CarrotPilot", new CarrotPanel(this)},
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
        font-size: 65px;
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

    const int lr_margin = name != tr("Network") ? 50 : 0;  // Network panel handles its own margins
    panel->setContentsMargins(lr_margin, 25, lr_margin, 25);

    ScrollView *panel_frame = new ScrollView(panel, this);
    panel_widget->addWidget(panel_frame);

    QObject::connect(btn, &QPushButton::clicked, [=, w = panel_frame]() {
      btn->setChecked(true);
      panel_widget->setCurrentWidget(w);
    });
  }
  sidebar_layout->setContentsMargins(50, 50, 100, 50);

  // main settings layout, sidebar + main panel
  QHBoxLayout *main_layout = new QHBoxLayout(this);

  sidebar_widget->setFixedWidth(500);
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
  carrotLayout->setMargin(10);

  QHBoxLayout* select_layout = new QHBoxLayout();
  select_layout->setSpacing(10);

  const QStringList tab_names = {"Start", "Cruise", "Speed", "Tuning", "Disp", "Path"};
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
  QPushButton* selectCarBtn = new QPushButton(selected.length() ? selected : tr("SELECT YOUR CAR"));
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
    selectCarBtn->setText(car.length() ? car : tr("SELECT YOUR CAR"));
    main_layout->setCurrentWidget(homeScreen);
  });
  startToggles->addItem(selectCarBtn);
  startToggles->addItem(new CValueControl("EnableAutoEngage", "EnableAutoEngage", "0:Not used,1:Auto Engage/Cruise OFF,2:Auto Engage/Cruise ON", SHELL_ICON, 0, 2, 1));
  startToggles->addItem(new ParamControl("KeepEngage", "Keep Enagage mode", "", SHELL_ICON, this));
  startToggles->addItem(new CValueControl("SoftHoldMode", "SoftHold(1)", "0:Not used,1:Use,2: with SCC(단,사이드가 걸리는 차량이 있음)", ROAD_ICON, 0, 2, 1));
  startToggles->addItem(new CValueControl("CruiseOnDist", "CRUISE: Auto ON distance(0cm)", "When GAS/Brake is OFF, Cruise ON when the lead car gets closer or warning (- value).", ROAD_ICON, -500, 500, 50));
  startToggles->addItem(new CValueControl("AutoResumeFromGas", "GAS CRUISE ON: Use", "Auto Cruise on when GAS pedal released, 60% Gas Cruise On automatically", ROAD_ICON, 0, 2, 1));
  startToggles->addItem(new CValueControl("AutoResumeFromGasSpeed", "GAS CRUISE ON: Speed(30)", "Driving speed exceeds the set value, Cruise ON", ROAD_ICON, 20, 140, 5));
  startToggles->addItem(new CValueControl("AutoResumeFromGasSpeedMode", "GAS CRUISE ON: Set Speed option(0)", "0:Current Speed, 1:Prev. speed, 2: Lead car speed, 3: 60M이상상직진시 이전속도", ROAD_ICON, 0, 3, 1));
  startToggles->addItem(new CValueControl("AutoCancelFromGasMode", "GAS CRUISE OFF: Mode", "Cruise OFF below speed(GAS CRUISE ON: speed). 1:Always, 2:No lear car", ROAD_ICON, 0, 140, 1));
  startToggles->addItem(new ParamControl("AutoResumeFromBrakeRelease", "BRAKE CRUISE ON: Use", "Auto Cruise On when Brake released", ROAD_ICON, this));
  startToggles->addItem(new CValueControl("AutoResumeFromBrakeReleaseDist", "BRAKE CRUISE ON: Moving, LeadCar(20)", "on moving, lead car is greater than the set dist", ROAD_ICON, 0, 80, 5));
  startToggles->addItem(new ParamControl("AutoResumeFromBrakeReleaseLeadCar", "BRAKE CRUISE ON: Stopping, LeadCar", "on stopping, lead car within 10meters", ROAD_ICON, this));
  startToggles->addItem(new CValueControl("AutoResumeFromBrakeCarSpeed", "BRAKE CRUISE ON: Moving, Speed(40)", "on moving, my car is greater then the set dist(no lead car)", ROAD_ICON, 0, 80, 5));
  startToggles->addItem(new ParamControl("AutoResumeFromBrakeReleaseTrafficSign", "BRAKE CRUISE ON: Moving, Traffic signal", "on moving, if traffic signal detected", ROAD_ICON, this));
  startToggles->addItem(new CValueControl("MixRadarInfo", "MixRadarInfo for SCC Rardar", "0:Not used,1:Use", SHELL_ICON, 0, 1, 1));
  startToggles->addItem(new CValueControl("CarrotRadar", "RADAR: carrot Lead Select(0)", "앞차 선택 방식(현대/기아). 0:기존 apilot,1:carrot dPath(끼어들기 위험 감지 포함). 재시작 후 적용", ROAD_ICON, 0, 1, 1));
  startToggles->addItem(new CValueControl("CarrotCutInPredecel", "RADAR: carrot CutIn Predecel(0)", "끼어들기 위험 시 미리 완만하게 감속(-0.25~-0.65m/s^2). RADAR: carrot Lead Select가 1일 때만 동작", ROAD_ICON, 0, 1, 1));
  startToggles->addItem(new CValueControl("CarrotStoppingLead", "RADAR: carrot Stopping Lead(0)", "정차 중 앞차 레이더 속도 잡음을 무시하고 실제로 0.15m 이상 멀어질 때만 출발로 판단. RADAR: carrot Lead Select가 1일 때만 동작", ROAD_ICON, 0, 1, 1));
  startToggles->addItem(new CValueControl("CarrotCutOutRelief", "RADAR: carrot CutOut Relief(0)", "앞차가 차선을 빠져나갈 것이 확인되면 빠져나간 이후 구간의 차간거리 여유를 최대 0.5초/8m만 줄여 불필요한 감속 방지. RADAR: carrot Lead Select=1 필요. 레이더 트랙 상태(trackState)를 주는 CAN FD 레이더 전용이라 현재 C2 레이더(만도/SCC)에서는 동작하지 않음", ROAD_ICON, 0, 1, 1));
  startToggles->addItem(new CValueControl("LongControlActiveSound", "Notify sound 0:OFF,1:Half, 2:ON", "", ROAD_ICON, 0, 2, 1));
  startToggles->addItem(new ParamControl("OpkrHotspotOnBoot", "Hotspot enable on boot", "", SHELL_ICON, this));
  startToggles->addItem(new ParamControl("CustomMapbox", "CustomMapBox입력", "http://IP주소:8082 에 접속하여 mapbox token을 입력하면 자동으로 켜집니다. 끄면, 초기화됩니다.", ROAD_ICON, this));
  auto updateBtn = new ButtonControl("Check Update and Apply", "Update");
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
  auto tmuxlog_btn = new ButtonControl("Tmux error log", tr("RUN"));
  QObject::connect(tmuxlog_btn, &ButtonControl::clicked, [=]() {
    const std::string txt = util::read_file("/data/tmux_error.log");
    ConfirmationDialog::alert(QString::fromStdString(txt), this);
  });
  startToggles->addItem(tmuxlog_btn);

  // ---- Cruise: buttons, cruise speed, gap, drive mode, traffic stop ----
  cruiseToggles = new ListWidget(this);
  cruiseToggles->addItem(new CValueControl("CruiseButtonMode", "Button: Cruise Speed Mode", "0:Normal,1:User1, 2:User2, 3:User3, 4:User4", ROAD_ICON, 0, 4, 1));
  cruiseToggles->addItem(new CValueControl("CruiseSpeedUnit", "Button: Cruise Speed Unit", "", ROAD_ICON, 1, 20, 1));
  cruiseToggles->addItem(new CValueControl("CruiseSpeedMin", "Cruise Speed: Lower limit(10)", "Cruise control MIN speed", ROAD_ICON, 5, 50, 1));
  cruiseToggles->addItem(new CValueControl("CruiseControlMode", "CRUISE: Eco control(4km/h)", "Temporarily increasing the set speed to improve fuel efficiency.", ROAD_ICON, 0, 10, 1));
  cruiseToggles->addItem(new CValueControl("AutoSyncCruiseSpeedMax", "CRUISE: Auto sync speed limit (120km/h)", "Driving speed exceeds target during acceleration, sync. target speed.", ROAD_ICON, 0, 200, 10));
  cruiseToggles->addItem(new CValueControl("AutoSpeedUptoRoadSpeedLimit", "CRUISE: Auto speed up (100%)", "Auto speed up based on the lead car upto RoadSpeedLimit.", ROAD_ICON, 0, 200, 10));
  cruiseToggles->addItem(new CValueControl("AutoSpeedAdjustWithLeadCar", "CRUISE: Auto speed set to lead Car(+0)", "useless, 선행차량의 속도에 옵셋속도를 더한 속도를 설정합니다.", ROAD_ICON, 0, 100, 5));
  cruiseToggles->addItem(new CValueControl("TFollowGap1", "GAP1: Apply TFollow (110)x0.01s", "선행차와의 간격1단계, 속도x시간", ROAD_ICON, 90, 300, 5));
  cruiseToggles->addItem(new CValueControl("TFollowGap2", "GAP2: Apply TFollow (120)x0.01s", "선행차와의 간격2단계, 속도x시간", ROAD_ICON, 90, 300, 5));
  cruiseToggles->addItem(new CValueControl("TFollowGap3", "GAP3: Apply TFollow (140)x0.01s", "선행차와의 간격3단계, 속도x시간", ROAD_ICON, 90, 300, 5));
  cruiseToggles->addItem(new CValueControl("TFollowGap4", "GAP4: Apply TFollow (160)x0.01s", "선행차와의 간격4단계, 속도x시간", ROAD_ICON, 90, 300, 5));
  cruiseToggles->addItem(new ParamControl("ApplyLongDynamicCost", "GAP: Dynamic Control(0)", "전방차량의 간격을 최대한 유지하도록 응답속도가 빨라집니다.", ROAD_ICON, this));
  cruiseToggles->addItem(new CValueControl("TFollowSpeedRatio", "GAP: Dynamic Gap adjust (110%)", "Dynamic Gap adjust based on speed", ROAD_ICON, 100, 300, 5));
  cruiseToggles->addItem(new CValueControl("InitMyDrivingMode", "DRIVEMODE: On boot(3)", "1:ECO,2:SAFE,3:NORMAL,4:HIGH(non E2E mode,5:AUTO)", ROAD_ICON, 1, 5, 1));
  cruiseToggles->addItem(new CValueControl("MyEcoModeFactor", "DRIVEMODE: ECO Accel ratio(80%)", "Acceleartion ratio in ECO mode", ROAD_ICON, 10, 95, 5));
  cruiseToggles->addItem(new CValueControl("MySafeModeFactor", "DRIVEMODE: SAFE ratio(80%)", "Accel/StopDistance/DecelRatio/Gap control ratio", ROAD_ICON, 10, 90, 10));
  cruiseToggles->addItem(new CValueControl("TrafficStopMode", "STOPPING: Traffice Stop Mode (1)", "0:사용안함,1:사용함,2:APilot모드", ROAD_ICON, 0, 2, 1));
  cruiseToggles->addItem(new CValueControl("TrafficStopAccel", "STOPPING: DECEL. rate (80%)", "신호를 만나면 서서히 감속하여 정지합니다.", ROAD_ICON, 10, 120, 10));
  cruiseToggles->addItem(new CValueControl("ApplyModelDistOrder", "STOPPING: DECEL. model (30)", "숫자가적을수록 미리감속하고 서서히 정지합니다.", ROAD_ICON, 1, 32, 1));
  cruiseToggles->addItem(new CValueControl("TrafficStopAdjustRatio", "STOPPING: Stop line adjust ratio (90)", "for Test", ROAD_ICON, 0, 200, 1));
  cruiseToggles->addItem(new CValueControl("TrafficStopDistanceAdjust", "TrafficStop Adjust(200cm)", "+값으로 하면 정지선에 다가갑니다.", ROAD_ICON, -1000, 1000, 10));

  // ---- Speed: curve, speed camera / bump, auto turn ----
  speedToggles = new ListWidget(this);
  speedToggles->addItem(new CValueControl("AutoCurveSpeedCtrlUse", "TURN: Auto Control(1)", "곡선도로를 만나면 속도를 줄여줍니다. 0:사용안함,1:도로설계기준,2:carrot(비전 커브, 거리기반 사전감속)", ROAD_ICON, 0, 3, 1));
  speedToggles->addItem(new CValueControl("CarrotTurnAccel", "TURN: carrot Accel Limit(0)", "커브에서 가속 제한 방식. 0:기존(조향각 기준),1:carrot(모델 경로 3초 앞 곡률 기준)", ROAD_ICON, 0, 1, 1));
  speedToggles->addItem(new CValueControl("AutoCurveSpeedFactor", "TURN: Auto Control ratio(100%)", "커브속도조절(커브속도 조절 3일때 170)", ROAD_ICON, 50, 300, 1));
  speedToggles->addItem(new CValueControl("AutoCurveSpeedFactorIn", "TURN: Auto Control ratio In(10%)", "커브속도조절진입", ROAD_ICON, 0, 300, 1));
  speedToggles->addItem(new CValueControl("AutoNaviSpeedCtrl", tr("SpeedCameraControl(2)"), "0:사용안함, 1:APM, 2:APM + 순정네비게이션, 3:NDA", ROAD_ICON, 0, 3, 1));
  speedToggles->addItem(new CValueControl("AutoNaviSpeedCtrlMode", "SpeedCameraDecelMode(1)", "0:기존방식, 1:APILOT방식", ROAD_ICON, 0, 1, 1));
  speedToggles->addItem(new CValueControl("AutoNaviSpeedCtrlStart", tr("SpeedCameraDecelStart(22s)"), "감속시작시점을 설정합니다. 값이 크면 감속을 카메라에서 멀리 시작", ROAD_ICON, 10, 50, 1));
  speedToggles->addItem(new CValueControl("AutoNaviSpeedCtrlEnd", tr("SpeedCameraDecelEnd(6s)"), "감속완료시점을 설정합니다.값이 크면 카메라에서 멀리 감속 완료", ROAD_ICON, 3, 20, 1));
  speedToggles->addItem(new CValueControl("AutoNaviSpeedDecelRate", "SpeedCameraDecelRatex0.01m/s^2(80)", "낮으면 멀리서부터 감속함", ROAD_ICON, 10, 200, 10));
  speedToggles->addItem(new CValueControl("AutoNaviSpeedSafetyFactor", "SpeedCameraSafetyFactor(105%)", "", ROAD_ICON, 80, 120, 1));
  speedToggles->addItem(new CValueControl("AutoNaviSpeedBumpDist", "SpeedBumpDistance(10M)", "", ROAD_ICON, 1, 50, 1));
  speedToggles->addItem(new CValueControl("AutoNaviSpeedBumpSpeed", "SpeedBumpSpeed(35Km/h)", "", ROAD_ICON, 10, 100, 5));
  speedToggles->addItem(new CValueControl("HapticFeedbackWhenSpeedCamera", "Haptic handle function", "0:사용안함,1:진동,2:계기판,3:HUD표시", ROAD_ICON, 0, 3, 1));
  speedToggles->addItem(new CValueControl("AutoTurnControl", "ATC: NOO Helper(0)", "0:없음,1:외부네비 작동, 2:자동차로변경, 3:자동속도제어", ROAD_ICON, 0, 3, 1));
  speedToggles->addItem(new CValueControl("AutoTurnControlSpeedLaneChange", "ATC: LaneChange Speed (60)", "0:없음,차로변경속도", ROAD_ICON, 0, 100, 10));
  speedToggles->addItem(new CValueControl("AutoTurnControlSpeedTurn", "ATC: Turn Speed (20)", "0:없음, 턴속도", ROAD_ICON, 0, 100, 5));
  speedToggles->addItem(new CValueControl("AutoTurnControlTurnEnd", "ATC: Turn CtrlDistTime (3)", "속도*거리", ROAD_ICON, 0, 30, 1));

  // ---- Tuning: lateral, longitudinal, accel table ----
  latLongToggles = new ListWidget(this);
  latLongToggles->addItem(new CValueControl("UseLaneLineSpeed", "Laneline mode speed(0)", "0: Always laneless, 으로 하면 안함", ROAD_ICON, 0, 200, 10));
  latLongToggles->addItem(new CValueControl("AutoLaneChangeSpeed", "LANE CHANGE: Speed (30)", "해당속도 이상에서만 자동차선변경", ROAD_ICON, 5, 60, 5));
  latLongToggles->addItem(new CValueControl("PathOffset", "LAT: PathOffset", "(-)Left, (+)Right", ROAD_ICON, -200, 200, 1));
  latLongToggles->addItem(new CValueControl("SteerRatioApply", "LAT: SteerRatio적용(0x0.1)", "0:사용안함", ROAD_ICON, 0, 300, 2));
  latLongToggles->addItem(new CValueControl("LiveSteerRatioApply", "LAT: LiveSteerRatioApply(100)", "오버스티어가 발생하면 줄입니다.", ROAD_ICON, 50, 110, 1));
  latLongToggles->addItem(new CValueControl("SteerActuatorDelay", "LAT:SteerActuatorDelay(30)", "표준", ROAD_ICON, 0, 100, 1));
  latLongToggles->addItem(new CValueControl("SteeringRateCost", "LAT: SteeringRateCost(700)", "", ROAD_ICON, 0, 2000, 10));
  latLongToggles->addItem(new CValueControl("PathCostApply", "LAT: PathCostApply(100)", "", ROAD_ICON, 0, 200, 5));
  latLongToggles->addItem(new CValueControl("LateralAccelCost", "LAT: LateralAccelCost(0)", "", ROAD_ICON, 0, 300, 1));
  latLongToggles->addItem(new CValueControl("LateralMotionCost", "LAT: LateralMotionCost(11)", "", ROAD_ICON, 0, 50, 1));
  latLongToggles->addItem(new CValueControl("LateralJerkCost", "LAT: LateralJerkCost(4)", "", ROAD_ICON, 0, 50, 1));
  latLongToggles->addItem(new CValueControl("LateralTorqueCustom", "LAT: TorqueCustom(0)", "", ROAD_ICON, 0, 2, 1));
  latLongToggles->addItem(new CValueControl("LateralTorqueAccelFactor", "LAT: TorqueAccelFactor(2500)", "", ROAD_ICON, 1000, 4000, 10));
  latLongToggles->addItem(new CValueControl("LateralTorqueFriction", "LAT: TorqueFriction(100)", "", ROAD_ICON, 0, 1000, 10));
  latLongToggles->addItem(new CValueControl("SteerDeltaUp", "LAT: SteerDeltaUp(3)", "", ROAD_ICON, 1, 20, 1));
  latLongToggles->addItem(new CValueControl("SteerDeltaDown", "LAT: SteerDeltaDown(7)", "", ROAD_ICON, 1, 20, 1));
  latLongToggles->addItem(new CValueControl("LongitudinalTuningKpV", "LONG: P Gain(100)", "(시험용) ", ROAD_ICON, 50, 150, 1));
  latLongToggles->addItem(new CValueControl("LongitudinalTuningKiV", "LONG: I Gain(200)", "(시험용) ", ROAD_ICON, 0, 2000, 5));
  latLongToggles->addItem(new CValueControl("LongitudinalTuningKf", "LONG: FF Gain(200)", "(시험용) ", ROAD_ICON, 0, 200, 1));
  latLongToggles->addItem(new CValueControl("JerkStartLimit", "LONG: JERK START(10)x0.1", "Starting Jerk.", ROAD_ICON, 1, 50, 1));
  latLongToggles->addItem(new CValueControl("StartAccelApply", "LONG: StartingAccel 2.0x(0%)", "정지->출발시 가속도의 가속율을 지정합니다 0: 사용안함.", ROAD_ICON, 0, 100, 10));
  latLongToggles->addItem(new CValueControl("StopAccelApply", "LONG: StoppingAccel -2.0x(30%)", "정지유지시 브레이크압을 조정합니다. 0: 사용안함. ", ROAD_ICON, 0, 100, 10));
  latLongToggles->addItem(new CValueControl("StopDistance", "LONG: StopDistance(600cm)", "선행차와 정지하는 거리를 입력합니다.", ROAD_ICON, 200, 1000, 50));
  latLongToggles->addItem(new CValueControl("CruiseMaxVals1", "ACCEL:0km/h(160)", "속도별 가속도를 지정합니다.(x0.01m/s^2)", ROAD_ICON, 1, 250, 5));
  latLongToggles->addItem(new CValueControl("CruiseMaxVals2", "ACCEL:40km/h(120)", "속도별 가속도를 지정합니다.(x0.01m/s^2)", ROAD_ICON, 1, 250, 5));
  latLongToggles->addItem(new CValueControl("CruiseMaxVals3", "ACCEL:60km/h(100)", "속도별 가속도를 지정합니다.(x0.01m/s^2)", ROAD_ICON, 1, 250, 5));
  latLongToggles->addItem(new CValueControl("CruiseMaxVals4", "ACCEL:80km/h(80)", "속도별 가속도를 지정합니다.(x0.01m/s^2)", ROAD_ICON, 1, 250, 5));
  latLongToggles->addItem(new CValueControl("CruiseMaxVals5", "ACCEL:110km/h(70)", "속도별 가속도를 지정합니다.(x0.01m/s^2)", ROAD_ICON, 1, 250, 5));
  latLongToggles->addItem(new CValueControl("CruiseMaxVals6", "ACCEL:140km/h(60)", "속도별 가속도를 지정합니다.(x0.01m/s^2)", ROAD_ICON, 1, 250, 5));
  latLongToggles->addItem(new CValueControl("MaxAngleFrames", "MaxAngleFrames(89)", "89:기본, 스티어계기판에러시 85~87", ROAD_ICON, 80, 100, 1));

  // ---- Disp: onroad display ----
  dispToggles = new ListWidget(this);
  dispToggles->addItem(new CValueControl("ShowHudMode", "Display Mode", "0:Normal,1:APilot,2:Bottom,3:Top,4:Left,5:Left-Bottom,6:Carrot(C3X)", SHELL_ICON, 0, 6, 1));
  dispToggles->addItem(new ParamControl("ShowDebugUI", "Debug Info", "", SHELL_ICON, this));
  dispToggles->addItem(new CValueControl("ShowTpms", "Tpms Info", "0:None,1:Display", SHELL_ICON, 0, 1, 1));
  dispToggles->addItem(new CValueControl("ShowDateTime", "Time Info", "0:None,1:Time/Date,2:Time,3:Date", SHELL_ICON, 0, 3, 1));
  dispToggles->addItem(new CValueControl("ShowPathEnd", "Path End", "0:None,1:Display", SHELL_ICON, 0, 2, 1));
  dispToggles->addItem(new CValueControl("ShowDeviceState", "Device State", "0:None,1:Display", SHELL_ICON, 0, 1, 1));
  dispToggles->addItem(new CValueControl("ShowLaneInfo", "Lane Info", "-1:None, 0:Path, 1:Path+Lane, 2: Path+Lane+RoadEdge", SHELL_ICON, -1, 2, 1));
  dispToggles->addItem(new CValueControl("ShowRadarInfo", "Radar Info", "0:None,1:Display,2:RelPos,3:Stopped Car", SHELL_ICON, 0, 3, 1));
  dispToggles->addItem(new CValueControl("ShowPlotMode", "Debug plot", "", SHELL_ICON, 0, 5, 1));
  dispToggles->addItem(new CValueControl("ShowSteerRotate", "Handle rotate", "0:None,1:Rotate", SHELL_ICON, 0, 1, 1));
  dispToggles->addItem(new CValueControl("ShowAccelRpm", "Accel meter", "0:None,1:Display,2:Accel+RPM", SHELL_ICON, 0, 2, 1));
  dispToggles->addItem(new CValueControl("ShowSteerMode", "Handle Display Mode", "0:Black,1:Color,2:None", SHELL_ICON, 0, 2, 1));
  dispToggles->addItem(new CValueControl("ShowConnInfo", "APM connection", "0:None,1:Display", SHELL_ICON, 0, 1, 1));
  dispToggles->addItem(new CValueControl("ShowBlindSpot", "BSD Info", "0:None,1:Display", SHELL_ICON, 0, 1, 1));
  dispToggles->addItem(new CValueControl("ShowGapInfo", "GAP Info", "0:None,1:Display", SHELL_ICON, -1, 1, 1));
  dispToggles->addItem(new CValueControl("ShowDmInfo", "DM Info", "0:None,1:Display,-1:Disable(Reboot)", SHELL_ICON, -1, 1, 1));

  // ---- Path: path drawing ----
  pathToggles = new ListWidget(this);
  pathToggles->addItem(new CValueControl("ShowZOffset", "Path Height adjust(170)", "(+) Down, (-) Up", SHELL_ICON, -300, 300, 10));
  pathToggles->addItem(new CValueControl("ShowPathModeCruiseOff", "Path Mode: Cruise OFF", "0:Normal,1,2:Rec,3,4:^^,5,6:Rec,7,8:^^,9,10,11,12:Smooth^^", SHELL_ICON, 0, 15, 1));
  pathToggles->addItem(new CValueControl("ShowPathColorCruiseOff", "Path Color: Cruise OFF", "(+10:Stroke)0:Red,1:Orange,2:Yellow,3:Green,4:Blue,5:Indigo,6:Violet,7:Brown,8:White,9:Black", SHELL_ICON, 0, 19, 1));
  pathToggles->addItem(new CValueControl("ShowPathMode", "Path Mode: Laneless", "0:Normal,1,2:Rec,3,4:^^,5,6:Rec,7,8:^^,9,10,11,12:Smooth^^", SHELL_ICON, 0, 15, 1));
  pathToggles->addItem(new CValueControl("ShowPathColor", "Path Color: Laneless", "(+10:Stroke)0:Red,1:Orange,2:Yellow,3:Green,4:Blue,5:Indigo,6:Violet,7:Brown,8:White,9:Black", SHELL_ICON, 0, 19, 1));
  pathToggles->addItem(new CValueControl("ShowPathModeLane", "Path Mode: LaneMode", "0:Normal,1,2:Rec,3,4:^^,5,6:Rec,7,8:^^,9,10,11,12:Smooth^^", SHELL_ICON, 0, 15, 1));
  pathToggles->addItem(new CValueControl("ShowPathColorLane", "Path Color: LaneMode", "(+10:Stroke)0:Red,1:Orange,2:Yellow,3:Green,4:Blue,5:Indigo,6:Violet,7:Brown,8:White,9:Black", SHELL_ICON, 0, 19, 1));
  pathToggles->addItem(new CValueControl("ShowPathWidth", "Path Width ratio(100%)", "", SHELL_ICON, 10, 200, 10));

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
    btnminus.setFixedSize(150, 100);
    btnplus.setFixedSize(150, 100);
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

  combobox.addItem(tr("Select Your TimeZone"));
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
    if (btn.text() == tr("UNSET")) {
      if (ConfirmationDialog::confirm(tr("Do you want to set default?"), tr("Reboot"), this)) {
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
      if (ConfirmationDialog::confirm(tr("Press OK to set your timezone as") + "\n" + str, tr("Reboot"), this)) {
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
    btn.setText(tr("UNSET"));
  } else {
    btn.setEnabled(false);
    btn.setText(tr("SET"));
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

  list->addItem(tr("[ Not selected ]"));

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
