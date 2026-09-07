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

GIT_TERMINAL_PROMPT=0 git push origin daily-intel
echo "pushed: $(git rev-parse --short HEAD) -> origin/daily-intel"
