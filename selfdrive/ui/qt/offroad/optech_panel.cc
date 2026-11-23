#include "selfdrive/ui/qt/offroad/optech_panel.h"

#include <cmath>

#include <QHBoxLayout>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QScroller>

#include "selfdrive/ui/qt/widgets/input.h"
#include "selfdrive/ui/ui.h"

// ---- small helpers, same look as optech-hkg ----

static QLabel *optech_section(const QString &title) {
  QLabel *label = new QLabel(title);
  label->setStyleSheet("font-size: 42px; font-weight: 600; color: #33ab4c; padding-top: 25px; padding-left: 10px;");
  return label;
}

static QLabel *optech_note(const QString &text) {
  QLabel *label = new QLabel(text);
  label->setWordWrap(true);
  label->setStyleSheet("font-size: 36px; color: #9A9A9A; padding: 10px 10px;");
  return label;
}

static const char *VALUE_BTN_STYLE = R"(
  padding: 0;
  border-radius: 50px;
  font-size: 35px;
  font-weight: 500;
  color: #E4E4E4;
  background-color: #393939;
)";

OptechValueControl::OptechValueControl(const QString &param, const QString &title, const QString &desc,
                                       int min_value, int max_value, int step, std::function<QString(int)> format)
    : AbstractControl(title, desc, ""), key(param.toStdString()), min_v(min_value), max_v(max_value), step_v(step), fmt(format) {
  label.setAlignment(Qt::AlignVCenter | Qt::AlignRight);
  label.setStyleSheet("color: #e0e879; padding-right: 20px;");
  hlayout->addWidget(&label);

  btnminus.setStyleSheet(VALUE_BTN_STYLE);
  btnplus.setStyleSheet(VALUE_BTN_STYLE);
  btnminus.setFixedSize(110, 100);
  btnplus.setFixedSize(110, 100);
  btnminus.setText("－");
  btnplus.setText("＋");
  hlayout->addWidget(&btnminus);
  hlayout->addWidget(&btnplus);

  QObject::connect(&btnminus, &QPushButton::released, [=]() { change(-step_v); });
  QObject::connect(&btnplus, &QPushButton::released, [=]() { change(step_v); });
  refresh();
}

void OptechValueControl::change(int delta) {
  int v = QString::fromStdString(Params().get(key)).toInt() + delta;
  if (v < min_v) v = min_v;
  if (v > max_v) v = max_v;
  Params().put(key, std::to_string(v));
  refresh();
  if (on_change) on_change(v);
}

void OptechValueControl::refresh() {
  label.setText(fmt(QString::fromStdString(Params().get(key)).toInt()));
}

// ---- car selection: brands first (same as optech-hkg SelectCar) ----

// brands shown in this order (same as optech-hkg: Hyundai / Kia / Genesis first)
static const QStringList BRAND_ORDER = {"HYUNDAI", "KIA", "GENESIS",
                                        "CHEVROLET", "GMC", "CADILLAC", "BUICK", "HOLDEN", "TOYOTA", "LEXUS", "HONDA", "ACURA",
                                        "VOLKSWAGEN", "AUDI", "SKODA", "SEAT", "MAZDA", "NISSAN", "SUBARU", "FORD",
                                        "CHRYSLER", "JEEP", "RAM", "TESLA"};
static const char *BOLT_CC_CAR = "CHEVROLET BOLT EV NO ACC";  // selfdrive/car/gm/values.py CAR.BOLT_CC
static const QStringList BRAND_HIDDEN = {"COMMA", "mock"};
// Hyundai / Kia / Genesis come from dp_car_list "hkg_menu" (selfdrive/car/hyundai/car_menu.py): normal CAN cars only,
// already in menu order (model family, then year), with optech-hkg names. The cars are not sorted again here.
static const QStringList HKG_BRANDS = {"HYUNDAI", "KIA", "GENESIS"};

// dp_car_list = {"cars": [...], "hkg_menu": [{"car", "brand", "name"}, ...]} written by the manager at every start
static QJsonObject carList() {
  return QJsonDocument::fromJson(QByteArray::fromStdString(Params().get("dp_car_list"))).object();
}

// the Hyundai / Kia / Genesis menu entry of a car ({"car", "brand", "name"}), empty when the car is not in that menu
static QJsonObject hkgEntry(const QString &car) {
  for (const auto &v : carList().value("hkg_menu").toArray()) {
    const QJsonObject o = v.toObject();
    if (o.value("car").toString() == car) return o;
  }
  return QJsonObject();
}

