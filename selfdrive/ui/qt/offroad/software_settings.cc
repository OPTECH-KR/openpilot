#include "selfdrive/ui/qt/offroad/settings.h"

#include <cassert>
#include <cmath>
#include <string>

#include <QDebug>
#include <QFile>
#include <QLabel>
#include <QRegularExpression>
#include <QTimer>

#include "common/params.h"
#include "common/util.h"
#include "selfdrive/ui/ui.h"
#include "selfdrive/ui/qt/util.h"
#include "selfdrive/ui/qt/widgets/controls.h"
#include "selfdrive/ui/qt/widgets/input.h"
#include "system/hardware/hw.h"

// optech: same update page as optech-hkg. C2 does not use comma's updated (it is off): the device checks and pulls
// with git directly (selfdrive/assets/addon/sh/gitcommit.sh / gitpull.sh) and shows the release notes ("• ..." lines).

// '저장소 · 브랜치' (optech-hkg 2026-11-27, selfdrive/assets/addon/sh/optech_git.sh). A job that ends in a reboot runs
// in the background; when it fails it leaves its exit code in OPTECH_GIT_FAIL, which the menu watches for.
static const char *OPTECH_GIT_SH = "/usr/bin/bash /data/openpilot/selfdrive/assets/addon/sh/optech_git.sh ";
static const char *OPTECH_GIT_FAIL = "/tmp/optech_git_fail";

static int optech_git_run(const QString &args) {
  return std::system((OPTECH_GIT_SH + args).toStdString().c_str());
}

