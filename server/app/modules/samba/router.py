"""小工具：Samba 任务目录。

共享目录下的每个子目录是一个任务；任务目录内存在 complete.txt 即视为完成。
支持：任务列表/状态、文件浏览/上传/下载、新建任务、标记/取消完成。
"""
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from ...auth import get_current_user
from ...models import User
from . import smbfs

TOOL = {"title": "Samba 任务目录", "importable": False}

router = APIRouter()

MARKER = "complete.txt"
MAX_UPLOAD = 50 * 1024 * 1024
NAME_RE = re.compile(r"^[^\\/:*?\"<>|\r\n\t]{1,120}$")


def _safe(name: str) -> str:
    if not name or not NAME_RE.match(name) or name in (".", ".."):
        raise HTTPException(400, f"非法名称：{name!r}（不允许斜杠、点号目录与特殊字符）")
    return name


def _mtime(st) -> str:
    return datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")


class TaskIn(BaseModel):
    name: str


@router.get("/status")
def samba_status(user: User = Depends(get_current_user)):
    ok, detail = smbfs.probe()
    return {"configured": smbfs.configured(), "connected": ok, "detail": detail}


@router.get("/tasks")
def list_tasks(user: User = Depends(get_current_user)):
    items = []
    for name in smbfs.listdir():
        st = smbfs.stat(name)
        if not smbfs.is_dir(st):
            continue
        done = smbfs.exists(name, MARKER)
        files = [f for f in smbfs.listdir(name) if f != MARKER]
        items.append({
            "name": name,
            "done": done,
            "complete_time": _mtime(smbfs.stat(name, MARKER)) if done else None,
            "files_count": len(files),
            "mtime": _mtime(st),
        })
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return {"total": len(items), "items": items}


@router.post("/tasks")
def create_task(body: TaskIn, user: User = Depends(get_current_user)):
    name = _safe(body.name)
    if smbfs.exists(name):
        raise HTTPException(400, f"任务目录已存在：{name}")
    smbfs.mkdir(name)
    return {"ok": True, "name": name}


@router.get("/tasks/{task}/files")
def list_files(task: str, user: User = Depends(get_current_user)):
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
def download(task: str, file: str, user: User = Depends(get_current_user)):
    task, file = _safe(task), _safe(file)
    if not smbfs.exists(task, file):
        raise HTTPException(404, "文件不存在")
    data = smbfs.read(task, file)
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{file}"},
    )


@router.post("/tasks/{task}/files")
async def upload(task: str, file: UploadFile, user: User = Depends(get_current_user)):
    task = _safe(task)
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(400, "文件超过 50MB 限制")
    name = _safe(file.filename or "unnamed")
    smbfs.write(task, name, data)
    return {"ok": True, "name": name, "size": len(data)}


@router.post("/tasks/{task}/complete")
def mark_complete(task: str, user: User = Depends(get_current_user)):
    task = _safe(task)
    if not smbfs.exists(task):
        raise HTTPException(404, "任务不存在")
    content = f"completed_at={datetime.now().isoformat(sep=' ')}\nby={user.username}\n"
    smbfs.write(task, MARKER, content.encode("utf-8"))
    return {"ok": True, "done": True, "complete_time": _mtime(smbfs.stat(task, MARKER))}


@router.delete("/tasks/{task}/complete")
def undo_complete(task: str, user: User = Depends(get_current_user)):
    task = _safe(task)
    if smbfs.exists(task, MARKER):
        smbfs.remove(task, MARKER)
    return {"ok": True, "done": False}
