# Cudro 技术拆解：VLA 安全过滤器的运行时是怎么造出来的

> 对象：[GauthamMK-0/Cudro](https://github.com/GauthamMK-0/Cudro)（C++20，CMake，约 3087 行，2026-09 新仓，0 星）
> 方法：clone 仓库读源码与 spec（2026-09-10 HEAD），只讲机制。
> 定位：L4（具身执行层）× 硬件屏障主题的**软件侧地基**——四层模型见 [unified-map.md](unified-map.md)。

## 0. 它要堵的缺口

具身智能的安全命题：VLA/神经策略输出的动作提案是**黑盒且不可证**的——后门、对抗扰动、幻觉都能变成关节指令。经典控制论早有答案：**把动作投影到"认证过的安全集合"上再执行**（流形投影/CBF 一族方法）。工程瓶颈在于：投影求解要跑在 100–1000 Hz 的控制环里，而约束（桌子高度变了、换了工具、动态禁入区）又会随时变——AOT 编译的专用核快但不能变，通用求解器能变但不够快。

Cudro 的回答：一个**运行时可重编译的约束编译器**——约束变了，5–9.5 ms 内 JIT 出一个新的专用投影核。

README 引用的直接背景是 McVAMP（IROS 2026）——向量化运动规划器用 AOT tracing 生成 SIMD 核，Cudro 补的就是它留下的 AOT→runtime 缺口。

## 1. 它是什么：一条五阶段编译流水线

输入是声明式的 `.cudro` 规范（机器人运动学 + 任务约束），输出是**进程内的 C 函数指针**：

```
.cudro 规范
  → ① Lexer/Parser（递归下降，错误恢复）        → AST
  → ② Sema（运动学树校验/符号解析/环检测）       → 合法 AST
  → ③ Lowering（FK 内联·Rodrigues 旋转、常量折叠、脱糖）→ 表达式 DAG
  → ④ 自动微分（前向模式对偶数）                 → 解析 Jacobian ∂g/∂q
  → ⑤ CodeGen + JIT（libtcc 内存编译 <15ms）     → project() / evaluate_constraints() / project_batch()
```

三个后端：`codegen_c`（TCC JIT，默认）、`codegen_llvm`、`codegen_cuda`——同一 DAG 可以落到不同目标（这一点在后面第 5 节有重要含义）。

## 2. 安全过滤的语义：投影，不是拒绝

与 Prismor（L2：allow/block 裁决）根本不同，Cudro 的安全动作是**modify**：给定神经策略的提案构型 `q*`，用阻尼 Levenberg-Marquardt 迭代求流形上最近点——

```
q_safe = argmin ‖q − q*‖   s.t.  g(q) ≥ 0（任务约束）+ clearance（碰撞距离）
```

策略想怎么疯都行，执行器只收到 `q_safe`。**"认证"来自约束侧的可验证性**：`g` 是声明式的、可微分验证的闭式表达（与神经策略的黑盒相对），配 Eigen 参考实现的**差分验证**——1 万个随机构型、30,022 条断言、误差 <1e-4。这个"独立参考实现差分测试"是安全数值软件的标准做法，在 0 星个人项目里见到算是工程纪律的强信号。

## 3. DSL：约束写得出来才算数

以 Panda 7-DOF 臂为例（`spec/panda7.cudro`）：

```cudro
robot panda7 {
  joint j1 { type revolute; axis [0,0,1]; origin [0,0,0.333]; limits [-2.8973, 2.8973]; }
  ...                                     // 运动学树：关节/轴/原点/限位
  link arm1 { spheres [[0,0,0.15, 0.06]]; parent base; joint_ref j2; }
  ...                                     // 碰撞几何：球体近似
}

task cup_on_table {                        // 任务约束：EE 平面
  link ee;
  plane { point_on_link [0,0,0.02]; normal [0,0,1]; offset 0.02; }
}

clearance { min_distance 0.03; }           // 全局最小间距
```

约束词汇目前是 plane/point/line/clearance 几类；碰撞用球体包络（保守近似，换来的是距离计算可微且 O(n)）。**表达力有限但每一条都可微、可编译、可验证**——这是安全约束语言的正确取舍方向。

## 4. 性能形态（决定了它能插在哪）

| 指标 | 实测 |
|---|---|
| JIT 编译延迟 | 5.1–9.5 ms |
| 批量约束评估 | 264–649 万构型/秒 |
| 批量 LM 投影 | 8.6–12 万次完整求解/秒 |
| Panda 7-DOF 单次投影 | **11.6 µs** |
| DAG 规模（planar2R） | 25 节点（降 79.5%） |

µs 级、单遍统一求值器、in-kernel 求解无堆分配——**这是能进实时控制环的形态**，也是能下沉到 MCU 的形态。

## 5. 我们的观察（硬件屏障视角，本文真正的落点）

1. **这就是"安全岛裁决"的算法候选**。我们的具身链是：传感器认证 → 安全岛裁决 → 执行器鉴权。中间那格的裁决算法长期缺开源实现——CBF/流形投影停留在论文和 MATLAB。Cudro 把它做成了"约束一变 5ms 重出专用核"的 runtime，且 11.6µs/次的确定性时延可分析（WCET）。**把 LLVM 后端 AOT 固化的投影核放进 lockstep 核的安全岛上跑，"策略再疯也出不了安全流形"就从 OS 层承诺变成硬件强制**——这是具身硬件屏障从架构图落到硅片路径上缺失的那块软件。
2. **一个真矛盾要盯：JIT 与安全认证互斥**。运行时生成机器码恰恰是 ISO 26262/DO-178C 这类标准最难接受的（认证对象不可枚举）。作者的解法空间其实已经埋在代码里：TCC JIT 用于开发/动态场景，`codegen_llvm` 后端用于部署期固化——**开发期 JIT 迭代约束、部署期 AOT 固化认证**，两段式是这类系统走向车规的正路。值得跟踪作者是否把这层区分显式化。
3. **VLA 集成目前只有 README 一句话**（"project noisy neural policy action proposals onto certified constraint manifolds at 100–1000 Hz"），仓库里没有 VLA 管线代码——它今天是"给规划器用的约束编译器"，"VLA 安全过滤器"是路线图不是现状。评估时要分开。

## 6. 局限与跟踪建议

- 个人项目、0 星、3087 行——**成熟度风险高**（作者弃坑概率不小），但代码结构教科书级（10 套测试含 fuzz、ASan/UBSan、差分验证、诊断 UI）；
- LM 投影**不保证可行**：约束不可满足时的 fail-safe 行为（投影失败→停机？降级？）在 README 与测试中未见明确语义——这在安全过滤里是必须回答的问题；
- 球体碰撞几何对细长构件过保守；约束词汇不含时间维（动态障碍的速度约束、CBF 的 ḣ 项）——到动态场景还有一步；
- 跟踪建议：已加入 watchlist（具身硬件屏障线第一仓）。**关注三个信号**：VLA 管线实际代码落地、LLVM/AOT 部署模式的显式化、投影失败的 fail-safe 语义。三者出现其一时值得升级精读。

---
*调研基线：HEAD@2026-09-10；引用 `src/{lexer,parser,sema,lower,ad,codegen_c,jit_tcc,planner}.cpp`、`spec/panda7.cudro`、README 性能表。姊妹篇：[Prismor 拆解](prismor-runtime-enforcement.md)（L2 裁决层，同日调研）。*
