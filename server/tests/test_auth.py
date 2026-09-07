"""认证与账号：登录、面板隔离、改密。"""


def test_login_ok(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    assert r.json()["token"]
    assert r.json()["user"]["is_admin"] is True


def test_login_wrong_password(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "bad"})
    assert r.status_code == 401


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_ok(client, admin):
    r = client.get("/api/auth/me", headers=admin)
    assert r.status_code == 200
    assert r.json()["username"] == "admin"


def test_admin_panel_rejects_business_user(client, admin, business):
    r = client.post(
        "/api/auth/login",
        json={"username": "zhangsan", "password": "zs123456", "panel": "admin"},
    )
    assert r.status_code == 403


def test_change_password_flow(client, admin):
    r = client.put(
        "/api/auth/password",
        json={"old_password": "admin123", "new_password": "newpass1"},
        headers=admin,
    )
    assert r.status_code == 200
    # 旧密码失效，新密码可用
    assert client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin123"}
    ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"username": "admin", "password": "newpass1"}
    ).status_code == 200
