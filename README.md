# 超级小工具平台

前后端分离的内部小工具平台：一个框架 + 开放源码，大家（借助 AI 编程）往里面开发自己的小工具。
**开发规范见 [docs/开发指南.md](docs/开发指南.md)（AI 助手必读）**，速查版在 `skills/super-tools-dev/SKILL.md`。

## 结构

```
├── server/               后端：FastAPI（模块自动发现 + crud 公共模块）
│   ├── app/modules/      ★ 每个小工具一个目录；_template/ 是复制模板
│   └── tests/            pytest 测试（发布门禁）
├── web/                  前端：Vue3 + Element Plus 门户
│   ├── src/modules/      ★ 每个小工具一个页面；_template/ 是复制模板
│   └── tests/            vitest 测试（发布门禁）
├── deploy/               部署工程（占位符配置 + 模板 + 打包/安装脚本）
└── docs/开发指南.md       ★ 权威开发规范
```

## 打包与部署（推荐流程）

```bash
bash deploy/package.sh    # 本地一键打包：跑全部测试 → 构建前端 → release/super-tools-<版本>.tar.gz
# 上环境：解压发布包，进入目录
cp deploy/deploy.conf.example deploy/deploy.conf   # 填写 __XXX__ 占位符（部署位置/数据库）
sudo bash deploy/install.sh                        # 一键部署；DRY_RUN=1 可先预检
```

- 部署位置、端口、数据库均在 `deploy.conf` 占位符化；敏感配置生成到 `server/.env`（不进 Git）
- Windows：`deploy\windows\deploy.conf` + `powershell -ExecutionPolicy Bypass -File deploy\windows\install-windows.ps1`
- 已部署环境的日常更新：Linux `sudo bash deploy/upgrade.sh`；Windows `upgrade-windows.ps1`（保留 .env 与数据，含测试门禁与健康检查）

## 本地开发

```bash
# 后端（server/）：python3.10+，需本地 PostgreSQL（或自配 server/.env 指向 sqlite）
python -m venv venv && venv/bin/pip install -r requirements.txt -r requirements-dev.txt
venv/bin/python -m pytest && venv/bin/python -m uvicorn app.main:app --reload

# 前端（web/）：node 18+，API 自动代理到 localhost:8000
npm install && npm run test && npm run dev
```

初始账号 `admin / admin123`（登录后请尽快修改密码）。业务面 `/`，管理面 `/admin`。

## 新增一个小工具

见 [docs/开发指南.md](docs/开发指南.md)——复制模板目录、改三个地方、提 PR 即可。
