# 具身智能 × 汽车物理安全：硬件抓手第三轨调研

> 调研日期：2026-09-08 ｜ 定位：这是"硬件抓手"图谱里**最成熟也最迫切**的一块——安全 MCU/安全岛本来就是为物理世界设计的，而 AI（VLA、端到端智驾）正在涌入这些平台，安全问题从比特世界进入物理世界（攻击的直接后果是撞车、机械伤人）。

---

## 1. 技术底座：两套并存的硬件信任体系

### 1.1 车载侧：安全 MCU 与安全岛
- **EVITA HSM 分级**（Light/Medium/Full）至今仍是车载硬件安全模块的主流分类：Light（AES-128，传感器/执行器 ECU）→ Medium（加非对称密码，网关）→ Full（独立 CPU + ECC/PKI，中央网关与 ADAS 控制器）（[Semiconductor Engineering](https://semiengineering.com/setting-the-standard-for-automotive-security/)）
- **安全 MCU 代表**：[Infineon AURIX TC3xx/TC4xx](https://www.infineon.com/dgdl/Infineon-TC33xDA-PB-v01_00__EN.pdf?fileId=5546d46269e1c019016a9c5b8e936f2f)——lockstep TriCore 实现 ASIL-D、集成 EVITA-Full HSM；**TC4Dx 已上后量子密码（PQC）**（[Microcontroller Tips](https://www.microcontrollertips.com/500-mhz-automotive-microcontroller-features-post-quantum-security/)）——车 15 年生命周期倒逼 PQC 提前上车；wolfHSM 等中间件生态跟进（[wolfSSL](https://www.wolfssl.com/wolfhsm-now-supports-the-infineon-aurix-tc4xx/)）
- **安全岛（Safety Island）**：区域架构/中央计算 SoC 中一块隔离的 lockstep MCU 域（如 Arm Cortex-R82AE 级别），跑 ASIL-D 控制逻辑（制动/转向），与高性能 AI 核隔离（[Arm 安全岛架构学习路径](https://learn.arm.com/learning-paths/automotive/openadkit2_safetyisolation/1d_safety_island_arch/)）——**这是"AI 大脑 + 确定性小脑"的硬件分权**
- 法规底座：ISO/SAE 21434（网络安全工程）+ UNECE R155/R156（强制认证/OTA 管理）+ ISO 26262（功能安全）三者交叉驱动

### 1.2 具身侧：VLA 模型成为新攻击面
- VLA（Vision-Language-Action）模型正在成为具身智能的统一底座（感知→语言→端到端动作），2026 年已出现首篇安全综述：[Vision-Language-Action Safety: Threats, Challenges, Evaluations](https://arxiv.org/html/2604.23775v1)
- 实测攻击：[BadVLA 后门攻击](https://neurips.cc/virtual/2025/poster/11580)（NeurIPS 2025，触发器→恶意行为）、[ADVLA 稀疏对抗补丁](https://arxiv.org/html/2511.21663v1)、[对抗图像让 VLA "冻结"无视指令](https://vlaattacker.github.io/)、[把 LLM 越狱手法迁移到 VLA 直接夺取机器人控制权](https://www.semanticscholar.org/paper/c8779507ec5e8c5c6812da756005eee4b920d65d)（Jones & Robey）
- **关键差异**：LLM 的注入攻击偷数据，VLA 的注入攻击**直接产生物理动作**——撞人、夹手、开出车道

## 2. 攻击景观（实战证据，非理论）

| 攻击 | 技术 | 出处 |
|---|---|---|
| Three Glitches to Rule One Car | 电压故障注入绕过联网 EV 的 secure boot + EM 注入打 autopilot 子系统 | [TU Berlin, ASIA CCS 2025](https://dl.acm.org/doi/10.1145/3708821.3710820) |
| RH850 调试保护绕过 | crowbar 电压毛刺 | [Quarkslab](https://blog.quarkslab.com/bypassing-debug-password-protection-on-the-rh850-family-using-fault-injection.html) |
| DST80 防盗器瓦解 | 电压故障注入打 ROM bootloader | [论文](https://www.semanticscholar.org/paper/93908feb863126571e45b66e1bb857e0f363fe22) |
| CAN Injection 偷车潮 | 经大灯线束注入伪造"合法钥匙" CAN 帧 | [Ken Tindell](https://kentindell.github.io/2023/04/03/can-injection/)，[北美激增报告](https://plaxidityx.com/blog/blog-post/keyless-car-theft-north-america/) |
| RKE 偷车体系化 | 中继/滚动码攻击 30 年系统化梳理 | [SoK: Stealing Cars Since Remote Keyless Entry (arXiv:2505.02713)](https://arxiv.org/html/2505.02713v1) |
| ASIL-D ≠ 抗攻击 | escar USA 2026 议题：ASIL-D MCU 的故障注入韧性评估 | [escar](https://escar.info/escar-usa/papers)（2017 同名研究延续） |

## 3. 业界新方向信号（2026）

1. **PQC 上车**：AURIX TC4Dx 等新一代 MCU 内置后量子算法——车载密码迁移周期已被拉响
2. **Safety × Security 融合成显学**："safety doesn't equal security"——lockstep/ECC/BIST 防的是随机故障，攻击者的确定性故障注入需要另一套对策；ISO 26262 与 ISO 21434 的协同工程（security-derived safety failure）成为 Tier-1 刚需
3. **SDV/区域架构落地**：安全岛从"伴飞 MCU"变为 SoC 内集成块，以太网骨干（100/1000BASE-T1 + MACsec、CANsec/CiA 601）替代传统 CAN
4. **抗妥协 OTA**：Uptane 标准成为车厂 OTA 安全基线（[标准仓库](https://github.com/uptane/uptane-standard)）
5. **学术会议热点**：[escar Europe 2026](https://escar.info/escar-europe)（11 月波恩）、DEF CON Car Hacking Village、Auto-ISAC 情报共享
6. **机器人漏洞开始建档**：[Alias Robotics RVD（Robot Vulnerability Database）](https://github.com/aliasrobotics/RVD)——机器人界的 CVE 库雏形

## 4. 找思路：六个值得下注的交叉点

1. **安全岛 = VLA/端到端策略的硬件护栏（最值得做）**：AI 核输出动作前必须经安全岛的确定性校验——动作白名单、关节/转向限幅、地理围栏、紧急停止。这本质上是 AI Agent 领域"最小代理权（Least Agency）"的**物理世界硬件实现**：语言层防不住的注入，物理层用 ASIL-D 的确定性规则兜底。产业界有部件（lockstep 岛、监控单元），缺的是"VLA 动作契约"的标准化接口——谁定义它谁吃标准红利。
2. **物理世界间接提示注入的评测基准**：把"招牌上的文字/贴纸/语音指令骗 VLA"做成系统化 benchmark（类似 AgentDojo 之于 LLM Agent）。学术空白明确，工程门槛低（现有 VLA 开源模型 + 真机/仿真），且直接对接保险与法规（ISO 21434 要求可复现测试）。
3. **车载/机器人 TEE × 策略供应链证明**：OTA 下发智驾策略/机器人策略时，用 HSM 签名链 + 远程证明保证"装进车/机器人的权重版本可验证"——把第一轨（TEE 证明）的成果平移到 Uptane/ISO 21434 语境。
4. **故障注入韧性评估服务/工具**：Three Glitches、RH850、DST80 证明物理注入是车载 MCU 的现实威胁，而车厂普遍缺 FI 红队；escar 系列每年都在出新的 MCU 打靶——这是"硬件渗透测试"的小众高价值赛道。
5. **CANsec/MACsec 落地测量**：车载以太网加密与 CAN 总线认证（CiA 601 CANsec）从规范走向量产，端到端延迟/成本测量与攻击面对比是 Tier-1 采购决策刚需。
6. **具身 IDS：用安全岛的确定性资源做异常检测**：安全岛常年在跑冗余校验，剩余算力可承载轻量异常检测（CAN 流量、电机电流、动作合理性）——"功能安全硬件复用做安全检测"是架构级巧思，学术上有新意。

## 5. 与前两轨的关系

三轨合成一张图谱：**第一轨（Agent 应用安全）暴露问题 → 第二轨（机密计算/TEE）保护计算过程 → 第三轨（车载/具身硬件）把边界推到物理执行**。共同主线是"Least Agency 的硬件化"：无论数据中心 TEE 里的密钥封存，还是底盘安全岛上的动作限幅，都是把"最终权限"锁进不可绕过的硬件层。

## 6. 持续跟踪源

| 类型 | 源 |
|---|---|
| 会议 | [escar Europe/USA](https://escar.info/escar-europe)、DEF CON Car Hacking Village、Black Hat 汽车议题 |
| 标准 | ISO/SAE 21434、UNECE R155/R156、[Uptane](https://github.com/uptane/uptane-standard)、CiA 601 CANsec、ISO 26262/21448（SOTIF） |
| 论文检索词 | `vision-language-action attack`、`fault injection automotive`、`CAN security`、`sensor spoofing`、`robot security` |
| 开源 | commaai/openpilot、autowarefoundation/autoware、CaringCaribou、can-utils、aliasrobotics/RVD |
| 厂商动态 | Infineon AURIX TC4x、NXP S32N/S32K3、Arm Automotive Enhanced、wolfHSM |
