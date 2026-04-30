# NoteMind 开发进度

**最后更新**：2026-04-03

---

## 项目概述

- **项目路径**：`/home/user/noteMind`
- **设计文档**：`/mnt/linux_share/blog_priv_1/temp/`
  - 需求分析报告.md
  - 笔记软件项目计划.md
  - 系统设计报告.md
- **项目阶段**：迭代 1 开发中

---

## 迭代进度

### 迭代 1：文件监控 + 解析 + 任务队列基础设施

**目标**：跑通"文件进入 inbox → 任务入队 → 被解析"的流程

| 功能 | 状态 | 说明 |
|------|------|------|
| 目录配置 | ✅ 完成 | main.py 中 WORKSPACE_ROOT 配置 |
| 文件监控 | ✅ 完成 | WatcherService（基于 watchdog） |
| 任务队列基础设施 | ✅ 完成 | TaskService + WorkerPool |
| 并发控制 | ✅ 完成 | WorkerPool 管理多 Worker |
| Markdown 解析 | ✅ 完成 | ParserService.parse_markdown() |
| PPT 解析 | ⚠️ 占位 | 只有 placeholder |
| Word 解析 | ⚠️ 占位 | 只有 placeholder |
| Excel 解析 | ⚠️ 占位 | 只有 placeholder |
| 图片 OCR | ⚠️ 占位 | 只有 placeholder |
| 任务状态 API | ✅ 完成 | /api/tasks |

**覆盖率**：未测试（tests/ 目录为空）

---

### 迭代 2：AI 理解 + 索引 + 搜索

**状态**：未开始

| 功能 | 状态 | 说明 |
|------|------|------|
| Embedding 生成 | ⚠️ Mock | MockAIService，尚未调用真实 API |
| 摘要生成 | ⚠️ Mock | MockAIService |
| 标签生成 | ⚠️ Mock | MockAIService |
| 错误处理机制 | ⚠️ 占位 | 框架在 ai_service.py |
| 向量存储 | ⏳ 待实现 | 需要接入 ChromaDB |
| 全文索引 | ✅ 完成 | SearchService.update_fts_index() |
| 关键词搜索 | ✅ 完成 | SearchService.fts_search() |
| 标签筛选 | ⏳ 待实现 | 搜索服务中有框架 |

---

### 迭代 3：归档 + Memory + Web UI

**状态**：未开始

| 功能 | 状态 |
|------|------|
| AI 自动分类 | ⏳ 待实现 |
| 文件移动 | ⏳ 待实现 |
| 软链接创建 | ⏳ 待实现 |
| Memory 模块 | ⏳ 待实现 |
| Web UI | ⏳ 待实现 |

---

## 代码结构

```
/home/user/noteMind/
├── backend/
│   ├── main.py              # FastAPI 入口，lifespan 管理
│   ├── run_test.py          # 测试脚本
│   └── app/
│       ├── api/             # API 路由
│       │   ├── files.py     # 文件 CRUD
│       │   ├── search.py    # 搜索
│       │   └── tasks.py    # 任务管理
│       ├── db/
│       │   └── database.py  # SQLite 初始化 + FTS
│       ├── models/
│       │   └── file.py      # File, Task 数据类
│       └── services/
│           ├── parser_service.py   # 文件解析
│           ├── file_service.py    # 文件管理
│           ├── task_service.py    # 任务队列
│           ├── search_service.py  # 搜索服务
│           ├── ai_service.py      # AI 服务 + Mock
│           ├── worker_service.py  # Worker 池
│           └── watcher_service.py # 文件监控
├── workspace/               # 工作目录
│   ├── inbox/              # 文件入口
│   ├── archive/            # 归档目录
│   ├── tags/               # 标签目录
│   └── index.db            # SQLite 数据库
├── tests/                  # 测试目录（空）
└── requirements.txt
```

---

## 待完善清单

1. **PPT/Word/Excel 解析** - 需要 python-pptx, python-docx, openpyxl
2. **图片 OCR** - 需要 PaddleOCR
3. **真实 AI 调用** - 用内部小模型 API 替换 MockAIService
4. **向量搜索** - 接入 ChromaDB
5. **智能归档** - ArchiveService
6. **调度系统** - TaskScheduler（白天/夜间不同速率）
7. **Web UI** - React + Vite
8. **Memory 模块** - UserMemoryService
9. **单元测试** - tests/ 目录需要填充
10. **错误处理完善** - 重试、降级策略

---

## 下一步

**最优先**：实现 PPT/Word/Excel 真实解析，替换占位符

**或者**：接入真实 AI API，替换 Mock
