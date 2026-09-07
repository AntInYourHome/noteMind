# AI Agent / AgentOS 安全：生态调研与情报体系设计

> 调研日期：2026-09-07 ｜ 方式：GitHub API 实测 + arXiv 检索 + Black Hat/产业资料分析
> 本文回答三个问题：攻击面长什么样（模型）、谁在做且做得成熟（项目）、如何持续跟踪（情报体系）。

---

## 1. 攻击面模型：Agent ≠ 应用，安全边界完全重构

一个 Agent = **LLM + 工具（MCP）+ 记忆 + 身份 + 通信**。相比传统应用，它把"不可信输入"直接接入"特权执行"，核心新攻击面：

| 攻击面 | 典型技术 | 代表案例 |
|---|---|---|
| 提示注入（直接/间接） | 邮件/网页/文档中嵌入指令 | **EchoLeak (CVE-2025-32711)**：全球首个 AI 代理零点击漏洞，邮件→M365 Copilot RAG 检索→markdown 图片外传数据 |
| 工具滥用 / 过度授权 | 诱导 Agent 用合法工具做恶意输出 | OWASP ASI02 引用的 Amazon Q 事件 |
| 技能/MCP 供应链投毒 | tool description 藏毒、恶意 skill 文件 | MCP tool poisoning；Black Hat 2026 "weaponized web content" 议题 |
| 身份与权限滥用 | 非人类身份（NHI）、静态凭证、权限过大 | ASI03；业界提出"From Least Privilege to Least Agency" |
| 记忆投毒 | 污染长期记忆影响后续行为 | ASI 风险项；OpenClaw LLM 投毒漏洞（Dark Reading 2026-09） |
| 多智能体协作 | A2A 消息注入、级联失败、rogue agents | ASI 级联失败/失控 Agent 条目 |
| GUI / Computer-Use | 视觉提示注入、屏幕内容操纵 | Yuxuan2003/Awesome-GUI-Agent-Security 论文清单（中文） |
| 资源耗尽 | 预算/算力/API 配额耗尽 | ASI05 Resource Overload |

**关键认知**：2026 年 9 月的最新在野情报显示，提示注入已从"学术攻击"进入**实战供应链利用**阶段——GitHub Agentic Workflows 的提示注入漏洞被发现主动利用（Rescana/SecurityWeek 告警），恶意 `.git` 配置可让 Claude Code/Codex/Cursor 在开发者机器上执行任意命令（Manifold Security，8 个漏洞）。

## 2. 参照框架：以 OWASP ASI01–ASI10 为主分类轴

