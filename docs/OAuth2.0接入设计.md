# OAuth 2.0 认证接入设计（v1.4.0 规划）

> 状态：已实施（v1.4.0）。落地差异：OAuth 用户 pass_hash 用不可登录哨兵哈希（免改列可空与 SQLite 重建迁移）；重定向统一 302。平台现状：本地账号（PBKDF2 密码）+ 平台自签 JWT 会话（24h），
> 业务面 `/` 与管理面 `/admin` 分离登录。

## 1. 背景与目标

- **背景**：组织已有统一 OAuth 2.0 认证系统（IdP），要求平台接入——经 IdP 认证的用户才能访问页面。
- **目标**：
  1. 支持 OAuth 2.0 授权码登录，兼容任意标准 IdP（Keycloak / Authing / 自建等）
  2. 登录后获得平台会话，**现有全部 API/页面权限体系不变**（业务/管理面、require_admin、访问日志）
  3. 本地账号登录可按配置保留或禁用（过渡期共存，最终可纯 OAuth）
  4. OAuth 用户自动开通账号（auto-provision），角色可映射或由管理员提升

## 2. 方案选型

| 项 | 选择 | 理由 |
|---|---|---|
| 授权流程 | **授权码模式（Authorization Code）** | Web 应用标准流程；implicit 已废弃；密码模式违背委托本意 |
| 客户端类型 | 机密客户端（client_secret 仅存后端） | secret 不暴露给浏览器 |
| 防护 | state 一次性令牌（必选）+ PKCE（可选配置） | 防 CSRF / 授权码注入 |
| 会话 | **登录后签发平台自有 JWT**，不复用 IdP token | 现有 API 鉴权零改动；IdP token 短命且不应散播；登出即弃 |
| 用户映射 | IdP 唯一标识 `sub` ↔ users 表 `(oauth_provider, oauth_sub)` | 首次登录自动建号，后续绑定同一账号 |

```
浏览器                前端SPA(静态)        后端FastAPI              IdP(认证系统)
  │ 点"统一认证登录"       │                    │                       │
  ├──────────────────────▶ GET /api/auth/oauth/{p}/login             │
  │◀──────── 302 Location: {authorize_url}?client_id&redirect_uri&state&scope
  ├─────────────────────────────────────────────────────────────────▶│ 输入账号密码
  │◀──────────────────────────────────────── 302 callback?code&state │
  ├──────────────────────▶ GET /api/auth/oauth/{p}/callback ─────────▶│ token 换 code
  │                       │  校验state(一次性) ──────────────────────▶│ GET userinfo(sub/name)
  │                       │  find-or-create 本地用户→签发平台JWT      │
  │◀────── 302 /oauth/done?token=… ────────────                      │
  │  前端存token→进入业务面；后续API带平台JWT（现状不变）                │
```

## 3. 配置设计（`server/.env`，敏感不进 Git）

```ini
# 认证模式：local=仅本地密码 | oauth=仅OAuth | mixed=两者都开（过渡默认）
AUTH_MODE=mixed

# ---- OAuth Provider（首个版本支持配置 1 个，结构上预留多 Provider）----
OAUTH_PROVIDER_NAME=sso              # 展示名（登录按钮文案："使用 sso 登录"）
OAUTH_AUTHORIZE_URL=https://sso.example.com/oauth2/authorize
OAUTH_TOKEN_URL=https://sso.example.com/oauth2/token
OAUTH_USERINFO_URL=https://sso.example.com/oauth2/userinfo
OAUTH_CLIENT_ID=__CLIENT_ID__
OAUTH_CLIENT_SECRET=__CLIENT_SECRET__
OAUTH_SCOPE=openid profile
OAUTH_REDIRECT_URI=https://tools.example.com/api/auth/oauth/sso/callback   # 在IdP侧登记
OAUTH_USE_PKCE=0                    # 公网/无法保密环境建议 1
OAUTH_ADMIN_GROUPS=                 # 可选：IdP组/角色声明映射为平台管理员，逗号分隔；留空=不自动映射
```