QString OptechCarSelect::brandOf(const QString &car) {
  return car.section(' ', 0, 0);
}

QString OptechCarSelect::brandKo(const QString &brand) {
  static const QMap<QString, QString> KO = {
    {"CHEVROLET", "쉐보레"}, {"GMC", "GMC"}, {"CADILLAC", "캐딜락"}, {"BUICK", "뷰익"}, {"HOLDEN", "홀덴"},
    {"TOYOTA", "토요타"}, {"LEXUS", "렉서스"}, {"HONDA", "혼다"}, {"ACURA", "어큐라"},
    {"VOLKSWAGEN", "폭스바겐"}, {"AUDI", "아우디"}, {"SKODA", "스코다"}, {"SEAT", "세아트"},
    {"MAZDA", "마쓰다"}, {"NISSAN", "닛산"}, {"SUBARU", "스바루"}, {"FORD", "포드"},
    {"CHRYSLER", "크라이슬러"}, {"JEEP", "지프"}, {"RAM", "램"}, {"TESLA", "테슬라"},
    {"HYUNDAI", "현대"}, {"KIA", "기아"}, {"GENESIS", "제네시스"}};
  return KO.value(brand);
}

QString OptechCarSelect::menuName(const QString &car) {
  const QJsonObject hkg = hkgEntry(car);
  if (!hkg.isEmpty()) return brandKo(hkg.value("brand").toString()) + "  " + hkg.value("name").toString();
  const QString brand = brandOf(car);
  const QString ko = brandKo(brand);
  return (ko.isEmpty() ? brand : ko) + "  " + car.section(' ', 1);
}

OptechCarSelect::OptechCarSelect(QWidget *parent) : QWidget(parent) {
  QVBoxLayout *layout = new QVBoxLayout(this);
  layout->setMargin(20);
  layout->setSpacing(20);

  // back: from a brand's cars back to the brands, from the brands back to the menu
  QPushButton *back = new QPushButton("뒤로");
  back->setFixedSize(500, 100);
  back->setStyleSheet("QPushButton { font-size: 50px; border-radius: 15px; background-color: #393939; } QPushButton:pressed { background-color: #4a4a4a; }");
  layout->addWidget(back, 0, Qt::AlignLeft);

  list = new QListWidget(this);
  list->setStyleSheet("QListView {padding: 40px; background-color: #393939; border-radius: 15px;} QListView::item{height: 100px}");
  list->setFixedHeight(900);
  QScroller::grabGesture(list->viewport(), QScroller::LeftMouseButtonGesture);
  list->setVerticalScrollMode(QAbstractItemView::ScrollPerPixel);
  layout->addWidget(list);

  const QJsonObject car_list = carList();
  const QJsonArray hkg = car_list.value("hkg_menu").toArray();
  for (const auto &v : hkg) {
    const QJsonObject o = v.toObject();
    const QString car = o.value("car").toString(), brand = o.value("brand").toString();
    if (car.isEmpty() || brand.isEmpty()) continue;
    cars[brand].append(car);
    names[car] = o.value("name").toString();
  }
  // all cars this base knows (without "hkg_menu", e.g. an old manager, the Hyundai / Kia / Genesis cars come from here)
  for (const auto &v : car_list.value("cars").toArray()) {
    const QString car = v.toString();
    const QString brand = brandOf(car);
    if (car.isEmpty() || BRAND_HIDDEN.contains(brand) || (!hkg.isEmpty() && HKG_BRANDS.contains(brand))) continue;
    cars[brand].append(car);
  }
  for (const QString &b : BRAND_ORDER) {
    if (cars.contains(b)) brands.append(b);
  }
  for (const QString &b : cars.keys()) {
    if (!brands.contains(b)) brands.append(b);
  }
  for (const QString &b : brands) {
    if (hkg.isEmpty() || !HKG_BRANDS.contains(b)) cars[b].sort();
  }

  QObject::connect(back, &QPushButton::clicked, [=]() {
    if (!cur_brand.isEmpty()) showBrands();
    else emit backPress();
  });

  QObject::connect(list, &QListWidget::itemClicked, [=](QListWidgetItem *item) {
    const QString brand = item->data(Qt::UserRole + 1).toString();
    if (!brand.isEmpty()) {  // a brand: show its cars
      showCars(brand);
      return;
    }
    if (!(item->flags() & Qt::ItemIsSelectable)) return;  // brand header
    const QString car = item->data(Qt::UserRole).toString();
    Params().put("dp_car_assigned", car.toStdString());  // empty = auto detect
    showBrands();  // next time the list starts from the brands again
    emit selectedCar();
  });

  showBrands();
}

