from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # OAuth 自动建号用户无本地密码：存不可登录的随机哨兵哈希（两种数据库免迁移）
    pass_hash: Mapped[str] = mapped_column(String(256))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # —— OAuth 绑定 ——
    oauth_provider: Mapped[str | None] = mapped_column(String(32))
    oauth_sub: Mapped[str | None] = mapped_column(String(128), index=True)
    email: Mapped[str | None] = mapped_column(String(128))
    display_name: Mapped[str | None] = mapped_column(String(64))


class OAuthState(Base):
    """OAuth state 一次性令牌（防 CSRF），回调校验后即删。"""

    __tablename__ = "oauth_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    verifier: Mapped[str | None] = mapped_column(String(128))  # PKCE code_verifier（可选）
    next_path: Mapped[str] = mapped_column(String(200), default="/")
    panel: Mapped[str] = mapped_column(String(8), default="")  # ""=业务面 / "admin"=管理面
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class AccessLog(Base):
    """访问日志：中间件自动写入，由老化线程按保留期清理。"""

    __tablename__ = "access_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    username: Mapped[str] = mapped_column(String(64), default="", index=True)
    method: Mapped[str] = mapped_column(String(8), default="")
    path: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    ip: Mapped[str] = mapped_column(String(64), default="")
