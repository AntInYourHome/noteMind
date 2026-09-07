import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import jwt
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .admin_data import router as admin_data_router
from .auth import (
    JWT_SECRET,
    get_current_user,
    hash_password,
    make_token,
    require_admin,
    verify_password,
)
from .config import LOG_RETENTION_DAYS, STATIC_DIR
from .db import Base, SessionLocal, engine, get_db
from .models import AccessLog, User
from .registry import load_tools, tools_info


class LoginIn(BaseModel):
    username: str
    password: str
    panel: str = ""  # "admin"：管理面登录，仅管理员账号允许


class UserCreateIn(BaseModel):
    username: str
    password: str
    is_admin: bool = False


class UserUpdateIn(BaseModel):
    is_admin: bool


class PasswordResetIn(BaseModel):
    new_password: str


def _user_brief(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "created_at": user.created_at,
    }


class PasswordIn(BaseModel):
    old_password: str
    new_password: str


def init_db():
    # 模块导入会触发各工具 models 的注册
    load_tools()
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.query(User).count() == 0:
            db.add(
                User(
                    username="admin",
                    pass_hash=hash_password("admin123"),
                    is_admin=True,
                )
            )
            db.commit()


app = FastAPI(title="超级小工具平台")
_START_TIME = time.time()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _write_access_log(entry: dict):
    try:
        with SessionLocal() as db:
            db.add(AccessLog(**entry))
            db.commit()
    except Exception:
        pass  # 日志失败不影响业务请求


@app.middleware("http")
async def access_log_middleware(request, call_next):
    start = time.time()
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        username = ""
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            try:
                username = jwt.decode(auth[7:], JWT_SECRET, algorithms=["HS256"]).get("username", "")
            except jwt.PyJWTError:
                pass
        await run_in_threadpool(
            _write_access_log,
            {
                "ts": datetime.now(),
                "username": (username or "")[:64],
                "method": request.method[:8],
                "path": request.url.path[:200],
                "status": response.status_code,
                "duration_ms": int((time.time() - start) * 1000),
                "ip": (request.client.host if request.client else "")[:64],
            },
        )
    return response


def _retention_loop():
    """日志老化：每 6 小时清理一次超期访问日志。"""
    while True:
        try:
            cutoff = datetime.now() - timedelta(days=LOG_RETENTION_DAYS)
            with SessionLocal() as db:
                db.query(AccessLog).filter(AccessLog.ts < cutoff).delete(
                    synchronize_session=False
                )
                db.commit()
        except Exception:
            pass
        time.sleep(6 * 3600)


@app.on_event("startup")
def startup():
    for _ in range(30):
        try:
            init_db()
            break
        except Exception:
            time.sleep(2)
    threading.Thread(target=_retention_loop, daemon=True).start()


@app.post("/api/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.pass_hash):
        raise HTTPException(401, "用户名或密码错误")
    if body.panel == "admin" and not user.is_admin:
        raise HTTPException(403, "该账号不是管理员")
    return {
        "token": make_token(user),
        "user": {"id": user.id, "username": user.username, "is_admin": user.is_admin},
    }


@app.get("/api/auth/me")
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "username": user.username, "is_admin": user.is_admin}


