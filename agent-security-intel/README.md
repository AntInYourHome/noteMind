# agent-security-intel — AI Agent 安全 × 硬件抓手 每日情报

每日自动采集并分析 **AI 安全全栈情报**，按四层模型组织（总纲见 [docs/unified-map.md](docs/unified-map.md)）：

- **L1 模型层**：越狱/对抗/后门（OWASP LLM Top 10）
- **L2 Agent/AgentOS 层**：提示注入、MCP/技能供应链、治理（OWASP Agentic ASI01-10）
- **L3 硬件/基础设施层**：TEE 机密计算、GPU 攻击面、远程证明
- **L4 物理执行层**：车载安全 MCU/安全岛、VLA/具身智能、故障注入

生成中文 Markdown 情报报告并每日推送到 noteMind 仓库 `daily-intel` 分支。纯 Python 标准库实现，无第三方依赖。

## 快速开始

```bash
# 采集并生成今日报告（报告输出到 reports/intel-YYYY-MM-DD.md）
/e/python/python.exe scripts/collect.py

# 只导出原始数据（data/latest-items.json），适合接 LLM 做二段分析
/e/python/python.exe scripts/collect.py --json-only

# 跳过某些源（调试用）
/e/python/python.exe scripts/collect.py --skip-gh --skip-arxiv
```

> Windows 下必须使用 `/e/python/python.exe`（PATH 里的 `python` 是 Windows Store 存根）。
> 建议设置 `GITHUB_TOKEN` 环境变量以解除 GitHub API 匿名限流（60 次/时）。

## 目录结构

```
agent-security-intel/
├── config.json              # 数据源、关键词权重、watchlist、分类规则（改这里即可扩展）
├── scripts/
│   ├── collect.py           # 主采集器：GitHub + arXiv + RSS → 报告
│   ├── probe_gh.py          # 调试：GitHub 关键词搜索探针
│   ├── probe_watchlist.py   # 调试：watchlist 批量核查（404/迁移检测）
│   └── probe_feeds.py       # 调试：arXiv/RSS 连通性探针
├── reports/
│   └── intel-YYYY-MM-DD.md  # 每日情报报告
├── data/
│   ├── state.json           # 去重指纹 + 星标快照 + 热词历史（趋势对比依据）
│   ├── latest-items.json    # 本次采集的原始条目（结构化，可二次加工）
│   └── editor-notes.md      # 分析师点评（会被下一期报告引用）
└── docs/
    └── landscape.md         # 领域调研：攻击面模型 / OWASP ASI 框架 / 成熟项目分层 / 会议信号
```

## 报告结构

1. **⚡ 今日速览** — 按相关度自动挑选的 Top 条目
2. **📄 论文雷达** — arXiv 近 7 天，关键词加权排序
3. **🌱 GitHub 新星** — 近 14 天新建仓库，安全相关优先
4. **🔥 GitHub 活跃** — 近 7 天活跃存量项目
5. **⭐ Watchlist 动态** — 23 个成熟项目（promptfoo/garak/PyRIT/SkillSpector/agent-scan…）星增排序
6. **🛰️ 安全资讯** — 6 个 RSS 源 + Google News，相关度≥阈值
7. **🎪 会议·框架·产业** — OWASP ASI Top 10、MITRE ATLAS、Black Hat、DEF CON AI Village
8. **📈 趋势信号** — 热词频次 + 与上一期对比的升降
9. **🧠 分析师点评** — 人工/LLM 撰写（写入 `data/editor-notes.md`）

## 数据源机制（避坑说明）

- GitHub watchlist 用**一条 `repo:a/b repo:c/d …` 批量搜索**拉取全部仓库元数据，把 28 次核心 API 调用压缩为 1 次，规避匿名限流。
- GitHub 搜索关键词必须用**引号短语**（`"agent security"`），否则 `agent security` 会被拆词匹配出十几万条泛结果。
- arXiv 用 `submittedDate:[… TO …]` 时间窗 + 分类限定，避免全库检索。
- 跨源转载的同名新闻按标题去重，保留相关度最高的一条。
- 所有源失败均如实记录在报告附录「数据源状态」，不会静默丢弃。

## 扩展指南

- **加数据源**：`config.json` 的 `rss` 数组加 `{name, url}`；关键词权重加进 `keywords`。
- **加 watchlist**：先跑 `scripts/probe_watchlist.py` 核实仓库名（改名/删除很常见，如 mcp-scan→snyk/agent-scan）。
- **调阈值**：`report.news_min_score`（资讯过滤线）、`report.gh_min_score`（仓库安全相关线）。
- **接 LLM 分析**：读 `data/latest-items.json`（含 score/hits/tags 字段），生成摘要写入 `data/editor-notes.md`。

## 免责声明

本项目聚合公开安全情报，仅供安全研究与防御学习使用。
