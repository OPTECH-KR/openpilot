#include "selfdrive/ui/qt/offroad/optech_panel.h"

#include <algorithm>
#include <cmath>

#include <QHBoxLayout>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QDir>
#include <QElapsedTimer>
#include <QImage>
#include <QNetworkInterface>
#include <QScroller>
#include <QTimer>

#include <QrCode.hpp>

#include "common/util.h"
#include "selfdrive/ui/qt/util.h"
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

// live text for 'GPS 확인' (optech-hkg gps_check_text): the GPS summary the UI keeps (ubloxGnss) + gpsLocationExternal
static QString optech_gps_check_text(int elapsed_s) {
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
  QString t = "<h2>GPS 확인 (판다/uno GPS)</h2>";
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
    t += "<p>GPS 칩에서 데이터가 오지 않아요. GPS 안테나가 연결돼 있는지 확인해 주세요.</p>";
  } else if (!fixed) {
    t += "<p>처음 켜면 위성을 찾는 데 1~3분 걸릴 수 있어요. 하늘이 잘 보이는 곳에서 확인하세요.</p>";
  }
  return t;
}

// '주행 기록 내려받기' (optech-hkg): the device's addresses a phone on the same Wi-Fi / hotspot can open
// (selfdrive/optech/logserver.py, port 8088); the device's own hotspot first
static QStringList optech_log_page_urls() {
  QStringList urls, others;
  for (const QNetworkInterface &nif : QNetworkInterface::allInterfaces()) {
    if (!(nif.flags() & QNetworkInterface::IsUp) || (nif.flags() & QNetworkInterface::IsLoopBack)) continue;
    if (nif.name().startsWith("rmnet")) continue;  // mobile data: a phone can't reach it
    for (const QNetworkAddressEntry &e : nif.addressEntries()) {
      if (e.ip().protocol() != QAbstractSocket::IPv4Protocol) continue;
      const QString url = QString("http://%1:8088").arg(e.ip().toString());
      (e.ip().toString().startsWith("192.168.43.") ? urls : others) << url;
    }
  }
  return urls + others;
}

