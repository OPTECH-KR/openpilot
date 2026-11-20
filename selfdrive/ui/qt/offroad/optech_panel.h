#pragma once

#include <functional>

#include <QLabel>
#include <QList>
#include <QPushButton>
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

private:
  std::string key;
  int min_v, max_v, step_v;
  std::function<QString(int)> fmt;
  QLabel label;
  QPushButton btnminus, btnplus;
  void change(int delta);
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
  int current_tab = 0;
  QList<QPushButton *> tab_btns;
  QList<ListWidget *> tab_lists;
  QList<OptechValueControl *> values;
  OptechValueControl *auto_shutdown_timer = nullptr;
  OptechValueControl *lane_priority_speed = nullptr;

  ParamControl *toggle(ListWidget *list, const QString &param, const QString &title, const QString &desc);
  OptechValueControl *value(ListWidget *list, const QString &param, const QString &title, const QString &desc,
                            int min, int max, int step, std::function<QString(int)> format);
  void showTab(int index);
  void updateTabStyles();
  void updateToggles();
};
