#include "selfdrive/ui/qt/offroad/settings.h"

#include <cassert>
#include <cmath>
#include <string>
#include <tuple>
#include <vector>

#include <QDebug>

#ifndef QCOM
#include "selfdrive/ui/qt/offroad/networking.h"
#endif

#include "common/params.h"
#include "common/watchdog.h"
#include "common/util.h"
#include "system/hardware/hw.h"
#include "selfdrive/ui/qt/widgets/controls.h"
#include "selfdrive/ui/qt/widgets/input.h"
#include "selfdrive/ui/qt/widgets/scrollview.h"
#include "selfdrive/ui/qt/widgets/ssh_keys.h"
#include "selfdrive/ui/qt/widgets/toggle.h"
#include "selfdrive/ui/ui.h"
#include "selfdrive/ui/qt/util.h"
#include "selfdrive/ui/qt/qt_window.h"
#include "selfdrive/ui/qt/widgets/input.h"
#include "selfdrive/ui/qt/offroad/settings_dp.h"
#include "selfdrive/ui/qt/offroad/optech_panel.h"

// car selection panel
#include <QJsonObject>
#include <QJsonDocument>
#include <QJsonArray>
#include <QListWidget>
CarSelectionPanel::CarSelectionPanel(SettingsWindow *parent) : QWidget(parent) {
  Params params;

  QVBoxLayout *layout = new QVBoxLayout;
  layout->setContentsMargins(QMargins());
  QString list = QString::fromStdString((params.get("dp_car_list")).c_str());
  QJsonDocument document = QJsonDocument::fromJson(list.toUtf8());
  QJsonObject object = document.object();
  QJsonArray models = object.value("cars").toArray();

  QListWidget* car_list = new QListWidget(this);
  car_list->setStyleSheet(R"(
    QScrollBar:vertical {
      width: 150px;
    }
  )");
  car_list->setFixedHeight(750);
  car_list->addItem(tr("[AUTO SELECT]"));
  int model_size = models.size();
  for (int i = 0; i < model_size; i++) {
    car_list->addItem(models.at(i).toString());
  }

  QObject::connect(car_list, QOverload<QListWidgetItem*>::of(&QListWidget::itemClicked), [=](QListWidgetItem* item) {
    QString text = item->text();
    Params().put("dp_car_assigned", text == tr("[AUTO SELECT]")? "" : text.toStdString());
    item->setSelected(false);
    emit carSelected();
    parent->closeSettings();
  });

  layout->addWidget(car_list);
  setLayout(layout);
}

// 토글 page in the same order, names and texts as optech-hkg. 실험 모드 / openpilot 가감속 sit 2nd and 3rd as on hkg,
// followed by the spst-only 옛 주행 모델 and 자동 E2E (user 2026-11-23: these belong here, not in OPTECH 고급).
// Other spst-only switches live in the OPTECH tabs (주행 기록 저장 -> 고급, 가속 페달 -> 주행, 주행 성향 -> 속도).
static int optech_dm_mode() {
  const int m = std::atoi(Params().get("OptechDmMode").c_str());
  return (m < 0 || m > 2) ? 0 : m;
}

// Hyundai / Kia / Genesis items: shown for those cars and while the car is not known yet (nothing chosen, never
// started in a car); hidden only once another brand is chosen or detected (user 2026-11-23: LDWS 차량 was missing)
static bool optech_hkg_car() {
  Params params;
  const QString assigned = QString::fromStdString(params.get("dp_car_assigned")).trimmed();
  if (!assigned.isEmpty()) {
    const QString brand = assigned.section(' ', 0, 0);
    return brand == "HYUNDAI" || brand == "KIA" || brand == "GENESIS";
  }
  const std::string cp_bytes = params.get("CarParamsPersistent");
  if (cp_bytes.empty()) return true;
  AlignedBuffer aligned_buf;
  capnp::FlatArrayMessageReader cmsg(aligned_buf.align(cp_bytes.data(), cp_bytes.size()));
  return QString::fromStdString(cmsg.getRoot<cereal::CarParams>().getCarName()) == "hyundai";
}