// QR code + how to use it, for the phone to open the log page (optech-hkg LogQrDialog)
class OptechLogQrDialog : public QDialogBase {
public:
  OptechLogQrDialog(QWidget *parent, const QStringList &urls) : QDialogBase(parent) {
    QHBoxLayout *main = new QHBoxLayout(this);
    main->setContentsMargins(60, 50, 60, 50);
    main->setSpacing(60);

    QLabel *qr = new QLabel();
    qrcodegen::QrCode code = qrcodegen::QrCode::encodeText(urls[0].toUtf8().data(), qrcodegen::QrCode::Ecc::MEDIUM);
    const int sz = code.getSize();
    QImage im(sz + 8, sz + 8, QImage::Format_RGB32);  // 4-module white border
    im.fill(qRgb(255, 255, 255));
    for (int y = 0; y < sz; y++) {
      for (int x = 0; x < sz; x++) {
        if (code.getModule(x, y)) im.setPixel(x + 4, y + 4, qRgb(0, 0, 0));
      }
    }
    const int px = (720 / (sz + 8)) * (sz + 8);
    qr->setPixmap(QPixmap::fromImage(im.scaled(px, px, Qt::KeepAspectRatio, Qt::FastTransformation)));
    main->addWidget(qr, 0, Qt::AlignVCenter);

    QVBoxLayout *right = new QVBoxLayout();
    right->setSpacing(30);
    QLabel *title = new QLabel("폰 카메라로 QR 코드를 찍으세요");
    title->setStyleSheet("font-size: 60px; font-weight: 600;");
    title->setWordWrap(true);
    right->addWidget(title);
    QLabel *desc = new QLabel(
      "열린 화면에서 '전체 기록 한 번에 받기'를 누르고, 받은 파일을 카카오톡으로 보내 주세요.\n\n"
      "폰이 이 기기와 같은 와이파이나 핫스팟에 연결돼 있어야 열립니다. 15분 뒤 자동으로 닫힙니다.\n\n"
      "주소: " + urls.join("  /  "));
    desc->setStyleSheet("font-size: 40px; color: #CCCCCC;");
    desc->setWordWrap(true);
    right->addWidget(desc);
    right->addStretch(1);
    QPushButton *close = new QPushButton("닫기");
    close->setFixedHeight(140);
    close->setStyleSheet("font-size: 50px; border-radius: 20px; background-color: #393939;");
    QObject::connect(close, &QPushButton::clicked, this, &QDialog::accept);
    right->addWidget(close);
    main->addLayout(right, 1);
  }
};

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
  // ======== 주행 (same order as optech-hkg: 사용 방식 at the top, then the sections) ========
  // '사용 방식' like optech-hkg (title = current choice, button 선택). Here it is dragonpilot's ALKA (dp_alka):
  // the car's own cruise does the speed once SET is pressed, so "steering only from the cruise button" is not possible
  ButtonControl *engage_mode_btn = new ButtonControl("", "선택",
    "openpilot 조향을 언제 켤지 고릅니다.\n"
    "크루즈와 함께: 크루즈 SET을 눌러 차의 크루즈가 켜지면 조향도 함께 켜집니다. 속도는 차의 크루즈가 맡습니다.\n"
    "메인만 켜도 조향: 크루즈 메인 버튼만 켜 두면 SET을 누르지 않아도 조향을 도와줍니다(ALKA). 속도는 운전자가 페달로 조절하고, "
    "SET을 누르면 차의 크루즈도 함께 켜집니다. 주행 중 브레이크를 밟은 채 메인 버튼을 두 번 누르면 잠시 껐다 켤 수 있습니다.\n"
    "재부팅해야 적용됩니다.");
  const QStringList engage_names = {"크루즈와 함께", "메인만 켜도 조향"};
  auto engage_name = [=]() { return "사용 방식: " + engage_names[params.getBool("dp_alka") ? 1 : 0]; };
  engage_mode_btn->setTitle(engage_name());
  QObject::connect(engage_mode_btn, &ButtonControl::clicked, [=]() {
    const QString cur = engage_name().section(": ", 1);
    const QString sel = MultiOptionDialog::getSelection("사용 방식을 고르세요", engage_names, cur, this);
    if (sel.isEmpty() || sel == cur) return;
    params.putBool("dp_alka", sel == engage_names[1]);
    engage_mode_btn->setTitle(engage_name());
  });
  drive->addItem(engage_mode_btn);
  // Hyundai / Kia / Genesis with the car's own cruise: selfdrive/car/hyundai/carcontroller.py set_speed_sync
  hkg_items.append(toggle(drive, "OptechCruiseSetCurrent", "켤 때 지금 속도로 설정",
    "달리는 중에 크루즈를 켜면, 차의 크루즈가 예전 설정 속도(예: 60)로 갑자기 빨라지지 않게 설정 속도를 지금 속도로 맞춥니다. "
    "openpilot이 크루즈 버튼(SET-, RES+)을 대신 눌러 1 km/h씩 맞추고, 다 맞춘 뒤에는 운전자가 버튼으로 바꾸는 대로 따릅니다.\n"
    "차의 크루즈는 30 km/h 아래로는 설정되지 않아서, 그보다 느릴 때는 30 km/h로 맞춥니다. "
    "현대·기아·제네시스에서 차의 순정 크루즈를 쓸 때만 동작합니다. 시동을 다시 걸면 적용됩니다."));
  drive->addItem(optech_section("가속 페달"));
  toggle(drive, "DisengageOnAccelerator", "가속 페달을 밟으면 끄기",
         "켜면 가속 페달을 밟는 순간 openpilot이 꺼집니다.\n"
         "끄면 페달을 밟는 동안만 운전자가 가속하고, 페달을 떼면 openpilot이 이어서 운전을 돕습니다.");

  drive->addItem(optech_section("과속카메라"));
  // same as optech-hkg: only '카메라 감속' while it is off; when on, its note, the timing values and the camera DB
  ParamControl *cam_decel = toggle(drive, "OptechSpeedCamDecel", "카메라 감속",
         "과속카메라 앞에서 제한 속도까지 미리 줄입니다. 켜면 아래에 동작 설명이 나옵니다.");
  QLabel *cam_note = optech_note(
    "● 과속카메라 앞 '감속 시작'에 정한 시간(처음 값 22초) 전부터 설정 속도를 조금씩 내려서, '감속 끝'(6초 전)까지 '목표 속도'(제한 속도의 %)에 맞춥니다. "
    "구간단속은 구간이 끝날 때까지 제한 속도를 지킵니다.\n"
    "● 카메라 정보는 아래 '내장 카메라 DB'에서 받습니다. 기기 GPS와 전국 카메라 위치(약 3만 1천 대)로 찾고, 내비 앱은 필요 없습니다. "
    "이동식·새 카메라는 모르고, 반대 차로의 카메라에도 줄일 수 있습니다.\n"
    "● openpilot이 가감속을 맡는 차량만 속도를 줄입니다. 차의 순정 크루즈를 쓰는 차량은 화면에 CAM 표시만 됩니다. GPS가 안 잡히면 동작하지 않습니다.");
  cam_note->setStyleSheet("font-size: 36px; color: #E0E0E0; background-color: #333333; border-radius: 10px; padding: 20px; margin: 10px 0px;");
  drive->addItem(cam_note);
  cam_group.append(cam_note);
  cam_group.append(value(drive, "OptechCamDecelStart", "감속 시작 (초 전)",
        "카메라에 도착하기 몇 초 전부터 설정 속도를 줄이기 시작할지 정합니다. 클수록 일찍, 부드럽게 줄입니다. "
        "시속 100km에서 22초면 약 600m 앞입니다. 처음 값 22.",
        5, 60, 1, [](int v) { return QString("%1초 전").arg(v); }));
  cam_group.append(value(drive, "OptechCamDecelEnd", "감속 끝 (초 전)",
        "카메라에 도착하기 몇 초 전까지 목표 속도에 맞출지 정합니다. 클수록 카메라보다 일찍 목표 속도가 됩니다. 처음 값 6.",
        0, 20, 1, [](int v) { return QString("%1초 전").arg(v); }));
  cam_group.append(value(drive, "OptechCamSafetyFactor", "목표 속도 (제한 속도의 %)",
        "카메라 앞과 구간단속 안에서 제한 속도의 몇 %로 달릴지 정합니다. "
        "100이면 제한 속도 그대로(단속 100km/h → 100km/h), 105면 5% 더 빠르게 (100km/h → 105km/h). 단속 기준을 넘지 않게 주의하세요.",
        90, 120, 1, [](int v) { return QString("%1%").arg(v); }));
  cam_group.append(value(drive, "HapticFeedbackWhenSpeedCamera", "과속 단속 알림",
        "과속 단속 카메라 앞에서 감속을 시작할 때 8초 동안 알려 주는 방법입니다.\n"
        "0:사용 안 함, 1:핸들 진동, 2:계기판 표시 (1·2는 현대·기아·제네시스의 차로 경고 표시를 씁니다), 3:화면에 알림",
        0, 3, 1, [](int v) {
          const char *names[] = {"사용 안 함", "핸들 진동", "계기판 표시", "화면 알림"};
          return QString(names[std::clamp(v, 0, 3)]);
        }));
  cam_group.append(value(drive, "OptechNaviLinkMode", "내비 연동 방식",
        "카메라 정보를 어디서 받을지 정합니다.\n0:내비 안 씀 (내장 카메라 DB만, 내비 앱이 보내는 정보는 무시)\n"
        "1:APM(내비 앱)\n2:APM + 순정 내비게이션\n3:NDA\n"
        "내비 앱은 폰과 이 기기가 같은 와이파이나 핫스팟에 연결돼 있어야 합니다. 앱 정보가 있으면 먼저 쓰고, 없을 때는 내장 카메라 DB로 채웁니다. "
        "바꾼 뒤 재부팅해야 적용됩니다.",
        0, 3, 1, [](int v) {
          const char *names[] = {"내비 안 씀", "APM", "APM+순정", "NDA"};
          return QString(names[std::clamp(v, 0, 3)]);
        }));
  cam_group.append(toggle(drive, "OptechSpeedCam", "내장 카메라 DB",
         "내비 앱 없이 기기 GPS로 앞쪽 고정식 단속카메라(과속·신호과속·구간단속)를 찾습니다.\n"
         "전국 약 3만 1천 대(공공데이터, 2026년 10월)의 위치가 기기에 들어 있습니다. 구간단속은 구간이 끝날 때까지 제한속도를 지킵니다.\n\n"
         "● 함께 켜야 할 것: '카메라 감속' (끄면 화면에 CAM 표시만 나오고 속도는 줄이지 않습니다)\n"
         "● 안 되는 경우: 이동식 카메라, 새로 생긴 카메라 / GPS가 안 잡힐 때\n"
         "● 주의: 반대 차로의 카메라에서도 속도를 줄일 수 있습니다.\n\n"
         "시동을 다시 걸면 적용됩니다."));
  // visibility only after addItem (a widget without a parent would open as its own window and crash the C2 UI)
  for (auto w : cam_group) w->setVisible(params.getBool("OptechSpeedCamDecel"));
  QObject::connect(cam_decel, &ToggleControl::toggleFlipped, [=](bool on) { for (auto w : cam_group) w->setVisible(on); });

  // 신호등 (selfdrive/controls/lib/optech_signal.py, StarPilot's stop light detector): HUD light + green light alert
  drive->addItem(optech_section("신호등"));
  ParamControl *signal_on = toggle(drive, "OptechSignalEnable", "신호등 사용",
    "켜 두면 주행 모델의 예측으로 빨간불·초록불을 판단해 주행 화면 가운데 위에 신호등을 보여 줍니다. "
    "차가 신호에 맞춰 서거나 출발하지는 않고, 화면 표시와 알림에만 씁니다.\n"
    "신호등을 직접 보는 것이 아니라서 노란불은 없고, 서지 않고 지나가는 초록불에서는 아무것도 켜지지 않습니다. "
    "끄면 신호등 표시와 초록불 알림이 모두 꺼집니다.");
  ParamControl *green_alert = toggle(drive, "OptechGreenAlert", "초록불 알림",
    "빨간불에 서 있다가 초록불로 바뀌면 소리와 함께 '초록불로 바뀌었어요'를 띄워 줍니다. 오픈파일럿이 켜져 있을 때만 알려 줍니다.\n"
    "신호등을 직접 보는 것이 아니라, 주행 모델이 멈출지 출발할지 예측한 것으로 판단합니다. "
    "앞차가 출발할 때도 울릴 수 있고, 늦거나 빠를 수 있으니 출발 전에는 꼭 신호를 직접 확인하세요.");
  green_alert->setVisible(params.getBool("OptechSignalEnable"));
  QObject::connect(signal_on, &ToggleControl::toggleFlipped, [=](bool on) { green_alert->setVisible(on); });

  // ======== 속도 ========
  speed->addItem(optech_note("이 탭의 설정은 openpilot이 가감속을 맡는 차량에서만 동작합니다. 차의 원래 크루즈를 쓰는 차량은 변화가 없습니다."));
  speed->addItem(optech_section("출발·정지 (출발이 굼뜨거나 정지가 거칠 때)"));
  toggle(speed, "dp_long_use_krkeegen_tune", "정체 구간 출발 보조",
         "막히는 길에서 앞차가 출발할 때 조금 더 빨리 가속을 시작합니다. (krkeegan 튠)");
  speed->addItem(optech_section("속도별 가속 세기 (가속이 너무 세거나 약할 때)"));
  speed->addItem(new ButtonParamControl("dp_long_accel_profile", "가속 성향",
                 "속도에 따른 가속 세기를 고릅니다.\nOP: 기본 값\nECO: 부드럽게(연비)\nNOR: 보통\nSPT: 빠르게(스포츠)", "",
                 std::vector<QString>{"OP", "ECO", "NOR", "SPT"}));
  speed->addItem(optech_section("차간거리"));
  speed->addItem(new ButtonParamControl("LongitudinalPersonality", "주행 성향 (차간거리)",
                 "보통을 추천합니다.\n가깝게: 앞차를 더 가까이 따라가고, 가속·감속이 빠릅니다.\n"
                 "멀리: 앞차와 거리를 더 두고 부드럽게 움직입니다.", "",
                 std::vector<QString>{"가깝게", "보통", "멀리"}));
  toggle(speed, "dp_long_use_df_tune", "다이내믹 차간거리",
         "'주행 성향' 설정에 맞춰 앞차와의 거리를 상황에 따라 자동으로 조절합니다.");

  // ======== 조향 ========
  steer->addItem(optech_section("조향"));
  // OptechLatMethod '조향 방식' (selfdrive/car/interfaces.py set_optech_lat_method, applied at the next start):
  // 0 the car's own (torque for most), 1 PID, 2 INDI, 3 LQR with OPKR's start values; only the chosen method's values show
  {
    const QStringList lm_names = {"기본 (차종 기본값)", "PID", "INDI", "LQR"};
    const QString lm_desc =
      "핸들을 얼마나 돌릴지 계산하는 방식을 고릅니다. 바꾼 뒤 기기를 다시 켜야 적용됩니다.\n"
      "\n"
      "[기본] 차종에 맞춘 원래 방식입니다(대부분 토크). 토크는 주행하며 차에 맞게 스스로 학습합니다. 잘 모르면 그대로 두세요.\n"
      "[PID] 오래된 기본 방식입니다. 핸들 각도 차이만큼 바로 돌립니다.\n"
      "[INDI] 핸들 움직임을 예측해서 돌립니다. 반응이 빠른 편입니다.\n"
      "[LQR] 핸들 각도와 움직임을 함께 보고 부드럽게 돌립니다.\n"
      "\n"
      "PID / INDI / LQR은 OPKR의 현대·기아 기본값으로 시작합니다. 차마다 맞는 값이 달라서 "
      "핸들이 흔들리거나 덜 꺾이면 아래 값을 조금씩 바꾸거나 기본으로 돌아가세요.";
    auto lm_mode = [=]() { return std::clamp(QString::fromStdString(params.get("OptechLatMethod")).toInt(), 0, 3); };
    ButtonControl *lm_btn = new ButtonControl("", "선택", lm_desc);
    steer->addItem(lm_btn);
    QList<QPair<int, QWidget *>> *lm_vals = new QList<QPair<int, QWidget *>>{
      {1, value(steer, "OptechPidKp", "PID 비례 (Kp, 0.01 단위)", "핸들 각도 차이에 바로 반응하는 세기입니다. 높이면 빨리 꺾고, 너무 높으면 흔들립니다. 처음 값 25.", 5, 100, 1, [](int v) { return QString::number(v); })},
      {1, value(steer, "OptechPidKi", "PID 적분 (Ki, 0.001 단위)", "오래 남은 차이를 조금씩 메우는 세기입니다. 커브에서 계속 덜 꺾이면 조금 올립니다. 처음 값 40.", 0, 200, 1, [](int v) { return QString::number(v); })},
      {1, value(steer, "OptechPidKf", "PID 앞먹임 (Kf, 0.00001 단위)", "필요한 핸들 각도를 미리 넣어 주는 세기입니다. 처음 값 7.", 0, 50, 1, [](int v) { return QString::number(v); })},
      {2, value(steer, "OptechIndiInner", "INDI 안쪽 게인 (0.1 단위)", "커브에 들어갈 때 꺾는 반응입니다. 처음 값 35.", 10, 100, 1, [](int v) { return QString::number(v); })},
      {2, value(steer, "OptechIndiOuter", "INDI 바깥 게인 (0.1 단위)", "차로 가운데를 지키는 세기입니다. 처음 값 20.", 10, 100, 1, [](int v) { return QString::number(v); })},
      {2, value(steer, "OptechIndiTime", "INDI 시간 상수 (0.1 단위)", "높이면 부드럽고 느리게, 낮추면 빠르게 움직입니다. 처음 값 14.", 5, 50, 1, [](int v) { return QString::number(v); })},
      {2, value(steer, "OptechIndiAct", "INDI 조향 효율 (0.1 단위)", "낮추면 더 많이 꺾습니다. 너무 많이 꺾이면 올립니다. 처음 값 20.", 5, 50, 1, [](int v) { return QString::number(v); })},
      {3, value(steer, "OptechLqrScale", "LQR 크기 (Scale)", "높이면 덜 꺾습니다. 처음 값 1500.", 500, 3000, 50, [](int v) { return QString::number(v); })},
      {3, value(steer, "OptechLqrKi", "LQR 적분 (Ki, 0.001 단위)", "오래 남은 차이를 메우는 세기입니다. 처음 값 16.", 0, 100, 1, [](int v) { return QString::number(v); })},
      {3, value(steer, "OptechLqrDcGain", "LQR DC 게인 (0.00001 단위)", "핸들 각도와 조향 힘의 비율입니다. 처음 값 265.", 100, 500, 5, [](int v) { return QString::number(v); })},
    };
    auto lm_refresh = [=]() {
      const int m = lm_mode();
      lm_btn->setTitle("조향 방식: " + lm_names[m]);
      for (auto &v : *lm_vals) v.second->setVisible(v.first == m);
    };
    QObject::connect(lm_btn, &ButtonControl::clicked, [=]() {
      ConfirmationDialog info("<b>조향 방식</b><br><br>" + lm_desc.toHtmlEscaped().replace("\n", "<br>"), "선택하기", "취소", true, this);
      if (!info.exec()) return;
      const QString cur = lm_names[lm_mode()];
      const QString sel = MultiOptionDialog::getSelection("조향 방식", lm_names, cur, this);
      if (sel.isEmpty() || sel == cur) return;
      params.put("OptechLatMethod", std::to_string(lm_names.indexOf(sel)));
      params.put("dp_lat_controller", "0");  // the dragonpilot switch this replaces
      lm_refresh();
      ConfirmationDialog::alert("기기를 다시 켜야 적용됩니다.", this);
    });
    lm_refresh();
  }
  value(steer, "PathOffset", "경로 좌우 보정 (쏠릴 때)",
        "차가 차로 안에서 한쪽으로 치우쳐 달리면 보정합니다. -값:왼쪽으로, +값:오른쪽으로 옮깁니다(cm). 주행 중에도 몇 초 안에 적용됩니다.",
        -50, 50, 1, [](int v) { return v == 0 ? QString("0") : QString("%1%2 cm").arg(v > 0 ? "+" : "").arg(v); });
  toggle(steer, "NNFF", "NNFF 조향 보정",
         "차종별로 미리 학습된 작은 신경망으로 커브에서 필요한 핸들 힘을 더 정확히 계산합니다(twilsonco NNFF, 당근 c3-wip에서 이식). "
         "현대·기아·제네시스 일부 차종에만 모델이 있고, 모델이 없는 차(K7, 그랜저 IG 등)는 켜도 기존 방식 그대로입니다. "
         "조향 방식이 토크인 차량에서만 동작합니다. 재부팅해야 적용됩니다.");
  toggle(steer, "NNFFLite", "NNFF 라이트",
         "NNFF 모델이 없는 차(K7, 그랜저 등)용입니다. 주행 모델이 예상한 앞쪽 커브 변화를 미리 보고, 커브에 들어가거나 나올 때 핸들 마찰 보정을 "
         "미리 넣어 늦게 꺾이거나 늦게 풀리는 느낌을 줄입니다. 보정 크기는 기존 마찰 값 안으로 제한됩니다. "
         "모델이 있는 차에서 NNFF를 켜면 NNFF가 우선합니다. 조향 방식이 토크인 차량에서만 동작합니다. 재부팅해야 적용됩니다.");
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
         "카메라로 앞 도로의 굽은 정도를 보고 커브에 맞는 속도로 미리 줄입니다. openpilot이 가감속을 맡는 차량만 해당됩니다.");
  steer->addItem(optech_section("조향 세부 (커브에서 덜 꺾이거나 너무 꺾일 때)"));
  value(steer, "SteerRatioApply", "조향비 고정",
        "핸들을 돌린 만큼 바퀴가 꺾이는 비율(조향비)을 고정합니다(0.1 단위, 150=15.0). 0:자동 학습값 사용. 주행 중에도 몇 초 안에 적용됩니다.",
        0, 300, 2, [](int v) { return v == 0 ? QString("자동") : QString::number(v / 10.0, 'f', 1); });
  value(steer, "LiveSteerRatioApply", "실시간 조향비 적용",
        "자동으로 학습한 조향비를 몇 %로 쓸지 정합니다. 커브에서 너무 많이 꺾이면(오버스티어) 낮추세요. '조향비 고정'을 쓰면 적용되지 않습니다.",
        50, 110, 1, [](int v) { return QString("%1%").arg(v); });
  value(steer, "SteerActuatorDelay", "조향 반응 지연 보정",
        "조향 명령을 보낸 뒤 실제로 핸들이 움직이기까지 걸리는 시간 보정입니다(0.01초 단위). 커브에서 늦게 꺾이면 조금 올려 보세요. "
        "0:차종 기본값. 시동을 다시 걸면 적용됩니다.",
        0, 100, 1, [](int v) { return v == 0 ? QString("차종 기본") : QString::number(v / 100.0, 'f', 2) + "초"; });
  OptechValueControl *torque_custom = value(steer, "LateralTorqueCustom", "토크 사용자 설정",
        "토크 조향 값을 직접 정할지 고릅니다. 끔:차량 기본값 + 주행하며 자동 학습, 켬:자동 학습을 끄고 아래 '토크 가속 계수'와 '토크 마찰 계수'를 사용"
        "(주행 중 바꿔도 몇 초 안에 적용). 조향 방식이 토크인 차량에서만 동작합니다.",
        0, 1, 1, [](int v) { return v > 0 ? QString("켬") : QString("끔"); });
  torque_values.append(value(steer, "LateralTorqueAccelFactor", "토크 가속 계수",
        "토크 조향에서 원하는 회전량을 내는 데 필요한 힘 계수입니다(0.001 단위). 커브에서 덜 꺾이면 낮추고, 너무 꺾이면 높이세요. "
        "'토크 사용자 설정'이 켜져 있을 때만 적용됩니다.",
        1000, 4000, 10, [](int v) { return QString::number(v / 1000.0, 'f', 2); }));
  torque_values.append(value(steer, "LateralTorqueFriction", "토크 마찰 계수",
        "핸들 마찰을 보정하는 값입니다(0.001 단위). 직진에서 핸들이 늦게 반응하면 조금 올려 보세요. "
        "'토크 사용자 설정'이 켜져 있을 때만 적용됩니다.",
        0, 1000, 10, [](int v) { return QString::number(v / 1000.0, 'f', 2); }));
  torque_custom->on_change = [=](int) { updateToggles(); };

  // ======== 화면 ========
  // OptechSettingsTimeout '화면 유지 시간' (ui.cc Device::resetInteractiveTimeout)
  {
    ButtonControl *keep_btn = new ButtonControl("", "선택",
      "설정을 천천히 보고 만질 수 있게 시간 여유를 둡니다. "
      "설정한 시간이 지나면 자동으로 메인 화면으로 돌아갑니다. 차량에 연결되어 있으면 주행 화면으로 돌아갑니다. "
      "화면을 만지면 시간을 처음부터 다시 셉니다. 항상: 돌아가지 않습니다. "
      "차량에 연결하지 않고 켜 두었을 때는 메인 화면으로 돌아가면서 화면도 꺼지고, 화면을 누르면 다시 켜집니다. "
      "설정 화면을 보다가 주행이 시작되면 시간과 상관없이 바로 주행 화면으로 바뀝니다.");
    const QStringList keep_names = {"1분", "3분", "5분", "10분", "항상"};
    const QList<int> keep_secs = {60, 180, 300, 600, -1};
    auto keep_name = [=]() {
      const std::string v = params.get("OptechSettingsTimeout");
      const int i = keep_secs.indexOf(v.empty() ? 180 : std::atoi(v.c_str()));
      return "화면 유지 시간: " + keep_names[i < 0 ? 1 : i];
    };
    keep_btn->setTitle(keep_name());
    QObject::connect(keep_btn, &ButtonControl::clicked, [=]() {
      const QString sel = MultiOptionDialog::getSelection("화면 유지 시간", keep_names, keep_name().section(": ", 1), this);
      if (sel.isEmpty()) return;
      params.put("OptechSettingsTimeout", std::to_string(keep_secs[keep_names.indexOf(sel)]));
      keep_btn->setTitle(keep_name());
    });
    disp->addItem(keep_btn);
  }
  // OptechDriveDim '주행 중 밝기' (ui.cc Device::updateBrightness)
  {
    ButtonControl *dim_btn = new ButtonControl("", "선택",
      "[주행 중 화면 어둡게] 주행 중에만 동작합니다. 화면을 30초 동안 만지지 않으면 화면을 고른 밝기로 어둡게 합니다. "
      "화면은 꺼지지 않습니다. 밤에 화면이 눈부실 때 쓰세요. "
      "화면을 만지거나 경고가 뜨면 바로 원래 밝기로 돌아옵니다. 끔(처음 값): 밝기를 낮추지 않습니다.");
    const QStringList dim_names = {"끔", "10%", "20%", "30%", "40%", "50%", "70%"};
    const QList<int> dim_pcts = {0, 10, 20, 30, 40, 50, 70};
    auto dim_name = [=]() {
      const int i = dim_pcts.indexOf(std::atoi(params.get("OptechDriveDim").c_str()));
      return "주행 중 밝기: " + dim_names[i < 0 ? 0 : i];
    };
    dim_btn->setTitle(dim_name());
    QObject::connect(dim_btn, &ButtonControl::clicked, [=]() {
      const QString sel = MultiOptionDialog::getSelection("주행 중 밝기", dim_names, dim_name().section(": ", 1), this);
      if (sel.isEmpty()) return;
      params.put("OptechDriveDim", std::to_string(dim_pcts[dim_names.indexOf(sel)]));
      dim_btn->setTitle(dim_name());
    });
    disp->addItem(dim_btn);
  }
  toggle(disp, "OptechShowRecordBtn", "녹화 버튼",
    "켜 두면(초록색) 주행 화면 오른쪽 아래에 동그란 'REC' 녹화 버튼이 보입니다. 누르면 기기 화면을 동영상으로 녹화하고 "
    "(녹화 중에는 버튼이 빨갛게 깜빡입니다), 다시 누르면 멈춥니다. 영상은 3분마다 나뉘어 기기 저장공간(videos 폴더)에 남습니다. "
    "주행 영상을 남기고 싶을 때만 켜세요. 끄면 버튼이 사라지고 하던 녹화도 멈춥니다.");
  toggle(disp, "ShowTpms", "타이어 공기압",
         "주행 화면 오른쪽 맨 아래 칸에 네 바퀴의 타이어 공기압(psi)을 보여 줍니다. 위 줄이 앞바퀴(왼쪽·오른쪽), 아래 줄이 뒷바퀴입니다. "
         "현대·기아·제네시스처럼 공기압을 보내는 차에서만 나옵니다.");
  toggle(disp, "ShowGpsInfo", "GPS 상태",
         "주행 화면 왼쪽 위(연결 표시 옆)에 GPS가 잡혔는지와 신호 세기(막대 4칸)를 보여 줍니다. 초록: 잘 잡힘, 주황: 찾는 중·약함. "
         "GPS는 시동이 켜져 있을 때만 동작합니다.");
  toggle(disp, "OptechShowDeviceState", "기기 상태",
         "주행 화면 오른쪽 가운데 칸에 기기의 CPU 온도와 CPU 사용률을 보여 줍니다. 80°C를 넘거나 사용률이 90%를 넘으면 빨갛게 깜빡입니다.");
  toggle(disp, "ShowBlindSpot", "후측방(BSD) 경고",
         "옆 차로 뒤쪽에 차가 있으면 화면 양옆에 노란 '차량 주의' 표시가 뜹니다. 그쪽으로 방향지시등을 켜면 빨간 표시와 "
         "'왼쪽/오른쪽 차량 주의' 글이 깜빡입니다. 시속 30km 이상에서만 보이고, 차에 후측방 감지(BSD)가 있어야 합니다.");
  // ShowRadarInfo '레이더 물체 표시': 0 off, 1 moving objects + speed, 2 also how far to the side, 3 also stopped ones
  {
    ButtonControl *radar_btn = new ButtonControl("", "선택",
      "앞 레이더가 잡은 주변 물체를 주행 화면에 네모로 보여 줍니다. 네모 안 숫자는 그 물체의 속도(km/h)입니다.\n"
      "초록: 같은 방향으로 가는 물체, 빨강: 마주 오는 물체, 주황 '정지': 서 있는 물체.\n"
      "사람·차·오토바이 같은 종류는 구별하지 못합니다. 레이더가 여러 물체를 보내 주는 차에서만 여러 개가 나옵니다.\n"
      "서 있는 물체까지 보이게 하면 가드레일·표지판도 잡혀서 화면이 복잡해질 수 있습니다.");
    const QStringList radar_names = {"안 보임", "움직이는 물체", "움직이는 물체 + 옆 거리", "전부 (서 있는 물체까지)"};
    auto radar_name = [=]() {
      return "레이더 물체 표시: " + radar_names[std::clamp(std::atoi(params.get("ShowRadarInfo").c_str()), 0, 3)];
    };
    radar_btn->setTitle(radar_name());
    QObject::connect(radar_btn, &ButtonControl::clicked, [=]() {
      const QString sel = MultiOptionDialog::getSelection("레이더 물체 표시", radar_names, radar_name().section(": ", 1), this);
      if (sel.isEmpty()) return;
      params.put("ShowRadarInfo", std::to_string(radar_names.indexOf(sel)));
      radar_btn->setTitle(radar_name());
    });
    disp->addItem(radar_btn);
  }
  toggle(disp, "ShowConnInfo", "APM 연결 표시",
         "주행 화면 왼쪽 위에 연결 상태 표시를 보여 줍니다. APM·APN: 내비 앱 연결, NDA: 차의 고속도로 주행 보조 연결, "
         "SCC2: 크루즈(SCC)가 카메라 쪽에 있는 차, RadarTracks: 레이더가 여러 물체를 보내는 차.");
  // '운전자 모니터링 아이콘' (ShowDmInfo 0 / 1); the mode itself is chosen on the 토글 page
  dm_icon = new ToggleControl("운전자 모니터링 아이콘",
    "주행 화면 왼쪽 위에 운전자 모니터링 아이콘(얼굴 모양)을 보여 줍니다. 토글 화면의 운전자 모니터링이 '기본 사용'일 때만 쓸 수 있습니다.",
    "", QString::fromStdString(params.get("ShowDmInfo")).toInt() >= 1, this);
  QObject::connect(dm_icon, &ToggleControl::toggleFlipped, [=](bool on) {
    if (QString::fromStdString(params.get("OptechDmMode")).toInt() == 0) params.put("ShowDmInfo", on ? "1" : "0");
  });
  disp->addItem(dm_icon);
  disp->addItem(optech_section("화면 버튼"));
  toggle(disp, "dp_long_personality_btn", "주행 성향 버튼",
         "주행 화면에 주행 성향(차간거리 성향) 버튼을 보여 줍니다.");
  toggle(disp, "dp_long_accel_btn", "가속 성향 버튼",
         "주행 화면에 가속 성향 버튼을 보여 줍니다.");

  // ======== 고급 ========
  adv->addItem(optech_section("기기"));
  // 'GPS 확인' (optech-hkg): GpsCheck keeps the uBlox (boardd) and ubloxd on with the car off while the screen is open
  {
    ButtonControl *gps_btn = new ButtonControl("GPS 확인", "확인",
      "시동을 걸지 않아도 GPS를 켜서 잡힘 여부, 신호 세기, 위성 수, 위치 오차를 실시간으로 보여 줍니다. "
      "GPS 안테나가 제대로 연결됐는지 확인할 때 쓰세요. 창을 닫으면 GPS도 다시 꺼집니다.");
    QObject::connect(gps_btn, &ButtonControl::clicked, [=]() {
      params.putBool("GpsCheck", true);
      ConfirmationDialog d(optech_gps_check_text(0), "닫기", "", true, this);
      QLabel *label = d.findChild<QLabel *>();
      QElapsedTimer started;
      started.start();
      QTimer refresh;
      QObject::connect(&refresh, &QTimer::timeout, [&]() {
        if (label) label->setText(optech_gps_check_text(started.elapsed() / 1000));
      });
      refresh.start(500);
      d.exec();
      refresh.stop();
      params.putBool("GpsCheck", false);
    });
    adv->addItem(gps_btn);
  }
  // OptechOffShutdown '시동 끈 뒤 꺼짐' (selfdrive/thermald/power_monitoring.py, read every few seconds)
  {
    ButtonControl *off_btn = new ButtonControl("", "선택",
      "[기기 전원을 끄는 시간] 상시 전원(시동을 꺼도 전기가 계속 들어오는 곳)에 연결한 차량용입니다. "
      "주행 후 시동을 끄고 고른 시간이 지나면 기기가 꺼져서 차 배터리를 아낍니다. "
      "시동을 끄면 전기도 끊기는 곳에 연결했다면 끔으로 두세요. 끔(처음 값): 꺼지지 않습니다. "
      "기기를 켠 뒤 한 번도 시동을 걸지 않았으면 (집에서 업데이트·설정할 때) 꺼지지 않습니다.");
    const QStringList off_names = {"끔", "30초", "1분", "3분", "5분", "10분"};
    const QList<int> off_secs = {0, 30, 60, 180, 300, 600};
    auto off_name = [=]() {
      const int i = off_secs.indexOf(std::atoi(params.get("OptechOffShutdown").c_str()));
      return "시동 끈 뒤 꺼짐: " + off_names[i < 0 ? 0 : i];
    };
    off_btn->setTitle(off_name());
    QObject::connect(off_btn, &ButtonControl::clicked, [=]() {
      const QString sel = MultiOptionDialog::getSelection("시동 끈 뒤 꺼짐", off_names, off_name().section(": ", 1), this);
      if (sel.isEmpty()) return;
      params.put("OptechOffShutdown", std::to_string(off_secs[off_names.indexOf(sel)]));
      params.putBool("dp_device_auto_shutdown", false);  // the dragonpilot switch this replaces
      off_btn->setTitle(off_name());
    });
    adv->addItem(off_btn);
  }
  toggle(adv, "OpkrHotspotOnBoot", "부팅 시 핫스팟 켜기",
         "켜 두면 기기가 켜질 때 핫스팟(테더링)이 자동으로 켜집니다. 재부팅해야 적용됩니다.");
  adv->addItem(new ButtonParamControl("dp_device_audible_alert_mode", "알림 소리",
               "기본: 원래대로 소리를 냅니다.\n경고만: 경고일 때만 소리를 냅니다.\n끄기: 소리를 내지 않습니다.", "",
               std::vector<QString>{"기본", "경고만", "끄기"}));

  adv->addItem(optech_section("주행 기록"));
  toggle(adv, "dp_logging", "주행 기록 저장",
         "주행 중 차량 정보와 카메라 영상을 기기에 저장합니다. 문제가 생겼을 때 원인을 찾는 데 꼭 필요합니다.\n"
         "새 주행 모델(아래 '옛 주행 모델 사용' 끔)과 함께 쓰면 기기가 느려질 수 있습니다.\n재부팅해야 적용됩니다.");
  // optech-hkg: selfdrive/optech/drivelog.py writes /data/drivelog/<date>-<time>.txt while driving
  ButtonControl *drivelog_btn = new ButtonControl("주행 기록 보기", "보기",
    "주행할 때마다 자동으로 남는 간단한 기록입니다. 고른 주행에서 켜짐·꺼짐, 경고, 오류, 프로그램 멈춤을 시간순으로 보여 줍니다. (최근 30번 보관)");
  QObject::connect(drivelog_btn, &ButtonControl::clicked, [=]() {
    const QString dir_path = "/data/drivelog";
    QDir dir(dir_path);
    const QStringList files = dir.entryList(QStringList() << "2*.txt" << "1*.txt", QDir::Files, QDir::Name | QDir::Reversed);
    if (files.isEmpty()) {
      ConfirmationDialog::alert("아직 주행 기록이 없어요.", this);
      return;
    }
    QStringList labels;  // file name YYYYmmdd-HHMMSS.txt -> "11/18 08:30 주행"
    for (const QString &f : files) {
      labels << QString("%1/%2 %3:%4 주행").arg(f.mid(4, 2), f.mid(6, 2), f.mid(9, 2), f.mid(11, 2));
    }
    const QString sel = MultiOptionDialog::getSelection("볼 주행을 고르세요", labels, "", this);
    if (sel.isEmpty()) return;
    const QString file = files[labels.indexOf(sel)];
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
    QString text = sel + (first_time.isEmpty() ? "" : " (" + first_time + " ~ " + last_time + ")") + "\n\n";
    if (events.isEmpty()) {
      text += "경고나 오류 없이 정상이었어요.";
    } else {
      if (events.size() > 200) {
        text += QString("(앞부분 %1줄 생략)\n").arg(events.size() - 200);
        events = events.mid(events.size() - 200);
      }
      text += events.join("\n");
    }
    ConfirmationDialog d(text, "확인", "", true, this);
    d.exec();
  });
  adv->addItem(drivelog_btn);
  ButtonControl *drivelog_get_btn = new ButtonControl("주행 기록 내려받기", "QR 보기",
    "주행 기록을 폰으로 받아 카카오톡 등으로 보낼 수 있습니다. 누르면 QR 코드가 뜨고, 폰으로 찍으면 기록 목록이 열립니다. "
    "기록에는 켜짐·꺼짐, 경고, 오류와 1초마다의 주행 상태가 들어 있고, 위치(좌표)는 들어 있지 않습니다. "
    "폰이 이 기기와 같은 와이파이나 핫스팟에 연결돼 있어야 합니다.");
  QObject::connect(drivelog_get_btn, &ButtonControl::clicked, [=]() {
    const QStringList urls = optech_log_page_urls();
    if (urls.isEmpty()) {
      ConfirmationDialog::alert("와이파이나 핫스팟에 연결돼 있지 않아요. 폰 핫스팟에 이 기기를 연결하거나, '부팅 시 핫스팟 켜기'로 "
                                "이 기기의 핫스팟을 켠 뒤 폰을 연결하고 다시 눌러 주세요.", this);
      return;
    }
    params.put("OptechLogServer", "1");  // logserver.py serves the page for 15 minutes
    OptechLogQrDialog(this, urls).exec();
  });
  adv->addItem(drivelog_get_btn);

  // 실험 모드 / openpilot 가감속 / 옛 주행 모델 / 자동 E2E are on the 토글 page (user 2026-11-23)
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
  if (lane_priority_speed) lane_priority_speed->setVisible(params.getBool("dp_lat_lane_priority_mode"));
  const bool torque_custom = QString::fromStdString(params.get("LateralTorqueCustom")).toInt() > 0;
  for (auto w : torque_values) w->setVisible(torque_custom);

  // 운전자 모니터링 아이콘: only with 토글 > 운전자 모니터링 '기본 사용'
  if (dm_icon) dm_icon->setEnabled(QString::fromStdString(params.get("OptechDmMode")).toInt() == 0);
}

void OptechPanel::showEvent(QShowEvent *event) {
  for (auto v : values) v->refresh();
  updateToggles();
  updateCarButton();
  updateBrandItems();
}
