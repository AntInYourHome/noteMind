#!/bin/bash
# ============================================================
# 本地一键打包（Windows GitBash / Linux 均可执行）
# 产出：release/super-tools-<版本>.tar.gz（含已测已构建的完整发布包）
# 用法：bash deploy/package.sh
# ============================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VER=$(tr -d ' \t\r\n' < VERSION 2>/dev/null || echo dev)
STAGE_NAME="super-tools-$VER"
STAGE="release/$STAGE_NAME"
PIP_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"
NPM_REGISTRY="https://registry.npmmirror.com"

# 本地构建用虚拟环境（Windows: Scripts/，Linux: bin/）
VENV=".venv-build"
if [ ! -d "$VENV" ]; then python -m venv "$VENV"; fi
if   [ -x "$VENV/Scripts/python.exe" ]; then PY="$VENV/Scripts/python.exe"
elif [ -x "$VENV/bin/python" ];        then PY="$VENV/bin/python"
else echo "找不到构建虚拟环境的 python"; exit 1; fi

echo "== [1/4] 后端依赖与测试 =="
"$PY" -m pip install -q -r server/requirements.txt -r server/requirements-dev.txt -i "$PIP_INDEX"
( cd server && "$ROOT/$PY" -m pytest )

echo "== [2/4] 前端依赖、测试与构建 =="
( cd web \
  && npm install --registry="$NPM_REGISTRY" --no-fund --no-audit \
  && npm run test \
  && npm run build )

echo "== [3/4] 组装发布包 =="
rm -rf "$STAGE"; mkdir -p "$STAGE" release
tar cf - \
  --exclude=server/.env --exclude=server/venv --exclude=server/data \
  --exclude=server/tests/data --exclude=node_modules \
  --exclude=.git --exclude=release --exclude=.venv-build --exclude=logs \
  server web docs deploy skills VERSION README.md \
  | tar xf - -C "$STAGE"

echo "== [4/4] 压缩与校验 =="
tar czf "release/$STAGE_NAME.tar.gz" -C release "$STAGE_NAME"
(cd release && sha256sum "$STAGE_NAME.tar.gz" > "$STAGE_NAME.tar.gz.sha256")
echo "打包完成：release/$STAGE_NAME.tar.gz"
echo "安装：解压 → cp deploy/deploy.conf.example deploy/deploy.conf 填写 → sudo bash deploy/install.sh"
echo "升级：sudo bash deploy/upgrade.sh（可重复执行，保留 .env 与数据）"