TogglesPanel::TogglesPanel(SettingsWindow *parent) : ListWidget(parent) {
  // param, title, desc, icon
  std::vector<std::tuple<QString, QString, QString, QString>> toggle_defs{
    {
      "OpenpilotEnabledToggle",
      "openpilot 사용",
      "어댑티브 크루즈 컨트롤 및 차선 유지 운전자 보조를 위해 openpilot 시스템을 사용하십시오. 이 기능을 사용하려면 항상 주의를 기울여야 합니다. "
      "설정변경은 장치 재부팅후 적용됩니다.",
      "../assets/offroad/icon_openpilot.png",
    },
    {
      "ExperimentalMode",
      "실험 모드",
      "",
      "../assets/img_experimental_white.svg",
    },
    {
      "ExperimentalLongitudinalEnabled",
      "openpilot 가감속 제어 (알파)",
      QString("<b>%1</b><br><br>%2")
      .arg("주의: 이 차에서는 아직 시험 단계이고, 켜면 차의 자동 긴급 제동(AEB)이 꺼집니다.")
      .arg("처음에는 차의 순정 크루즈(ACC)가 속도를 맡습니다. 이것을 켜면 openpilot이 가속과 감속을 직접 맡습니다. "
           "이 차가 지원할 때만 보이고, 시동을 다시 걸면 적용됩니다."),
      "../assets/offroad/icon_speed_limit.png",
    },
    {
      "dp_0813",
      "옛 주행 모델 사용 (0.8.13.1)",
      "C2에서 가볍게 도는 예전 주행 모델(0.8.13.1)을 씁니다(처음 값: 꺼짐).\n"
      "켜 두면 기기 부담과 발열이 줄지만, 실험 모드, openpilot 가감속(알파), 자동 E2E / ACC 전환, 과속 카메라 감속은 동작하지 않습니다.\n"
      "꺼 두면 새 주행 모델(0.8.16)을 씁니다. 기기가 너무 뜨거워지거나 느려지면 켜 보세요.\n재부팅해야 적용됩니다.",
      "../assets/offroad/icon_road.png",
    },
    {
      "dp_long_de2e",
      "자동 E2E / ACC 전환",
      "상황에 따라 E2E(카메라 판단) 가감속과 ACC(앞차 기준) 가감속을 자동으로 바꿉니다.\nopenpilot이 가감속을 맡는 차량만 해당됩니다.",
      "../assets/img_experimental_grey.svg",
    },
    {
      // OPKR 'LDWS 차량 설정' (LdwsCarFix): hyundaican.create_lkas11 sends CF_Lkas_LdwsOpt_USM = 3
      "OptechLdwsCar",
      "LDWS 차량 (차로 유지 보조 없음)",
      "차선 이탈 경고(LDWS)만 있고 차로 유지 보조(LKAS)가 없는 차만 켜세요. "
      "이런 차에서 조향이 안 되거나 계기판에 차로 유지 관련 오류가 뜰 때 씁니다 (OPKR의 'LDWS 차량 설정'과 같습니다). "
      "LKAS가 있는 차는 켜지 마세요. 현대·기아·제네시스에서만 보입니다. 재부팅해야 적용됩니다.",
      "../assets/offroad/icon_warning.png",
    },
    {
      "IsLdwEnabled",
      "차선 이탈 경고 사용",
      "차량이 50km/h(31mph) 이상의 속도로 주행하는 동안 방향지시등 없이 감지된 차선 위를 주행할 경우 차선이탈 경고를 표시합니다.",
      "../assets/offroad/icon_warning.png",
    },
    {
      "IsMetric",
      "미터법 사용",
      "mph 대신 km/h로 속도를 표시합니다.",
      "../assets/offroad/icon_metric.png",
    },
    {
      "RecordFront",
      "운전자 카메라 녹화 및 업로드",
      "운전자를 보는 카메라 영상도 주행 기록에 함께 저장합니다. (이 버전은 부팅할 때 자동으로 켜지고, 서버로 올리지는 않습니다.)",
      "../assets/offroad/icon_monitoring.png",
    },
#ifdef ENABLE_MAPS
    {
      "NavSettingTime24h",
      "도착 시간 24시간 표시",
      "도착 예정 시간을 오전/오후 대신 24시간으로 보여 줍니다.",
      "../assets/offroad/icon_metric.png",
    },
    {
      "NavSettingLeftSide",
      "지도를 왼쪽에 표시",
      "화면을 나눠 볼 때 지도를 왼쪽에 보여 줍니다.",
      "../assets/offroad/icon_road.png",
    },
#endif
  };

  for (auto &[param, title, desc, icon] : toggle_defs) {
    auto toggle = new ParamControl(param, title, desc, icon, this);

    bool locked = params.getBool((param + "Lock").toStdString());
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
  connect(toggles["dp_0813"], &ToggleControl::toggleFlipped, [=]() {
    updateToggles();
  });

  // 운전자 모니터링: 기본 사용 / 경도 사용 / 사용 안 함 (optech-hkg; the icon switch is on OPTECH > 화면).
  // 경도 사용 and 사용 안 함 turn the driver camera off (dp_device_no_ir_ctrl); 경도 사용 runs dpmonitoringd instead
  {
    const QStringList dm_names = {"기본 사용", "경도 사용", "사용 안 함"};
    const QString dm_desc =
      "운전자가 운전에 집중하는지 확인하는 방식입니다.\n"
      "바꾼 뒤 기기를 다시 켜야 적용됩니다.\n"
      "\n"
      "[기본 사용] 운전자 카메라로 얼굴을 봅니다.\n"
      "· 앞을 안 보거나 졸면 경고하고, 계속되면 크게 경고합니다\n"
      "\n"
      "[경도 사용] 카메라를 쓰지 않습니다. (기기 발열이 줄어듭니다)\n"
      "· 핸들·페달·크루즈 버튼을 5분 동안 전혀 안 쓰면 경고합니다 (15초 전부터 알림)\n"
      "· 하나라도 쓰면 처음부터 다시 셉니다\n"
      "\n"
      "[사용 안 함] 카메라도, 경고도 없습니다.\n"
      "· 운전자가 반응이 없어도 계속 운전하므로 사용을 추천하지 않습니다\n"
      "\n"
      "[경고가 계속되면]\n"
      "· openpilot이 가감속을 맡는 차량: 천천히 감속합니다\n"
      "· 차의 순정 크루즈를 쓰는 차량: 감속하지 않으니 직접 운전해 주세요\n"
      "· 비상등은 켜지지 않습니다";
    auto dm_btn = new ButtonControl("", "선택", dm_desc);
    auto dm_title = [=]() { dm_btn->setTitle("운전자 모니터링: " + dm_names[optech_dm_mode()]); };
    dm_title();
    QObject::connect(dm_btn, &ButtonControl::clicked, [=]() {
      // show the explanation first, then the choice
      ConfirmationDialog info("<b>운전자 모니터링</b><br><br>" + dm_desc.toHtmlEscaped().replace("\n", "<br>"),
                              "선택하기", "취소", true, this);
      if (!info.exec()) return;
      const QString cur = dm_names[optech_dm_mode()];
      const QString sel = MultiOptionDialog::getSelection("운전자 모니터링", dm_names, cur, this);
      if (sel.isEmpty() || sel == cur) return;
      const int m = dm_names.indexOf(sel);
      Params p;
      p.put("OptechDmMode", std::to_string(m));
      p.putBool("dp_device_no_ir_ctrl", m != 0);
      if (m != 0) {
        p.put("ShowDmInfo", "-1");
      } else if (std::atoi(p.get("ShowDmInfo").c_str()) < 0) {
        p.put("ShowDmInfo", "1");
      }
      dm_title();
      ConfirmationDialog::alert("기기를 다시 켜야 적용됩니다.", this);
    });
    addItem(dm_btn);
  }
}

void TogglesPanel::expandToggleDescription(const QString &param) {
  toggles[param.toStdString()]->showDescription();
}

void TogglesPanel::showEvent(QShowEvent *event) {
  updateToggles();
}

void TogglesPanel::updateToggles() {
  auto experimental_mode_toggle = toggles["ExperimentalMode"];
  auto op_long_toggle = toggles["ExperimentalLongitudinalEnabled"];
  toggles["OptechLdwsCar"]->setVisible(optech_hkg_car());

  const QString e2e_description = QString("%1<br><h4>%2</h4><br>%3")
                                  .arg("openpilot은 처음에 <b>편안한 모드</b>로 달립니다. 실험 모드를 켜면 아직 시험 중인 기능을 씁니다:")
                                  .arg("카메라 판단 가감속 (E2E)")
                                  .arg("주행 모델이 직접 가속과 감속을 정합니다. 사람처럼 판단해서 빨간불이나 정지 표지판 앞에서 멈추기도 합니다. "
                                       "설정 속도는 '최고 속도'로만 쓰입니다. 시험 기능이라 실수할 수 있으니 항상 주의하세요.");

  const bool is_release = params.getBool("IsReleaseBranch");
  const bool is_old_model = params.getBool("dp_0813");
  auto cp_bytes = params.get("CarParamsPersistent");
  // the old 0.8.13.1 model cannot use 실험 모드 / openpilot 가감속; openpilot 가감속 only shows when the car offers it
  if (is_old_model) {
    params.remove("ExperimentalMode");
    params.remove("ExperimentalLongitudinalEnabled");
    op_long_toggle->setVisible(false);
    experimental_mode_toggle->setEnabled(false);
    experimental_mode_toggle->setDescription("<b>옛 주행 모델을 켜 두면 실험 모드를 쓸 수 없습니다.</b><br><br>" + e2e_description);
    experimental_mode_toggle->refresh();
  } else if (!cp_bytes.empty()) {
    AlignedBuffer aligned_buf;
    capnp::FlatArrayMessageReader cmsg(aligned_buf.align(cp_bytes.data(), cp_bytes.size()));
    cereal::CarParams::Reader CP = cmsg.getRoot<cereal::CarParams>();

    const bool long_available = CP.getExperimentalLongitudinalAvailable() && !is_release;
    if (!long_available) {
      params.remove("ExperimentalLongitudinalEnabled");
    }
    op_long_toggle->setVisible(long_available);
    op_long_toggle->refresh();
    if (hasLongitudinalControl(CP)) {
      experimental_mode_toggle->setEnabled(true);
      experimental_mode_toggle->setDescription(e2e_description);
    } else {
      experimental_mode_toggle->setEnabled(false);
      params.remove("ExperimentalMode");
      experimental_mode_toggle->setDescription("<b>이 차는 순정 크루즈(ACC)가 속도를 맡고 있어서, 지금은 실험 모드를 쓸 수 없습니다.</b><br><br>" + e2e_description);
    }
    experimental_mode_toggle->refresh();
  } else {
    // no car seen yet: 실험 모드 can be set ahead, openpilot 가감속 waits until the car says it is available
    op_long_toggle->setVisible(false);
    experimental_mode_toggle->setEnabled(true);
    experimental_mode_toggle->setDescription(e2e_description);
  }
}

DevicePanel::DevicePanel(SettingsWindow *parent) : ListWidget(parent) {
//  setSpacing(50);
  auto tmuxBtn = new ButtonControl(tr("Debug Console"), tr("VIEW"), "");
  connect(tmuxBtn, &ButtonControl::clicked, [=]() {
    FILE* pipe = popen("tmux capture-pane -p -t 0 -S -250", "r");
    if (pipe) {
      char buffer[128];
      std::string result = "";
      while (!feof(pipe)) {
        if (fgets(buffer, 128, pipe) != nullptr) {
          // rick - reversely
          result = std::string(buffer) + result;
        }
      }
      pclose(pipe);
      ConfirmationDialog::rich(QString::fromStdString(result), this);
    } else {
      ConfirmationDialog::rich(tr("Error displaying tmux output."), this);
    }
  });
  addItem(tmuxBtn);

  addItem(new LabelControl(tr("Dongle ID"), getDongleId().value_or(tr("N/A"))));
  addItem(new LabelControl(tr("Serial"), params.get("HardwareSerial").c_str()));

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
      params.put("LanguageSetting", langs[selection].toStdString());
      qApp->exit(18);
      watchdog_kick(0);
    }
  });
  addItem(translateBtn);

  #ifdef QCOM
  auto sysVolBtn = new ButtonControl(tr("Adjust System Sound Settings"), tr("ADJUST"), "");
  connect(sysVolBtn, &ButtonControl::clicked, [=]() {
    QObject::connect(sysVolBtn, &ButtonControl::clicked, [=]() { HardwareEon::launch_vol(); });
  });
  addItem(sysVolBtn);
  #endif

