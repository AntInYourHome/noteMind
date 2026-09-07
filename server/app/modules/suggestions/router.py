"""小工具：改进意见。用户在业务面提交建议（≤100字，仅中文/字母/数字/常见标点）。

管理员查看全部建议：管理面「数据管理」→ 改进意见 → suggestions 表（自动出现）。
"""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...auth import get_current_user
from ...db import get_db
from ...models import User
from .models import Suggestion

TOOL = {
    "title": "改进意见",
    "importable": False,
    "tables": {"suggestions": "改进意见"},
}

router = APIRouter()

MAX_LEN = 100
# 允许：中文、字母、数字、空白、常见中英文标点（不支持特殊字符）
ALLOWED_RE = re.compile(r"^[\u4e00-\u9fa5A-Za-z0-9 \s，。！？、：；“”‘’（）\-_,.!?;:()]+$")


class SuggestionIn(BaseModel):
    content: str


def _validate(content_raw: str) -> str:
    content = content_raw.strip()
    if not content:
        raise HTTPException(400, "内容不能为空")
    if len(content) > MAX_LEN:
        raise HTTPException(400, f"最多 {MAX_LEN} 字，当前 {len(content)} 字")
    if not ALLOWED_RE.match(content):
        raise HTTPException(400, "包含不支持的字符：仅允许中文、字母、数字与常见标点")
    return content


@router.post("")
def submit_suggestion(
    body: SuggestionIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    content = _validate(body.content)
    s = Suggestion(username=user.username, content=content)
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"id": s.id, "content": s.content, "created_at": s.created_at}


@router.get("")
def my_suggestions(
    skip: int = 0,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = (
        select(Suggestion)
        .where(Suggestion.username == user.username)
        .order_by(Suggestion.id.desc())
    )
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    items = [
        {"id": s.id, "content": s.content, "created_at": s.created_at}
        for s in db.scalars(q.offset(skip).limit(min(limit, 100)))
    ]
    return {"total": total, "items": items}
