#!/usr/bin/env bash
# 每日情报仓库内同步（替代旧的外部目录拷贝模式 push_intel.sh）
# 用法: bash scripts/sync_intel.sh collect   # 切 daily-intel 分支 + pull + 全量采集
#       bash scripts/sync_intel.sh publish   # 提交 + 推送（无变化则跳过提交）
set -e
INTEL="$(cd "$(dirname "$0")/.." && pwd)"   # agent-security-intel
REPO="$(cd "$INTEL/.." && pwd)"             # noteMind 仓库根

PYBIN="$(command -v py || command -v python3 || command -v python)"

cmd="${1:-}"
case "$cmd" in
  collect)
    cd "$REPO"
    git switch daily-intel 2>/dev/null || git switch daily-intel 2>/dev/null || git switch -c daily-intel
    git pull --rebase origin daily-intel 2>/dev/null || echo "(pull 跳过：无远端更新或网络问题，继续)"
    cd "$INTEL"
    "$PYBIN" scripts/collect.py
    ;;
  publish)
    cd "$REPO"
    git add agent-security-intel
    if git diff --cached --quiet; then
      echo "nothing to sync: 情报内容无变化"
    else
      git commit -m "intel: $(date +%F) 每日情报更新" --quiet
    fi
    GIT_TERMINAL_PROMPT=0 git push origin daily-intel
    echo "pushed: $(git rev-parse --short HEAD) -> origin/daily-intel"
    ;;
  *)
    echo "用法: bash scripts/sync_intel.sh [collect|publish]" >&2
    exit 1
    ;;
esac