//  QObject::connect(uiState(), &UIState::offroadTransition, [=](bool offroad) {
//    for (auto btn : findChildren<ButtonControl *>()) {
//      btn->setEnabled(offroad);
//    }
//  });

  // power buttons
  QHBoxLayout *power_layout = new QHBoxLayout();
  power_layout->setSpacing(30);

  QPushButton *reboot_btn = new QPushButton(tr("Reboot"));
  reboot_btn->setObjectName("reboot_btn");
  power_layout->addWidget(reboot_btn);
  QObject::connect(reboot_btn, &QPushButton::clicked, this, &DevicePanel::reboot);

  QPushButton *poweroff_btn = new QPushButton(tr("Power Off"));
  poweroff_btn->setObjectName("poweroff_btn");
  power_layout->addWidget(poweroff_btn);
  QObject::connect(poweroff_btn, &QPushButton::clicked, this, &DevicePanel::poweroff);

  if (!Hardware::PC()) {
    connect(uiState(), &UIState::offroadTransition, poweroff_btn, &QPushButton::setVisible);
  }

  setStyleSheet(R"(
    #reboot_btn { height: 120px; border-radius: 0px; background-color: #393939; }
    #reboot_btn:pressed { background-color: #4a4a4a; }
    #poweroff_btn { height: 120px; border-radius: 0px; background-color: #E22C2C; }
    #poweroff_btn:pressed { background-color: #FF2424; }
  )");
  addItem(power_layout);
}

