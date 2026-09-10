# Prismor 技术拆解：Agent 运行时裁决是怎么做的

> 对象：[PrismorSec/prismor](https://github.com/PrismorSec/prismor)（Apache-2.0，Python，`pip install prismor`）
> 方法：直接读仓库源码与文档（2026-09-10 HEAD），本文只讲机制，不讲宣传。
> 定位：L2（AgentOS 运行时安全层）——四层模型见 [unified-map.md](unified-map.md)。

## 0. 它要堵的缺口

Prismor 的问题定义很准确：编码类 agent 执行 shell、读写文件、碰凭证、调外部 API，全程多步自治、检查点稀少。传统 OS/终端安全工具监控内核与文件系统——**等它们看见动作时，agent 已经决定做了**。缺口在 agent 层：要在"决定"与"执行"之间插一道闸。

## 1. 总体架构：四阶段流水线

每个工具调用走同一条路径：

```
Stage 1 集成面（入口） → Stage 2 执行前评估（裁决） → Stage 3 证据（防篡改） → [Stage 4 可选自托管控制面]
```

- **Stage 1**：调用从哪个门进来（hooks / MCP gateway / 框架 adapter / eval-server）；
- **Stage 2**：策略引擎 + 预执行检查 + 秘密/供应链保护，产出 allow / warn / block 裁决；
- **Stage 3**：会话存储（SQLite + JSONL）、Web/终端 dashboard、**hash chain + Ed25519 签名的防篡改证据链**；
- **Stage 4**（可选）：企业控制面下发**签名远程策略**，设备一旦注册（enroll），远程策略即权威——本地跑 observe 模式也越不出组织边界。

## 2. 关键设计一：多集成面 + 统一事件模型

没有单一拦截点能覆盖所有 agent，所以 Stage 1 故意开了六个门：

| 表面 | 管什么 | 拒绝 | 改写输入 | 脱敏输出 |
|---|---|:--:|:--:|:---:|
| Coding-agent hooks | agent 全部工具面（Claude Code/Codex/Cursor 等 13+） | ✓ | Claude/Qwen | ✗ |
| MCP gateway | 一个连接器后面的所有 MCP server，响应做注入扫描 | ✓ | ✓ | ✓ |
| Mirrored built-ins | 用 MCP 镜像 agent 自带的 Bash/Read/Write | ✓ | ✓ | ✓ |
| 框架 SDK adapter | 13 个框架（LangChain/CrewAI/OpenAI Agents/AutoGen…） | ✓ | ✗ | ✗ |
| eval-server | 非 Python 调用方/外部代理 | ✓ | ✓ | ✓ |
| inference-hook | 托管转录轮次的 webhook 通道 | ✓ | ✗ | ✗ |

核心机制：**每个表面把自己看到的东西规范化为同一个 canonical event，问同一个评估器要裁决**——规则写一次，动作无论从哪个门进来都同样生效。"改写/脱敏"能力差异是镜像存在的原因：pre-hook 只能*拒绝*一次文件读，而携带响应的表面可以*放行但把凭证打码后返回*。

一致性是被测试保证的，不是被宣称的：`tests/test_surface_conformance.py` 把同一动作重放进每个表面自己的 normalizer，裁决或规则不一致即失败。

裁决词汇表（`docs/decision-contract.md`）：`allow | block | step_up | defer | modify`。`defer` = 交给更深的语义评估器终裁；`modify` = 改写后放行。**Fail-closed**：无法执行自己裁决的表面选择拒绝——评估器不可达时默认阻断而非悄悄放行。

## 3. 关键设计二：策略引擎

YAML 规则，三个要点：

- **16 个内置阻断类别**：destructive_command、secret_exfiltration、secret_access、remote_execution、prompt_injection、prompt_injection_semantic、dos_resource_exhaustion、rce_canary、db_modification、privilege_escalation、skill_risk、persistence、security_bypass、dependency_risk、iam、reconnaissance——覆盖面本身就是一张 agent 攻击面清单。
- **分层策略**：org → project → repo，下层只能收紧不能放松，且存在**不可覆盖的底线规则**（non-overridable floor）。
- **逐规则 observe/enforce**：不是全局开关——可以"egress 观察、破坏性命令强制"混跑，这是灰度落地的正确粒度。

## 4. 关键设计三：egress 是"目的地驱动"的（本文最值得抄的设计）

把**每个**网络事件（WebFetch/WebSearch、远程 MCP 调用、每条 shell 命令）分解成具体目的地——任意 scheme 的 URL、`user@host:path`（git/scp）、curl/wget 的裸主机名、nc/telnet/socat 的 host:port——然后逐个过闸：

- 评估顺序：`deny`（首匹配即中）→ 私网豁免 → `allow` → `default`；
- `default: deny` + allowlist 是**边界**而非黑名单——黑名单只能挡住"有人想到要列"的外传终点，allowlist 把整个机群圈进你批准过的目的地；
- `resolve: true`：**把主机名重新解析到地址再查一遍**，防止用"给 metadata endpoint 起个好名字"绕过 deny 列表；且重解析只会收紧不会放松（公共域名解析到内网 IP 会变 deny，反之不会变 allow）；
- 云 metadata 端点（169.254.169.254 等）**永远不算私网**——直接堵死凭证窃取最经典的一条路。

这正是"裁决器解析器必须与工具解析器一致"的工程化：不比参数表面值，比解析后的真实目的地。

## 5. 关键设计四：混合语义注入防御

Regex 抓已知注入形态的壳，语义层补泛化能力：

1. 启发式预筛 <1ms 处理明显案例；
2. 不确定输入 **escalate 给 LLM judge，judge 拥有终裁权**——确认 regex 只看到一半的改写攻击，也放行只触发"权威声明"信号的无害文本；
3. 官方评测：800+ 用例，**+30% recall、零新增误报**（含改写攻击与文件内注入）。

与我们此前讨论的判定框架完全对应：结构化规则先行，LLM 只在不确定带做终裁，且 judge 的输入边界是被设计的（不吸收工具返回的自由文本）。

## 6. 关键设计五：秘密与供应链（canary + cloaking 是亮点）

- **Cloaking（遮蔽）**：把真实秘密替换为占位符给 agent 用，输出侧 scrub 还原——agent 全程见不到真值；配 env_guard 管 `PRISMOR_HOME` 之外的敏感环境变量。
- **Canary（诱饵）**：在 agent 踩点路径上埋"看起来像真凭证"的假文件（假 AWS key/假 SSH 私钥/假 .env），文件内含唯一标记串——与按文件名识别的 `secret_access` 规则不同，**canary 要求 agent 真的打开文件才命中**，文件名再普通也逃不掉；命中即 CRITICAL，并可向 webhook POST 防篡改载荷。这是把入侵检测的蜜罐思路搬进了 agent 运行时。
- **供应链**：npm/pip/cargo/go 依赖评分 + skill 扫描器 + 签名 advisory feed（自有情报 + NVD 合并，`pipeline/fetch_nvd_intel.py`）。

## 7. 关键设计六：证据链与学习闭环

- **防篡改**：hash chain + Ed25519 签名的事件流、attestation bundle、主机发现——block 争议可回溯审计；
- **Transcript 回放**：安装前的历史 transcript 可以过一遍当前策略——回答"如果早有这套规则，过去哪些动作会被拦"；
- **Learning**：从会话学习"建议规则"、标误报、检测规避行为——正面回应审批疲劳问题（规则越用越准，人只看真正异常的）；
- block 时打印 **narrowest-first 的解除步骤**（最小授权提示），而不是一句拒绝。

## 8. 我们的观察（L2 × 硬件抓手）

1. **裁决点全部在主机 OS 层**——hooks、gateway、adapter 都是与 agent 同权限域的用户态进程。前述三类绕过（拆闸/解析走私/TOCTOU）对它依然成立：注入成功的 agent 可以 `pkill prismor`、改 `.prismor/policy.yaml`、或利用裁决器与执行器解析不一致走私。
2. **但它已经把"可证明"做出来了**：hash chain + Ed25519 的证据链和签名远程策略，意味着策略与日志的完整性锚点只剩最后一步在 OS 里——**签名密钥与策略度量的锚点若下沉到 TEE/安全岛（硬件信任根），"裁决组件自身可信"就从密码学承诺升级为硬件承诺**。这是 Prismor 这类产品与 L3 硬件抓手最自然的接口，也是我们跟踪清单上值得盯的演进方向。
3. **16 个阻断类别 + egress 目的地模型 + canonical event** 是可直接复用的设计资产：无论最终裁决器跑在哪一层，"agent 动作规范化 + 目的地驱动外传控制 + 分层策略 + 逐规则灰度"这套语言已经收敛。

## 9. 快速评估

- 成熟度：早期（v0.x），但工程纪律好——surface conformance 测试、fail-closed 语义、决策契约文档化都是正确工程的味道；
- 未解问题：控制平面自身的防绕过只靠"隐藏 + 检测"（learning 检测规避），无强制隔离；judge 的模型供应链（用谁的 LLM 判）未讨论；多 agent/A2A 场景策略表达尚未展开；
- 与同日情报的 pipelock（egress 轴）、SkillSpector/mcp-triage（静态轴）拼起来，L2 运行时安全层的分工版图已经比较完整。

---
*调研基线：commit HEAD@2026-09-10；引用文件 `prismor/runtime/{policy_engine,canary,egress,semantic_guard,cloaking/}`、`docs/decision-contract.md`、`README.md`。*