void OptechCarSelect::showBrands() {
  cur_brand.clear();
  list->clear();
  const QString selected = QString::fromStdString(Params().get("dp_car_assigned"));
  QListWidgetItem *auto_item = new QListWidgetItem("[ 자동 인식 ]");
  auto_item->setData(Qt::UserRole, QString());
  list->addItem(auto_item);
  list->setCurrentItem(auto_item);
  for (const QString &b : brands) {
    const QString ko = brandKo(b);
    QListWidgetItem *item = new QListWidgetItem("   " + b + (ko.isEmpty() || ko == b ? "" : "  " + ko) +
                                                QString("   (%1)   ▶").arg(cars[b].size()));
    item->setData(Qt::UserRole + 1, b);
    list->addItem(item);
    if (cars[b].contains(selected)) list->setCurrentItem(item);
  }
  list->scrollToTop();
}

void OptechCarSelect::showCars(const QString &brand) {
  cur_brand = brand;
  list->clear();
  const QString selected = QString::fromStdString(Params().get("dp_car_assigned"));
  const QString ko = brandKo(brand);
  QListWidgetItem *header = new QListWidgetItem("■ " + brand + (ko.isEmpty() || ko == brand ? "" : "  " + ko));
  header->setFlags(Qt::NoItemFlags);  // not selectable
  header->setForeground(QColor("#33ab4c"));
  QFont f = header->font();
  f.setBold(true);
  header->setFont(f);
  list->addItem(header);
  for (const QString &car : cars[brand]) {
    QListWidgetItem *item = new QListWidgetItem("      " + names.value(car, car.section(' ', 1)));
    item->setData(Qt::UserRole, car);
    list->addItem(item);
    if (car == selected) list->setCurrentItem(item);
  }
  if (list->currentItem()) list->scrollToItem(list->currentItem(), QAbstractItemView::PositionAtCenter);
  else list->scrollToTop();
}

ParamControl *OptechPanel::toggle(ListWidget *list, const QString &param, const QString &title, const QString &desc) {
  ParamControl *t = new ParamControl(param, title, desc, "", this);
  t->setEnabled(!params.getBool((param + "Lock").toStdString()));
  list->addItem(t);
  return t;
}

OptechValueControl *OptechPanel::value(ListWidget *list, const QString &param, const QString &title, const QString &desc,
                                       int min_value, int max_value, int step, std::function<QString(int)> format) {
  OptechValueControl *v = new OptechValueControl(param, title, desc, min_value, max_value, step, format);
  list->addItem(v);
  values.append(v);
  return v;
}

// ---- the menu ----

