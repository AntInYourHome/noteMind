"""测试夹具：独立 SQLite 测试库 + TestClient + 常用账号头。

运行：cd server && python -m pytest
"""
import os
from pathlib import Path

# 必须在导入 app 之前设置环境变量（config.py 在导入时读取）
_TEST_DB = Path(__file__).parent / "data" / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ["JWT_SECRET"] = "test-secret-0123456789abcdef-0123456789abcdef"
os.environ["STATIC_DIR"] = ""

import time

import pytest
from fastapi.testclient import TestClient

from app.db import engine
from app.main import app


def _remove_test_db():
    """Windows 下 WAL 句柄释放有延迟：重试清理 db 及 -wal/-shm 文件。"""
    for suffix in ("", "-wal", "-shm"):
        p = _TEST_DB.parent / (_TEST_DB.name + suffix)
        for _ in range(30):
            try:
                if p.exists():
                    p.unlink()
                break
            except PermissionError:
                time.sleep(0.1)


@pytest.fixture()
def client():
    _TEST_DB.parent.mkdir(parents=True, exist_ok=True)
    _remove_test_db()
    with TestClient(app) as c:  # 触发 startup：建表 + 种子 admin
        yield c
    engine.dispose()  # Windows 下必须先释放连接池，否则文件被占用无法删除
    _remove_test_db()


@pytest.fixture()
def admin(client):
    """管理员请求头。"""
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    token = r.json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def business(client, admin):
    """业务用户请求头（zhangsan / zs123456，不存在则创建）。"""
    client.post(
        "/api/admin/users",
        json={"username": "zhangsan", "password": "zs123456", "is_admin": False},
        headers=admin,
    )
    r = client.post("/api/auth/login", json={"username": "zhangsan", "password": "zs123456"})
    return {"Authorization": f"Bearer {r.json()['token']}"}
