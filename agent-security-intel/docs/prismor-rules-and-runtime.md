# Prismor 运行机制与规则全集：框架怎么跑、规则怎么写

> 对象：[PrismorSec/prismor](https://github.com/PrismorSec/prismor) HEAD@2026-09-10。
> 本文回答两个问题：**① 框架怎么运行（完整调用链）；② 81 条内置规则长什么样（全清单 + 典型案例精讲）**。
> 姊妹篇：[Prismor 拆解](prismor-runtime-enforcement.md)（架构总览）、[安全硬件强制方案](hardware-enforcement-scheme.md)（下沉推导）。

---

## 一、框架怎么运行：一次工具调用的完整旅程

### 1.1 安装时：把裁决器"焊"进 agent 配置

`prismor setup` 调 `install_hooks()`（hooks.py），向每个 agent 的配置文件**写入一个分发 shim**（dispatch shim）——一段指向 prismor 入口的命令。对 Claude Code 写进 `settings.json` 的 hooks 段，对 Codex 写 TOML（还要先开启其 hooks feature flag），对 Cursor/Windsurf/Copilot/Grok/Kiro/OpenClaw/OpenCode/Hermes 各有对应的 merge 函数（`_merge_claude/_merge_codex/_merge_copilot/...`）。卸载对称（`uninstall_hooks` + `_strip_*` 按 marker 清理）。**框架不改 agent 代码，只占住框架预留的 PreToolUse 检查点。**

### 1.2 运行时调用链（六步）

```
agent 发起工具调用
  ① hook 触发：agent 框架把 payload（stdin JSON）交给 shim → prismor 入口
  ② 规范化 normalize_payload()：各家方言 → canonical event（见 1.3）
  ③ 策略评估 PolicyEngine.evaluate()：
       CompiledRule 逐条匹配：event_types 过滤 → 字段提取（_extract_fields）
       → 文本归一化（_normalize_command / _fold_confusables / 不可见字符检测）
       → 正则 patterns 匹配 → 可选条件表达式（any_of/all_of/n_of 编译成 AST 求值）
       → 产出 findings；blocking finding 决定 verdict
  ④ 增强检查（与 ③ 并行/级联）：
       egress：extract_destinations() 把事件分解为目的地列表逐个过闸
                （deny→私网→allow→default；DNS 重解析只收紧不放松）
       semantic guard：正则不确定带 → 启发式评分（40+ 信号加权，≥0.75 block）
                → 可选升级 LLM judge（litellm 路由 haiku/gpt-4o-mini）
       canary：读文件命中 PRISMOR-CANARY- 标记 → CRITICAL + webhook
       污点：_TaintStore 标记"不可信来源数据 → 敏感动作"的流
  ⑤ 裁决返回：verdict ∈ {allow, block, step_up, defer, modify}
       —— hook 路径只能 allow/block（拒绝原样执行）
       —— 携带响应的表面（MCP gateway/mirror）可 modify：改写参数或脱敏输出
       —— block 附带"最窄优先"的解除步骤提示
       —— fail-closed：评估器不可达 → 默认阻断
  ⑥ 证据落盘：sinks.py → 每条裁决进 SQLite+JSONL 会话库；
       遥测走 hash chain（sha256(canonical_json(fields+seq+prev_hash))，
       链状态在 ~/.prismor/telemetry_chain.json，fcntl 锁序列化并发）
```

### 1.3 规范化：canonical event 是规则的载体

每个 agent 一条 `_normalize_<agent>()`（copilot/codex/grok/kiro/claude/...），统一输出：

```python
{ "ts", "session_id", "agent", "agent_event": "PreToolUse",
  "type": "shell" | "file_read" | "file_write" | "network" | "prompt"
          | "mcp" | "tool_result" | "skill_manifest" | "memory",
  <type 对应载荷字段>,                     # shell→command, file_write→path+content
  "metadata": {"cwd", "tool_name", "raw": 原始 payload} }
```

规则只写在 `type + 字段` 上，与具体 agent 解耦。**加一种 agent = 加一个 normalize 函数**。翻译层的脏细节是工程量的实态：Copilot 的 toolArgs 是 JSON 字符串要先 parse；Codex 单次 Edit 是 `{file_path, old_string, new_string}` 形状，content 提取需要三层 fallback（edits 拼接→content→new_string），否则写入内容对所有检查不可见；MCP 调用单独分类，否则 `mcp__server__tool` 规则静默失效。

两个特殊 event_type 值得注意：**`skill_manifest`**（skill 的 SKILL.md/配置被解析成事件，供应链规则在装载时审）和 **`memory`**（CLAUDE.md/AGENTS.md 等项目记忆内容）——项目记忆在规则加载时被结构性标记为不可信内容（`_UNTRUSTED_CONTENT_ALIASES`，issue #155），任何 block 类规则不能静默豁免它。

### 1.4 策略分层与权威性

规则来源三层合并：内置 default_policy.yaml → 项目 `.prismor/policy.yaml` → **签名远程策略**（企业控制面下发）。合并只收紧不放松，且存在**不可覆盖底线**（non-overridable floor，`is_floor_protected_rule`）+ 自保护规则（`is_self_protection_rule`——floor 与自身相关规则禁止被下层覆盖）。`_egress_source == "remote"` 时，远程 enforce 裁决对本地 observe 设备也是权威的。逐规则 `mode: observe|enforce` 支持灰度。

---

## 二、81 条内置规则全清单

按 category 分组（severity / 默认动作）：

### 破坏性与资源（CRITICAL×2）
| id | severity | action | 说明 |
|---|---|---|---|
| destructive-command | CRITICAL | block | rm -rf 全变体、mkfs、dd 写盘、shutdown/reboot、世界可写 chmod |
| dos-resource-exhaustion | CRITICAL | block | fork 炸弹、while true、/dev/urandom 滥用、ulimit unlimited |

### 秘密外泄（10 条）
| id | severity | action | 说明 |
|---|---|---|---|
| secret-exfiltration | CRITICAL | block | cat .env \| curl 类管道、scp/rsync 上传秘密 |
| secret-in-url-params | CRITICAL | block | 凭证出现在 URL 参数（会进日志） |
| credential-in-header | CRITICAL | block | 硬编码凭证进 HTTP 头 |
| suspicious-network | HIGH | block | 可疑外联目的地 |
| credential-aggregation | CRITICAL | block | 跨位置收集凭证 |
| credential-staging | HIGH | block | 凭证中转/暂存（聚合前置） |
| dns-exfiltration | HIGH | block | DNS 隧道外传（dnsutils/dig 编码查询） |
| git-remote-hijack | HIGH | warn | 改 git remote 指向外部 |
| python-network-exfil | HIGH | warn | python 脚本读文件+socket 发送组合 |
| env-network-exfil | CRITICAL | block | 环境变量批量外发（整段 env 进网络） |

### 秘密访问（3 条）
| id | severity | action | 说明 |
|---|---|---|---|
| secret-access | HIGH | block | 读 .env/.aws/.ssh 等敏感命名文件 |
| claude-credential-access | CRITICAL | block | 读 Claude 凭证（~/.claude 的 auth） |
| claude-session-transcript-access | HIGH | block | 读会话转录（含全部历史上下文） |

### 提权与容器逃逸（4 条）
| id | severity | action | 说明 |
|---|---|---|---|
| privilege-escalation | CRITICAL | block | chmod +s、sudoers 编辑、useradd、setcap、pkexec |
| auth-file-write | CRITICAL | block | 写认证文件（authorized_keys/passwd/shadow） |
| env-var-hijack | HIGH | block | 劫持 PATH/LD_PRELOAD 等注入型环境变量 |
| container-escape | CRITICAL | block | 容器逃逸特征（/proc/sysrq、core_pattern、fd 重挂载宿主） |

### RCE / 反向 shell / 混淆（3 条）
| id | severity | action | 说明 |
|---|---|---|---|
| rce-canary | CRITICAL | block | /dev/tcp、nc -lvp、echo\|crontab、python -c exec、mkfifo+sh |
| python-reverse-shell | CRITICAL | block | python socket+subprocess 反弹组合 |
| shell-obfuscation | CRITICAL | block | base64\|bash、eval 拼接、$() 嵌套、十六进制解码执行 |

### 提示注入（3 条）
| id | severity | action | 说明 |
|---|---|---|---|
| prompt-injection | HIGH | block | 指令覆盖、系统提示词提取、隐蔽外传指令（详见案例 4） |
| prompt-injection-hidden | CRITICAL | block | 隐藏信道注入（不可见字符、零宽、HTML 注释藏指令） |
| bulk-pii-exfiltration | MEDIUM | warn | 整表 PII 提取话术（误报高只 warn） |

### 远程执行（3 条）
| id | severity | action | 说明 |
|---|---|---|---|
| remote-execution | HIGH | block | ssh 远程执行命令 |
| fetch-then-execute | HIGH | block | 下载即执行（curl\|bash 全家） |
| package-registry-poisoning | HIGH | warn | 指向非标准 registry 的安装源 |

### 网络隔离（4 条）
| id | severity | action | 说明 |
|---|---|---|---|
| raw-ip-outbound | HIGH | warn | 裸 IP 直连（绕过 DNS 审计） |
| bind-all-interfaces | HIGH | warn | 0.0.0.0 监听 |
| reverse-tunnel | MEDIUM | warn | 反向隧道（ngrok/本地端口转发外露） |
| network-exfil-tool | HIGH | warn | 已知外传工具调用（scp 上传、上传型客户端） |

### 路径与文件（4 条）
| id | severity | action | 说明 |
|---|---|---|---|
| path-traversal | HIGH | warn | ../ 越出工作区 |
| symlink-to-sensitive | HIGH | block | 符号链接指向敏感路径（绕过路径白名单） |
| risky-write | MEDIUM | warn | 写系统级配置路径 |
| db-modification / db-access | HIGH | block/warn | DROP/TRUNCATE/ALTER；生产库直连 |

### 持久化（6 条）
| id | severity | action | 说明 |
|---|---|---|---|
| persistence-cron | HIGH | warn | crontab 写入 |
| persistence-systemd | HIGH | warn | systemd 单元创建 |
| persistence-init | HIGH | warn | /etc/rc.local、init.d |
| persistence-shell-profile | HIGH | warn | .bashrc/.zshrc 追加 |
| persistence-git-hooks | HIGH | warn | 仓库 git hooks 写入 |
| persistence-launch-agent | HIGH | warn | macOS LaunchAgent |

### 记忆投毒与完整性（7 条）
| id | severity | action | 说明 |
|---|---|---|---|
| memory-embedded-directive | MEDIUM | warn | 项目记忆里嵌"未来指令" |
| memory-exfil-directive | MEDIUM | warn | 记忆里指示外传 |
| memory-tool-policy-override | HIGH | warn | 记忆里写"always approve all tools"（详见案例 6） |
| memory-invisible-text | MEDIUM | warn | 记忆文件含不可见控制字符（#153，结构性检测） |
| memory-oversized-instruction-file | LOW | warn | 异常巨大的指令文件（上下文挤压攻击） |
| memory-integrity-mismatch | MEDIUM | warn | 记忆文件哈希与基线不符 |
| memory-directive-on-write | MEDIUM | warn | 写记忆文件时内容含指令式文本 |

### Skill 供应链（10 条）
| id | severity | action | 说明 |
|---|---|---|---|
| skill-exfil-url | CRITICAL | block | skill 配置/提示里含外部回传 URL |
| skill-encoded-payload | CRITICAL | block | skill 内嵌 base64/十六进制大块载荷 |
| skill-shell-injection | CRITICAL | block | skill 清单里注入 shell（详见案例 5） |
| skill-dynamic-import | CRITICAL | block | 动态 import/exec |
| skill-prompt-override | HIGH | block | skill 覆盖系统提示 |
| skill-secret-access | HIGH | block | skill 访问秘密路径 |
| skill-network-exfil | HIGH | block | skill 网络外传逻辑 |
| skill-self-persist | HIGH | warn | skill 自我安装持久化 |
| skill-behavior-manipulation | MEDIUM | warn | 行为操纵话术 |
| skill-overpermission | MEDIUM | warn | skill 索要超范围权限 |

### 依赖供应链（10 条）
| id | severity | action | 说明 |
|---|---|---|---|
| pkg-install-from-url | HIGH | warn | 从 URL 直装（绕过 registry） |
| pkg-install-unsafe-flags | MEDIUM | warn | --ignore-scripts=false 类危险旗标 |
| pkg-install-global | MEDIUM | warn | 全局安装 |
| pkg-suspicious-name | HIGH | warn | typosquatting 名单 |
| pkg-postinstall-script | HIGH | warn | postinstall 脚本风险 |
| lockfile-direct-edit | HIGH | warn | 手改锁文件 |
| lockfile-deletion | HIGH | **block** | 删锁文件（后续投毒无对账基准） |
| dependency-confusion | HIGH | warn | 内部包名被外部源抢占安装 |
| npm-git-install | HIGH | warn | git URL 安装 npm 包 |
| execute-vendored-script | HIGH | **block** | 执行仓库内来路不明脚本 |

### 侦察（2 条）
| id | severity | action | 说明 |
|---|---|---|---|
| cloud-metadata-ssrf | CRITICAL | block | 探测 169.254.169.254 云凭证端点 |
| mcp-arg-metadata-endpoint | CRITICAL | block | MCP 参数里指向 metadata 端点 |

### 安全自保护（7 条——框架知道自己是靶子）
| id | severity | action | 说明 |
|---|---|---|---|
| agent-config-tampering / -path | CRITICAL | block | 改 agent 配置文件（注入/去防护） |
| prismor-self-edit | CRITICAL | block | **改 Prismor 自己的策略/配置** |
| audit-trail-tampering | CRITICAL | block | 删/改审计记录与链状态文件 |
| disable-security-controls | HIGH | block | 停用各类安全组件（EDR/auditd/apparmor） |
| tls-verification-disabled | HIGH | warn | curl -k / NODE_TLS_REJECT_UNAUTHORIZED |
| agent-instruction-tampering | HIGH | warn | 改 agent 指令文件 |

### 其他
| id | severity | action | 说明 |
|---|---|---|---|
| pii-exposure | HIGH | warn | 输出含 PII 数据类 |
| model-manipulation | HIGH | warn | 温度/采样参数被异常调高（越狱前置） |

---

## 三、典型案例精讲（六条）

### 案例 1：destructive-command —— 一条规则里的防误报工程

`rm -rf` 的正则要覆盖 flag 的**全部排列**：`-rf / -fr / -r -f / -f -r / --recursive --force / --force --recursive`（用先行断言 `(?=...)` 一次性匹配），目标分五档：根 `/`、系统目录（/etc|bin|boot|sys|proc...）、用户目录顶层（/home|/var|/usr...）、`$HOME` 与 `~`、通配符 `*`、父目录链 `../..`——每档误报代价不同所以分开写。`sudo rm` 无条件加权。

**防误报的关键技法是"命令位置锚定"**：`mkfs/shutdown/reboot` 必须出现在行首、shell 分隔符（`; && || |`）之后、或 `sudo/doas/systemctl` 之后——否则 `git commit -m "graceful shutdown handler"`、`npm run reboot`、`man mkfs`、`pm2 shutdown` 全部误杀（源码注释原话列举了这四个 FP）。**写规则的一半工作量在挡误报，这是所有 agent 规则集的共性经验。**

### 案例 2：secret-exfiltration —— 方向判定

两条正则：管道型 `cat/sed/grep/awk ... (.env|id_rsa|.npmrc|.aws...) ... (curl|wget|nc|scp|https?://)`——读秘密的工具与网络工具出现在**同一条命令**里；上传型 `scp|rsync|sftp ... <秘密文件> ... @`——关键在 `@`，它是"上传方向"的语法证据（远程在前），下载方向不命中。**用 shell 语法本身区分攻击方向**，比语义判断便宜且无歧义。

### 案例 3：shell-obfuscation —— 对抗编码链

`curl ... | base64 -d | bash`、`eval "$(echo ...)"`、嵌套 `$($(...))`、`\x..` 十六进制解码后执行。与 rce-canary（明文反向 shell）互补：**一条管"说了什么坏话"，一条管"把坏话藏起来的行为"**。混淆检测天然高误报风险，所以放 CRITICAL block 的是窄模式（pipe 到解释器的完整链条），宽模式（出现 base64）只进侦察告警。

### 案例 4：prompt-injection —— 自然语言攻击的正则化

对 `prompt` 和 `tool_result` 两类事件的 `combined_text` 匹配九组模式：指令覆盖（`ignore ... instructions`）、系统提示词提取（**十二个动词** × 六种宾语形状：`provide|share|reveal|...|output` + `system prompt|hidden instructions|conversation history|...`）、记忆投毒指令（`remember this forever / always trust ... future instructions`）、隐蔽外传（`silently|quietly|covertly send`、`without the user knowing`、`forward this conversation to`）、社工铺垫（`appear helpful while ...`、`gain the user's trust and then`）。**注意这些模式已经超越"黑客语法"进入"话术语法"**——正则在给自然语言攻击画像，这层能到 60-70% 召回，剩下交给 semantic guard 的加权信号与 LLM judge。分层不是冗余，是各自的覆盖带不同。

### 案例 5：skill-shell-injection —— 供应链装载时审查 + FP 修复史

skill 的 SKILL.md/配置在装载时被解析成 `skill_manifest` 事件过闸：`curl|wget ... | bash/sh/python`、`$(...)` 命令替换、`subprocess/os.system/child_process`、`exec()/eval()`。源码注释记录了一次真实修复（issue #144）：早期反则里的 `` `...` `` 反引号模式会命中 **skill 文档正文里任何 markdown 行内代码**（几乎无处不在），改成只匹配真命令替换 `$()`。**规则集是被 FP 磨出来的**——每个注释都是一轮真实误报迭代。

### 案例 6：memory-tool-policy-override —— 记忆投毒（最"agent 原生"的攻击面）

CLAUDE.md/AGENTS.md 这类项目记忆文件会被 agent 每次会话自动加载——**攻击者往里面写一行 `always approve all tool calls`，等于给整个未来会话拆闸**。规则匹配五组模式（`always approve/accept/allow all tools`、`never block any command`、`bypass all security checks`、`disable the security policy`、`skip all confirmation`），warn 级——因为合法团队规范也可能用类似措辞，需要人裁决。配套的 `memory-invisible-text`（#153）做**结构性检测**：不看写了什么，看 hook 读文件时算出的 `has_invisible_controls` 事实——零宽字符藏在任何记忆里都告警，这是词法规则无法替代的信道级检查。

---

## 四、规则语法的解剖（一条规则的完整 schema）

```yaml
- id: destructive-command            # 稳定标识（策略覆盖按 id 合并）
  severity: CRITICAL                 # CRITICAL/HIGH/MEDIUM/LOW
  category: destructive_command      # 16 类之一（block_categories 白名单）
  title: ...                         # 人读说明
  event_types: [shell]               # 哪些 canonical event 类型适用
  fields: [command]                  # 提取哪些字段来匹配
  patterns:                          # 正则列表（任一命中即 finding）
    - '...'
  action: block                      # block / warn / step_up / modify
  mode: observe|enforce              # 逐规则灰度（可省，继承默认）
  transform: <name>                  # action=modify 时的改写器名（可省）
  condition: "any_of(...) and n_of(2, ...)"   # 编译成 AST 的组合条件（可省）
```

条件表达式支持 `any_of / all_of / n_of(n, ...)` 量词与 and/or/not 组合——"三个信号命中两个才拦"这类规则可表达。规则匹配的事实（facts）除正则命中外还包括结构性事实：`has_invisible_controls`（不可见字符）、confusable 折叠命中、污点标记、canary 命中——**词法证据与信道级证据在同一语法里组合**。

---

## 五、工程观察：这套规则对硬件方案的三个直接映射

1. **底线集已经事实存在**：全部 21 条 CRITICAL block 规则（destructive/exfil/privesc/rce/侦察 metadata/自保护）+ `lockfile-deletion`、`execute-vendored-script` 等少数 HIGH block，跨框架高度趋同（Claude Code 默认 deny、Invariant 示例规则交集一致）——**这就是"不可协商底线集 v0"的素材，且 Prismor 已有 non-overridable floor 机制承载它**（只是 floor 本身还锁在 YAML 文件里）。
2. **自保护类规则是"软件互锁"的自认**：`prismor-self-edit`、`audit-trail-tampering`、`agent-config-tampering` 七条规则全部指向"用 agent 攻击裁决器自身"——框架能做的是**检测**这些尝试并 block（当 agent 还在 hook 管辖内时有效）；但 root 级/进程外攻击不在管辖内。**硬件方案的准确切入点 = 把这七条规则防护的对象（策略文件、审计链、裁决进程）移出 NS 域**。
3. **防误报知识是最难的资产**：81 条里近半数代码行数花在 FP 防御（命令锚定、方向判定、动词×宾语矩阵、markdown 排除）。这部分知识跨框架不可移植（各家用不同 DSL）——**canonical rule format 若要做，承载的首要价值就是这层 FP 工程知识**，而不是干巴巴的攻击模式。
