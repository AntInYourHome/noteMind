# 统一情报图谱：AI 安全 × AgentOS 安全 × 硬件抓手 × 具身/车载物理安全

> 更新日期：2026-09-08 ｜ 本文是情报体系的总纲：四层模型定义"看什么"，横切主线定义"怎么串"，每层数据源定义"从哪看"。

---

## 1. 四层模型：一条攻击链上的四个战场

一个现代 AI 系统的攻击链是**贯通的**：语义层攻击（提示注入）→ 劫持 Agent/AgentOS（工具滥用）→ 穿透基础设施（窃取密钥/权重）→ 最终落到物理执行（车辆/机器人动作）。情报按这四层组织：

| 层 | 战场 | 代表风险 | 参照框架 | 代表项目/事件 |
|---|---|---|---|---|
| **L1 模型层**（AI 安全） | 模型本身 | 越狱、对抗样本、后门、训练数据投毒、模型窃取 | OWASP LLM Top 10、MITRE ATLAS | garak、PyRIT、BadVLA 后门 |
| **L2 Agent/AgentOS 层** | 智能体平台与运行时 | 提示注入（间接）、工具滥用、MCP/技能供应链投毒、记忆投毒、过度授权、多 Agent 级联 | OWASP Agentic Top 10 (ASI01-10) | EchoLeak、GitHub Agentic Workflows 在野注入、SkillSpector、agent-scan |
| **L3 硬件/基础设施层**（硬件抓手） | 算力与信任根 | GPU 侧信道（LeftoverLocals）、Rowhammer 位翻转打权重、TEE 完整性绑定缺陷、证明链 | Confidential Computing、EVITA HSM | NVIDIA H100/BW CC、Apple PCC、OpenPcc、breaking-GPU-CC（BH26） |
| **L4 物理执行层**（具身/车载） | 消费端硬件 | 故障注入绕 secure boot、CAN injection 偷车、VLA 物理注入、传感器欺骗 | ISO/SAE 21434、UNECE R155、ISO 26262、SOTIF | Three Glitches、RH850 绕过、CAN 注入偷车潮 |

**情报视角的关键**：真正的"新"往往发生在**层间接口**——L2 的注入借助 L3 的侧信道外传（EchoLeak 的 markdown 图片链）、L1 的后门通过 L4 的动作落地（BadVLA）、L2 的供应链攻击以 L3 的证明缺失为前提（MCP 工具投毒无版本证明）。跨层条目在报告中以多标签呈现（如`侧信道攻击/汽车/具身`）。

## 2. 横切主线（分析时的四把尺子）

1. **最小代理权的硬件化**：L3 的密钥封存（varlock/TEE 内 MCP 能力封存）→ L4 的安全岛动作白名单。看任何防御新闻先问：它把什么"最终权限"锁进了不可绕过的层？
2. **供应链证明的贯通**：模型权重哈希 → Agent 技能扫描 → ECU 固件签名 → Uptane OTA。四个环节在各自社区独立演进，统一"可验证的软件物料链"是趋势。
3. **后果等级的跃迁**：L1/L2 偷数据 → L3 偷权重/IP → L4 直接物理伤害。情报评级应随后果等级加权（VLA 注入 > LLM 注入）。
4. **法规驱动的节奏差**：车载（R155 强制认证）> 云端 AI（EU AI Act 分阶段）> Agent 生态（OWASP 自律）。法规落地时点=产业采购时点，是情报的先行指标。

## 3. 各层情报源配置（对应 config.json）

| 层 | arXiv 检索词（节选） | GitHub 搜索/仓库（节选） | 资讯源 |
|---|---|---|---|
| L1+L2 | prompt injection、agent security、jailbreak、tool poisoning、MCP、guardrail | "agent security"/"MCP security" 新星；watchlist: garak/PyRIT/promptfoo/agentdojo/SkillSpector/agent-scan/governance-toolkit/mcp servers | THN/DarkReading/GoogleNews-AI 安全 |
| L3 | confidential computing、GPU TEE、rowhammer、attestation | "confidential inference"/"GPU TEE" 新星；watchlist: hopper-llm-benchmark/cc-repo/breaking-gpu-cc | GoogleNews-硬件 AI 安全/硬件漏洞 |
| L4 | vision-language-action、fault injection、CAN bus、sensor spoofing、Uptane | "automotive security"/"VLA security" 新星；watchlist: openpilot/Autoware/CaringCaribou/RVD/uptane-standard | GoogleNews-汽车网络安全/具身智能机器人 |

常设目录（报告"会议·框架"节）：OWASP Agentic Top 10 + LLM Top 10、MITRE ATLAS、CCC、Apple PCC、NVIDIA CC、escar、Uptane、Black Hat AI Summit、VLA Safety 综述、CC-for-Agentic-AI 综述。

## 4. 四层×风险映射速查（补齐后的覆盖检查）

| OWASP ASI 风险 | L1 模型 | L2 AgentOS | L3 硬件 | L4 物理 |
|---|---|---|---|---|
| ASI01 目标劫持/注入 | 越狱研究 | 间接注入（在野） | ✗（语义盲区） | VLA 物理注入；安全岛兜底 |
| ASI02 工具滥用 | — | MCP 投毒、过度授权 | TEE 能力封存 | 动作白名单 |
| ASI03 身份/密钥 | — | NHI 凭证滥用 | 硬件绑定密钥 | HSM/EVITA |
| ASI04 供应链 | 权重投毒 | 技能/MCP 投毒 | 远程证明 | Uptane/secure boot（可被 FI 绕过） |
| ASI05 资源耗尽 | — | 预算耗尽 | — | — |
| 记忆投毒 | 训练数据投毒 | Agent 记忆投毒 | 内存完整性（ECC/MTE） | — |
| 级联/失控 | 对齐失败 | 多 Agent 级联 | — | 安全岛监控/E-stop |

覆盖结论：**四层各有独立数据源与关键词，情报缺口已补齐**；唯一长期留白是 ASI05 与"治理类"风险（依赖法规动态跟踪）。

## 5. 分析师工作法（每日报告怎么读）

1. 先看**跨层条目**（多标签）——层间接口的新攻击/新防御价值最高；
2. 用四把尺子归位：权限？证明？后果等级？法规节点？
3. 热词趋势对照 §2 主线——`prompt injection` 升 = L2 加热；`fault injection` 升 = L4 攻击侧加热；`attestation` 升 = 供应链证明落地前兆。
