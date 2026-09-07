"""管理面：用户管理、统计、通用数据管理、权限隔离。"""
import time


def _wait_for_log(client, admin, path):
    """访问日志经线程池异步写入：轮询直到统计里出现该接口记录。"""
    for _ in range(40):
        body = client.get("/api/admin/stats", headers=admin).json()
        if any(row["path"] == path for row in body["recent"]):
            return body
        time.sleep(0.05)
    raise AssertionError(f"访问日志未记录 {path}")


# ---------- 用户管理 ----------

def test_user_lifecycle(client, admin):
    # 创建
    r = client.post(
        "/api/admin/users",
        json={"username": "lisi", "password": "ls123456", "is_admin": False},
        headers=admin,
    )
    assert r.status_code == 200
    uid = r.json()["id"]
    # 重复创建被拒
    assert (
        client.post(
            "/api/admin/users",
            json={"username": "lisi", "password": "ls123456"},
            headers=admin,
        ).status_code
        == 400
    )
    # 重置密码后新密码可登录
    client.put(f"/api/admin/users/{uid}/password", json={"new_password": "new123456"}, headers=admin)
    r = client.post("/api/auth/login", json={"username": "lisi", "password": "new123456"})
    assert r.status_code == 200
    # 删除
    assert client.delete(f"/api/admin/users/{uid}", headers=admin).status_code == 200


def test_cannot_delete_self(client, admin):
    r = client.get("/api/admin/users", headers=admin)
    admin_id = r.json()["items"][0]["id"]
    assert client.delete(f"/api/admin/users/{admin_id}", headers=admin).status_code == 400


# ---------- 统计 ----------

def test_stats_shape(client, admin):
    # 访问日志异步落库：轮询直到带身份的请求被计入
    body = None
    for _ in range(40):
        body = client.get("/api/admin/stats", headers=admin).json()
        if body["overview"]["active_users_today"] >= 1:
            break
        time.sleep(0.05)
    assert body["overview"]["active_users_today"] >= 1
    assert set(body) >= {"overview", "daily", "per_tool", "recent", "health"}
    assert len(body["daily"]) == 14
    assert body["health"]["tools"] >= 3


def test_access_log_recorded(client, admin):
    client.get("/api/admin/stats", headers=admin)
    body = _wait_for_log(client, admin, "/api/admin/stats")
    assert any(
        row["path"] == "/api/admin/stats" and row["username"] == "admin"
        for row in body["recent"]
    )


# ---------- 通用数据管理 ----------

def test_data_generic_crud_and_export(client, admin):
    r = client.get("/api/admin/data/notes/notes", headers=admin)
    assert r.status_code == 200
    cols = {c["name"]: c for c in r.json()["columns"]}
    assert cols["id"]["pk"] is True
    assert cols["title"]["required"] is True

    r = client.post(
        "/api/admin/data/notes/notes",
        json={"data": {"title": "g1", "content": "gc"}},
        headers=admin,
    )
    row_id = r.json()["id"]
    assert r.json()["title"] == "g1"

    r = client.put(
        f"/api/admin/data/notes/notes/{row_id}",
        json={"data": {"title": "g2"}},
        headers=admin,
    )
    assert r.json()["title"] == "g2"

    r = client.get("/api/admin/data/notes/notes/export", params={"format": "csv"}, headers=admin)
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "g2" in r.text

    assert client.delete(f"/api/admin/data/notes/notes/{row_id}", headers=admin).status_code == 200


def test_data_import_csv(client, admin):
    # 第三行 title 为空，违反必填约束应被跳过
    csv_content = "title,content\nimp-1,c1\nimp-2,c2\n,c3\n"
    r = client.post(
        "/api/admin/data/notes/notes/import",
        files={"file": ("t.csv", csv_content.encode("utf-8"), "text/csv")},
        headers=admin,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["inserted"] == 2
    assert body["skipped"] == 1


def test_admin_apis_reject_business_user(client, business):
    for path, method in [
        ("/api/admin/users", "get"),
        ("/api/admin/stats", "get"),
        ("/api/admin/data/notes/notes", "get"),
        ("/api/admin/users", "post"),
    ]:
        r = getattr(client, method)(path, headers=business)
        assert r.status_code == 403, f"{method} {path}"


def test_multi_tables_per_tool(client, admin):
    """一个工具可声明多张表：数据管理接口按表切换返回各自列元信息。"""
    r = client.get("/api/admin/data/notes", headers=admin)
    assert r.json()["tables"] == {"notes": "备忘录", "note_categories": "分类"}

    r = client.get("/api/admin/data/notes/notes", headers=admin)
    cols = {c["name"] for c in r.json()["columns"]}
    assert cols == {"id", "title", "content", "created_at"}

    # 切换到第二张表：列结构不同、可独立增删
    r = client.get("/api/admin/data/notes/note_categories", headers=admin)
    cols = {c["name"] for c in r.json()["columns"]}
    assert cols == {"id", "name", "sort_order"}
    r = client.post(
        "/api/admin/data/notes/note_categories",
        json={"data": {"name": "工作", "sort_order": 1}},
        headers=admin,
    )
    assert r.status_code == 200 and r.json()["name"] == "工作"
    r = client.get("/api/admin/data/notes/note_categories", headers=admin)
    assert r.json()["total"] == 1
    # 切回第一张表不受影响
    assert client.get("/api/admin/data/notes/notes", headers=admin).json()["columns"][0]["name"] == "id"
