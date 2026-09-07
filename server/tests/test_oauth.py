"""OAuth 2.0：providers 配置、授权码全流程、state 防护、自动建号、模式与面板隔离。"""
from urllib.parse import parse_qs, urlparse

from app import oauth
from app.db import SessionLocal
from app.models import User as UserModel


def _enable_provider(monkeypatch, **extra):
    monkeypatch.setenv("OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("OAUTH_AUTHORIZE_URL", "https://sso.test/authorize")
    monkeypatch.setenv("OAUTH_TOKEN_URL", "https://sso.test/token")
    monkeypatch.setenv("OAUTH_USERINFO_URL", "https://sso.test/userinfo")
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "http://tools.test/api/auth/oauth/sso/callback")
    for k, v in extra.items():
        monkeypatch.setenv(k, v)


def _fake_idp(monkeypatch, sub="u-123", name="张三", groups=None):
    monkeypatch.setattr(oauth, "_exchange_code", lambda code, verifier: "fake-at")
    monkeypatch.setattr(oauth, "_fetch_userinfo", lambda at: {
        "sub": sub, "name": name, "email": f"{sub}@t.cn", "groups": groups or [],
    })


def _start_login(client, monkeypatch, **login_params) -> str:
    r = client.get("/api/auth/oauth/sso/login", params=login_params, follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://sso.test/authorize")
    return parse_qs(urlparse(loc).query)["state"][0]


def _callback(client, state, code="c1"):
    return client.get(
        "/api/auth/oauth/sso/callback",
        params={"code": code, "state": state},
        follow_redirects=False,
    )


# ---------- providers ----------

def test_providers_hidden_when_unconfigured(client):
    r = client.get("/api/auth/providers")
    assert r.status_code == 200
    assert r.json() == {"mode": "mixed", "providers": []}


def test_providers_listed_when_configured(client, monkeypatch):
    _enable_provider(monkeypatch, OAUTH_PROVIDER_NAME="corp-sso")
    r = client.get("/api/auth/providers")
    body = r.json()
    assert body["mode"] == "mixed"
    assert body["providers"][0]["name"] == "corp-sso"


# ---------- 登录跳转 ----------

def test_login_redirect_with_state(client, monkeypatch):
    _enable_provider(monkeypatch)
    r = client.get("/api/auth/oauth/sso/login", follow_redirects=False)
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["client_id"] == ["cid"] and q["state"]
    assert q["redirect_uri"] == ["http://tools.test/api/auth/oauth/sso/callback"]


def test_login_open_redirect_blocked(client, monkeypatch):
    _enable_provider(monkeypatch)
    r = client.get("/api/auth/oauth/sso/login", params={"next": "https://evil.com/x"}, follow_redirects=False)
    assert r.status_code == 302  # next 被存为 /，跳转本身仍到 IdP


def test_login_unconfigured_404(client):
    r = client.get("/api/auth/oauth/sso/login")
    assert r.status_code == 404


# ---------- 回调全流程 ----------

def test_full_flow_success_and_me(client, monkeypatch):
    _enable_provider(monkeypatch)
    _fake_idp(monkeypatch)
    state = _start_login(client, monkeypatch)
    r = _callback(client, state)
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["token"][0] and q["next"] == ["/"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {q['token'][0]}"})
    assert me.status_code == 200
    assert me.json()["username"]  # 自动建号成功


def test_state_one_time_use(client, monkeypatch):
    _enable_provider(monkeypatch)
    _fake_idp(monkeypatch)
    state = _start_login(client, monkeypatch)
    assert _callback(client, state).status_code == 302
    r2 = _callback(client, state)  # 重放
    assert r2.headers["location"].startswith("/oauth/done")
    assert "error=state_invalid" in r2.headers["location"]


def test_unknown_state_rejected(client, monkeypatch):
    _enable_provider(monkeypatch)
    r = _callback(client, "forged-state")
    assert "error=state_invalid" in r.headers["location"]


def test_provision_once_and_reuse_same_account(client, monkeypatch):
    _enable_provider(monkeypatch)
    _fake_idp(monkeypatch, sub="u-777")
    for _ in range(2):
        state = _start_login(client, monkeypatch)
        assert _callback(client, state).status_code == 302
    with SessionLocal() as db:
        n = db.query(UserModel).filter(UserModel.oauth_sub == "u-777").count()
    assert n == 1


def test_panel_admin_rejects_non_admin(client, monkeypatch):
    _enable_provider(monkeypatch)
    _fake_idp(monkeypatch, sub="u-888")
    state = _start_login(client, monkeypatch, panel="admin", next="/admin/users")
    r = _callback(client, state)
    assert "error=not_admin" in r.headers["location"]


def test_panel_admin_allows_admin_user(client, monkeypatch, admin):
    _enable_provider(monkeypatch)
    _fake_idp(monkeypatch, sub="u-999")
    # 第一次登录：自动建号（业务角色）
    state = _start_login(client, monkeypatch)
    assert _callback(client, state).status_code == 302
    users = client.get("/api/admin/users", headers=admin).json()["items"]
    u = next(x for x in users if x["oauth_provider"])
    client.put(f"/api/admin/users/{u['id']}", json={"is_admin": True}, headers=admin)
    # 提升后再次以管理面入口登录：应放行并带回 next
    state2 = _start_login(client, monkeypatch, panel="admin", next="/admin/users")
    r = _callback(client, state2)
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["token"][0] and q["next"] == ["/admin/users"]


def test_admin_groups_mapping(client, monkeypatch):
    _enable_provider(monkeypatch, OAUTH_ADMIN_GROUPS="ops,devs")
    _fake_idp(monkeypatch, sub="u-a", groups=["devs"])
    state = _start_login(client, monkeypatch, panel="admin")
    r = _callback(client, state)
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["token"][0]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {q['token'][0]}"})
    assert me.json()["is_admin"] is True


def test_userinfo_missing_sub(client, monkeypatch):
    _enable_provider(monkeypatch)
    monkeypatch.setattr(oauth, "_exchange_code", lambda code, verifier: "at")
    monkeypatch.setattr(oauth, "_fetch_userinfo", lambda at: {"name": "无sub"})
    state = _start_login(client, monkeypatch)
    r = _callback(client, state)
    assert "error=userinfo_failed" in r.headers["location"]


# ---------- 模式与账号策略 ----------

def test_oauth_only_mode_rejects_password(client, monkeypatch):
    _enable_provider(monkeypatch, AUTH_MODE="oauth")
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 403


def test_oauth_user_cannot_reset_password(client, monkeypatch, admin):
    _enable_provider(monkeypatch)
    _fake_idp(monkeypatch, sub="u-oauth")
    state = _start_login(client, monkeypatch)
    _callback(client, state)
    users = client.get("/api/admin/users", headers=admin).json()["items"]
    oauth_user = next(u for u in users if u["oauth_provider"])
    r = client.put(
        f"/api/admin/users/{oauth_user['id']}/password",
        json={"new_password": "abc12345"},
        headers=admin,
    )
    assert r.status_code == 400


def test_user_brief_contains_oauth_fields(client, monkeypatch, admin):
    _enable_provider(monkeypatch)
    _fake_idp(monkeypatch, sub="u-brief", name="李四")
    state = _start_login(client, monkeypatch)
    _callback(client, state)
    users = client.get("/api/admin/users", headers=admin).json()["items"]
    u = next(x for x in users if x["oauth_provider"] == "sso")
    assert u["display_name"] == "李四" and u["email"]