void DevicePanel::updateCalibDescription() {
  QString desc =
      tr("openpilot requires the device to be mounted within 4° left or right and "
         "within 5° up or 8° down. openpilot is continuously calibrating, resetting is rarely required.");
  std::string calib_bytes = params.get("CalibrationParams");
  if (!calib_bytes.empty()) {
    try {
      AlignedBuffer aligned_buf;
      capnp::FlatArrayMessageReader cmsg(aligned_buf.align(calib_bytes.data(), calib_bytes.size()));
      auto calib = cmsg.getRoot<cereal::Event>().getLiveCalibration();
      if (calib.getCalStatus() != cereal::LiveCalibrationData::Status::UNCALIBRATED) {
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
        params.putBool("DoReboot", true);
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
        params.putBool("DoShutdown", true);
      }
    }
  } else {
    ConfirmationDialog::alert(tr("Disengage to Power Off"), this);
  }
}

C2NetworkPanel::C2NetworkPanel(QWidget *parent) : QWidget(parent) {
  QVBoxLayout *layout = new QVBoxLayout(this);
//  layout->setContentsMargins(50, 0, 50, 0);

  ListWidget *list = new ListWidget();
  list->setSpacing(30);
  // wifi + tethering buttons

#ifdef QCOM
  auto wifiBtn = new ButtonControl(tr("Wi-Fi Settings"), tr("OPEN"));
  QObject::connect(wifiBtn, &ButtonControl::clicked, [=]() { HardwareEon::launch_wifi(); });
  list->addItem(wifiBtn);

  auto tetheringBtn = new ButtonControl(tr("Tethering Settings"), tr("OPEN"));
  QObject::connect(tetheringBtn, &ButtonControl::clicked, [=]() { HardwareEon::launch_tethering(); });
  list->addItem(tetheringBtn);
#endif

  ipaddress = new LabelControl(tr("IP Address"), "");
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

SettingsWindow::SettingsWindow(QWidget *parent) : QFrame(parent) {

  // setup two main layouts
  sidebar_widget = new QWidget;
  QVBoxLayout *sidebar_layout = new QVBoxLayout(sidebar_widget);
  sidebar_layout->setMargin(0);
  panel_widget = new QStackedWidget();

  // close button
  QPushButton *close_btn = new QPushButton(tr("HOME"));
  close_btn->setStyleSheet(R"(
    QPushButton {
      font-size: 48px;
      padding-bottom: 0px;
      border 1px grey solid;
      border-radius: 0px;
      background-color: #292929;
      font-weight: 500;
    }
    QPushButton:pressed {
      background-color: #3B3B3B;
    }
  )");
  close_btn->setFixedSize(200, 100);
  sidebar_layout->addSpacing(20);
  sidebar_layout->addWidget(close_btn, 0, Qt::AlignCenter);
  QObject::connect(close_btn, &QPushButton::clicked, this, &SettingsWindow::closeSettings);

  // setup panels
  DevicePanel *device = new DevicePanel(this);
  QObject::connect(device, &DevicePanel::reviewTrainingGuide, this, &SettingsWindow::reviewTrainingGuide);
  QObject::connect(device, &DevicePanel::showDriverView, this, &SettingsWindow::showDriverView);

  TogglesPanel *toggles = new TogglesPanel(this);
  QObject::connect(this, &SettingsWindow::expandToggleDescription, toggles, &TogglesPanel::expandToggleDescription);

  QList<QPair<QString, QWidget *>> panels = {
    {tr("Device"), device},
    #ifdef QCOM
    {tr("Network"), new C2NetworkPanel(this)},
    #else
    {tr("Network"), new Networking(this)},
    #endif
    {tr("Toggles"), toggles},
    {tr("Software"), new SoftwarePanel(this)},
    {"OPTECH", new OptechPanel(this)},
  };

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
        font-size: 56px;
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
  sidebar_layout->setContentsMargins(10, 50, 10, 50);

  // main settings layout, sidebar + main panel
  QHBoxLayout *main_layout = new QHBoxLayout(this);

  sidebar_widget->setFixedWidth(400);
  main_layout->addWidget(sidebar_widget);

  // OPTECH: the car is chosen in OPTECH > 시작 (brand first), so no car bar above the panels
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

void SettingsWindow::hideEvent(QHideEvent *event) {
  #ifdef QCOM
  HardwareEon::close_activities();
  #endif
}
