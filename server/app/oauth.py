"""OAuth 2.0 通用认证（授权码模式）。设计见 docs/OAuth2.0接入设计.md。

- 兼容任意标准 IdP（Keycloak/Authing/自建），配置全部走环境变量（server/.env），运行时动态读取
- 登录成功后签发平台自有 JWT，现有 API/权限体系零改动
- state 一次性令牌防 CSRF；PKCE 可选；next 路径白名单防开放重定向
"""
import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from .auth import hash_password, make_token
from .db import SessionLocal
from .models import OAuthState, User

router = APIRouter(prefix="/api/auth")

STATE_TTL = timedelta(minutes=5)


def _conf() -> dict:
    """每次请求动态读取配置（便于不重启切换/测试注入）。"""
    return {
        "name": os.environ.get("OAUTH_PROVIDER_NAME", "sso"),
        "authorize_url": os.environ.get("OAUTH_AUTHORIZE_URL", ""),
        "token_url": os.environ.get("OAUTH_TOKEN_URL", ""),
        "userinfo_url": os.environ.get("OAUTH_USERINFO_URL", ""),
        "client_id": os.environ.get("OAUTH_CLIENT_ID", ""),
        "client_secret": os.environ.get("OAUTH_CLIENT_SECRET", ""),
        "scope": os.environ.get("OAUTH_SCOPE", "openid profile"),
        "redirect_uri": os.environ.get("OAUTH_REDIRECT_URI", ""),
        "use_pkce": os.environ.get("OAUTH_USE_PKCE", "0") == "1",
        "admin_groups": [
            g.strip() for g in os.environ.get("OAUTH_ADMIN_GROUPS", "").split(",") if g.strip()
        ],
    }


def _mode() -> str:
    m = os.environ.get("AUTH_MODE", "mixed")
    return m if m in ("local", "oauth", "mixed") else "mixed"


def _provider_ready(c: dict) -> bool:
    return all([c["client_id"], c["client_secret"], c["authorize_url"], c["token_url"], c["userinfo_url"]])


def _safe_next(path: str) -> str:
    """只允许站内路径，防开放重定向。"""
    return path if path.startswith("/") and not path.startswith("//") else "/"


@router.get("/providers")
def list_providers():
    c = _conf()
    ps = []
    if _provider_ready(c):
        ps.append({"name": c["name"], "title": f"{c['name']} 统一认证"})
    return {"mode": _mode(), "providers": ps}


@router.get("/oauth/{provider}/login")
def oauth_login(provider: str, next: str = "/", panel: str = ""):
    c = _conf()
    if not _provider_ready(c) or provider != c["name"]:
        raise HTTPException(404, "OAuth 未配置或不存在")
    if _mode() == "local":
        raise HTTPException(403, "已禁用 OAuth 登录")

    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48) if c["use_pkce"] else None
    with SessionLocal() as db:
        db.add(OAuthState(
            state=state,
            verifier=verifier,
            next_path=_safe_next(next)[:200],
            panel="admin" if panel == "admin" else "",
        ))
        db.commit()

    params = {
        "response_type": "code",
        "client_id": c["client_id"],
        "redirect_uri": c["redirect_uri"],
        "scope": c["scope"],
        "state": state,
    }
    if verifier:
        challenge = base64url_nopad(hashlib.sha256(verifier.encode()).digest())
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"
    return RedirectResponse(f"{c['authorize_url']}?{urlencode(params)}", status_code=302)


def base64url_nopad(raw: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _exchange_code(code: str, verifier: str | None) -> str:
    """授权码换 access_token（client_secret 仅存后端）。测试可打桩替换本函数。"""
    c = _conf()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": c["client_id"],
        "client_secret": c["client_secret"],
        "redirect_uri": c["redirect_uri"],
    }
    if verifier:
        data["code_verifier"] = verifier
    with httpx.Client(timeout=10) as http:
        r = http.post(c["token_url"], data=data)
        r.raise_for_status()
        token = r.json().get("access_token")
    if not token:
        raise RuntimeError("token 响应缺少 access_token")
    return token


def _fetch_userinfo(access_token: str) -> dict:
    """拉取用户信息（sub 必需；name/email/groups 可选）。测试可打桩替换本函数。"""
    c = _conf()
    with httpx.Client(timeout=10) as http:
        r = http.get(c["userinfo_url"], headers={"Authorization": f"Bearer {access_token}"})
        r.raise_for_status()
        return r.json()


def _fail(err: str, detail: str = "") -> RedirectResponse:
    q = urlencode({"error": err, "detail": detail[:200]})
    return RedirectResponse(f"/oauth/done?{q}", status_code=302)


def _gen_username(sub: str, db) -> str:
    base = re.sub(r"[^A-Za-z0-9_-]", "", sub)[:32] or "oauth-user"
    username, i = base, 2
    while db.query(User).filter(User.username == username).first():
        username, i = f"{base}-{i}", i + 1
    return username


@router.get("/oauth/{provider}/callback")
def oauth_callback(provider: str, code: str = "", state: str = "", error: str = ""):
    if error:
        return _fail("idp_error", error)

    with SessionLocal() as db:
        st = db.query(OAuthState).filter(OAuthState.state == state).first()
        if not st:
            return _fail("state_invalid", "state 不存在或已被使用")
        db.delete(st)
        db.commit()
        if datetime.now() - st.created_at > STATE_TTL:
            return _fail("state_expired")

        try:
            access_token = _exchange_code(code, st.verifier)
            info = _fetch_userinfo(access_token)
        except Exception as e:  # noqa: BLE001 统一转错误跳转
            return _fail("code_exchange_failed", str(e))

        sub = str(info.get("sub") or "")
        if not sub:
            return _fail("userinfo_failed", "userinfo 缺少 sub")
        groups = info.get("groups") or []

        user = db.query(User).filter(
            User.oauth_provider == provider, User.oauth_sub == sub
        ).first()
        if user is None:
            user = User(
                username=_gen_username(sub, db),
                pass_hash=hash_password(secrets.token_urlsafe(32)),  # 不可登录哨兵
                oauth_provider=provider,
                oauth_sub=sub[:128],
                email=str(info.get("email") or "")[:128] or None,
                display_name=str(info.get("name") or "")[:64] or None,
                is_admin=bool(_conf()["admin_groups"] and set(_conf()["admin_groups"]) & set(groups)),
            )
            db.add(user)
        else:
            user.email = str(info.get("email") or "")[:128] or user.email
            user.display_name = str(info.get("name") or "")[:64] or user.display_name
        db.commit()
        db.refresh(user)

        if st.panel == "admin" and not user.is_admin:
            return _fail("not_admin", "该账号不是管理员")

        q = urlencode({"token": make_token(user, provider=provider), "next": st.next_path})
        return RedirectResponse(f"/oauth/done?{q}", status_code=302)


def clean_expired_states(keep_minutes: int = 60) -> int:
    """清理遗留 state（由日志老化线程周期调用）。"""
    cutoff = datetime.now() - timedelta(minutes=keep_minutes)
    with SessionLocal() as db:
        n = db.query(OAuthState).filter(OAuthState.created_at < cutoff).delete(
            synchronize_session=False
        )
        db.commit()
    return n


def extract_state(location: str) -> str:
    """从 login 302 的 Location 取 state（测试辅助）。"""
    return parse_qs(urlparse(location).query).get("state", [""])[0]