static void optech_git_background(const QString &args) {
  QFile::remove(OPTECH_GIT_FAIL);
  // 'a || b &' puts the whole list in the background
  optech_git_run(args + " > /tmp/optech_git.log 2>&1 || echo $? > " + OPTECH_GIT_FAIL + " &");
}

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
      // the scrolling small-font dialog (optech-hkg): the big confirm dialog cut the change list off the screen
      if (ConfirmationDialog::richConfirm("새 업데이트가 있어요. (" + local + " → " + remote + ")\n\n바뀐 내용:\n" + changes +
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

  // ---- 저장소 · 브랜치 (optech-hkg 2026-11-27: a tester sent OPKR's 'Git 리포지토리/브랜치' menu. The branch choice:
  //      the other OPTECH branch (spst <-> hkg) installs by itself, '기타' asks for the address the OPKR way: id,
  //      repository, branch) ----
  QLabel *gitTitle = new QLabel("저장소 · 브랜치");
  gitTitle->setStyleSheet("font-size: 42px; font-weight: 600; color: #33ab4c; padding-top: 25px; padding-left: 10px;");
  addItem(gitTitle);

  addItem(new ParamControl("OptechGitPullOnBoot", "켤 때마다 자동 업데이트",
    "켜 두면(초록색) 기기를 켤 때 와이파이가 연결돼 있으면 새 버전을 확인하고, 있으면 받아서 바로 씁니다 "
    "(받은 뒤 처음 켤 때 몇 분 빌드). 와이파이가 없으면 15초쯤 기다렸다가 그냥 켜집니다. 처음 값: 꺼짐", "", this));

  // the same rule as the web page (selfdrive/optech_web): car off, or gear P with openpilot off
  auto parked_or_off = [=]() {
    const SubMaster &sm = *(uiState()->sm);
    const bool parked = sm.alive("carState") &&
                        sm["carState"].getCarState().getGearShifter() == cereal::CarState::GearShifter::PARK &&
                        !sm["controlsState"].getControlsState().getEnabled();
    if (is_onroad && !parked) {
      ConfirmationDialog::rich("시동이 켜져 있을 때는 기어를 P에 놓고 오픈파일럿을 꺼야 할 수 있어요.", this);
      return false;
    }
    return true;
  };

  // a background job that failed: tell the user and give the button back (a job that worked reboots the device)
  auto watch_job = [=](ButtonControl *btn, const QString &idle, const QString &what) {
    QTimer *t = new QTimer(this);
    QObject::connect(t, &QTimer::timeout, [=]() {
      if (!QFile::exists(OPTECH_GIT_FAIL)) return;
      t->stop();
      t->deleteLater();
      btn->setValue(idle);
      btn->setEnabled(true);
      ConfirmationDialog::rich(what + " 하지 못했어요.\n와이파이 연결을 확인한 뒤 다시 해 주세요.", this);
    });
    t->start(1000);
  };

  auto branchBtn = new ButtonControl("브랜치 바꾸기", "선택",
    "OPTECH 브랜치끼리 바꾸거나 (spst: 다른 차종 + 일반 CAN 현대·기아 ↔ hkg: 현대·기아 전용), 다른 저장소의 브랜치를 "
    "받아 씁니다. 바꾸면 받은 뒤 자동으로 다시 켜지고, 처음 켤 때 몇 분 빌드합니다. 설정값은 그대로 남습니다. "
    "원래대로 돌아가려면 아래 '이전 버전으로 되돌리기'를 누르세요.");
  connect(branchBtn, &ButtonControl::clicked, [=]() {
    if (!parked_or_off()) return;
    const QString cur = QString::fromStdString(params.get("GitBranch"));
    const QString other = cur.startsWith("optech-spst") ? "optech-hkg" : "optech-spst";
    const QString etc = "기타 (주소 직접 입력)";
    const QString sel = MultiOptionDialog::getSelection("브랜치 바꾸기", {other, etc}, "", this);
    if (sel.isEmpty()) return;
    QString url = "https://github.com/OPTECH-KR/openpilot.git", br = other;
    if (sel == etc) {
      const QString id = InputDialog::getText("1/3 GitHub 아이디를 입력하세요", this,
                                              "github.com/[아이디]/[저장소].git -b [브랜치]", false, 1, "OPTECH-KR");
      if (id.isEmpty()) return;
      QString repo = InputDialog::getText("2/3 저장소 이름을 입력하세요", this,
                                          "github.com/" + id + "/[저장소].git -b [브랜치]", false, 1, "openpilot");
      if (repo.isEmpty()) return;
      if (repo.endsWith(".git")) repo.chop(4);
      br = InputDialog::getText("3/3 브랜치 이름을 입력하세요", this,
                                "github.com/" + id + "/" + repo + ".git -b [브랜치]", false, 1, cur);
      if (br.isEmpty()) return;
      // only plain names: they go into a shell command
      const QRegularExpression ok_name("^[A-Za-z0-9._-]+$"), ok_branch("^[A-Za-z0-9._/-]+$");
      if (!ok_name.match(id).hasMatch() || !ok_name.match(repo).hasMatch() || !ok_branch.match(br).hasMatch()) {
        ConfirmationDialog::rich("영문, 숫자와 . _ - 만 쓸 수 있어요 (브랜치는 / 도). 다시 입력해 주세요.", this);
        return;
      }
      url = "https://github.com/" + id + "/" + repo + ".git";
    }
    branchBtn->setEnabled(false);
    branchBtn->setValue("확인 중...");
    const int found = optech_git_run("check '" + url + "' '" + br + "'");
    branchBtn->setValue("선택");
    branchBtn->setEnabled(true);
    if (found != 0) {
      ConfirmationDialog::rich("브랜치를 찾지 못했어요.\n" + url + " -b " + br + "\n주소와 와이파이 연결을 확인해 주세요.", this);
      return;
    }
    if (ConfirmationDialog::richConfirm(br + " 브랜치로 바꿀까요?\n\n받은 뒤 자동으로 다시 켜지고, 처음 켤 때 몇 분 빌드해요.\n"
                                        "설정값은 그대로 남아요.", "바꾸기", this)) {
      branchBtn->setEnabled(false);
      branchBtn->setValue("받는 중...");
      optech_git_background("switch '" + url + "' '" + br + "'");
      watch_job(branchBtn, "선택", "브랜치를 바꾸지");
    }
  });
  addItem(branchBtn);

  auto gitResetBtn = new ButtonControl("바뀐 파일 되돌리기 (Git 리셋)", "실행",
    "기기 안의 프로그램 파일이 바뀌었을 때 씁니다. 예를 들어 누가 파일을 직접 고쳤거나 업데이트가 중간에 끊겨서 "
    "'최신 업데이트'가 안 되거나 동작이 이상할 때입니다. 프로그램 파일만 지금 버전의 원래 내용으로 되돌리고 다시 켭니다. "
    "버전은 그대로이고, 설정값과 주행 기록도 지워지지 않습니다.");
  connect(gitResetBtn, &ButtonControl::clicked, [=]() {
    if (!parked_or_off()) return;
    if (ConfirmationDialog::richConfirm("바뀐 프로그램 파일을 지금 버전의 원래 내용으로 되돌리고 다시 켤까요?\n\n"
                                        "버전은 그대로이고, 설정값과 주행 기록도 그대로예요.", "되돌리기", this)) {
      gitResetBtn->setEnabled(false);
      optech_git_background("reset");
      watch_job(gitResetBtn, "실행", "파일을 되돌리지");
    }
  });
  addItem(gitResetBtn);

  auto restoreBtn = new ButtonControl("이전 버전으로 되돌리기", "실행",
    "마지막 업데이트나 브랜치 바꾸기를 하기 전 버전으로 돌아가고 다시 켭니다. 새 버전이 이상할 때 쓰세요. "
    "한 번 더 누르면 다시 지금 버전으로 돌아옵니다.");
  connect(restoreBtn, &ButtonControl::clicked, [=]() {
    if (!parked_or_off()) return;
    // '브랜치 커밋 주소' (optech_git.sh save_prev, gitpull.sh)
    const QStringList prev = QString::fromStdString(util::read_file("/data/optech_prev_commit")).trimmed().split(' ');
    if (prev.size() < 2 || prev[0].isEmpty()) {
      ConfirmationDialog::rich("되돌릴 이전 버전이 없어요.\n업데이트나 브랜치 바꾸기를 한 뒤에 쓸 수 있어요.", this);
      return;
    }
    if (ConfirmationDialog::richConfirm(prev[0] + " (" + prev[1].left(7) + ") 버전으로 되돌릴까요?\n\n되돌린 뒤 자동으로 다시 켜지고, "
                                        "처음 켤 때 몇 분 빌드해요.", "되돌리기", this)) {
      restoreBtn->setEnabled(false);
      optech_git_background("restore");
      watch_job(restoreBtn, "실행", "이전 버전으로 되돌리지");
    }
  });
  addItem(restoreBtn);

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
