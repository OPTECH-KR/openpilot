#pragma once

#include <QList>
#include <QPushButton>
#include <QVBoxLayout>

#include "selfdrive/ui/qt/widgets/controls.h"

// OPTECH settings menu (same look as optech-hkg): 6 tabs, one list per tab.
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
  ParamSpinBoxControl *auto_shutdown_timer = nullptr;
  ParamSpinBoxControl *lane_priority_speed = nullptr;

  ParamControl *toggle(ListWidget *list, const QString &param, const QString &title, const QString &desc);
  void showTab(int index);
  void updateTabStyles();
  void updateToggles();
};