@app.put("/api/auth/password")
def change_password(
    body: PasswordIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(body.old_password, user.pass_hash):
        raise HTTPException(400, "原密码不正确")
    user.pass_hash = hash_password(body.new_password)
    db.commit()
    return {"ok": True}


@app.get("/api/tools")
def list_tools(user: User = Depends(get_current_user)):
    return tools_info()


@app.get("/api/admin/stats")
def admin_stats(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    now = datetime.now()
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since14 = today0 - timedelta(days=13)

    requests_today = db.query(func.count(AccessLog.id)).filter(AccessLog.ts >= today0).scalar() or 0
    uv_today = (
        db.query(func.count(func.distinct(AccessLog.username)))
        .filter(AccessLog.ts >= today0, AccessLog.username != "")
        .scalar()
        or 0
    )
    errors_today = (
        db.query(func.count(AccessLog.id))
        .filter(AccessLog.ts >= today0, AccessLog.status >= 500)
        .scalar()
        or 0
    )

    # 近14天：取出 (时间, 用户) 后在 Python 侧聚合，避免 date() 的 SQL 方言差异
    rows_14 = (
        db.query(AccessLog.ts, AccessLog.username).filter(AccessLog.ts >= since14).all()
    )
    daily_map: dict[str, list] = {}
    for ts, username in rows_14:
        d = ts.strftime("%Y-%m-%d")
        bucket = daily_map.setdefault(d, [0, set()])
        bucket[0] += 1
        if username:
            bucket[1].add(username)
    daily = []
    for i in range(13, -1, -1):
        d = (today0 - timedelta(days=i)).strftime("%Y-%m-%d")
        reqs, uvs = daily_map.get(d, (0, set()))
        daily.append({"date": d[5:], "requests": reqs, "users": len(uvs)})

    tool_rows = (
        db.query(AccessLog.path, func.count(AccessLog.id))
        .filter(AccessLog.ts >= since14, AccessLog.path.like("/api/tools/%"))
        .group_by(AccessLog.path)
        .all()
    )
    per_tool: dict[str, int] = {}
    for p, c in tool_rows:
        parts = p.split("/")
        if len(parts) > 3 and parts[3]:
            per_tool[parts[3]] = per_tool.get(parts[3], 0) + c

    recent = [
        {
            "ts": r.ts.strftime("%m-%d %H:%M:%S"),
            "username": r.username or "-",
            "method": r.method,
            "path": r.path,
            "status": r.status,
            "duration_ms": r.duration_ms,
        }
        for r in db.query(AccessLog).order_by(AccessLog.id.desc()).limit(15)
    ]

    return {
        "overview": {
            "total_users": db.query(func.count(User.id)).scalar() or 0,
            "requests_today": requests_today,
            "active_users_today": uv_today,
            "errors_today": errors_today,
        },
        "daily": daily,
        "per_tool": dict(sorted(per_tool.items(), key=lambda kv: -kv[1])),
        "recent": recent,
        "health": {
            "db": True,
            "uptime_sec": int(time.time() - _START_TIME),
            "tools": len(tools_info()),
            "retention_days": LOG_RETENTION_DAYS,
            "version": "1.1",
        },
    }


app.include_router(admin_data_router)


# ---------- 管理面接口（业务面与管理面分离，全部仅管理员） ----------

@app.get("/api/admin/users")
def admin_list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.id).all()
    return {"total": len(users), "items": [_user_brief(u) for u in users]}


@app.post("/api/admin/users")
def admin_create_user(
    body: UserCreateIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    import re

    if not re.fullmatch(r"[A-Za-z0-9_-]{2,32}", body.username):
        raise HTTPException(400, "用户名须为 2-32 位字母/数字/下划线/连字符")
    if len(body.password) < 6:
        raise HTTPException(400, "密码至少 6 位")
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(400, "用户名已存在")
    user = User(
        username=body.username,
        pass_hash=hash_password(body.password),
        is_admin=body.is_admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_brief(user)


@app.put("/api/admin/users/{uid}")
def admin_update_user(
    uid: int,
    body: UserUpdateIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, uid)
    if not user:
        raise HTTPException(404, "用户不存在")
    if user.id == admin.id and not body.is_admin:
        raise HTTPException(400, "不能撤销自己的管理员权限")
    user.is_admin = body.is_admin
    db.commit()
    return _user_brief(user)


@app.put("/api/admin/users/{uid}/password")
def admin_reset_password(
    uid: int,
    body: PasswordResetIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, uid)
    if not user:
        raise HTTPException(404, "用户不存在")
    if len(body.new_password) < 6:
        raise HTTPException(400, "密码至少 6 位")
    user.pass_hash = hash_password(body.new_password)
    db.commit()
    return {"ok": True}


@app.delete("/api/admin/users/{uid}")
def admin_delete_user(
    uid: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, uid)
    if not user:
        raise HTTPException(404, "用户不存在")
    if user.id == admin.id:
        raise HTTPException(400, "不能删除自己")
    db.delete(user)
    db.commit()
    return {"ok": True}


# 挂载所有小工具路由：/api/tools/{模块名}/...
for _tool in load_tools():
    app.include_router(_tool["router"], prefix=f"/api/tools/{_tool['meta']['name']}")

# 前端静态托管（无 nginx 场景，如 Windows/SQLite 部署）：STATIC_DIR 指向 web/dist
if STATIC_DIR and Path(STATIC_DIR).is_dir():

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404, "Not Found")
        target = Path(STATIC_DIR) / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(Path(STATIC_DIR) / "index.html")
