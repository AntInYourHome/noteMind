# NoteMind 软件架构文档

## 1. 项目定位

NoteMind 是一个 **本地文档 → Obsidian Vault 的 ETL 工具**。将 PDF、Word、PPT、Excel、图片、OneNote、Markdown、纯文本等异构文档，通过 AI 分析（摘要、标签、分类、图片描述），自动转换为结构化的 Obsidian Markdown 笔记，并按分类归档。

**核心设计原则：**
- 零强制依赖（纯 Python 3.10+ 标准库，第三方库仅在解析特定格式时需要）
- 本地优先（所有数据存储在用户本地磁盘，无外部服务依赖）
- 可观测性（指标采集、检查点恢复、Provider 健康追踪）

---

## 2. 系统架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        NoteMind v1.3.0                              │
│                                                                     │
│  ┌──────────┐    ┌─────────────────────────────────────────────┐   │
│  │ config   │    │              import.py (编排器)              │   │
│  │ .json    │───>│  CLI args → 加载配置 → 初始化子系统          │   │
│  └──────────┘    │  collect_files() → 遍历源目录                │   │
│                  │  逐文件调用 handle_file() 管道               │   │
│  ┌──────────┐    │  完成后 update_moc() + 健康报告             │   │
│  │ tools/   │    └──────────────┬──────────────────────────────┘   │
│  │api_diag  │                   │                                   │
│  └──────────┘    ┌──────────────▼──────────────────────────────┐   │
│                  │           handle_file() 管道                 │   │
│  ┌──────────┐    │                                             │   │
│  │ scripts/ │    │  [1] 解析 ──→ parsers.py                    │   │
│  │          │    │  [2] AI分析 ─→ analyzer.py + ai_client.py   │   │
│  │ parsers  │    │  [3] 分类 ──→ classifier.py                 │   │
│  │ analyzer │    │  [4] 归档 ──→ 原始文件 → _archive/          │   │
│  │ ai_client│    │  [5] 图片 ──→ 复制到 Vault                  │   │
│  │ builder  │    │  [6] 构建 ──→ builder.py → .md              │   │
│  │classifier│    │  [7] 去重 ──→ dedup.py                      │   │
│  │ dedup    │    │  [8] 记忆 ──→ memory.py (SQLite)            │   │
│  │ memory   │    └──────────────┬──────────────────────────────┘   │
│  │ metrics  │                   │                                   │
│  │scheduler │    ┌──────────────▼──────────────────────────────┐   │
│  │ builder  │    │              输出层                          │   │
│  └──────────┘    │  vault/<category>/<date>-<name>.md          │   │
│                  │  vault/MOC.md                                │   │
│  ┌──────────┐    │  vault/_archive/ (原始文件)                  │   │
│  │ tests/   │    │  vault/.notemind_assets/ (提取的图片)       │   │
│  └──────────┘    │  vault/.notemind_index.json (去重索引)      │   │
│                  │  vault/.notemind_memory.db (记忆数据库)     │   │
│                  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. 核心子系统

### 3.1 解析层 — `scripts/parsers.py`

**职责：** 将不同格式的原始文件统一转换为 `ParseResult` 数据结构。

```
ParseResult
├── text: str          # 全文提取
├── images: list[str]  # 提取的图片路径
└── sections: list[Section]
    ├── title: str     # 章节标题
    ├── text: str      # 章节文本
    └── images: list   # 章节内嵌图片
```

**支持的格式：**

| 格式 | 依赖库 | 解析策略 |
|------|--------|----------|
| PDF | PyMuPDF (fitz) | 逐页提取文本和内嵌图片 |
| DOCX | python-docx | 按标题样式分割章节，提取表格和图片 |
| PPTX | python-pptx | 逐页提取文本和图片 |
| XLSX | openpyxl (read-only) | 每个工作表作为一个章节 |
| Markdown | 标准库 re | 清理语法，提取本地图片引用，按 `#` 分割 |
| TXT/CSV/LOG | 标准库 | UTF-8 直接读取 |
| OneNote | onenote2xml | XML 解析 + 二进制降级 |
| 图片 | 标准库 | 无文本，仅返回路径（由 AI 视觉分析） |

**工厂模式：** `PARSERS` 字典注册表 + `get_parser(file_path)` 按扩展名分发。

