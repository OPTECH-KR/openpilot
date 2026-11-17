#pragma once

#include <QButtonGroup>
#include <QFileSystemWatcher>
#include <QFrame>
#include <QLabel>
#include <QPushButton>
#include <QStackedWidget>
#include <QWidget>
#include <QStackedLayout>
#include <QComboBox>

#include "selfdrive/ui/qt/widgets/controls.h"

// ********** settings window + top-level panels **********
class SettingsWindow : public QFrame {
  Q_OBJECT

public:
  explicit SettingsWindow(QWidget *parent = 0);
  void setCurrentPanel(int index, const QString &param = "");

protected:
  void showEvent(QShowEvent *event) override;

signals:
  void closeSettings();
  void reviewTrainingGuide();
  void showDriverView();
  void expandToggleDescription(const QString &param);

private:
  QPushButton *sidebar_alert_widget;
  QWidget *sidebar_widget;
  QButtonGroup *nav_btns;
  QStackedWidget *panel_widget;
};

class DevicePanel : public ListWidget {
  Q_OBJECT
public:
  explicit DevicePanel(SettingsWindow *parent);
signals:
  void reviewTrainingGuide();
  void showDriverView();
  void closeSettings();

private slots:
  void poweroff();
  void reboot();
  void updateCalibDescription();

private:
  Params params;
};

class TogglesPanel : public ListWidget {
  Q_OBJECT
public:
  explicit TogglesPanel(SettingsWindow *parent);
  void showEvent(QShowEvent *event) override;

public slots:
  void expandToggleDescription(const QString &param);

private:
  Params params;
  std::map<std::string, ParamControl*> toggles;

  void updateToggles();
};

class SoftwarePanel : public ListWidget {
  Q_OBJECT
public:
  explicit SoftwarePanel(QWidget* parent = nullptr);

private:
  void showEvent(QShowEvent *event) override;
  void updateLabels();
  void checkForUpdates();

  bool is_onroad = false;

  QLabel *onroadLbl;
  LabelControl *versionLbl;
  LabelControl *lastUpdateLbl;
  LabelControl *branchLbl;
  LabelControl *commitLbl;
  LabelControl *osLbl;
  ButtonControl *installBtn;
  ButtonControl *downloadBtn;
  ButtonControl *targetBranchBtn;

  Params params;
  QFileSystemWatcher *fs_watch;
};

class C2NetworkPanel: public QWidget {
  Q_OBJECT
public:
  explicit C2NetworkPanel(QWidget* parent = nullptr);

private:
  void showEvent(QShowEvent *event) override;
  QString getIPAddress();
  LabelControl *ipaddress;
};




class SelectCar : public QWidget {
  Q_OBJECT
public:
  explicit SelectCar(QWidget* parent = 0);

private:

signals:
  void backPress();
  void selectedCar();

};

// carrot (C3X) style "CarrotPilot" panel: Start / Cruise / Speed / Tuning / Disp / Path tabs
class CarrotPanel : public QWidget {
  Q_OBJECT

private:
  QStackedLayout* main_layout = nullptr;
  QWidget* homeScreen = nullptr;
  SelectCar* selectCar = nullptr;
  int currentCarrotIndex = 0;

  QVBoxLayout* carrotLayout;

  ListWidget* cruiseToggles;
  ListWidget* speedToggles;
  ListWidget* steerToggles;
  ListWidget* dispToggles;
  ListWidget* startToggles;
  ListWidget* advancedToggles;

  void togglesCarrot(int widgetIndex);
  void updateButtonStyles();

public:
  explicit CarrotPanel(QWidget* parent = nullptr);
};

// ajouatom:
class CValueControl : public AbstractControl {
    Q_OBJECT

public:
    CValueControl(const QString& params, const QString& title, const QString& desc, const QString& icon, int min, int max, int unit = 1);

signals:
    void valueChanged(int value);

private:
    QPushButton btnplus;
    QPushButton btnminus;
    QLabel label;

    QString m_params;
    int     m_min;
    int     m_max;
    int     m_unit;

    void refresh();
};
class CPrebuiltToggle : public ToggleControl {
    Q_OBJECT

public:
    CPrebuiltToggle() : ToggleControl("빠른 부팅 (프리빌트)", "켜두면 한 번 빌드한 뒤로는 빌드를 건너뛰어 부팅이 빨라집니다. 업데이트로 코드가 바뀌면 다음 부팅 때 자동으로 한 번만 다시 빌드합니다.", "../assets/offroad/icon_shell.png", Params().getBool("OpkrPrebuiltOn")) {
        QObject::connect(this, &CPrebuiltToggle::toggleFlipped, [=](int state) {
            Params().putBool("OpkrPrebuiltOn", (bool)state);

            if (state)
            {
                std::system("cd /data/openpilot; git rev-parse HEAD > .prebuilt_commit && touch prebuilt");
            }
            else
            {
                std::system("cd /data/openpilot; rm -f prebuilt");
            }

        });
    }
};
class TimeZoneSelectCombo : public AbstractControl 
{
  Q_OBJECT

public:
  TimeZoneSelectCombo();

private:
  QPushButton btn;
  QComboBox combobox;
  Params params;

  void refresh();
};

class UseBaseTorqueToggle : public ToggleControl {
  Q_OBJECT

public:
  UseBaseTorqueToggle() : ToggleControl(tr("기본 토크 값 사용"), "", "../assets/offroad/icon_openpilot.png", Params().getBool("UseBaseTorqueValues")) {
    QObject::connect(this, &UseBaseTorqueToggle::toggleFlipped, [=](int state) {
      bool status = state ? true : false;
      Params().putBool("UseBaseTorqueValues", status);
    });
  }
};

class GitHash : public AbstractControl {
    Q_OBJECT

public:
    GitHash();

private:
    QLabel local_hash;
    QLabel remote_hash;
};

