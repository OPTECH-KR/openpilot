#!/usr/bin/bash

export LD_LIBRARY_PATH=/data/data/com.termux/files/usr/lib
export HOME=/data/data/com.termux/files/home
export PATH=/usr/local/bin:/data/data/com.termux/files/usr/bin:/data/data/com.termux/files/usr/sbin:/data/data/com.termux/files/usr/bin/applets:/bin:/sbin:/vendor/bin:/system/sbin:/system/bin:/system/xbin:/data/data/com.termux/files/usr/bin/python
export PYTHONPATH=/data/openpilot
# NEOS cannot verify current GitHub TLS chains
export GIT_SSL_NO_VERIFY=true

# acquire git hash from remote
cd /data/openpilot
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
LOCAL_HASH=$(git rev-parse HEAD)
/usr/bin/git fetch
REMOTE_HASH=$(git rev-parse --verify origin/$CURRENT_BRANCH)
echo -n "$REMOTE_HASH" > /data/params/d/GitCommitRemote
# list what the update changes (newest first), shown in the update dialog.
# A release commit carries its change list in the message body ("• ..." lines); after a rewritten
# release (history not continuing from ours) only the newest release is described.
if git merge-base --is-ancestor HEAD origin/$CURRENT_BRANCH 2>/dev/null; then
  RANGE="HEAD..origin/$CURRENT_BRANCH"
else
  RANGE="-1 origin/$CURRENT_BRANCH"
fi
git log --no-merges --format='%b' $RANGE 2>/dev/null | grep '^•' | head -n 12 > /tmp/update_changelog.txt
if [ ! -s /tmp/update_changelog.txt ]; then
  git log --no-merges --format='• %s' $RANGE 2>/dev/null | head -n 12 > /tmp/update_changelog.txt
fi