OptechPanel::OptechPanel(QWidget *parent) : QWidget(parent) {
  stack = new QStackedLayout(this);
  home = new QWidget(this);
  QVBoxLayout *main_layout = new QVBoxLayout(home);
  main_layout->setMargin(0);
  car_select = new OptechCarSelect(this);
  stack->addWidget(home);
  stack->addWidget(car_select);

  // tab buttons (same names and colors as optech-hkg)
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

  // ======== 시작 ========
  car_btn = new QPushButton();
  car_btn->setStyleSheet(R"(
    QPushButton {
      margin-top: 20px; margin-bottom: 20px; padding: 10px; height: 120px; border-radius: 15px;
      font-size: 50px; color: #FFFFFF; background-color: #2C2CE2;
    }
    QPushButton:pressed { background-color: #2424FF; }
  )");
  QObject::connect(car_btn, &QPushButton::clicked, [=]() { stack->setCurrentWidget(car_select); });
  QObject::connect(car_select, &OptechCarSelect::backPress, [=]() { stack->setCurrentWidget(home); });
  QObject::connect(car_select, &OptechCarSelect::selectedCar, [=]() {
    updateCarButton();
    updateBrandItems();
    stack->setCurrentWidget(home);
    if (QString::fromStdString(params.get("dp_car_assigned")) == BOLT_CC_CAR) {
      ConfirmationDialog::alert("이 차량은 따로 확인할 설정이 있어요.\n차종 버튼 아래의 '볼트 EV 설정'을 확인해 주세요.", this);
    }
  });
  start->addItem(car_btn);
  start->addItem(optech_note("자동 인식이 잘 되면 '자동 인식'으로 두세요. 인식이 안 될 때만 직접 고르면 다음 시동부터 적용됩니다. "
                             "현대·기아·제네시스는 일반 CAN 차량만 있어요(CAN FD 차량은 optech-hkg-fd를 쓰세요). "
                             "그랜저 IG · K7 · K9 · 모하비 · 캐스퍼 · 넥쏘 · EQ900 같은 국내 차종과 ACC 없는 GM 차량(… NO ACC)은 자동 인식이 안 되니 직접 고르세요."));

  // '볼트 EV 설정': only while the Bolt EV without ACC is the chosen car (same texts as optech-hkg)
  QLabel *bolt_section = optech_section("볼트 EV 설정");
  start->addItem(bolt_section);
  bolt_items.append(bolt_section);
  QLabel *bolt_intro = optech_note(
    "어댑티브 크루즈(ACC)가 없는 볼트 EV(2017~2021)입니다. 카메라 하네스로 연결합니다. 페달 장치가 없으면 openpilot은 조향만 하고, "
    "차의 일반 크루즈를 켜면 함께 켜집니다. 레이더가 없으니 앞차와의 거리는 항상 운전자가 지켜 주세요. "
    "아직 실제 차로 시험하지 않았으니, 처음에는 'openpilot 사용'을 끄고(읽기 전용) 짧게 달려 본 뒤 조향을 켜 주세요.");
  start->addItem(bolt_intro);
  bolt_items.append(bolt_intro);
  bolt_items.append(toggle(start, "BoltYear2017", "2017년식",
    "2017년식 볼트 EV면 켜세요. 2017년식은 핸들 모터(EPS)가 약해서, 스타파일럿의 2017년식 조향 튜닝과 더 큰 조향 힘 한도를 씁니다. "
    "2018~2021년식은 끈 채로 두세요. 재부팅해야 적용됩니다."));
  QLabel *pedal_section = optech_section("페달 (comma 페달 장치)");
  start->addItem(pedal_section);
  bolt_items.append(pedal_section);
  bolt_items.append(toggle(start, "BoltPedal", "페달 사용",
    "comma 페달 장치를 단 경우에만 켜세요(스타파일럿 볼트 EV 방식). 켜면 openpilot이 가속페달로 가감속을 맡습니다. "
    "기어는 L(원페달) 모드여야 하고, 차의 크루즈 메인 버튼은 꺼 둔 채 SET 또는 RES 버튼으로 켭니다. "
    "브레이크 장치가 없어 감속은 회생제동만큼만 됩니다. 페달 장치가 인식되지 않으면 켜 두어도 조향만 합니다. 재부팅해야 적용됩니다."));
  bolt_items.append(value(start, "BoltPedalMax", "페달 최대 밟는 양",
    "openpilot이 가속페달을 최대 몇 %까지 밟을지 정합니다. 처음에는 낮게 시작해 보세요. 20~100%, 기본 100%(스타파일럿 그대로). "
    "저속에서는 스타파일럿이 따로 정한 상한(정지 근처 20%부터)이 먼저 적용됩니다.",
    20, 100, 5, [](int v) { return QString("%1%").arg(v); }));
  // '사용 방식' like optech-hkg (title = current choice, button 선택). Here it is dragonpilot's ALKA (dp_alka):
  // the car's own cruise does the speed once SET is pressed, so "steering only from the cruise button" is not possible
  start->addItem(optech_section("사용 방식"));
  ButtonControl *engage_mode_btn = new ButtonControl("", "선택",
    "openpilot 조향을 언제 켤지 고릅니다.\n"
    "크루즈와 함께: 크루즈 SET을 눌러 차의 크루즈가 켜지면 조향도 함께 켜집니다. 속도는 차의 크루즈가 맡습니다.\n"
    "메인만 켜도 조향: 크루즈 메인 버튼만 켜 두면 SET을 누르지 않아도 조향을 도와줍니다(ALKA). 속도는 운전자가 페달로 조절하고, "
    "SET을 누르면 차의 크루즈도 함께 켜집니다. 주행 중 브레이크를 밟은 채 메인 버튼을 두 번 누르면 잠시 껐다 켤 수 있습니다.\n"
    "재부팅해야 적용됩니다.");
  const QStringList engage_names = {"크루즈와 함께", "메인만 켜도 조향"};
  auto engage_name = [=]() { return engage_names[params.getBool("dp_alka") ? 1 : 0]; };
  engage_mode_btn->setTitle(engage_name());
  QObject::connect(engage_mode_btn, &ButtonControl::clicked, [=]() {
    const QString sel = MultiOptionDialog::getSelection("사용 방식을 고르세요", engage_names, engage_name(), this);
    if (sel.isEmpty() || sel == engage_name()) return;
    params.putBool("dp_alka", sel == engage_names[1]);
    engage_mode_btn->setTitle(engage_name());
  });
  start->addItem(engage_mode_btn);

  // ======== 주행 ========
  drive->addItem(optech_section("과속카메라"));
  // same order as optech-hkg: 카메라 감속 first, its explanation right under it while it is on, then the camera source
  ParamControl *cam_decel = toggle(drive, "OptechSpeedCamDecel", "카메라 감속",
         "과속카메라 앞에서 제한 속도까지 미리 줄입니다. 켜면 아래에 동작 설명이 나옵니다.");
  QLabel *cam_note = optech_note(
    "● 과속카메라 약 22초 전(아래 '감속 시작')부터 설정 속도를 조금씩 내려서, 카메라 앞에서는 제한 속도 근처로 지나갑니다. "
    "구간단속은 구간이 끝날 때까지 제한 속도를 지킵니다.\n"
    "● 카메라 정보는 아래 '내장 카메라 DB'에서 받습니다. 기기 GPS와 전국 카메라 위치(약 3만 1천 대)로 찾고, 내비 앱은 필요 없습니다. "
    "이동식·새 카메라는 모르고, 반대 차로의 카메라에도 줄일 수 있습니다.\n"
    "● openpilot이 가감속을 맡는 차량만 속도를 줄입니다. 차의 순정 크루즈를 쓰는 차량은 화면에 CAM 표시만 됩니다. GPS가 안 잡히면 동작하지 않습니다.");
  cam_note->setStyleSheet("font-size: 36px; color: #E0E0E0; background-color: #333333; border-radius: 10px; padding: 20px; margin: 10px 0px;");
  drive->addItem(cam_note);
  // only after it is in the list: a parentless widget shown would open as its own window and crash the C2 UI
  cam_note->setVisible(params.getBool("OptechSpeedCamDecel"));
  QObject::connect(cam_decel, &ToggleControl::toggleFlipped, [=](bool on) { cam_note->setVisible(on); });
  toggle(drive, "OptechSpeedCam", "내장 카메라 DB",
         "내비 앱 없이 기기 GPS로 앞쪽 고정식 단속카메라(과속·신호과속·구간단속)를 찾아 화면 속도 상자에 'CAM'으로 보여 줍니다. "
         "'카메라 감속'을 끄면 CAM 표시만 나오고 속도는 줄이지 않습니다.\n"
         "자료: 공공데이터포털 전국무인교통단속카메라 (2026년 10월, 약 3만 1천 대).\n시동을 다시 걸면 적용됩니다.");
  value(drive, "OptechCamDecelStart", "감속 시작",
        "카메라에 도착하기 몇 초 전부터 줄이기 시작할지 정합니다. 클수록 일찍, 부드럽게 줄입니다.",
        5, 60, 1, [](int v) { return QString("%1초 전").arg(v); });
  value(drive, "OptechCamDecelEnd", "감속 끝",
        "카메라에 도착하기 몇 초 전까지 목표 속도에 맞출지 정합니다.",
        0, 20, 1, [](int v) { return QString("%1초 전").arg(v); });
  value(drive, "OptechCamSafetyFactor", "카메라 앞 목표 속도",
        "제한 속도의 몇 %로 지나갈지 정합니다. 100%는 제한 속도 그대로, 105%는 5% 더 빠르게 지나갑니다.",
        90, 120, 1, [](int v) { return QString("%1%").arg(v); });

  // ======== 속도 ========
  speed->addItem(optech_note("이 탭의 설정은 openpilot이 가감속을 맡는 차량에서만 동작합니다. 차의 원래 크루즈를 쓰는 차량(볼트 EUV 등)은 변화가 없습니다."));
  speed->addItem(optech_section("가속 세기"));
  speed->addItem(new ButtonParamControl("dp_long_accel_profile", "가속 성향",
                 "OP: 기본 값\nECO: 부드럽게(연비)\nNOR: 보통\nSPT: 빠르게(스포츠)", "",
                 std::vector<QString>{"OP", "ECO", "NOR", "SPT"}));
  speed->addItem(optech_section("차간거리"));
  toggle(speed, "dp_long_use_df_tune", "다이내믹 차간거리",
         "'주행 성향' 설정에 맞춰 앞차와의 거리를 상황에 따라 자동으로 조절합니다.");
  speed->addItem(optech_section("출발·정지"));
  toggle(speed, "dp_long_use_krkeegen_tune", "정체 구간 출발 보조",
         "막히는 길에서 앞차가 출발할 때 조금 더 빨리 가속을 시작합니다. (krkeegan 튠)");

  // ======== 조향 ========
  steer->addItem(optech_section("조향"));
  value(steer, "dp_lat_lane_change_assist_speed", "차선변경 최소 속도",
        "방향지시등을 켰을 때 이 속도 이상이면 차선 변경을 도와줍니다. 끄기: 차선 변경 보조를 쓰지 않습니다.",
        0, 80, 5, [](int v) { return v == 0 ? QString("끄기") : QString("%1 km/h").arg((int)std::round(v * 1.609)); });
  ParamControl *lane_priority = toggle(steer, "dp_lat_lane_priority_mode", "차선 우선 모드",
         "차선이 잘 보이면 차선을 따라 조향하고, 차선이 흐리면 자동으로 차선 없는 모드로 바뀝니다.");
  QObject::connect(lane_priority, &ToggleControl::toggleFlipped, [=]() { updateToggles(); });
  lane_priority_speed = value(steer, "dp_lat_lane_priority_mode_speed_based", "차선 우선: 이 속도 이상에서만",
        "모든 속도: 차선이 보이면 항상 차선을 따릅니다. 숫자: 그 속도보다 빠를 때만 차선을 따릅니다.",
        0, 120, 5, [](int v) { return v == 0 ? QString("모든 속도") : QString("%1 km/h").arg(v); });
  steer->addItem(optech_section("커브"));
  toggle(steer, "dp_mapd_vision_turn_control", "커브 자동 감속",
         "카메라로 앞 도로의 굽은 정도를 보고 커브에 맞는 속도로 미리 줄입니다.");

  // ======== 화면 ========
  disp->addItem(optech_section("주행 화면"));
  toggle(disp, "OptechHud", "OPTECH 속도 상자",
         "왼쪽 아래에 optech-hkg와 같은 속도 상자(현재 속도, 설정 속도, 기어, 차간거리, GPS 속도)를 보여 줍니다. 끄면 원래 화면(위쪽 가운데 속도)으로 돌아갑니다.");
  toggle(disp, "OptechShowDeviceState", "기기 상태",
         "속도 상자 위에 CPU 온도, CPU 사용률, 화면 FPS를 보여 줍니다. 너무 높으면 빨갛게 깜빡입니다.");
  // '운전자 모니터링' like optech-hkg (ShowDmInfo): -1 = the function off (dragonpilot dp_device_no_ir_ctrl: no driver
  // camera checks, no IR light, the monitoring processes do not run), 0 = icon hidden, 1 = icon shown
  disp->addItem(optech_section("운전자 모니터링"));
  if (params.getBool("dp_device_no_ir_ctrl") && params.get("ShowDmInfo") != "-1") params.put("ShowDmInfo", "-1");
  OptechValueControl *dm_mode = value(disp, "ShowDmInfo", "운전자 모니터링",
        "운전자를 보는 카메라로 졸음과 전방 주시를 확인하는 기능입니다.\n"
        "기능 끄기: '앞을 보세요' 같은 경고가 나오지 않고, 운전자 카메라의 적외선 조명도 꺼집니다. 기기 부담도 줄어듭니다. "
        "졸음운전을 잡아 주지 않으니 항상 주의하세요.\n"
        "아이콘 안 보임 / 아이콘 보임: 기능은 켜 두고, 주행 화면의 얼굴 아이콘만 숨기거나 보여 줍니다.\n"
        "기능을 끄거나 다시 켜면 재부팅해야 적용됩니다.",
        -1, 1, 1, [](int v) { return v < 0 ? QString("기능 끄기") : (v == 0 ? QString("아이콘 안 보임") : QString("아이콘 보임")); });
  dm_mode->on_change = [=](int v) { params.putBool("dp_device_no_ir_ctrl", v < 0); };
  disp->addItem(optech_section("화면 버튼"));
  toggle(disp, "dp_long_personality_btn", "주행 성향 버튼",
         "주행 화면에 주행 성향(차간거리 성향) 버튼을 보여 줍니다.");
  toggle(disp, "dp_long_accel_btn", "가속 성향 버튼",
         "주행 화면에 가속 성향 버튼을 보여 줍니다.");

  // ======== 고급 ========
  adv->addItem(optech_section("기기"));
  ParamControl *auto_shutdown = toggle(adv, "dp_device_auto_shutdown", "자동 꺼짐",
         "시동을 끈 뒤 기기를 자동으로 끕니다.\n재부팅해야 적용됩니다.");
  QObject::connect(auto_shutdown, &ToggleControl::toggleFlipped, [=]() { updateToggles(); });
  auto_shutdown_timer = value(adv, "dp_device_auto_shutdown_in", "꺼지기까지 기다리는 시간",
        "시동을 끈 뒤 기기가 꺼질 때까지 기다리는 시간입니다.",
        0, 600, 5, [](int v) { return v == 0 ? QString("바로") : QString("%1분").arg(v); });
  adv->addItem(new ButtonParamControl("dp_device_audible_alert_mode", "알림 소리",
               "기본: 원래대로 소리를 냅니다.\n경고만: 경고일 때만 소리를 냅니다.\n끄기: 소리를 내지 않습니다.", "",
               std::vector<QString>{"기본", "경고만", "끄기"}));

  adv->addItem(optech_section("실험 모드"));
  toggle(adv, "dp_long_de2e", "자동 E2E / ACC 전환",
         "상황에 따라 E2E(카메라 판단) 가감속과 ACC(앞차 기준) 가감속을 자동으로 바꿉니다.\nopenpilot이 가감속을 맡는 차량만 해당됩니다.");

  adv->addItem(optech_section("개발용"));
  toggle(adv, "dp_car_dashcam_mode_removal", "대시캠 모드 해제 (위험)",
         "주행 중 '대시캠 모드'가 뜨면 이것을 켜서 openpilot 제어를 강제로 켭니다. 대시캠 모드는 보통 완전히 지원되지 않는 차량이라는 뜻입니다.\n본인 책임으로 사용하세요. 재부팅해야 적용됩니다.");

  brand_note = optech_note("차종이 정해지면(직접 고르거나 한 번 시동을 걸어 자동 인식되면) 그 브랜드 전용 설정이 여기에 나옵니다.");
  adv->addItem(brand_note);
  QLabel *hkg_section = optech_section("현대 / 기아 / 제네시스 전용");
  adv->addItem(hkg_section);
  hkg_items.append(hkg_section);
  hkg_items.append(toggle(adv, "dp_hkg_min_steer_speed_bypass", "저속 조향 허용",
         "차가 정한 최저 조향 속도보다 느릴 때도 openpilot이 조향합니다(0 km/h까지).\n"
         "차에 따라 MDPS 개조가 필요할 수 있어요. 재부팅해야 적용됩니다."));
  hkg_items.append(toggle(adv, "OptechHkgCameraScc", "크루즈(SCC)가 카메라 쪽에 있음",
         "차의 크루즈(SCC) 신호가 레이더가 아니라 카메라 쪽에서 나오는 차입니다. 주행 중 openpilot이 스스로 알아내서 켜 주니 보통은 그대로 두세요.\n"
         "차를 바꿨는데 켜져 있으면 끄세요. 켜져 있으면 openpilot 가감속은 쓸 수 없고 차의 크루즈가 속도를 맡습니다. 시동을 다시 걸어야 적용됩니다."));
  QLabel *toyota_section = optech_section("토요타 / 렉서스 전용");
  adv->addItem(toyota_section);
  toyota_items.append(toyota_section);
  toyota_items.append(toggle(adv, "dp_toyota_sng", "정차 후 재출발 (SnG)",
         "완전히 멈췄을 때 정차 신호를 보내지 않아 다시 출발할 수 있게 합니다.\n일부 차량만 됩니다. 재부팅해야 적용됩니다."));
  toyota_items.append(toggle(adv, "dp_toyota_enhanced_bsm", "후측방 감지 강화 (BSM)",
         "진단용 CAN 메시지로 후측방 신호를 더 많이 받습니다.\n일부 차량만 됩니다. 재부팅해야 적용됩니다."));
  toyota_items.append(toggle(adv, "dp_toyota_auto_lock", "자동 문 잠금",
         "10 km/h 이상으로 달리면 문을 잠급니다.\n재부팅해야 적용됩니다."));
  toyota_items.append(toggle(adv, "dp_toyota_auto_unlock", "자동 문 열림",
         "기어를 P로 놓으면 문 잠금을 풉니다.\n재부팅해야 적용됩니다."));
  toyota_items.append(toggle(adv, "dp_toyota_zss", "ZSS 조향 센서 사용",
         "ZSS(Zorro 조향 센서)를 달았을 때만 켜세요. 더 정확하게 조향합니다.\n재부팅해야 적용됩니다."));

  QLabel *vag_section = optech_section("폭스바겐 / 아우디 / 스코다 / 세아트 전용");
  adv->addItem(vag_section);
  vag_items.append(vag_section);
  vag_items.append(toggle(adv, "dp_vag_timebomb_bypass", "조향 시간 제한 우회",
         "약 6분마다 조향이 끊기는 제한을 잠깐 껐다 켜서 피합니다.\n5분 40초 경고, 5분 45초 조향 꺼짐, 5분 48초 다시 켜짐.\n재부팅해야 적용됩니다."));

  adv->addItem(optech_section("초기화"));
  ButtonControl *reset_btn = new ButtonControl("설정 초기화", "초기화", "OPTECH 설정을 모두 처음 값으로 되돌립니다.");
  QObject::connect(reset_btn, &ButtonControl::clicked, [=]() {
    if (ConfirmationDialog::confirm("OPTECH 설정을 모두 처음 값으로 되돌릴까요?", "초기화", this)) {
      params.putBool("dp_reset_conf", true);
    }
  });
  adv->addItem(reset_btn);

  updateCarButton();
  updateBrandItems();
  showTab(0);
}

// brand of the car this device drives: the chosen car, else the one auto detected at the last start
QString OptechPanel::currentBrand() {
  const QString assigned = QString::fromStdString(params.get("dp_car_assigned")).trimmed();
  if (!assigned.isEmpty()) return OptechCarSelect::brandOf(assigned);
  const std::string cp_bytes = params.get("CarParamsPersistent");
  if (cp_bytes.empty()) return "";
  AlignedBuffer aligned_buf;
  capnp::FlatArrayMessageReader cmsg(aligned_buf.align(cp_bytes.data(), cp_bytes.size()));
  cereal::CarParams::Reader CP = cmsg.getRoot<cereal::CarParams>();
  const QString name = QString::fromStdString(CP.getCarName());  // "toyota", "volkswagen", ...
  if (name == "toyota") return "TOYOTA";
  if (name == "volkswagen") return "VOLKSWAGEN";
  return name.toUpper();
}

void OptechPanel::updateCarButton() {
  const QString assigned = QString::fromStdString(params.get("dp_car_assigned")).trimmed();
  car_btn->setText(assigned.isEmpty() ? QString("차종 선택  (지금: 자동 인식)") : OptechCarSelect::menuName(assigned));
}

void OptechPanel::updateBrandItems() {
  const QString brand = currentBrand();
  const bool toyota = brand == "TOYOTA" || brand == "LEXUS";
  const bool vag = brand == "VOLKSWAGEN" || brand == "AUDI" || brand == "SKODA" || brand == "SEAT";
  for (auto w : toyota_items) w->setVisible(toyota);
  for (auto w : vag_items) w->setVisible(vag);
  for (auto w : hkg_items) w->setVisible(HKG_BRANDS.contains(brand));
  const bool bolt_cc = QString::fromStdString(params.get("dp_car_assigned")).trimmed() == BOLT_CC_CAR;
  for (auto w : bolt_items) w->setVisible(bolt_cc);
  brand_note->setVisible(brand.isEmpty());  // brand known but nothing special: no note
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
  for (auto v : values) v->refresh();
  updateToggles();
  updateCarButton();
  updateBrandItems();
}
