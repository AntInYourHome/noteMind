# NoteMind

**v1.5.0 — 本地文件 → Obsidian Vault 智能导入工具**

将 PDF、Word、PPT、Excel、图片等文件自动解析、AI 摘要分类，生成精简 Markdown 笔记并建立文档关联，存入 Obsidian Vault。

## 快速开始

```bash
# 1. 编辑配置（填入 API key）
vim config.json

# 2. 导入文件
python import.py --source /path/to/files

# 3. 用 Obsidian 打开 Vault 目录
```

## 核心特性

| 特性 | 说明 |
|------|------|
| **智能 OCR** | 文字为主的文档跳过图片 OCR，扫描版/图片型文档自动 OCR |
| **AI 摘要** | 每篇文档生成 300 字核心摘要，大文档按章节摘要 |
| **自动分类** | 基于完整摘要 AI 归类到预设分类 |
| **自动打标** | 每篇 3-8 个中文标签，去重去噪 |
| **文档双链** | 基于标签/分类/内容相似度自动建立 Obsidian `[[wikilink]]` |
| **MD5 去重** | 重复文件自动跳过 |
| **原始文件归档** | 复制到 `_archive/` 目录 |
| **知识树 MOC** | 自动生成 `MOC.md` 总览页 |

## 支持格式

| 格式 | 解析方式 | OCR |
|------|---------|-----|
| PDF | 逐页提取文字+图片 | 智能判断（文字量 < 100 字符/页时启用） |
| Word (.docx) | 按标题拆分章节 | 智能判断 |
| PPT (.pptx) | 逐页提取文字 | 智能判断 |
| Excel (.xlsx) | 按工作表提取 | 不涉及 |
| Markdown (.md) | 清洗格式+提取图片 | 智能判断 |
| 图片 (.jpg/.png/.bmp/.webp/.tiff) | OCR 提取文字 | 始终启用 |
| 纯文本 (.txt/.csv/.log) | 直接读取 | 不涉及 |

## 项目结构

```
noteMind/
├── import.py              # 主入口
├── config.json            # 配置文件（已加入 .gitignore）
├── config.json.example    # 配置模板
├── install.sh             # 安装脚本（Linux/Mac）
├── requirements.txt       # 依赖列表
├── scripts/
│   ├── ai_client.py       # AI 客户端（多 Provider 池 + 重试）
│   ├── parsers.py         # 格式解析器（含智能 OCR）
│   ├── analyzer.py        # AI 分析策略（短文档/长文档）
│   ├── builder.py         # Markdown 构建器
│   ├── classifier.py      # AI 分类器
│   ├── crosslink.py       # 文档双链模块
│   └── dedup.py           # MD5 去重模块
├── tests/                 # 测试目录
├── logs/                  # 运行时日志（已加入 .gitignore）
├── knowledge-base/        # Obsidian Vault（默认）
└── README.md              # 本文档
```

## 配置说明

编辑 `config.json`：

```json
{
    "ai": {
        "providers": [
            {
                "api_key": "sk-xxx",
                "model": "deepseek-chat",
                "base_url": "https://api.deepseek.com/v1",
                "multimodal": false
            }
        ],
        "concurrency": 5,
        "max_retries": 3,
        "retry_delay": 1
    },
    "vault": {
        "path": "./knowledge-base",
        "categories": ["芯片", "安全", "项目", "笔记", "其他"]
    },
    "import": {
        "archive_dir": "_archive",
        "failed_dir": "_failed",
        "dedup": true,
        "dedup_index": ".notemind_index.json"
    },
    "performance": {
        "chunk_size": 5,
        "report_enabled": true
    },
    "logging": {
        "level": "INFO",
        "file": "logs/import.log",
        "log_dir": "logs"
    }
}
```

### 关键配置项

| 配置 | 说明 | 默认值 |
|------|------|--------|
| `ai.providers` | API Provider 列表，支持多 Key 轮转 | - |
| `ai.concurrency` | AI 并发数 | 5 |
| `ai.max_retries` | 失败重试次数 | 3 |
| `vault.categories` | 预设分类列表 | `["其他"]` |
| `performance.chunk_size` | 长文档每组合并章节数 | 5 |
| `import.dedup` | MD5 去重开关 | true |