---

### 3.2 AI 客户端 — `scripts/ai_client.py`

**职责：** 管理与 DashScope API 的通信，提供多 Provider 负载均衡和健康追踪。

```
APIProviderPool
├── providers: list[dict]     # 配置的 API Key 列表
├── concurrency: int          # 最大并发数
├── _trackers: list[ProviderHealthTracker]  # 健康追踪（每个 provider 一个）
└── _index: int               # 轮询指针

ProviderHealthTracker (每个 provider 独立实例)
├── success_count: int        # 成功次数
├── failure_count: int        # 失败次数
├── rate_limit_count: int     # 限流次数
├── circuit_open_until: float # 熔断截止时间（429 后 30 秒冷却）
├── health_score() → float    # 健康评分 0.0-1.0
└── is_available() → bool     # 是否可调用
```

**关键机制：**
- **轮询分发：** `next_provider()` 跳过处于熔断冷却状态的 provider
- **熔断器：** 收到 429 限流 → 该 provider 冷却 30 秒，期间自动跳过
- **重试策略：** 指数退避 (1s × 2^(n-1)) + 随机抖动，针对 429/5xx/超时
- **批量并发：** `batch_call()` 使用 `ThreadPoolExecutor` 同时发起多个请求

---

### 3.3 分析策略 — `scripts/analyzer.py`

**职责：** 根据文档特征自动选择最优分析策略。

```
AnalysisContext.analyze(text, images, sections, scheduler=None)
    │
    ├── 文本 < 3000 字符 AND 章节 < 3
    │   └── ShortDocStrategy
    │       ├── generate_summary(full_text) → 1 个摘要
    │       └── generate_tags(full_text)    → 1 组标签
    │
    └── 文本 >= 3000 字符 OR 章节 >= 3
        └── LongDocStrategy
            ├── 逐章节 generate_summary(section.text) → 每章摘要
            ├── 逐章节 generate_tags(section.text)    → 每章标签
            └── 逐图片 analyze_image(image_path)      → 图片描述
                (有 scheduler 时批量并发执行)
```

---

### 3.4 构建器 — `scripts/builder.py`

**职责：** 将分析结果组装为 Obsidian 格式的 Markdown 文档。

```
MarkdownBuilder (链式调用)
  .add_frontmatter(category, tags, source_path)
  .add_title()
  .add_file_summary(summary)          ← 短文档或索引文件
  .add_sections(section_results)       ← 长文档正文
  .add_images(vault_paths, desc)       ← 图片及 AI 描述
  .add_tags_section(tags)
  .add_footer()
  .build() → str

分裂模式（大文档）：
  .build_index(section_links)    → 主文档（摘要 + 目录链接）
  .build_section_note(section)   → 每个章节独立 .md 文件
```

**输出示例（大文档拆分）：**
```
vault/芯片/
├── 2026-04-30-芯片架构白皮书.md          ← 索引文件 (doc_type: index)
├── 2026-04-30-芯片架构白皮书-01-概述.md   ← 章节 1 (parent: 索引文件名)
├── 2026-04-30-芯片架构白皮书-02-指令集.md ← 章节 2
└── 2026-04-30-芯片架构白皮书-03-安全.md   ← 章节 3
```

---

### 3.5 其他子系统

| 子系统 | 文件 | 职责 |
|--------|------|------|
| 分类器 | `classifier.py` | AI 从配置的分类列表中选择最匹配的类别 |
| 去重 | `dedup.py` | MD5 哈希 + JSON 索引，防止重复处理同一文件 |
| 记忆 | `memory.py` | SQLite 存储文档元数据，支持标签索引和相关文档查找 |
| 指标 | `metrics.py` | 逐文件耗时追踪、检查点恢复、健康检查、JSON 报告 |
| 调度器 | `agent_scheduler.py` | 按优先级（图片 > 摘要 > 分类 > 标签）批量并发 AI 调用 |
| 诊断 | `tools/api_diag.py` | 独立工具，测试 API 连通性、能力、并发性能 |

---

## 4. 设计模式

