"""示例小工具：备忘录。开发新工具时复制本目录（notes/）改名，修改三处：
1. TOOL 元信息（name 由目录名决定，改 title 即可）
2. models.py 数据表
3. router.py 的增删改查字段
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...auth import get_current_user
from ...db import get_db
from ...models import User
from ...utils.importer import read_rows
from .models import Note

TOOL = {
    "title": "备忘录（示例工具）",
    "importable": True,  # 为 True 时出现在管理面的“数据导入”里
    "tables": {"notes": "备忘录", "note_categories": "分类"},
}

router = APIRouter()


class NoteIn(BaseModel):
    title: str
    content: str = ""


@router.get("")
def list_notes(
    skip: int = 0,
    limit: int = 50,
    keyword: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = select(Note).order_by(Note.id.desc())
    if keyword:
        q = q.where(Note.title.contains(keyword) | Note.content.contains(keyword))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    return {"total": total, "items": db.scalars(q.offset(skip).limit(limit)).all()}


@router.post("")
def create_note(
    body: NoteIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    note = Note(title=body.title, content=body.content)
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.put("/{note_id}")
def update_note(
    note_id: int,
    body: NoteIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    note = db.get(Note, note_id)
    if not note:
        raise HTTPException(404, "记录不存在")
    note.title = body.title
    note.content = body.content
    db.commit()
    db.refresh(note)
    return note


@router.delete("/{note_id}")
def delete_note(
    note_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    note = db.get(Note, note_id)
    if not note:
        raise HTTPException(404, "记录不存在")
    db.delete(note)
    db.commit()
    return {"ok": True}


@router.post("/import")
async def import_notes(
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """管理面数据导入：CSV/XLSX 需包含表头列 title（可选 content）。"""
    rows = read_rows(file)
    inserted = 0
    for row in rows:
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        db.add(Note(title=title, content=str(row.get("content") or "")))
        inserted += 1
    db.commit()
    return {"inserted": inserted, "total_rows": len(rows)}