## 使用场景

### 场景 1：每日资料收集

```bash
mkdir ~/today-input
cp ~/Downloads/*.pdf ~/today-input/
cp ~/Screenshots/*.png ~/today-input/

python import.py --source ~/today-input
# 用 Obsidian 打开 ./knowledge-base
```

### 场景 2：预览模式

```bash
python import.py --source ~/old-documents --dry-run
# 只预览，不实际写入
```

### 场景 3：指定不同 Vault

```bash
python import.py --source ~/work-docs --vault ~/work-knowledge
```

### 场景 4：图片 OCR

将含文字截图放入目录导入，会自动通过 RapidOCR 提取文字。无需额外配置。

安装 RapidOCR（可选）：
```bash
./install.sh  # 选择选项 7
# 或直接：pip install rapidocr_onnxruntime
```

## 安装

```bash
# 克隆项目
cd noteMind

# 安装依赖（Linux/Mac）
./install.sh

# 或手动安装
pip install pymupdf python-docx python-pptx openpyxl
```

### Windows

```powershell
cd C:\Users\yourname\noteMind
pip install pymupdf python-docx python-pptx openpyxl
python import.py --source C:\Users\yourname\Documents\inbox
```

## 测试

```bash
# 运行全部测试（需排除未安装 OCR 依赖的测试）
python -m pytest tests/ -v --ignore=tests/test_ocr_real_pdf.py --ignore=tests/test_ocr_spike.py

# 快速冒烟测试
python -m pytest tests/test_smoke.py tests/test_dedup.py tests/test_parsers.py -v
```

## FAQ

**Q: 需要联网吗？**
A: AI 摘要/分类/打标需要联网。文件解析和 OCR 是本地执行的。

**Q: 智能 OCR 是什么？**
A: 导入 PDF/Word/PPT 时，系统先评估文档的文字含量。文字为主的文档（每页 > 100 字符）跳过图片 OCR，因为文字已足够理解。扫描版/图片型文档则对图片做 OCR 提取文字。

**Q: 文档双链怎么工作？**
A: 导入完成后，系统基于标签重叠、同分类匹配、摘要关键词相似度自动在文档间建立关联，以 Obsidian `[[wikilink]]` 格式写入 Markdown 末尾的 `## 相关文档` 段落。

**Q: 输出文件很大吗？**
A: 不会。每篇原始文档只生成一个精简 Markdown 文件，包含标题、AI 摘要、章节索引和标签，不包含原文全文。避免 Obsidian 打开大文件时卡顿。

**Q: API 调用会花很多钱吗？**
A: DeepSeek Chat 等模型价格很低，通常每次导入几篇文档只需几分钱。

**Q: Vault 可以被多个设备同步吗？**
A: 可以，Vault 是纯 Markdown 文件夹，支持 iCloud、Git、Syncthing 等同步方式。

**Q: 支持哪些图片格式？**
A: JPG、PNG、GIF、BMP、WebP、TIFF。

## 版本历史

### v1.6.0 (2026-05-07)

- **多级分类树**：3 级分类（领域 → 平台/场景 → 具体系统），支持数千文档精细分类
- **文档类型标签**：AI 自动识别文档类型（白皮书、教程、报告、架构文档、学习笔记等）
- **MOC 递归扫描**：知识树总览页自动适配多级目录结构
- **分类器重写**：一级领域关键词 + 二级 AI 判断 + 三级 AI 判断，逐级递进
- **旧格式兼容**：categories 支持 dict（新格式）和 list（旧格式平级分类）

### v1.5.0 (2026-05-07)

- **智能 OCR**：文字为主的文档跳过图片 OCR，大幅减少无用 OCR 调用
- **文档双链**：基于标签/分类/内容相似度自动建立 `[[wikilink]]` 关联
- **代码精简**：删除 `agent_scheduler.py`、`memory.py`、`metrics.py` 等无用模块
- **分类器改进**：使用完整摘要作为分类输入，提升分类准确率
- **测试完善**：45 个测试全部通过

### v1.4.1 (2026-05-06)

- HarmonyOS+6.0 安全技术白皮书适配

### v1.4.0 (2026-05-06)

- 性能优化方法论 + 章节合并