> `OAUTH_REDIRECT_URI` 指向后端回调（同域 nginx 已反代 `/api/`，无需额外路由）。

## 4. 数据结构

### 4.1 users 表扩展（迁移）

```sql
ALTER TABLE users ADD COLUMN oauth_provider VARCHAR(32) NULL;   -- IdP标识，如 sso
ALTER TABLE users ADD COLUMN oauth_sub       VARCHAR(128) NULL;  -- IdP用户唯一ID(sub)
ALTER TABLE users ADD COLUMN email           VARCHAR(128) NULL;  -- IdP返回的邮箱(展示用)
ALTER TABLE users ADD COLUMN display_name    VARCHAR(64)  NULL;  -- IdP显示名
CREATE UNIQUE INDEX uq_users_oauth ON users(oauth_provider, oauth_sub);
-- pass_hash 允许为空：OAuth 自动建号用户无本地密码
ALTER TABLE users ALTER COLUMN pass_hash DROP NOT NULL;   -- PG
-- SQLite 无 DROP NOT NULL：迁移时重建表（迁移脚本统一处理两种方言）
```

ORM（`models.py`）：

```python
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    pass_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)  # OAuth用户为空
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # —— OAuth 绑定（与本地账号 1:1，预留 1:N 拆表空间）——
    oauth_provider: Mapped[str | None] = mapped_column(String(32))
    oauth_sub: Mapped[str | None] = mapped_column(String(128), index=True)
    email: Mapped[str | None] = mapped_column(String(128))
    display_name: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("oauth_provider", "oauth_sub", name="uq_users_oauth"),)
```

**用户名生成规则**（自动建号时）：优先 `sub`，冲突则 `sub-2/-3…`；`display_name` 仅展示不改 username。

### 4.2 新表 oauth_states（防 CSRF，state 一次性）

```python
class OAuthState(Base):
    __tablename__ = "oauth_states"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    next_path: Mapped[str] = mapped_column(String(200), default="/")  # 登录后回跳
    panel: Mapped[str] = mapped_column(String(8), default="")         # ""=业务面 / "admin"=管理面
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
```

- 生成：`secrets.token_urlsafe(32)`；**用后即删**；超过 5 分钟未用由老化逻辑清理（复用现有清理线程）。

### 4.3 不引入的东西（明确边界）

- **不存 IdP 的 access/refresh token**：仅用于登录时换 userinfo，随即丢弃（降低泄露面）
- **不做 IdP 会话同步登出**（单点登出）：平台登出=前端清 JWT；IdP 侧仍登录属正常 OAuth 行为，后续可选接 `end_session_url`

## 5. API 设计

| 方法/路径 | 说明 |
|---|---|
| `GET /api/auth/providers` | 未登录可用。返回 `{"mode":"mixed","providers":[{"name":"sso","title":"统一认证"}]}`，前端据此渲染登录按钮/密码框 |
| `GET /api/auth/oauth/{p}/login?next=&panel=` | 生成 state 入库 → `302` 到 IdP authorize_url（含 client_id/redirect_uri/scope/state[/PKCE]） |
| `GET /api/auth/oauth/{p}/callback?code=&state=` | ① 校验 state（存在即删，过期 400）→ ② 后端携 client_secret 换 token → ③ GET userinfo 取 `sub/name/email`（及可选 groups）→ ④ find-or-create 用户（业务角色；若 `OAUTH_ADMIN_GROUPS` 命中则 is_admin）→ ⑤ 签发平台 JWT → `302 /oauth/done?token=...` |
| 失败路径 | `302 /oauth/done?error=state_invalid|code_exchange_failed|userinfo_failed&detail=...` |

**兼容性约束**：
- `AUTH_MODE=oauth` 时 `POST /api/auth/login`（密码）返回 403「已切换统一认证」；`local/mixed` 行为不变
- 管理面沿用 `panel=admin` 语义：OAuth 回调带 `panel=admin` 时，非管理员用户**不签发 token**，跳错误页「该账号不是管理员」——与现有本地登录的管理面隔离策略一致
- 平台 JWT payload 增加 `provider` 字段（本地登录为 `"local"`），access_logs 自动记录来源

