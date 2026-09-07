"""Samba 任务状态记录：共享目录是状态真源（complete.txt），数据库负责留痕与查询。"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ...db import Base


class SambaTask(Base):
    """任务状态镜像：每次访问共享后同步，便于查询与导出。"""

    __tablename__ = "samba_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    complete_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    files_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class SambaEvent(Base):
    """操作事件流水：created / upload / download / complete / undo_complete。"""

    __tablename__ = "samba_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_name: Mapped[str] = mapped_column(String(120), index=True)
    event: Mapped[str] = mapped_column(String(32))
    file: Mapped[str] = mapped_column(String(200), default="")
    username: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
