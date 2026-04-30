# NoteMind

**本地文件 → Obsidian Vault 智能导入工具**

将 PDF、Word、PPT、Excel、图片、OneNote 等文件自动解析、AI 摘要分类，生成标准 Markdown 笔记存入 Obsidian Vault。

## 快速开始

```bash
# 1. 编辑配置（填入 API key）
vim config.json

# 2. 导入文件
./import.py --source /path/to/files

# 3. 用 Obsidian 打开 Vault 目录
```

## 目录

- [功能清单](#功能清单)
- [项目结构](#项目结构)
- [配置说明](#配置说明)
- [使用场景](#使用场景)
- [Windows 使用指南](#windows-使用指南)
- [测试验证清单](#测试验证清单)
- [FAQ](#faq)

---

## 功能清单

### 核心功能（零外部依赖）

| # | 功能 | 状态 | 说明 |
|---|------|------|------|
| 1 | 图片 AI 识别 | ✅ | qwen3.6-flash 视觉模型，识别图片内容概要 |
| 2 | 文本摘要生成 | ✅ | AI 提取核心要点（3-5 条） |
| 3 | 自动标签 | ✅ | 每篇 3-8 个中文标签 |
| 4 | AI 自动分类 | ✅ | 根据内容归类到预设分类 |
| 5 | MD5 去重 | ✅ | 重复文件自动跳过 |
| 6 | 原始文件归档 | ✅ | 复制到 `_archive/` 目录 |
| 7 | 知识树 MOC | ✅ | 自动生成 `MOC.md` 总览页 |
| 8 | 纯文本/Markdown 解析 | ✅ | 内置正则清洗 |

### 可选功能（需安装依赖）

| # | 功能 | 依赖 | 说明 |
|---|------|------|------|
| 9 | PDF 解析 | pymupdf | 提取全文 |
| 10 | Word 解析 | python-docx | 提取文本 + 表格 |
| 11 | PPT 解析 | python-pptx | 逐页提取文本 |
| 12 | Excel 解析 | openpyxl | 逐行提取数据 |
| 13 | OneNote 解析 | onenote2xml | .one 文件提取 |

### 容错机制

| # | 功能 | 说明 |
|---|------|------|
| 14 | 解析重试 | 失败自动重试 3 次（可配置） |
| 15 | 失败隔离 | 失败文件移入 `_failed/` + 错误日志 |
| 16 | 文件名冲突处理 | 自动追加序号 |
| 17 | 空内容跳过 | 空文件不处理 |
| 18 | 预览模式 | `--dry-run` 不实际写入 |

### 批量处理能力（V3 新增）

| # | 功能 | 说明 |
|---|------|------|
| 19 | AI API 重试 | 指数退避 + 随机抖动，应对网络波动 |
| 20 | 断点续传 | `--resume` 从上次中断处继续，不重复处理 |
| 21 | 健康监控 | 实时追踪成功/失败率，异常自动告警 |
| 22 | 指标报告 | 每次运行生成 JSON 报告（`logs/report_*.json`） |
| 23 | 进度日志 | 每 10 个文件打印一次进度摘要 |
| 24 | 独立日志 | 所有日志写入 `logs/import.log` |
| 25 | 长文档拆分 | 自动按章节拆分，逐章生成 AI 摘要 |

---

## 项目结构

```
noteMind/
├── import.py              # 主脚本（核心入口）
├── config.json            # 配置文件（已加入 .gitignore）
├── config.json.example    # 配置模板，复制后修改
├── install.sh             # 安装脚本（Linux/Mac）
├── requirements.txt       # 可选依赖列表
├── scripts/
│   ├── ai_client.py       # AI 客户端（urllib 纯标准库，含重试）
│   ├── parsers.py         # 格式解析器（支持 sections 拆分）
│   ├── analyzer.py        # AI 分析策略（短文档/长文档）
│   ├── builder.py         # Markdown 构建器（Builder 模式）
│   ├── classifier.py      # AI 分类器（工厂模式）
│   ├── metrics.py         # 指标采集器 + 断点检查点
│   └── dedup.py           # MD5 去重模块
├── tests/                 # 测试目录
├── logs/                  # 运行时日志（已加入 .gitignore）
│   ├── import.log         # 运行日志
│   ├── checkpoint.json    # 断点检查点
│   └── report_*.json      # 指标报告
├── README.md              # 本文档
├── 使用教程.md            # 详细使用教程
└── TEST_PLAN.md           # 测试验证计划
```

---

## 配置说明

编辑 `config.json`：

```json
{
    "ai": {
        "api_key": "sk-xxx",       // 你的 API key
        "model": "qwen3.6-flash",  // AI 模型
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"
    },
    "vault": {
        "path": "~/knowledge-base",  // Vault 目录
        "categories": ["芯片", "安全", "项目", "笔记", "其他"]  // 预设分类
    },
    "import": {
        "archive_dir": "_archive",       // 原始文件归档目录
        "failed_dir": "_failed",         // 失败文件目录
        "max_retries": 3,                // 最大重试次数
        "retry_delay": 2,                // 重试间隔（秒）
        "dedup": true,                   // MD5 去重开关
        "dedup_index": ".notemind_index.json"
    },
    "logging": {
        "level": "INFO",                 // 日志级别
        "file": "logs/import.log",       // 日志文件路径
        "log_dir": "logs"               // 日志目录
    }
}
```

---

## 使用场景

### 场景 1：每日资料收集

```bash
# 把今天下载的 PDF、截图、笔记放到一个目录
mkdir ~/today-input
cp ~/Downloads/*.pdf ~/today-input/
cp ~/Screenshots/*.png ~/today-input/

# 一键导入
./import.py --source ~/today-input

# 用 Obsidian 打开 ~/knowledge-base，查看 MOC.md
```

### 场景 2：批量历史资料整理

```bash
# 假如有 500 个历史文件
./import.py --source ~/old-documents --vault ~/knowledge-base

# 如果中途中断了，用 --resume 从断点继续
./import.py --source ~/old-documents --resume

# 预览模式先看看有多少文件
./import.py --source ~/old-documents --dry-run
```

### 场景 3：会议记录整理

```bash
# 会议截图 + 录音转录文本
./import.py --source ~/meeting-2026-04-29

# AI 自动识别图片内容（PPT 截图/白板/文档照片）
# 自动生成摘要和标签
```

### 场景 4：重复文件防护

```bash
# 第一次导入
./import.py --source ~/docs

# 第二次导入同一个目录（相同 MD5 的文件自动跳过）
./import.py --source ~/docs
# 输出: [SKIP] 重复文件: xxx.pdf (已存在于 项目/xxx.pdf)
```

### 场景 5：指定不同 Vault

```bash
# 工作资料
./import.py --source ~/work-docs --vault ~/work-knowledge

# 个人笔记
./import.py --source ~/personal --vault ~/personal-knowledge
```

### 场景 6：大批量文件 + 断点续传

```bash
# 处理上万文件时如果中断了，无需从头开始
./import.py --source ~/massive-collection --resume
# 输出: [恢复] 从检查点恢复，已处理 1234 个文件
# 输出: [恢复] 成功: 1200, 失败: 34

# 处理完成后可查看指标报告
cat logs/report_*.json | python3 -m json.tool
```

### 场景 7：查看处理报告

```bash
# 每次运行都会在 logs/ 目录生成报告
# 包含：处理时长、成功/失败数量、每个文件的详细耗时
ls logs/report_*.json
```

---

## Windows 使用指南

### 方法 1：WSL（推荐）

```powershell
# 1. 启用 WSL
wsl --install

# 2. 在 WSL 中运行
wsl
cd /mnt/c/Users/yourname/noteMind
chmod +x install.sh
./install.sh

# 3. 导入文件
./import.py --source /mnt/c/Users/yourname/Documents/inbox
```

### 方法 2：直接使用 Python（无需 WSL）

```powershell
# 1. 安装 Python 3.10+（从 python.org 或 Microsoft Store）

# 2. 打开 PowerShell，进入项目目录
cd C:\Users\yourname\noteMind

# 3. 编辑 config.json（用记事本或 VS Code）
notepad config.json

# 4. 运行导入
python import.py --source C:\Users\yourname\Documents\inbox

# 5. 用 Obsidian 打开 Vault（默认 %USERPROFILE%\knowledge-base）
```

### 方法 3：创建批处理文件

创建 `导入笔记.bat`：

```batch
@echo off
cd /d "%~dp0"
python import.py --source "%USERPROFILE%\Desktop\inbox"
pause
```

双击即可运行。

### Windows 可选依赖安装

```powershell
# PDF
pip install pymupdf

# Word
pip install python-docx

# PPT
pip install python-pptx

# Excel
pip install openpyxl
```

---

## 测试验证计划

详见 [TEST_PLAN.md](./TEST_PLAN.md)，包含：

| 测试类别 | 测试项 | 优先级 |
|----------|--------|--------|
| 功能测试 | 各格式解析 | P0 |
| 功能测试 | AI 图片识别 | P0 |
| 功能测试 | AI 摘要/标签/分类 | P0 |
| 功能测试 | MD5 去重 | P0 |
| 功能测试 | MOC 知识树更新 | P1 |
| 可靠性 | 重试机制 | P0 |
| 可靠性 | 失败文件隔离 | P1 |
| 可靠性 | 空文件处理 | P2 |
| 可靠性 | 大文件处理 | P1 |
| 稳定性 | 连续 10 次导入 | P1 |
| 稳定性 | API 超时/错误处理 | P0 |
| 边界条件 | 特殊字符文件名 | P2 |
| 边界条件 | 超大文件（100MB+） | P2 |
| 性能 | 100 文件批量导入耗时 | P2 |

---

## FAQ

**Q: 需要联网吗？**
A: 是的，AI 调用需要联网。文件解析是本地进行的。

**Q: API 调用会花很多钱吗？**
A: qwen3.6-flash 价格很低，通常每次调用几分钱。

**Q: 支持哪些图片格式？**
A: JPG、PNG、GIF、BMP、WebP、TIFF。

**Q: Vault 可以被多个设备同步吗？**
A: 可以，Vault 是纯 Markdown 文件夹，支持 iCloud、Git、Syncthing 等同步方式。

**Q: 可以自定义分类吗？**
A: 可以，编辑 `config.json` 中的 `categories` 数组即可。

**Q: 处理中断了怎么办？**
A: 用 `--resume` 参数重新启动，会从上次检查点继续处理已处理的文件不会重复处理。

**Q: 如何查看处理报告？**
A: 运行完成后查看 `logs/report_*.json`，包含每个文件的处理状态和耗时。

**Q: 长文档会怎么处理？**
A: 超过 3000 字或有 3 个以上章节的文档会自动按章节拆分，每章独立生成 AI 摘要。
