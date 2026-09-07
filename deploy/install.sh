#!/bin/bash
# ============================================================
# 发布包一键部署（Linux）：sudo bash deploy/install.sh
# 配置：deploy/deploy.conf（占位符，见 deploy.conf.example）
# 可选环境变量：DRY_RUN=1 仅校验并渲染到 ./rendered/，不实际安装
#              SKIP_NGINX=1 / SKIP_SYSTEMD=1 / SKIP_FIREWALLD=1 按需跳过
# ============================================================
set -euo pipefail
PKG="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PKG"
DRY_RUN="${DRY_RUN:-0}"

CONF="deploy/deploy.conf"
if [ ! -f "$CONF" ]; then
  cp deploy/deploy.conf.example "$CONF"
  echo "已生成 $CONF（全部为占位符）。请编辑填写后重新执行本脚本。"
  exit 1
fi

val() { { grep -E "^$1=" "$CONF" | head -1 | cut -d= -f2- | tr -d '\r"'; } || true; }

APP_HOME=$(val APP_HOME); WEB_ROOT=$(val WEB_ROOT); SERVICE_NAME=$(val SERVICE_NAME)
RUN_USER=$(val RUN_USER); SERVER_PORT=$(val SERVER_PORT); NGINX_CONF=$(val NGINX_CONF)
DB_MODE=$(val DB_MODE); PG_HOST=$(val PG_HOST); PG_PORT=$(val PG_PORT)
PG_USER=$(val PG_USER); PG_PASSWORD=$(val PG_PASSWORD); PG_DB=$(val PG_DB)
JWT_SECRET=$(val JWT_SECRET); RETENTION=$(val RETENTION_DAYS)

# 校验：必填 + 占位符残留检测
for k in APP_HOME WEB_ROOT SERVICE_NAME RUN_USER SERVER_PORT DB_MODE; do
  cur=$(eval "echo \$$k")
  [ -n "$cur" ] || { echo "配置项 $k 为空，请检查 deploy.conf"; exit 1; }
  case "$cur" in *__* ) echo "配置项 $k 仍是占位符，请编辑 deploy.conf"; exit 1;; esac
done
if [ "$DB_MODE" = "postgres" ]; then
  for k in PG_USER PG_PASSWORD PG_DB; do
    cur=$(eval "echo \$$k")
    [ -n "$cur" ] || { echo "postgres 模式下 $k 必填"; exit 1; }
  done
fi
[ -z "$JWT_SECRET" ] && JWT_SECRET=$(openssl rand -hex 24)
[ -z "$RETENTION" ] && RETENTION=90
[ -z "$NGINX_CONF" ] && NGINX_CONF=/etc/nginx/nginx.conf

echo "== 部署计划 =="
echo "  代码目录   APP_HOME    = $APP_HOME"
echo "  静态目录   WEB_ROOT    = $WEB_ROOT"
echo "  服务名     SERVICE     = $SERVICE_NAME (用户 $RUN_USER)"
echo "  后端端口   PORT        = $SERVER_PORT"
echo "  数据库     DB_MODE     = $DB_MODE"
echo "  nginx 配置 NGINX_CONF  = $NGINX_CONF  DRY_RUN=$DRY_RUN"

# 渲染函数：模板占位符 → 实际值
render() {
  sed -e "s|__APP_HOME__|$APP_HOME|g" -e "s|__WEB_ROOT__|$WEB_ROOT|g" \
      -e "s|__RUN_USER__|$RUN_USER|g" -e "s|__SERVICE_NAME__|$SERVICE_NAME|g" \
      -e "s|__SERVER_PORT__|$SERVER_PORT|g" "$1" > "$2"
}

if [ "$DRY_RUN" = "1" ]; then
  mkdir -p rendered
  render deploy/templates/super-tools.service.tpl rendered/super-tools.service
  render deploy/templates/nginx.conf.tpl rendered/nginx.conf
  echo "DRY_RUN：配置校验通过，模板已渲染到 ./rendered/ 供检查，未做任何安装。"
  exit 0
fi

# ---- 1. 系统依赖 ----
command -v python3 >/dev/null 2>&1 || dnf -q install -y python3 || apt-get install -y python3
if [ "$DB_MODE" = "postgres" ]; then
  command -v psql >/dev/null 2>&1 || dnf -q install -y postgresql-server postgresql || apt-get install -y postgresql
