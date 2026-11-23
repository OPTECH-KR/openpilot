#pragma once

#include <functional>

#include <QLabel>
#include <QList>
#include <QListWidget>
#include <QPushButton>
#include <QStackedLayout>
#include <QVBoxLayout>

#include "selfdrive/ui/qt/widgets/controls.h"

// optech-hkg style number setting: value on the right, then － / ＋ buttons.
// `format` turns the stored number into the text shown (e.g. 0 -> "끄기").
class OptechValueControl : public AbstractControl {
  Q_OBJECT
public:
  OptechValueControl(const QString &param, const QString &title, const QString &desc,
                     int min, int max, int step, std::function<QString(int)> format);
  void refresh();
  std::function<void(int)> on_change;  // optional: called with the new value after a －/＋ press

private:
  std::string key;
  int min_v, max_v, step_v;
  std::function<QString(int)> fmt;
  QLabel label;
  QPushButton btnminus, btnplus;
  void change(int delta);
};

// optech-hkg style car selection: brands first, then that brand's cars.
// Stores the car in dp_car_assigned (car_helpers uses it as the fixed fingerprint); empty = auto detect.
class OptechCarSelect : public QWidget {
  Q_OBJECT
public:
  explicit OptechCarSelect(QWidget *parent = nullptr);
  void showBrands();

  static QString brandOf(const QString &car);
  static QString brandKo(const QString &brand);
  static QString menuName(const QString &car);  // "쉐보레  BOLT EUV 2022"

signals:
  void backPress();
  void selectedCar();

private:
  QListWidget *list;
  QStringList brands;
  QMap<QString, QStringList> cars;  // brand -> car names
  QMap<QString, QString> names;     // Hyundai / Kia / Genesis: car -> menu name ("K5 DL3 2020-2023")
  QString cur_brand;
  void showCars(const QString &brand);
};

// OPTECH settings menu (same tabs and look as optech-hkg): one list per tab.
// The items are the dragonpilot (legacypilot) settings this base really uses.
class OptechPanel : public QWidget {
  Q_OBJECT
public:
  explicit OptechPanel(QWidget *parent = nullptr);
  void showEvent(QShowEvent *event) override;

private:
  Params params;
  QStackedLayout *stack;
  QWidget *home;
  OptechCarSelect *car_select;
  QPushButton *car_btn;
  int current_tab = 0;
  QList<QPushButton *> tab_btns;
  QList<ListWidget *> tab_lists;
  QList<OptechValueControl *> values;
  OptechValueControl *lane_priority_speed = nullptr;
  QList<QWidget *> toyota_items, vag_items, bolt_items, hkg_items;
  QList<QWidget *> ray_items, porter_items;  // cars without SCC with their own settings (optech-hkg)
  QLabel *non_scc_note = nullptr;            // the trims without SCC (… NO SCC)
  QList<QWidget *> cam_group;      // 과속카메라: shown while 카메라 감속 is on
  QList<QWidget *> torque_values;  // 토크 가속 / 마찰 계수: shown while 토크 사용자 설정 is on
  ToggleControl *dm_icon = nullptr;
  QLabel *brand_note = nullptr;

  ParamControl *toggle(ListWidget *list, const QString &param, const QString &title, const QString &desc);
  OptechValueControl *value(ListWidget *list, const QString &param, const QString &title, const QString &desc,
                            int min, int max, int step, std::function<QString(int)> format);
  QString currentBrand();
  void updateCarButton();
  void updateBrandItems();
  void showTab(int index);
  void updateTabStyles();
  void updateToggles();
};
