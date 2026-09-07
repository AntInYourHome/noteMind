#!/bin/bash
# ============================================================
# 升级脚本（可重复执行）：适用于已用 install.sh 部署过的环境
#   流程：同步代码(保留venv/.env/数据) → 依赖 → 测试门禁 → 静态文件 → 重启 → 健康检查
# 用法：sudo bash deploy/upgrade.sh
#   - 在解压的新发布包内执行：自动把代码同步到 deploy.conf 的 APP_HOME 后升级
#   - 直接在已部署的 APP_HOME 内执行：就地升级
# 一次性动作（建库/注册服务/nginx 配置）不在本脚本，见 install.sh
# ============================================================
set -euo pipefail
PKG="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PKG"

CONF="deploy/deploy.conf"
if [ ! -f "$CONF" ]; then
  echo "缺少 $CONF。首次部署请用 install.sh；升级请携带与安装时相同的 deploy.conf。"
  exit 1
fi
val() { { grep -E "^$1=" "$CONF" | head -1 | cut -d= -f2- | tr -d '\r"'; } || true; }

APP_HOME=$(val APP_HOME); WEB_ROOT=$(val WEB_ROOT); SERVICE_NAME=$(val SERVICE_NAME)
RUN_USER=$(val RUN_USER); SERVER_PORT=$(val SERVER_PORT); DB_MODE=$(val DB_MODE)

for k in APP_HOME WEB_ROOT SERVICE_NAME SERVER_PORT DB_MODE; do
  cur=$(eval "echo \$$k")
  [ -n "$cur" ] || { echo "配置项 $k 为空，请检查 deploy.conf"; exit 1; }
  case "$cur" in *__* ) echo "配置项 $k 仍是占位符，请编辑 deploy.conf"; exit 1;; esac
done
[ -z "$RUN_USER" ] && RUN_USER=root

echo "== 升级计划： APP_HOME=$APP_HOME  WEB_ROOT=$WEB_ROOT  SERVICE=$SERVICE_NAME  DB=$DB_MODE =="

# ---- 1. 同步代码（保留 venv / .env / 数据库 / node_modules） ----
if [ "$(cd "$PKG" && pwd)" != "$(cd "$APP_HOME" && pwd)" ]; then
  [ -d "$APP_HOME/server" ] || { echo "$APP_HOME 不是已部署环境，请先执行 install.sh"; exit 1; }
  echo "== [1/6] 同步代码到 $APP_HOME =="
  tar cf - -C "$PKG" \
    --exclude=server/venv --exclude=server/.env --exclude=server/data \
    --exclude=server/tests/data --exclude=node_modules \
    server web docs deploy skills VERSION README.md | tar xf - -C "$APP_HOME"
else
  echo "== [1/6] 就地升级（$PKG 即部署目录）=="
fi
cd "$APP_HOME"

# ---- 2. 依赖（含测试依赖；postgres 模式补驱动） ----
echo "== [2/6] 更新依赖 =="
PIP_EXTRA=()
if [ "$DB_MODE" = "postgres" ]; then PIP_EXTRA=(-r server/requirements-postgres.txt); fi
server/venv/bin/pip install -q \
  -r server/requirements.txt -r server/requirements-dev.txt ${PIP_EXTRA[@]+"${PIP_EXTRA[@]}"} \
  -i https://pypi.tuna.tsinghua.edu.cn/simple

# ---- 3. 敏感配置：保留原 server/.env；缺失时仅 sqlite 可自动生成 ----
if [ ! -f server/.env ]; then
  if [ "$DB_MODE" = "postgres" ]; then
    echo "server/.env 丢失且为 postgres 模式，请人工恢复 DATABASE_URL/JWT_SECRET 后重试"; exit 1
  fi
  mkdir -p server/data
  printf 'DATABASE_URL=sqlite:///./data/app.db\nJWT_SECRET=%s\n' "$(openssl rand -hex 24)" > server/.env
fi

# ---- 4. 测试门禁（不过则中止升级，线上继续跑旧版本） ----
echo "== [3/6] 后端测试门禁 =="
( cd server && ./venv/bin/python -m pytest -q )

# ---- 5. 前端静态文件：有 node 就重建（保证新鲜），否则沿用现有 dist ----
echo "== [4/6] 前端静态文件 =="
if command -v node >/dev/null 2>&1 && [ -f web/package.json ]; then
  ( cd web \
    && npm install --registry=https://registry.npmmirror.com --no-fund --no-audit \
    && npm run test && npm run build )
  SRC="$APP_HOME/web/dist"
elif [ -d "$APP_HOME/web/dist" ]; then
  echo "无 node，沿用现有 dist（若本次升级含前端改动，需安装 node 或使用带预构建 dist 的发布包）"
  SRC="$APP_HOME/web/dist"
else
  echo "无 node 且无 dist，前端无法更新"; exit 1
fi
rm -rf "${WEB_ROOT:?}"/*
cp -r "$SRC/"* "$WEB_ROOT"/

# ---- 6. 重启与健康检查 ----
echo "== [5/6] 重启服务 =="
chown -R "$RUN_USER" "$APP_HOME"
systemctl restart "$SERVICE_NAME"
sleep 4
systemctl is-active --quiet "$SERVICE_NAME" \
  || { journalctl -u "$SERVICE_NAME" -n 30 --no-pager; exit 1; }

echo "== [6/6] 健康检查 =="
CODE=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$SERVER_PORT/api/tools" || true)
case "$CODE" in
  200|401) echo "服务在线（HTTP $CODE）。升级完成 ✓";;
  *) echo "警告：后端探测异常（HTTP $CODE），请检查 journalctl -u $SERVICE_NAME"; exit 1;;
esac
