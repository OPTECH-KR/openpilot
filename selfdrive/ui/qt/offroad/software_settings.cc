#include "selfdrive/ui/qt/offroad/settings.h"

#include <cassert>
#include <cmath>
#include <string>

#include <QDebug>
#include <QLabel>

#include "selfdrive/common/params.h"
#include "selfdrive/common/util.h"
#include "selfdrive/ui/ui.h"
#include "selfdrive/ui/qt/util.h"
#include "selfdrive/ui/qt/widgets/controls.h"
#include "selfdrive/ui/qt/widgets/input.h"
#include "selfdrive/hardware/hw.h"


void SoftwarePanel::checkForUpdates() {
  std::system("pkill -SIGUSR1 -f selfdrive.updated");
}

SoftwarePanel::SoftwarePanel(QWidget* parent) : ListWidget(parent) {
  onroadLbl = new QLabel(tr("Updates are only downloaded while the car is off."));
  onroadLbl->setStyleSheet("font-size: 50px; font-weight: 400; text-align: left; padding-top: 30px; padding-bottom: 30px;");
  addItem(onroadLbl);

  // version info rows (version / last update / check / branch / commit / OS / uninstall)
  versionLbl = new LabelControl("버전", "");
  addItem(versionLbl);

  lastUpdateLbl = new LabelControl("마지막 업데이트", "");
  addItem(lastUpdateLbl);

  // download update btn: C2 has no updated process, so check/pull with git directly
  downloadBtn = new ButtonControl("최신 업데이트", "확인");
  connect(downloadBtn, &ButtonControl::clicked, [=]() {
    downloadBtn->setEnabled(false);
    downloadBtn->setValue("확인 중...");
    std::system("/data/openpilot/selfdrive/assets/addon/sh/gitcommit.sh");
    std::system("date -u '+%Y-%m-%dT%H:%M:%S' > /data/params/d/LastUpdateTime");
    QString local = QString::fromStdString(params.get("GitCommit")).left(7);
    QString remote = QString::fromStdString(params.get("GitCommitRemote")).left(7);
    if (remote.isEmpty()) {
      ConfirmationDialog::alert("업데이트 서버에 연결하지 못했어요.\n와이파이 연결을 확인해 주세요.", this);
    } else if (local == remote) {
      ConfirmationDialog::alert("이미 최신 버전이에요.\n(" + local + ")", this);
    } else {
      QString changes = QString::fromStdString(util::read_file("/tmp/update_changelog.txt")).trimmed();
      if (changes.isEmpty()) changes = "(바뀐 내용 목록을 불러오지 못했어요)";
      if (ConfirmationDialog::richConfirm("새 업데이트가 있어요. (" + local + " → " + remote + ")\n\n바뀐 내용:\n" + changes +
                                      "\n\n받은 뒤 자동으로 재부팅해요. 업데이트할까요?", "업데이트", this)) {
        downloadBtn->setValue("업데이트 받는 중...");
        std::system("/data/openpilot/selfdrive/assets/addon/sh/gitpull.sh");
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

  // install update btn
  installBtn = new ButtonControl(tr("Install Update"), tr("INSTALL"));
  connect(installBtn, &ButtonControl::clicked, [=]() {
    installBtn->setEnabled(false);
    params.putBool("DoReboot", true);
  });
  addItem(installBtn);

  // branch selecting
  targetBranchBtn = new ButtonControl(tr("Target Branch"), tr("SELECT"));
  connect(targetBranchBtn, &ButtonControl::clicked, [=]() {
    auto current = params.get("GitBranch");
    QStringList branches = QString::fromStdString(params.get("UpdaterAvailableBranches")).split(",");
    for (QString b : {current.c_str(), "devel-staging", "devel", "master-ci", "master"}) {
      auto i = branches.indexOf(b);
      if (i >= 0) {
        branches.removeAt(i);
        branches.insert(0, b);
      }
    }

    QString cur = QString::fromStdString(params.get("UpdaterTargetBranch"));
    QString selection = MultiOptionDialog::getSelection(tr("Select a branch"), branches, cur, this);
    if (!selection.isEmpty()) {
      params.put("UpdaterTargetBranch", selection.toStdString());
      targetBranchBtn->setValue(QString::fromStdString(params.get("UpdaterTargetBranch")));
      checkForUpdates();
    }
  });
  // targetBranchBtn needs selfdrive.updated, which is off on C2: not shown

  // uninstall button
  auto uninstallBtn = new ButtonControl(getBrand() + " 삭제", tr("UNINSTALL"));
  connect(uninstallBtn, &ButtonControl::clicked, [&]() {
    if (ConfirmationDialog::confirm(tr("Are you sure you want to uninstall?"), tr("Uninstall"), this)) {
      params.putBool("DoUninstall", true);
    }
  });
  addItem(uninstallBtn);

  fs_watch = new QFileSystemWatcher(this);
  QObject::connect(fs_watch, &QFileSystemWatcher::fileChanged, [=](const QString path) {
    updateLabels();
  });

  connect(uiState(), &UIState::offroadTransition, [=](bool offroad) {
    is_onroad = !offroad;
    updateLabels();
  });

  updateLabels();
}

void SoftwarePanel::showEvent(QShowEvent *event) {
  // nice for testing on PC
  installBtn->setEnabled(true);

  updateLabels();
}

void SoftwarePanel::updateLabels() {
  // add these back in case the files got removed
  fs_watch->addPath(QString::fromStdString(params.getParamPath("LastUpdateTime")));
  fs_watch->addPath(QString::fromStdString(params.getParamPath("UpdateFailedCount")));
  fs_watch->addPath(QString::fromStdString(params.getParamPath("UpdaterState")));
  fs_watch->addPath(QString::fromStdString(params.getParamPath("UpdateAvailable")));

  if (!isVisible()) {
    return;
  }

  // updater only runs offroad
  onroadLbl->setVisible(is_onroad);
  downloadBtn->setVisible(!is_onroad);

  // download update
  {
    QString local = QString::fromStdString(params.get("GitCommit")).left(7);
    QString remote = QString::fromStdString(params.get("GitCommitRemote")).left(7);
    if (remote.isEmpty()) downloadBtn->setValue("눌러서 확인");
    else if (local == remote) downloadBtn->setValue("최신 버전");
    else downloadBtn->setValue("업데이트 있음");
    downloadBtn->setEnabled(true);
  }
  targetBranchBtn->setValue(QString::fromStdString(params.get("UpdaterTargetBranch")));

  // current version and git info (C2 updater often cannot reach the server, so show what is on the device)
  versionLbl->setText("openpilot-c2");
  versionLbl->setDescription(QString::fromStdString(params.get("UpdaterCurrentReleaseNotes")));
  auto last_tm = params.get("LastUpdateTime");
  lastUpdateLbl->setText(last_tm.empty() ? "없음" : timeAgo(QDateTime::fromString(QString::fromStdString(last_tm + "Z"), Qt::ISODate)));
  branchLbl->setText(QString::fromStdString(params.get("GitBranch")));
  // when this code was released (date and time to the second); the hash when the date is not known yet
  const QString commit_date = QString::fromStdString(params.get("GitCommitDate"));
  commitLbl->setText(commit_date.isEmpty() ? QString::fromStdString(params.get("GitCommit")).left(10) : commit_date);

  installBtn->setVisible(false);  // needs selfdrive.updated (off on C2)
  installBtn->setValue(QString::fromStdString(params.get("UpdaterNewDescription")));
  installBtn->setDescription(QString::fromStdString(params.get("UpdaterNewReleaseNotes")));

  update();
}
