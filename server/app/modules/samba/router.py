"""小工具：Samba 任务目录。

共享目录下的每个子目录是一个任务；任务目录内存在 complete.txt 即视为完成。
支持：任务列表/状态、文件浏览/上传/下载、新建任务、标记/取消完成。
状态与操作记录入库（samba_tasks 镜像 / samba_events 流水），两表自动出现在管理面"数据管理"。
"""
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...auth import get_current_user
from ...db import get_db
from ...models import User
from . import smbfs
from .models import SambaEvent, SambaTask

TOOL = {
    "title": "Samba 任务目录",
    "importable": False,
    "tables": {"samba_tasks": "Samba任务状态", "samba_events": "Samba操作事件"},
}

router = APIRouter()

MARKER = "complete.txt"
MAX_UPLOAD = 50 * 1024 * 1024
NAME_RE = re.compile(r"^[^\\/:*?\"<>|\r\n\t]{1,120}$")
TIME_FMT = "%Y-%m-%d %H:%M:%S"


def _safe(name: str) -> str:
    if not name or not NAME_RE.match(name) or name in (".", ".."):
        raise HTTPException(400, f"非法名称：{name!r}（不允许斜杠、点号目录与特殊字符）")
    return name


def _mtime(st) -> str:
    return datetime.fromtimestamp(st.st_mtime).strftime(TIME_FMT)


# ---- 数据库记录（失败不影响共享操作本身）----

def _sync_mirror(db: Session, name: str, done: bool, complete_time: str | None, files_count: int | None):
    """files_count=None 表示不更新该字段（如仅标记完成时）。"""
    try:
        row = db.query(SambaTask).filter(SambaTask.task_name == name).first()
        if not row:
            row = SambaTask(task_name=name)
            db.add(row)
        row.done = done
        row.complete_time = datetime.strptime(complete_time, TIME_FMT) if (done and complete_time) else None
        if files_count is not None:
            row.files_count = files_count
        row.updated_at = datetime.now()
        db.commit()
    except Exception:
        db.rollback()


def _log(db: Session, task: str, event: str, username: str, file: str = ""):
    try:
        db.add(SambaEvent(task_name=task[:120], event=event, file=(file or "")[:200], username=username[:64]))
        db.commit()
    except Exception:
        db.rollback()


class TaskIn(BaseModel):
    name: str


@router.get("/status")
def samba_status(user: User = Depends(get_current_user)):
    ok, detail = smbfs.probe()
    return {"configured": smbfs.configured(), "connected": ok, "detail": detail}


@router.get("/tasks")
def list_tasks(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = []
    for name in smbfs.listdir():
        st = smbfs.stat(name)
        if not smbfs.is_dir(st):
            continue
        done = smbfs.exists(name, MARKER)
        files = [f for f in smbfs.listdir(name) if f != MARKER]
        complete_time = _mtime(smbfs.stat(name, MARKER)) if done else None
        items.append({
            "name": name,
            "done": done,
            "complete_time": complete_time,
            "files_count": len(files),
            "mtime": _mtime(st),
        })
        _sync_mirror(db, name, done, complete_time, len(files))
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return {"total": len(items), "items": items}


@router.post("/tasks")
def create_task(body: TaskIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    name = _safe(body.name)
    if smbfs.exists(name):
        raise HTTPException(400, f"任务目录已存在：{name}")
    smbfs.mkdir(name)
    _log(db, name, "created", user.username)
    _sync_mirror(db, name, False, None, 0)
    return {"ok": True, "name": name}


@router.get("/tasks/{task}/files")
def list_files(task: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = _safe(task)
    if not smbfs.exists(task):
        raise HTTPException(404, "任务不存在")
    items = []
    for f in smbfs.listdir(task):
        if f == MARKER:
            continue
        st = smbfs.stat(task, f)
        items.append({"name": f, "size": st.st_size, "mtime": _mtime(st)})
    items.sort(key=lambda x: x["name"])
    return {"total": len(items), "items": items, "done": smbfs.exists(task, MARKER)}


@router.get("/tasks/{task}/download")
def download(task: str, file: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task, file = _safe(task), _safe(file)
    if not smbfs.exists(task, file):
        raise HTTPException(404, "文件不存在")
    data = smbfs.read(task, file)
    _log(db, task, "download", user.username, file)
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{file}"},
    )


@router.post("/tasks/{task}/files")
async def upload(task: str, file: UploadFile, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = _safe(task)
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(400, "文件超过 50MB 限制")
    name = _safe(file.filename or "unnamed")
    smbfs.write(task, name, data)
    _log(db, task, "upload", user.username, name)
    done = smbfs.exists(task, MARKER)
    _sync_mirror(
        db, task, done,
        _mtime(smbfs.stat(task, MARKER)) if done else None,
        len([f for f in smbfs.listdir(task) if f != MARKER]),
    )
    return {"ok": True, "name": name, "size": len(data)}


@router.post("/tasks/{task}/complete")
def mark_complete(task: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = _safe(task)
    if not smbfs.exists(task):
        raise HTTPException(404, "任务不存在")
    content = f"completed_at={datetime.now().isoformat(sep=' ')}\nby={user.username}\n"
    smbfs.write(task, MARKER, content.encode("utf-8"))
    complete_time = _mtime(smbfs.stat(task, MARKER))
    _log(db, task, "complete", user.username, MARKER)
    _sync_mirror(db, task, True, complete_time, None)
    return {"ok": True, "done": True, "complete_time": complete_time}


@router.delete("/tasks/{task}/complete")
def undo_complete(task: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = _safe(task)
    if smbfs.exists(task, MARKER):
        smbfs.remove(task, MARKER)
        _log(db, task, "undo_complete", user.username, MARKER)
    _sync_mirror(db, task, False, None, None)
    return {"ok": True, "done": False}


# ---- 数据库记录查询 ----

@router.get("/db/tasks")
def db_tasks(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(SambaTask).order_by(SambaTask.updated_at.desc()).all()
    return {"total": len(rows), "items": [
        {
            "task_name": r.task_name,
            "done": r.done,
            "complete_time": r.complete_time.strftime(TIME_FMT) if r.complete_time else None,
            "files_count": r.files_count,
            "updated_at": r.updated_at.strftime(TIME_FMT),
        }
        for r in rows
    ]}


@router.get("/db/events")
def db_events(
    task: str = "",
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(SambaEvent).order_by(SambaEvent.id.desc())
    if task:
        q = q.filter(SambaEvent.task_name == task)
    rows = q.limit(min(limit, 500)).all()
    return {"total": len(rows), "items": [
        {
            "created_at": r.created_at.strftime(TIME_FMT),
            "task_name": r.task_name,
            "event": r.event,
            "file": r.file or "",
            "username": r.username,
        }
        for r in rows
    ]}
