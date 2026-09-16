#!/usr/bin/env bash
# 每日情报同步推送：agent-security-intel -> noteMind 仓库 daily-intel 分支
# 用法: bash scripts/push_intel.sh   （在 agent-security-intel 目录或任意位置执行均可）
set -e
SRC="/e/openwork/agent-security-intel"
DST="/e/openwork/noteMind"

if [ ! -d "$DST/.git" ]; then
  echo "ERROR: $DST 不是 git 克隆，请先: git clone https://github.com/AntInYourHome/noteMind.git" >&2
  exit 1
fi

cd "$DST"
git switch daily-intel 2>/dev/null || git switch -c daily-intel
# 远端若有新提交（如人工编辑），先变基再推
git pull --rebase origin daily-intel 2>/dev/null || echo "(pull 跳过：无远端更新或网络问题，继续)"

mkdir -p agent-security-intel/data
cp -r "$SRC/scripts" "$SRC/reports" "$SRC/docs" agent-security-intel/
cp "$SRC/config.json" "$SRC/README.md" agent-security-intel/
cp "$SRC/data/editor-notes.md" agent-security-intel/data/

git add agent-security-intel
TODAY=$(date +%F)
if git diff --cached --quiet; then
  echo "nothing to sync: 情报内容无变化"
else
  git commit -m "intel: ${TODAY} 每日情报更新" --quiet
fi

GIT_TERMINAL_PROMPT=0 git push origin daily-intel || {
  echo "(proxy push failed, retrying direct connection)"
  # 直连重试 3 次（github.com 直连常间歇性失败，本地/远端代理也可能随时恢复）
  for i in 1 2 3; do
    sleep 20
    GIT_TERMINAL_PROMPT=0 git -c http.https://github.com.proxy= -c http.proxy= -c https.proxy= push origin daily-intel && break
    # 直连失败后顺手探测代理是否恢复，恢复则走代理再推
    if curl -s -o /dev/null --max-time 8 -x http://127.0.0.1:7890 https://api.github.com/zen 2>/dev/null; then
      GIT_TERMINAL_PROMPT=0 git push origin daily-intel && break
    fi
    [ "$i" = "3" ] && echo "PUSH_FAILED: 所有重试均失败，内容已提交到本地 noteMind 克隆（daily-intel 分支），网络恢复后重跑本脚本即可" && exit 0
  done
}
echo "pushed: $(git rev-parse --short HEAD) -> origin/daily-intel"
