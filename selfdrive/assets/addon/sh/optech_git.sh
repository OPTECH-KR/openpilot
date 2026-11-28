#!/usr/bin/bash
# OPTECH 웹 > 도구 (optech-hkg에서는 소프트웨어 메뉴도) '저장소 · 브랜치' (2026-11-27, 테스터가 보낸 OPKR 'Git 리포지토리/브랜치' 메뉴처럼)
#   optech_git.sh check  <주소> <브랜치>  그 저장소에 그 브랜치가 있으면 0 (없거나 연결이 안 되면 0이 아님)
#   optech_git.sh switch <주소> <브랜치>  그 브랜치를 받아 바꾸고 다시 켬 (처음 켤 때 몇 분 빌드)
#   optech_git.sh reset                    기기에서 바뀐 프로그램 파일만 지금 버전 그대로 되돌리고 다시 켬 (설정값 그대로)
#   optech_git.sh restore                  마지막 업데이트 / 브랜치 바꾸기 전으로 되돌리고 다시 켬
#   optech_git.sh bootpull                 켤 때 자동 업데이트: 새 버전을 받았으면 0 (launch_chffrplus.sh가 처음부터 다시 시작)
# 되돌릴 곳은 /data/optech_prev_commit 에 '브랜치 커밋 주소' 한 줄로 남김 (gitpull.sh도 업데이트 전에 씀)

export LD_LIBRARY_PATH=/data/data/com.termux/files/usr/lib
export HOME=/data/data/com.termux/files/home
export PATH=/usr/local/bin:/data/data/com.termux/files/usr/bin:/data/data/com.termux/files/usr/sbin:/data/data/com.termux/files/usr/bin/applets:/bin:/sbin:/vendor/bin:/system/sbin:/system/bin:/system/xbin:/data/data/com.termux/files/usr/bin/python
export PYTHONPATH=/data/openpilot
# NEOS cannot verify current GitHub TLS chains
export GIT_SSL_NO_VERIFY=true

cd /data/openpilot || exit 1
PREV=/data/optech_prev_commit

save_prev() {
  echo "$(git rev-parse --abbrev-ref HEAD) $(git rev-parse HEAD) $(git remote get-url origin)" > $PREV
}

# origin = that repository, fetching only that branch (devices are set up single-branch)
use_branch() {
  git remote set-url origin "$1"
  git config --replace-all remote.origin.fetch "+refs/heads/$2:refs/remotes/origin/$2"
}

# other code now: build it on the next start (an older launch script would trust the 'prebuilt' mark)
drop_prebuilt() {
  rm -f /data/openpilot/prebuilt /data/openpilot/.prebuilt_commit
}

do_reboot() {
  sync
  if [ -f /EON ]; then reboot; else sudo reboot; fi
}

case "$1" in
  check)
    timeout 20 git ls-remote --exit-code --heads "$2" "$3" > /dev/null 2>&1
    exit $?
    ;;

  switch)
    URL="$2"; BR="$3"
    { [ -n "$URL" ] && [ -n "$BR" ]; } || exit 2
    timeout 20 git ls-remote --exit-code --heads "$URL" "$BR" > /dev/null 2>&1 || exit 3
    OLD_URL=$(git remote get-url origin)
    OLD_BR=$(git rev-parse --abbrev-ref HEAD)
    save_prev
    use_branch "$URL" "$BR"
    if ! timeout 600 git fetch origin; then
      use_branch "$OLD_URL" "$OLD_BR"   # could not download: leave everything as it was
      exit 4
    fi
    if ! git checkout -f -B "$BR" "origin/$BR"; then
      use_branch "$OLD_URL" "$OLD_BR"
      exit 5
    fi
    git branch --set-upstream-to="origin/$BR" "$BR" > /dev/null 2>&1
    drop_prebuilt
    do_reboot
    ;;

  reset)
    git reset --hard HEAD > /dev/null 2>&1
    do_reboot
    ;;

  restore)
    [ -f $PREV ] || exit 6
    read -r P_BR P_HASH P_URL < $PREV
    { [ -n "$P_BR" ] && git cat-file -e "$P_HASH^{commit}" 2>/dev/null; } || exit 6
    save_prev   # pressing it again comes back to where we are now
    [ -n "$P_URL" ] && use_branch "$P_URL" "$P_BR"
    git checkout -f -B "$P_BR" "$P_HASH" || exit 7
    git branch --set-upstream-to="origin/$P_BR" "$P_BR" > /dev/null 2>&1
    drop_prebuilt
    do_reboot
    ;;

  bootpull)
    # wait up to 15 s for a wifi address (no wifi in the car: the device starts 15 s later while this is on)
    i=0
    while [ $i -lt 15 ] && ! ip -4 addr show wlan0 2>/dev/null | grep -q inet; do sleep 1; i=$((i+1)); done
    ip -4 addr show wlan0 2>/dev/null | grep -q inet || exit 1
    BR=$(git rev-parse --abbrev-ref HEAD)
    timeout 60 git fetch origin > /dev/null 2>&1 || exit 1
    REMOTE=$(git rev-parse --verify -q "origin/$BR") || exit 1
    [ "$REMOTE" != "$(git rev-parse HEAD)" ] || exit 1
    save_prev
    # release branches are published as rewritten release commits: take them as they are (like gitpull.sh)
    git reset --hard "origin/$BR" > /dev/null 2>&1 || exit 1
    exit 0
    ;;
esac
exit 1