| 模式 | 位置 | 说明 |
|------|------|------|
| **策略模式** | `analyzer.py` | `ShortDocStrategy` / `LongDocStrategy` 按文档特征切换 |
| **建造者模式** | `builder.py` | `MarkdownBuilder` 链式构建复杂文档 |
| **工厂模式** | `parsers.py` | `PARSERS` 注册表 + `get_parser()` 按扩展名分发 |
| **单例模式** | `ai_client.py` | `_pool` 全局单例 + `init_pool()`/`get_pool()` |
| **熔断器模式** | `ai_client.py` | `ProviderHealthTracker` 429 限流后自动冷却 |
| **观察者模式** | `metrics.py` | `MetricsCollector` 观察每个文件的生命周期 |

---

## 5. 配置系统

```json
{
    "ai": {
        "providers": [                     // 多 Key 池，轮询分发
            {
                "api_key": "sk-...",
                "model": "qwen3.6-flash",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"
            }
        ],
        "concurrency": 5,                  // 最大并发 AI 调用数
        "max_retries": 3,                  // 每次调用的最大重试次数
        "retry_delay": 1                   // 重试基础延迟（秒）
    },
    "vault": {
        "path": "~/knowledge-base",        // 目标 Obsidian Vault 路径
        "categories": ["芯片", "安全", "项目", "笔记", "其他"]  // AI 分类目标
    },
    "import": {
        "archive_dir": "_archive",         // 原始文件归档目录
        "failed_dir": "_failed",           // 失败文件隔离目录
        "dedup": true,                     // 启用 MD5 去重
        "dedup_index": ".notemind_index.json",
        "split_threshold_sections": 5,     // 章节数 ≥ 此值时拆分文件
        "split_threshold_chars": 10000     // 字符数 > 此值时拆分文件
    },
    "memory": {
        "enabled": true,                   // 启用 SQLite 文档记忆
        "db_path": ".notemind_memory.db"
    },
    "logging": {
        "level": "INFO",
        "file": "logs/import.log",
        "log_dir": "logs"
    }
}
```

---

## 6. 数据模型

### ParseResult（解析结果）
```python
ParseResult(
    text: str,           # 全文纯文本
    images: list[str],   # 提取的图片文件路径
    sections: list[Section]  # 结构化章节
)

Section(
    title: str,          # 章节标题
    text: str,           # 章节文本
    images: list         # 章节内嵌图片
)
```

### AnalysisResult（分析结果）
```python
AnalysisResult(
    summary: str,            # 文档级摘要
    tags: list[str],         # 文档级标签
    sections: list[dict],    # 逐章节分析 [{title, summary, text}, ...]
    image_descriptions: list[str]  # 图片 AI 描述
)
```

### Markdown Frontmatter（输出元数据）
```yaml
---
source: 原始文件名.pdf
date: 2026-04-30
category: 芯片
tags: [RISC-V, 芯片架构, 安全]
original_path: /path/to/original/file.pdf  # 溯源路径
doc_type: index                            # 仅索引文件有此字段
sections: 12                               # 仅索引文件有此字段
parent: 2026-04-30-芯片架构白皮书           # 仅章节文件有此字段
---
```

---

## 7. 依赖关系图

```
import.py (编排器)
├── scripts/metrics.py          ← MetricsCollector
├── scripts/parsers.py          ← PARSERS, IMAGE_EXTS, get_parser, ParseResult
├── scripts/analyzer.py         ← AnalysisContext
├── scripts/classifier.py       ← classify
├── scripts/builder.py          ← MarkdownBuilder
├── scripts/dedup.py            ← compute_md5, check_duplicate, add_to_index
├── scripts/memory.py           ← MemoryStore
├── scripts/ai_client.py        ← APIProviderPool, init_pool, get_pool, print_log_analysis
└── scripts/agent_scheduler.py  ← AgentScheduler

scripts/analyzer.py
└── scripts/ai_client.py        ← analyze_image, generate_summary, generate_tags

scripts/agent_scheduler.py
└── scripts/ai_client.py        ← generate_summary, generate_tags, analyze_image (延迟导入)

scripts/classifier.py
└── scripts/ai_client.py        ← _call_api

tools/api_diag.py               ← 独立工具，直接读取 config.json

tests/
├── test_parsers.py             ← scripts/parsers.py
├── test_dedup.py               ← scripts/dedup.py
└── test_smoke.py               ← 集成测试（subprocess 调用 import.py）
```
