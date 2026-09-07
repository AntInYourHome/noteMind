**2026-09-08（硬件抓手专题期）洞察：**

1. **子领域已正式成形**：arXiv 2605.03213《A Survey of Confidential Computing for Agentic AI》（2026-05）是首篇专门综述，TEE 隔离 Agent 代码与数据已成独立研究方向；本周论文雷达继续验证该方向高产出（PRISM、TEE-X、GIFT 等）。
2. **攻击面与防御面在硬件层正面对撞**：ROBBIN（Rowhammer 推理期后门注入）证明"物理层打模型权重"可行；JITterFlip 揭示 JIT 编译的 LLM 服务存在故障攻击面；而 NVIDIA Blackwell 机密计算基准显示防御侧开销持续下降——攻防两侧都值得跟踪。
3. **GIFT 论文值得重点读**：用 GPU 信息流追踪（hardware taint tracking）在 LLM 服务中强制用户数据隔离——这是"硬件级提示注入遏制"从概念到系统的首个具体信号，此前我们认为该方向尚属未来。
4. **Agent 专属 TEE 原型集中在 Web3 圈**：Dealproof（TEE 内 Agent 数据协商）、Confid-Intent-Tee（意图封装 SDK）、Phala/anda-cloud 等先行，但传统安全厂商尚未跟进——存在"搬运到企业级场景"的空窗机会。
5. **局限要常记**：TEE 解决机密性/完整性/证明，不解决语义（注入意图、目标劫持）；Black Hat 2026 已演示 GPU CC 的请求-输入绑定完整性可被破坏——做防御必须同步跟踪攻击文献。