## 6. 前端设计

| 位置 | 改动 |
|---|---|
| `Login.vue` / `AdminLogin.vue` | 按 `/api/auth/providers` 渲染：OAuth 按钮（`window.location = /api/auth/oauth/sso/login?panel=...`）+ 密码表单（mode=oauth 时隐藏） |
| 新增 `OAuthDone.vue`（路由 `/oauth/done`） | 从 query 取 `token` 存 localStorage（走现有 store）→ 按 next 跳业务面；`error` 时展示原因与重试按钮 |
| 路由守卫 | 不变（仍然只认 localStorage 的平台 JWT），OAuth 只是多一种"获取 token"的方式 |
| `AdminUsers.vue` | 用户列表加「来源」列（本地/OAuth+provider）、显示 display_name/email；**密码重置按钮对 OAuth 用户禁用** |

页面访问控制说明：SPA 静态壳本身任何人可下载（行业常态），**所有数据与操作必须携带有效平台 JWT**，未认证用户在守卫处即被弹回登录页——满足"经认证用户才能访问页面"。

## 7. 安全设计

1. **state**：服务端生成、一次性（回调即删）、5 分钟时效、绑定 next/panel
2. **client_secret / token 交换**：仅发生在后端（浏览器不可见）
3. **PKCE 可选**：`OAUTH_USE_PKCE=1` 时 code_verder 仅存 oauth_states 行（服务端持 verifier，防截获）
4. **HTTPS**：生产要求回调域名走 HTTPS（nginx 加证书；或至少 IdP 允许 http 内网回调的开发豁免需显式确认）
5. **会话**：沿用平台 JWT 24h；token 前端 localStorage 存储（与现状一致，风险已知）
6. **自动建号默认无管理权限**；管理角色靠 `OAUTH_ADMIN_GROUPS` 声明映射或管理员手工提升
7. 回调接口计入 access_logs（来源、成功/失败），异常登录可在「使用统计」观测

## 8. 迁移与实施步骤

平台暂无 Alembic，本设计附带**轻量启动迁移**：`init_db()` 中检测 `users` 缺列则执行方言化 ALTER（PG）/重建表（SQLite），保证 `upgrade.sh` 升级即完成迁移、老数据不动。

| 步骤 | 内容 | 交付 |
|---|---|---|
| 1 | 后端：配置解析 + models/迁移 + oauth_states + 4 个端点 | `auth_oauth.py` |
| 2 | 前端：providers 渲染 + OAuthDone 页 + AdminUsers 来源列 | 3 个文件改动 |
| 3 | 测试：内置 Fake IdP（TestClient 内Stub授权/令牌/用户信息端点）| `test_oauth.py` ≥10 用例 |
| 4 | 联调：真实 IdP 测试环境验证全流程 → `AUTH_MODE` 切换演练 | 验证记录 |
| 5 | 文档/SKILL 更新，`package.sh` 出 v1.4.0 包 | 发布包 |

**测试用例清单**：完整授权码流成功；state 重放拒绝；state 过期拒绝；自动建号且二次登录同账号；`AUTH_MODE=oauth` 时密码登录被拒；`panel=admin` 非管理员被拒；`OAUTH_ADMIN_GROUPS` 命中映射管理员；OAuth 用户不能重置密码；mixed 模式两种登录并存；userinfo 取不到 sub 报错。

## 9. 待确认问题（实施前需拍板）

1. IdP 具体是哪家/协议端点是否标准授权码（提供 authorize/token/userinfo 三个 URL 与 client 凭证）
2. 过渡策略：是否需要 mixed 共存期，还是直接切 oauth-only
3. 管理员产生方式：IdP 组声明映射（需告知组名）还是管理员在管理面手工提升
4. 回调地址与 HTTPS：平台对外域名、证书由谁提供
5. 一个自然人是否可能同时有本地账号与 OAuth 账号（是否需要"绑定"能力，本期仅共存不合并）
