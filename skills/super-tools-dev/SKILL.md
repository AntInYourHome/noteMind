---
name: super-tools-dev
description: 超级小工具平台的开发规范：如何新增小工具（_template 模板三步法）、crud 公共模块用法、管理面现成能力、测试要求、一键打包部署流程。当用户要求在该平台上开发工具、导入导出数据、改管理面或部署时使用；完整规范见仓库 docs/开发指南.md。
---

# 超级小工具平台 · 开发 Skill

前后端分离内部工具平台：FastAPI+SQLAlchemy / Vue3+Element Plus，核心是**模块自动发现**——加工具不改框架代码。**完整规范见仓库 `docs/开发指南.md`（必读），本文是速查。**

## 新增工具三步（标准路径）

1. 复制 `server/app/modules/_template/` → `server/app/modules/<工具名>/`（英文小写下划线，保留 `__init__.py`）；`router.py` 里 `TOOL={"title":菜单名,"tables":{表名:中文名}}`，CRUD 直接用 `from ..crud import list_rows, create_row, update_row, delete_row`，每个接口带 `Depends(get_current_user)`
2. 复制 `web/src/modules/_template/TemplateView.vue`，在 `web/src/modules/registry.js` 注册一行
3. 在 `server/tests/` 写测试（夹具 `client`/`admin`/`business` 现成）

## 可复用框架能力（勿重复造轮子）

- crud 公共模块：任意表增删改查/搜索、`import_rows`(批量导入)、`export_bytes(db, Model, "csv"|"xlsx")`、`coerce` 类型转换、`table_columns` 列元信息
- 管理面现成：用户管理 / 使用统计看板 / 任意表数据管理（`/api/admin/*`，仅管理员）——别重复开发
- 访问日志 access_logs 自动记录、90 天老化

## 测试与发布（强制门禁）

```bash
cd server && venv/bin/python -m pytest     # 后端测试（SQLite 独立库，零配置）
cd web && npm run test                     # 前端 vitest
bash deploy/package.sh                     # 本地一键打包（自动先跑全部测试）→ release/*.tar.gz
# 安装：解压 → cp deploy/deploy.conf.example deploy/deploy.conf 填占位符 → sudo bash deploy/install.sh
# 升级：sudo bash deploy/upgrade.sh（保留 .env 与数据，测试门禁+健康检查，可重复执行）
```

- 部署位置/数据库全部在 `deploy.conf` 占位符配置（APP_HOME/WEB_ROOT/PORT/DB_MODE/PG_*），敏感配置生成到 `server/.env`（不进 Git）
- Windows：`deploy\windows\deploy.conf` + `install-windows.ps1`（安装）/ `upgrade-windows.ps1`（升级）

## 红线

不改框架文件（main/registry/crud/auth/db/router.js/api.js/store.js/布局）；表名模块名全站唯一；接口必须鉴权；新代码必须带测试；前端改动发布后必须真实浏览器验证；不提交密钥/.env。