fi
command -v nginx >/dev/null 2>&1 || dnf -q install -y nginx || apt-get install -y nginx || true

# ---- 2. 数据库 ----
PIP_EXTRA=()
if [ "$DB_MODE" = "postgres" ]; then
  systemctl enable --now postgresql 2>/dev/null || {
    [ -f /var/lib/pgsql/data/PG_VERSION ] || postgresql-setup --initdb \
      || sudo -u postgres /usr/bin/initdb -D /var/lib/pgsql/data
    systemctl enable --now postgresql
  }
  sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$PG_USER'" | grep -q 1 \
    || sudo -u postgres psql -qc "CREATE USER $PG_USER WITH PASSWORD '$PG_PASSWORD';"
  sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$PG_DB'" | grep -q 1 \
    || sudo -u postgres psql -qc "CREATE DATABASE $PG_DB OWNER $PG_USER;"
  PGHBA=$(sudo -u postgres psql -tAc "show hba_file;")
  sed -i 's/\bident\b/scram-sha-256/g' "$PGHBA"
  systemctl restart postgresql
  DATABASE_URL="postgresql+psycopg2://$PG_USER:$PG_PASSWORD@${PG_HOST:-127.0.0.1}:${PG_PORT:-5432}/$PG_DB"
  PIP_EXTRA=(-r server/requirements-postgres.txt)
else
  mkdir -p "$APP_HOME/server/data"
  DATABASE_URL="sqlite:///./data/app.db"
fi

# ---- 3. 代码 + 虚拟环境 ----
mkdir -p "$APP_HOME"
if [ "$(cd "$PKG" && pwd)" != "$(cd "$APP_HOME" && pwd)" ]; then
  tar cf - -C "$PKG" server web docs deploy skills VERSION README.md | tar xf - -C "$APP_HOME"
fi
python3 -m venv "$APP_HOME/server/venv"
"$APP_HOME/server/venv/bin/pip" install -q \
  -r server/requirements.txt -r server/requirements-dev.txt -r server/requirements-samba.txt "${PIP_EXTRA[@]+"${PIP_EXTRA[@]}"}" \
  -i https://pypi.tuna.tsinghua.edu.cn/simple

# ---- 4. 数据库等敏感配置 → 独立配置文件 server/.env ----
cat > "$APP_HOME/server/.env" <<EOF
DATABASE_URL=$DATABASE_URL
JWT_SECRET=$JWT_SECRET
LOG_RETENTION_DAYS=$RETENTION
EOF
chown -R "$RUN_USER" "$APP_HOME"

# ---- 5. 前端静态文件（包内已预构建，无需 node） ----
if [ -d "$PKG/web/dist" ]; then
  mkdir -p "$WEB_ROOT"; rm -rf "${WEB_ROOT:?}"/*; cp -r "$PKG/web/dist/"* "$WEB_ROOT"/
elif command -v node >/dev/null 2>&1; then
  ( cd "$APP_HOME/web" && npm install --registry=https://registry.npmmirror.com --no-fund --no-audit \
    && npm run build && mkdir -p "$WEB_ROOT" && cp -r dist/* "$WEB_ROOT"/ )
else
  echo "发布包内无预构建 dist 且机器无 node，前端不可用"; exit 1
fi

# ---- 6. systemd 服务 ----
if [ "${SKIP_SYSTEMD:-0}" != "1" ]; then
  render deploy/templates/super-tools.service.tpl "/etc/systemd/system/$SERVICE_NAME.service"
  systemctl daemon-reload
  systemctl enable --now "$SERVICE_NAME"
  sleep 3; systemctl is-active --quiet "$SERVICE_NAME" || { journalctl -u "$SERVICE_NAME" -n 30 --no-pager; exit 1; }
fi

# ---- 7. nginx ----
if [ "${SKIP_NGINX:-0}" != "1" ]; then
  render deploy/templates/nginx.conf.tpl "$NGINX_CONF"
  nginx -t
  systemctl reload nginx 2>/dev/null || systemctl enable --now nginx
fi

# ---- 8. 防火墙 ----
if [ "${SKIP_FIREWALLD:-0}" != "1" ] && systemctl is-active --quiet firewalld; then
  firewall-cmd --permanent --add-service=http >/dev/null
  firewall-cmd --reload >/dev/null
fi

echo "== 部署完成：curl http://127.0.0.1/ 自检，初始账号 admin/admin123 =="
