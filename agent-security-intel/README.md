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
py scripts/collect.py

# 只导出原始数据（data/latest-items.json），适合接 LLM 做二段分析
py scripts/collect.py --json-only

# 跳过某些源（调试用）
py scripts/collect.py --skip-gh --skip-arxiv

# 把 LLM 分析（data/analysis.json）填入今日报告（幂等，可重复调用）
py scripts/collect.py --apply-analysis data/analysis.json

# 仓库内一键同步（切 daily-intel 分支+采集 / 提交推送）
bash scripts/sync_intel.sh collect
bash scripts/sync_intel.sh publish
```

> Windows 下使用 `py` 启动 Python（PATH 里的 `python` 是 Windows Store 存根）。
> 建议设置 `GITHUB_TOKEN` 环境变量以解除 GitHub API 匿名限流（60 次/时）。

## 目录结构

```
agent-security-intel/
├── config.json              # 数据源、关键词权重、watchlist、精读清单、分类规则（改这里即可扩展）
├── scripts/
│   ├── collect.py           # 主采集器：GitHub + arXiv + RSS + 经典项目精读 → 报告
│   ├── sync_intel.sh        # 仓库内同步：collect（切分支+采集）/ publish（提交+推送）
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

1. **🎯 今日要点（Top 10）** — 全部条目按综合关键度统一排序（相关度+跨层+顶会接收+新信号）：第 1 名附深度分析（是什么/技术机制/证据强度/四层定位/影响与对策），第 2-10 名逐条一句话简评
2. **📊 其余雷达（数字摘要）** — 论文/顶会/新星/活跃/watchlist/精读/资讯的计数一览；完整结构化数据在 `data/latest-items.json`
3. **📈 趋势信号** — 热词频次 + 与上一期对比的升降
4. **🧠 分析师点评** — 自动化流水线写入 `data/analysis.json` 后经 `--apply-analysis` 幂等填充

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