| 框架 | 用途 |
|---|---|
| [OWASP Agentic Applications Top 10 (2026)](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/)（ASI01–ASI10，2025-12 发布） | 智能体安全风险的主分类轴：目标劫持、工具滥用、身份滥用、供应链、资源耗尽、记忆投毒、权限妥协、级联失败、不安全智能体通信、失控 Agent |
| [OWASP GenAI LLM Top 10 (2026)](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/) | 单体 LLM 应用层风险（提示注入仍是 LLM01） |
| [MITRE ATLAS](https://atlas.mitre.org/) | 针对 AI 系统的攻击战术/技术知识库（类 ATT&CK），用于攻击技术画像 |
| NIST AI RMF + GenAI Profile | 治理与合规对标 |

微软 [agent-governance-toolkit](https://github.com/microsoft/agent-governance-toolkit) 宣称覆盖 OWASP Agentic Top 10 全部 10 项，可作为"框架→工程控制"映射的参考实现。

## 3. GitHub 成熟项目分层（2026-09-07 星数快照，均经 API 核实）

### 3.1 攻击评估 / AI 红队（先于攻击者发现问题）
- **promptfoo**（24.9k⭐）— 提示/Agent/RAG 红队测试与 CI 集成，事实上的工程标配
- **NVIDIA/garak**（9.1k⭐）— LLM 漏洞扫描器（探测器插件体系）
- **microsoft/PyRIT**（4.4k⭐）— 微软生成式 AI 风险识别框架，自动化红队 pipeline
- **msoedov/agentic_security**（2.0k⭐）— Agentic 漏洞扫描/红队工具包
- **elder-plinius/T3MP3ST**（6.0k⭐）— 自主红队元框架；**0x4m4/hexstrike-ai**（11.6k⭐）— 让 Agent 自主调用 100+ 进攻工具的 MCP 服务器（攻防两用）

### 3.2 运行时防护（Guardrails / 防火墙）
- **guardrails-ai**（7.4k⭐）/ **NVIDIA-NeMo/Guardrails**（7.1k⭐）— 可编程护栏双雄
- **protectai/llm-guard**（3.2k⭐）— LLM 输入输出安全工具箱
- **luckyPipewrench/pipelock**（835⭐）— Agent 防火墙：扫描 MCP/A2A/HTTP 出口流量，防外传/SSRF/提示注入
- **dmno-dev/varlock**（4.4k⭐）— "AI 安全的 .env"：Agent 密钥隔离
- **superagent-ai/superagent**（6.7k⭐）— 防提示注入/数据泄露的防护 API

### 3.3 供应链与技能扫描（AgentOS 时代的 SAST）
- **NVIDIA/SkillSpector**（16.5k⭐）— 安装前扫描 Claude Code/Codex/MCP 技能：漏洞、恶意模式、提示注入、数据外传
- **snyk/agent-scan**（3.0k⭐，原 invariantlabs-ai/mcp-scan）— Agent/MCP/技能安全扫描器
- **Tencent/AI-Infra-Guard**（6.2k⭐）— 腾讯全栈 AI 红队平台：Agent Scan / Skills Scan / MCP Scan / 越狱评测

### 3.4 治理与身份
- **microsoft/agent-governance-toolkit**（6.2k⭐）— 策略执行、零信任身份、执行沙箱
- **TracecatHQ/tracecat**（3.8k⭐）— 面向团队与 Agent 的安全自动化
- **Noma**（商业）— 企业级 Agent/MCP 访问控制（2026-09 发布）

### 3.5 评测基准与观测
- **ethz-spylab/agentdojo**（807⭐）— LLM Agent 攻防动态评测环境（提示注入防御基准）
- **langfuse**（34.3k⭐）/ **helicone**（6.1k⭐）/ **AgentOps**（5.8k⭐）— 观测与评测平台（安全审计的数据底座）

### 3.6 情报与知识库型仓库（跟情报最相关）
- **webpro255/awesome-ai-agent-attacks** — 2024-2026 真实 Agent 安全事件时间线（每条有出处）
- **mukul975/Anthropic-Cybersecurity-Skills**（32.3k⭐）— 817 个网络安全技能映射 MITRE ATT&CK/ATLAS/NIST 等 6 大框架
- **Yuxuan2003/Awesome-GUI-Agent-Security**（中文）— GUI/Computer-Use/Browser Agent 安全论文清单

## 4. 会议与产业信号（Black Hat USA 2026，2026-08 闭幕）

- AI Agent 是绝对主题：[AI Summit](https://blackhat.com/us-26/ai-summit.html) + 大量 Agent 议题；Dark Reading 总结"Agentic AI Risks 渗透全场"
- [Zenity 回顾](https://zenity.io/blog/ai-agent-security-black-hat-recap)：**Agent 供应链（技能文件、MCP 服务器）、错位模型、武器化网页内容**是攻击者新弹药
- 防御产业化加速：OpenAI 发布《Designing AI agents to resist prompt injection》；Menlo Security 把 MARS 扩展到 Copilot/Claude Code/Gemini in Chrome；promptfoo 在 OpenAI 展位现场演示注入与越狱
- 训练侧：AppSecEngineer 等推出"AI Agent Security Masterclass"（用真实 MCP 服务器与 RAG 管线演练攻防）

## 5. 情报体系设计（本项目工具的依据）

**五类数据源 → 统一评分 → 五维报告 → 趋势对比 → 分析师点评**：

| 维度 | 数据源 | 频率 |
|---|---|---|
| 论文雷达 | arXiv cs.CR/cs.AI/cs.CL × 11 组关键词，7 天窗口 | 每日 |
| GitHub 新星/活跃 | 6 组安全精确搜索（引号短语限定，过滤泛 Agent 噪音） | 每日 |
| 成熟项目 Watchlist | 23 个分层仓库，批量 `repo:` 搜索一次拉取（省配额），星增追踪 | 每日 |
| 安全资讯 | THN/BleepingComputer/DarkReading/SecurityWeek/Schneier + Google News AI 安全查询，关键词加权过滤 | 每日 |
| 会议/框架 | OWASP/MITRE ATLAS/Black Hat/DEF CON AI Village 常设目录 | 常设 |

评分机制：关键词权重（提示注入=6，MCP=5，越狱=4……）→ 相关度分 → 分类标签（攻击/防御/评测/治理/事件）→ 各版块按相关度排序；同事件跨源转载按标题去重。GitHub 搜索用**引号短语 + `created:`/`pushed:` 时间窗**，实测能把"agent security"从 18 万条泛匹配收敛到数百条精准结果。

## 6. 跟进建议

1. **设 `GITHUB_TOKEN` 环境变量**：未认证 IP 级配额（60 次/时）在批量采集时会被限流；当前工具已用批量搜索把核心调用压缩到 1 次，但设 token 后可加密度。
2. 增加研究博客源：Zenity、Invariant Labs、Wiz AI 研究、Anthropic/OpenAI 安全博客（RSS 均可用）。
3. 引入 LLM 做二段分析：对 `data/latest-items.json` 做聚类摘要，把"条目列表"升级为"叙事情报"。
4. 对 watchlist 增加 release/commit 频次维度，识别"突然加速"的项目（新攻击工具的早期信号）。
