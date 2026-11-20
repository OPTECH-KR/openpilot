#include "selfdrive/ui/qt/offroad/settings.h"

#include <cassert>
#include <cmath>
#include <string>

#include <QDebug>
#include <QLabel>

#include "common/params.h"
#include "common/util.h"
#include "selfdrive/ui/ui.h"
#include "selfdrive/ui/qt/util.h"
#include "selfdrive/ui/qt/widgets/controls.h"
#include "selfdrive/ui/qt/widgets/input.h"
#include "system/hardware/hw.h"

// optech: same update page as optech-hkg. C2 does not use comma's updated (it is off): the device checks and pulls
// with git directly (selfdrive/assets/addon/sh/gitcommit.sh / gitpull.sh) and shows the release notes ("• ..." lines).

void SoftwarePanel::checkForUpdates() {
  std::system("/usr/bin/bash /data/openpilot/selfdrive/assets/addon/sh/gitcommit.sh");
  std::system("date -u '+%Y-%m-%dT%H:%M:%S' > /data/params/d/LastUpdateTime");
}

SoftwarePanel::SoftwarePanel(QWidget* parent) : ListWidget(parent) {
  onroadLbl = new QLabel("업데이트는 차가 멈춰 있을 때만 받을 수 있어요.");
  onroadLbl->setStyleSheet("font-size: 50px; font-weight: 400; text-align: left; padding-top: 30px; padding-bottom: 30px;");
  addItem(onroadLbl);

  versionLbl = new LabelControl("버전", "");
  addItem(versionLbl);

  lastUpdateLbl = new LabelControl("마지막 업데이트 확인", "");
  addItem(lastUpdateLbl);

  downloadBtn = new ButtonControl("최신 업데이트", "확인");
  connect(downloadBtn, &ButtonControl::clicked, [=]() {
    // some cars keep the ignition line on while parked: allow it whenever the car is not moving
    const SubMaster &sm = *(uiState()->sm);
    if (is_onroad && sm.alive("carState") && sm["carState"].getCarState().getVEgo() > 0.5) {
      ConfirmationDialog::alert("주행 중에는 업데이트할 수 없어요.\n차를 세운 뒤에 다시 눌러 주세요.", this);
      return;
    }
    downloadBtn->setEnabled(false);
    downloadBtn->setValue("확인 중...");
    checkForUpdates();
    QString local = QString::fromStdString(params.get("GitCommit")).left(7);
    QString remote = QString::fromStdString(params.get("GitCommitRemote")).left(7);
    if (remote.isEmpty()) {
      ConfirmationDialog::alert("업데이트 서버에 연결하지 못했어요.\n와이파이 연결을 확인해 주세요.", this);
    } else if (local == remote) {
      ConfirmationDialog::alert("이미 최신 버전이에요.\n(" + local + ")", this);
    } else {
      QString changes = QString::fromStdString(util::read_file("/tmp/update_changelog.txt")).trimmed();
      if (changes.isEmpty()) changes = "(바뀐 내용 목록을 불러오지 못했어요)";
      if (ConfirmationDialog::confirm("새 업데이트가 있어요. (" + local + " → " + remote + ")\n\n바뀐 내용:\n" + changes +
                                      "\n\n받은 뒤 자동으로 재부팅해요. 처음 부팅 때 빌드로 시간이 걸릴 수 있어요. 업데이트할까요?", "업데이트", this)) {
        downloadBtn->setValue("업데이트 받는 중...");
        std::system("/usr/bin/bash /data/openpilot/selfdrive/assets/addon/sh/gitpull.sh");
      }
    }
    updateLabels();
  });
  addItem(downloadBtn);

  branchLbl = new LabelControl("브랜치 이름", "");
  addItem(branchLbl);
  commitLbl = new LabelControl("브랜치 커밋", "");
  addItem(commitLbl);
  osLbl = new LabelControl("운영체제 버전", QString::fromStdString(Hardware::get_os_version()).trimmed());
  addItem(osLbl);

  // comma's updated is off on C2: its install / branch buttons are kept (header) but not shown
  installBtn = new ButtonControl(tr("Install Update"), tr("INSTALL"));
  connect(installBtn, &ButtonControl::clicked, [=]() {
    installBtn->setEnabled(false);
    params.putBool("DoReboot", true);
  });
  installBtn->setVisible(false);
  targetBranchBtn = new ButtonControl(tr("Target Branch"), tr("SELECT"));
  targetBranchBtn->setVisible(false);

  auto uninstallBtn = new ButtonControl(getBrand() + " 삭제", "삭제");
  connect(uninstallBtn, &ButtonControl::clicked, [&]() {
    if (ConfirmationDialog::confirm("정말 삭제할까요?", "삭제", this)) {
      params.putBool("DoUninstall", true);
    }
  });
  addItem(uninstallBtn);

  fs_watch = new ParamWatcher(this);
  QObject::connect(fs_watch, &ParamWatcher::paramChanged, [=](const QString &param_name, const QString &param_value) {
    updateLabels();
  });

  connect(uiState(), &UIState::offroadTransition, [=](bool offroad) {
    is_onroad = !offroad;
    updateLabels();
  });

  updateLabels();
}

void SoftwarePanel::showEvent(QShowEvent *event) {
  updateLabels();
}

void SoftwarePanel::updateLabels() {
  // add these back in case the files got removed
  fs_watch->addParam("LastUpdateTime");
  fs_watch->addParam("GitCommitRemote");

  if (!isVisible()) {
    return;
  }

  onroadLbl->setVisible(false);
  downloadBtn->setVisible(true);  // checked again on press (not while moving)

  QString local = QString::fromStdString(params.get("GitCommit")).left(7);
  QString remote = QString::fromStdString(params.get("GitCommitRemote")).left(7);
  if (remote.isEmpty()) downloadBtn->setValue("눌러서 확인");
  else if (local == remote) downloadBtn->setValue("최신 버전");
  else downloadBtn->setValue("업데이트 있음");
  downloadBtn->setEnabled(true);

  versionLbl->setText("optech-spst");
  auto last_tm = params.get("LastUpdateTime");
  lastUpdateLbl->setText(last_tm.empty() ? "없음" : timeAgo(QDateTime::fromString(QString::fromStdString(last_tm + "Z"), Qt::ISODate)));
  branchLbl->setText(QString::fromStdString(params.get("GitBranch")));
  // when this code was released (Korea time); the hash when the date is not known yet
  const QString commit_date = QString::fromStdString(params.get("GitCommitDate"));
  commitLbl->setText(commit_date.isEmpty() ? QString::fromStdString(params.get("GitCommit")).left(10) : commit_date);

  update();
}
