"""新工具模板（复制本目录为 server/app/modules/<你的工具名>/，目录名=URL 前缀，须英文小写下划线）。

注意：
- 本目录以下划线开头，框架不会加载它，仅作为复制模板
- models.py 定义数据表（表名全站唯一）；无数据表的工具可不保留此文件
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...db import Base


class Item(Base):
    """示例表：按业务改字段。所有类型：Integer/String(n)/Text/Float/Boolean/DateTime/Date"""

    __tablename__ = "template_items"  # ← 改成你的表名（全站唯一）

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))  # 必填字段
    remark: Mapped[str] = mapped_column(Text, default="")  # 可空字段给 default
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
