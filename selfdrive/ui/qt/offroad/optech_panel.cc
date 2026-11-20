#include "selfdrive/ui/qt/offroad/optech_panel.h"

#include <QHBoxLayout>
#include <QLabel>

#include "selfdrive/ui/qt/widgets/input.h"

static QLabel *optech_section(const QString &title) {
  QLabel *label = new QLabel(title);
  label->setStyleSheet("font-size: 45px; font-weight: 600; color: #33ab4c; padding-top: 30px; padding-bottom: 10px;");
  return label;
}

ParamControl *OptechPanel::toggle(ListWidget *list, const QString &param, const QString &title, const QString &desc) {
  ParamControl *t = new ParamControl(param, title, desc, "", this);
  t->setEnabled(!params.getBool((param + "Lock").toStdString()));
  list->addItem(t);
  return t;
}

OptechPanel::OptechPanel(QWidget *parent) : QWidget(parent) {
  QVBoxLayout *main_layout = new QVBoxLayout(this);
  main_layout->setMargin(0);

  // ---- tab buttons (same names and colors as optech-hkg) ----
  QHBoxLayout *tab_layout = new QHBoxLayout();
  tab_layout->setSpacing(10);
  const QStringList tab_names = {"시작", "주행", "속도", "조향", "화면", "고급"};
  for (int i = 0; i < tab_names.size(); i++) {
    QPushButton *btn = new QPushButton(tab_names[i]);
    btn->setObjectName(QString("tab_btn_%1").arg(i));
    QObject::connect(btn, &QPushButton::clicked, [=]() { showTab(i); });
    tab_layout->addWidget(btn);
    tab_btns.append(btn);
  }
  main_layout->addLayout(tab_layout);

  for (int i = 0; i < tab_names.size(); i++) {
    ListWidget *list = new ListWidget(this);
    tab_lists.append(list);
    main_layout->addWidget(list);
  }
  ListWidget *start = tab_lists[0], *drive = tab_lists[1], *speed = tab_lists[2];
  ListWidget *steer = tab_lists[3], *disp = tab_lists[4], *adv = tab_lists[5];

  // ---- 시작 ----
  start->addItem(optech_section("차량"));
  QLabel *car_note = new QLabel("차종은 설정 화면 맨 위의 '차량 모델' 버튼에서 고릅니다. 자동 인식이 되면 그대로 두셔도 됩니다.");
  car_note->setWordWrap(true);
  car_note->setStyleSheet("font-size: 38px; color: #AAAAAA; padding: 10px 0px;");
  start->addItem(car_note);
  toggle(start, "dp_alka", "항상 조향 (ALKA)",
         "크루즈 메인 버튼(ACC MAIN)이 켜져 있으면 크루즈를 켜지 않아도 조향을 계속 도와줍니다.\n재부팅해야 적용됩니다.");
  toggle(start, "dp_car_dashcam_mode_removal", "대시캠 모드 해제",
         "주행 중 '대시캠 모드'가 뜨면 이것을 켜서 openpilot 제어를 강제로 켭니다.\n대시캠 모드는 보통 완전히 지원되지 않는 차량이라는 뜻입니다.\n본인 책임으로 사용하세요. 재부팅해야 적용됩니다.");

  // ---- 주행 ----
  drive->addItem(optech_section("가감속"));
  drive->addItem(new ButtonParamControl("dp_long_accel_profile", "가속 성향",
                 "OP: 기본 값\nECO: 부드럽게(연비)\nNOR: 보통\nSPT: 빠르게(스포츠)", "",
                 std::vector<QString>{"OP", "ECO", "NOR", "SPT"}));
  toggle(drive, "dp_long_use_df_tune", "다이내믹 차간거리",
         "'주행 성향' 설정에 맞춰 앞차와의 거리를 상황에 따라 자동으로 조절합니다.");
  toggle(drive, "dp_long_use_krkeegen_tune", "정체 구간 출발 보조 (SNG Boost)",
         "막히는 길에서 앞차가 출발할 때 조금 더 빨리 가속을 시작합니다. (krkeegan 튠)");
  toggle(drive, "dp_long_de2e", "자동 E2E / ACC 전환",
         "상황에 따라 E2E(카메라 판단) 가감속과 ACC(앞차 기준) 가감속을 자동으로 바꿉니다.\nopenpilot 가감속(롱컨)을 지원하는 차량만 해당됩니다.");

  // ---- 속도 ----
  speed->addItem(optech_section("커브 감속"));
  toggle(speed, "dp_mapd_vision_turn_control", "커브 감속 (카메라)",
         "카메라로 앞 도로의 굽은 정도를 보고 커브에 맞는 속도로 미리 줄입니다.");
  speed->addItem(optech_section("지도"));
  toggle(speed, "dp_mapd", "지도 정보 (MapD)",
         "현재 도로 이름과 제한 속도를 화면에 보여 줍니다.\n주의: 주행 경로가 OpenStreetMap 서버로 올라갑니다.\n재부팅해야 적용됩니다.");

  // ---- 조향 ----
  steer->addItem(optech_section("조향 제어"));
  steer->addItem(new ButtonParamControl("dp_lat_controller", "조향 제어 방식",
                 "조향 제어기를 바꿉니다. 보통은 기본(DEFAULT)을 쓰세요.\n본인 책임으로 사용하세요. 재부팅해야 적용됩니다.", "",
                 std::vector<QString>{"기본", "INDI", "LQR"}));
  steer->addItem(optech_section("차선"));
  ParamControl *lane_priority = toggle(steer, "dp_lat_lane_priority_mode", "차선 우선 모드",
         "차선이 잘 보이면 차선을 따라 조향하고, 차선이 흐리면 자동으로 차선 없는 모드로 바뀝니다.");
  QObject::connect(lane_priority, &ToggleControl::toggleFlipped, [=]() { updateToggles(); });
  lane_priority_speed = new ParamSpinBoxControl("dp_lat_lane_priority_mode_speed_based", "이 속도 이상에서만",
                        "모든 속도: 차선이 보이면 항상 차선을 따릅니다.\n숫자: 그 속도보다 빠를 때만 차선을 따릅니다.",
                        "", 0, 120, 1, " km/h", "모든 속도");
  steer->addItem(lane_priority_speed);
  steer->addItem(optech_section("차선 변경"));
  steer->addItem(new ParamSpinBoxControl("dp_lat_lane_change_assist_speed", "차선 변경 보조 시작 속도",
                 "방향지시등을 켰을 때 이 속도 이상이면 차선 변경을 도와줍니다.\n끄기 = 차선 변경 보조를 쓰지 않음.\n1 mph = 약 1.6 km/h",
                 "", 0, 80, 1, " mph", "끄기"));

  // ---- 화면 ----
  disp->addItem(optech_section("화면 버튼"));
  toggle(disp, "dp_long_personality_btn", "주행 성향 버튼",
         "주행 화면에 주행 성향(차간거리 성향) 버튼을 보여 줍니다.");
  toggle(disp, "dp_long_accel_btn", "가속 성향 버튼",
         "주행 화면에 가속 성향 버튼을 보여 줍니다.");
  disp->addItem(optech_section("소리"));
  disp->addItem(new ButtonParamControl("dp_device_audible_alert_mode", "알림 소리",
                "기본: 원래대로 소리를 냅니다.\n경고만: 경고일 때만 소리를 냅니다.\n끄기: 소리를 내지 않습니다.", "",
                std::vector<QString>{"기본", "경고만", "끄기"}));

  // ---- 고급 ----
  adv->addItem(optech_section("기기"));
  toggle(adv, "dp_device_disable_temp_check", "온도 검사 끄기",
         "기기 온도 검사를 끕니다.\n주의: 기기가 너무 뜨거우면 갑자기 꺼지거나 느려질 수 있습니다.\n재부팅해야 적용됩니다.");
  toggle(adv, "dp_device_no_ir_ctrl", "적외선(IR) 끄기",
         "운전자 카메라의 적외선 조명을 완전히 끕니다.\n재부팅해야 적용됩니다.");
  ParamControl *auto_shutdown = toggle(adv, "dp_device_auto_shutdown", "자동 꺼짐",
         "시동을 끈 뒤 기기를 자동으로 끕니다.\n재부팅해야 적용됩니다.");
  QObject::connect(auto_shutdown, &ToggleControl::toggleFlipped, [=]() { updateToggles(); });
  auto_shutdown_timer = new ParamSpinBoxControl("dp_device_auto_shutdown_in", "꺼지기까지 기다리는 시간",
                        "시동을 끈 뒤 기기가 꺼질 때까지 기다리는 시간입니다.", "", 0, 600, 1, " 분", "바로");
  adv->addItem(auto_shutdown_timer);

  adv->addItem(optech_section("토요타 / 렉서스"));
  toggle(adv, "dp_toyota_sng", "정차 후 재출발 (SnG)",
         "완전히 멈췄을 때 정차 신호를 보내지 않아 다시 출발할 수 있게 합니다.\n일부 차량만 됩니다. 재부팅해야 적용됩니다.");
  toggle(adv, "dp_toyota_enhanced_bsm", "후측방 감지 강화 (BSM)",
         "진단용 CAN 메시지로 후측방 신호를 더 많이 받습니다.\n일부 차량만 됩니다. 재부팅해야 적용됩니다.");
  toggle(adv, "dp_toyota_auto_lock", "자동 문 잠금",
         "10 km/h 이상으로 달리면 문을 잠급니다.\n재부팅해야 적용됩니다.");
  toggle(adv, "dp_toyota_auto_unlock", "자동 문 열림",
         "기어를 P로 놓으면 문 잠금을 풉니다.\n재부팅해야 적용됩니다.");
  toggle(adv, "dp_toyota_zss", "ZSS 조향 센서 사용",
         "ZSS(Zorro 조향 센서)를 달았을 때만 켜세요. 더 정확하게 조향합니다.\n재부팅해야 적용됩니다.");

  adv->addItem(optech_section("폭스바겐 / 스코다 / 아우디"));
  toggle(adv, "dp_vag_timebomb_bypass", "조향 시간 제한 우회",
         "조향이 약 5분 45초마다 끊기는 제한을 잠깐 껐다 켜서 피합니다.\n5분 40초 경고, 5분 45초 조향 꺼짐, 5분 48초 다시 켜짐.\n재부팅해야 적용됩니다.");

  adv->addItem(optech_section("초기화"));
  ButtonControl *reset_btn = new ButtonControl("설정 초기화", "초기화", "위의 OPTECH(드래곤파일럿) 설정을 모두 처음 값으로 되돌립니다.");
  QObject::connect(reset_btn, &ButtonControl::clicked, [=]() {
    if (ConfirmationDialog::confirm("OPTECH 설정을 모두 처음 값으로 되돌릴까요?", "초기화", this)) {
      params.putBool("dp_reset_conf", true);
    }
  });
  adv->addItem(reset_btn);

  showTab(0);
}

void OptechPanel::showTab(int index) {
  current_tab = index;
  for (int i = 0; i < tab_lists.size(); i++) {
    tab_lists[i]->setVisible(i == index);
  }
  updateTabStyles();
}

void OptechPanel::updateTabStyles() {
  // style each tab button on its own so the buttons inside the lists keep their own look
  for (int i = 0; i < tab_btns.size(); i++) {
    const QString bg = i == current_tab ? "#33ab4c" : "#393939";
    tab_btns[i]->setStyleSheet(QString(R"(
      QPushButton {
        font-size: 50px; font-weight: 500; color: #FFFFFF;
        height: 120px; border-radius: 15px; background-color: %1;
      }
      QPushButton:pressed { background-color: #4a4a4a; }
    )").arg(bg));
  }
}

void OptechPanel::updateToggles() {
  if (auto_shutdown_timer) auto_shutdown_timer->setVisible(params.getBool("dp_device_auto_shutdown"));
  if (lane_priority_speed) lane_priority_speed->setVisible(params.getBool("dp_lat_lane_priority_mode"));
}

void OptechPanel::showEvent(QShowEvent *event) {
  updateToggles();
}
