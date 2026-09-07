import os
from pathlib import Path

from dotenv import load_dotenv

# 原生部署时读取 server/.env（Docker 部署时环境变量优先）
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://tools:tools_secret@localhost:5432/tools",
)
JWT_SECRET = os.environ.get("JWT_SECRET", "dev_secret")
TOKEN_EXPIRE_SECONDS = 86400
# 指向 web/dist 时由后端直接托管前端（无 nginx 场景，如 Windows 部署）
STATIC_DIR = os.environ.get("STATIC_DIR", "")
# 访问日志保留天数（老化清理）
LOG_RETENTION_DAYS = int(os.environ.get("LOG_RETENTION_DAYS", "90"))
