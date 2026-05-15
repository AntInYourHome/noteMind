# NoteMind

**丢一堆文件进去，自动出来一个有结构的知识库。**

> NoteMind 是一个本地优先的个人知识管理工具。它将散乱的文档（PDF、Word、PPT、图片等）自动解析、AI 分析、分类打标，并构建成结构化的 Obsidian Wiki 知识图谱。所有数据纯本地，无需云端服务。

---

## 项目约束

### 1. 需要 Obsidian 查看

NoteMind 输出的是标准 Markdown 文件，但知识图谱的可视化浏览和双链跳转**需要使用 [Obsidian](https://obsidian.md/) 打开 Vault 目录**。Obsidian 免费、跨平台、本地运行。

### 2. Source 目录需要手动分类

NoteMind **不会替你整理源文件**。你需要先把文件按主题放到不同的目录中，工具会镜像这个目录结构到 Vault，分类基于你已整理好的目录路径。

### 3. 离线 VLM 需首次下载模型

图片文件默认通过云端 LLM API 分析。如需完全离线，运行 `python scripts/setup_vlm.py` 下载 ~450MB 模型权重。下载后纯 CPU 推理，无需联网。

---

## 核心价值

| 价值 | 说明 |
|------|------|
| **知识自动化** | 无需手动分类、整理、建索引，AI 自动完成 |
| **多模态理解** | 图片用 VLM 分析，文档用 LLM 摘要，OCR 提取文字 |
| **自组织图谱** | 自动生成 MOC 导航页和文档间双链关联 |
| **增量累积** | 只处理新增/变更文件，历史状态本地持久化 |
| **隐私优先** | 零外部依赖（可选 AI API），数据完全在本地 |

## 快速开始

```bash
# 1. 安装
pip install -e .

# 2. 配置（填入你的 LLM API key）
cp config.json.example config.json
vim config.json

# 3. 导入文件
python import.py --source /path/to/files

# 4. 用 Obsidian 打开 knowledge-base/ 目录
```

## 技术规格

| 维度 | 规格 |
|------|------|
| **Python 版本** | 3.10+ |
| **核心依赖** | 零外部依赖（可选安装 PDF/Office/OCR） |
| **支持格式** | PDF, DOCX/DOC, PPTX/PPT, XLSX/XLS, MD, TXT, CSV, SVG, JPG/PNG/BMP/WebP/TIFF |
| **AI 集成** | OpenAI 兼容 API（多 Provider 池 + 自动重试） |
| **本地模型** | MiniMind-V 63.9M 参数 VLM（可选，纯 CPU） |
| **状态管理** | SQLite 增量处理 + MD5 去重 |
| **输出格式** | 纯 Markdown + Obsidian `[[wikilink]]` |
| **Vault 结构** | 镜像源目录结构，跨设备可迁移 |
| **架构** | 模块化设计（8 个核心脚本模块 + 薄 CLI 入口） |
| **许可证** | MIT |

## 核心特性

| 特性 | 说明 |
|------|------|
| **智能 OCR** | 文字量充足的文档跳过 OCR，扫描版/图片型自动启用 |
| **AI 摘要** | 每篇文档生成 300 字核心摘要，大文档按章节拆分 |
| **自动分类** | 镜像源目录路径，或 AI 归类到预设分类 |
| **自动打标** | 每篇 3-8 个中文标签，去重去噪 |
| **文档双链** | 基于标签/分类/内容相似度自动建立 `[[wikilink]]` |
| **MD5 去重** | 重复文件自动跳过 |
| **知识树 MOC** | 自动生成 MOC.md 多级导航页（>500 条自动分割） |
| **增量更新** | 源文件内容变更检测（MD5），自动重新处理并更新 MOC/双链 |
| **级联删除** | 删除源文件时自动清理关联 Wiki 页面 |
| **健康检查** | 检测孤立页、断链、无外链页 |
| **模块化架构** | import.py 瘦身 80%，7 个新模块各司其职 |

## 安装

### 基础安装（零外部依赖）

```bash
pip install -e .
```

### 带格式支持

```bash
pip install -e ".[pdf,office]"
```

### 完整安装（含 OCR + VLM）

```bash
pip install -e ".[all,vlm]"
```

### 命令行用法

```bash
# 主导入
python import.py --source /path/to/files

# 预览模式（不写入）
python import.py --source /path/to/files --dry-run

# 指定不同 Vault
python import.py --source /path/to/files --vault /path/to/vault

# 环境诊断
python import.py --check

# 更新已有文档
python import.py --update

# 快速迁移已有文档到新格式
python import.py --migrate

# 强制重新处理所有图片
python import.py --update-image

# Wiki 健康检查
python import.py --lint

# 队列模式（支持崩溃恢复）
python import.py --source /path/to/files --queue
python import.py --resume  # 从上次中断处恢复
```

## 项目结构

```
noteMind/
├── import.py              # 薄 CLI 入口（~450行，模式分发 + 组件组装）
├── src/notemind/          # Python 包（pip install 后可用）
├── scripts/               # 核心模块
│   ├── config.py          # 配置加载
│   ├── path_utils.py      # 路径计算工具
│   ├── file_collector.py  # 文件收集
│   ├── status_db.py       # SQLite 状态追踪（类封装）
│   ├── file_processor.py  # 核心处理管线（parse → analyze → build）
│   ├── moc_manager.py     # MOC 生成（统一树渲染）
│   ├── handlers.py        # 不支持/失败文件处理器
│   ├── vault_ops.py       # 对齐/迁移/校验操作
│   ├── ai_client.py       # AI 多 Provider 池 + 重试
│   ├── parsers.py         # 格式解析器（含智能 OCR）
│   ├── analyzer.py        # AI 分析策略
│   ├── builder.py         # Markdown 构建器
│   ├── classifier.py      # AI 分类器
│   ├── crosslink.py       # 文档双链
│   ├── dedup.py           # 去重检测与合并
│   ├── cascade_delete.py  # 级联删除
│   ├── lint.py            # Wiki 健康检查
│   └── ingest_*.py        # 增量分析管道
├── knowledge-base/        # 输出 Vault（Obsidian 打开）
├── tests/                 # 测试套件（159 个用例）
└── docs/                  # 文档
```

## 常见问题

**Q: 需要联网吗？**
A: AI 摘要/分类/打标需要联网（调用 LLM API）。文件解析和 OCR 是本地执行的。本地 VLM 模型可完全离线使用。

**Q: API 调用费用？**
A: DeepSeek Chat 等模型价格很低，通常每次导入几篇文档只需几分钱。

**Q: Vault 可以跨设备同步吗？**
A: 可以。Vault 是纯 Markdown 文件夹，支持 iCloud、Git、Syncthing 等同步方式。

**Q: 输出文件很大吗？**
A: 每篇原始文档只生成一个精简 Markdown 文件（标题 + AI 摘要 + 章节索引 + 标签），不包含原文全文。

## 测试

```bash
# 运行全部测试
python -m pytest tests/ -v

# 快速冒烟测试
python -m pytest tests/test_smoke.py tests/test_dedup.py tests/test_parsers.py -v
```

---

[CHANGELOG](CHANGELOG.md) · [CONTRIBUTING](CONTRIBUTING.md) · [SECURITY](SECURITY.md)
