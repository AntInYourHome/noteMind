# Cudro 核心算法与算例：从 DSL 到 11.6µs 投影核

> 对象：[GauthamMK-0/Cudro](https://github.com/GauthamMK-0/Cudro) HEAD@2026-09-10（master 分支）。
> 本文回答：**① 核心算法链每一步的数学与实现；② 一个可手算的完整数值例子；③ 生成的代码长什么样**。
> 姊妹篇：[Cudro 拆解](cudro-vla-safety-filter.md)（架构总览）、[Prismor 规则与运行机制](prismor-rules-and-runtime.md)（L2 对照）。

---

## 一、问题定义（数学形式）

机器人有 n 个关节，构型 q ∈ ℝⁿ（如 Panda 臂 n=7）。安全/任务要求写成**约束函数**：

```
g : ℝⁿ → ℝᵐ，   安全集合 = { q : g(q) ≥ 0 }（m 条约束）
```

VLA/神经策略给出提案 q*（可能违规——被后门、对抗样本、幻觉带偏）。**安全过滤器 = 投影**：

```
q_safe = argmin ‖q − q*‖   s.t.  g(q) ≥ 0
```

即流形上离提案最近的合法点。要求：**每个控制周期（1–10 ms）算完一次，且耗时确定可预测**。

Cudro 的解法是把这个问题变成**编译问题**：约束（声明式）→ 中间表示（DAG）→ 解析导数（符号微分）→ 定制 C 代码（JIT/AOT）→ 机器码函数指针。

---

## 二、算法链总览（五阶段）

```
.cudro spec（运动学树 + 约束）
  ① Lexer/Parser（递归下降）                    → AST
  ② Sema（运动学树环检测/符号解析）              → 合法 AST
  ③ Lowering：FK 内联（Rodrigues）+ 常量折叠     → ExprDAG（planar2r: 122→25 节点）
  ④ 符号微分：对每个约束每个输入生成导数节点       → 雅可比并入 DAG
  ⑤ CodeGen → C 源码 → libtcc JIT（<15ms）      → project() / evaluate_constraints() / project_batch()
```

`evaluate_dag(q, g, J)` **一次遍历同时算出约束值 g 和雅可比 J**——这是性能的来源。

---

## 三、算法一：正运动学与约束函数（g 从哪来）

`.cudro` 描述运动学树：每个关节 `{axis, origin, limits}`，每个连杆带碰撞几何（球体列表）。以 `spec/planar2r.cudro` 原文为例：

```cudro
robot planar2r {
  joint j1 { type revolute; axis [0,0,1]; origin [0,0,0];  limits [-π, π]; }
  joint j2 { type revolute; axis [0,0,1]; origin [1.0,0,0]; limits [-π, π]; }   // 第二关节在第一臂末端
  link base { spheres [[0,0,0, 0.05]]; parent world; joint_ref j1; }
  link arm1 { spheres [[0.5,0,0, 0.04], [1.0,0,0, 0.04]]; parent base; joint_ref j2; }
  link ee   { spheres [[0.5,0,0, 0.03]]; parent arm1; }                          // EE 球心在第二臂 0.5 处
}
task keep_ee_above { link ee; plane { point_on_link [0,0,0]; normal [0,0,1]; offset 0.1; } }
clearance { min_distance 0.02; }
```

**Lowering 做的事**：把运动学树展开成矩阵乘法序列——每个关节一个变换 `Tᵢ = Translate(origin) · RotAxis(axis, qᵢ)`，连杆世界位置 = 连乘 `T₁·T₂·…·Tᵢ` 作用于连杆局部坐标。旋转用 **Rodrigues 公式**（轴角 → 3×3 矩阵），全部内联成 DAG 节点；静态已知量（连杆几何、轴向量）常量折叠掉。

约束种类：`plane`（点到平面有向距离 ≥ offset）、`point`（点到点距离）、`clearance`（任意两球之间距离 − 半径和 ≥ min_distance，球体几何保证这一项可微且 O(球数)）。所有约束统一成 g ≥ 0 形式。

## 四、算法二：符号微分（解析雅可比是怎么"长"出来的）

`diff_dag_node`（ad.cpp）对 DAG 做**逐节点符号微分**——不是运行时数值求导，而是**在编译期生成导数 DAG**。规则表（源码实现）：

| 节点 | 求导规则（生成的新节点） |
|---|---|
| Add/Sub | 逐操作数传递（线性） |
| Mul | `(uv)' = u'v + uv'`；若 `u'≡1` 短路为 `v`，`u'≡0` 直接 0（常量折叠短路） |
| RotAxis(轴角) | Rodrigues 导数**逐元素显式展开**：`m00' = d(cosθ) + ax²·d(1−cosθ)`，其中 `d(cosθ)=−sinθ·θ'`、`d(1−cosθ)=sinθ·θ'`——9 个矩阵元素的乘加树全部手写展开 |
| MatMul | 积规则 `dA·B + A·dB` |
| Translate | 只有平移分量有导数，旋转块为 0 |

两个剪枝：`active[]` 标记子图是否依赖输入 q——不依赖的子图导数直接为常量 0，**不生成节点**；`is_constant_one/zero` 在生成时短路。最终 `build_analytical_jacobians` 为每个约束 c × 每个输入 j 建立导数节点，**J 与 g 在同一次 DAG 遍历中求值**（单遍统一求值器 `evaluate_dag(q, g, J)`）。

对比有限差分：数值微分每步 LM 需要 n+1 次 DAG 遍历且带截断误差；解析版一遍、零截断——README 性能表 16.7µs → **11.6µs** 的全部来源。

## 五、算法三：LM 阻尼投影（生成的求解器本体）

codegen_c.cpp 生成的 `project_single` 是**展开的求解器**（维度全部是编译期字面量）：

```c
static inline void project_single(const float* q_in, int n, float* q_out) {
    float q[N];  float g[M];  float J[M*N];       // 栈上定长，无 malloc
    const float lambda = 1e-3f;                   // LM 阻尼
    const int   max_iters = 20;                   // 硬顶（WCET 的来源）
    const float tol_sq = 1e-8f;                   // 收敛容差
    q ← q_in;
    for (iter = 0; iter < 20; ++iter) {
        evaluate_dag(q, g, J);                    // 一遍出 g 和 J
        if (Σ g²  < tol_sq) break;                // 已在流形上
        if (M == 1) {                             // ── 单约束：rank-1 特化 ──
            denom = lambda + Σⱼ J[j]²;
            q[j] -= g[0]·J[j] / denom;            // 高斯-牛顿方向 + 阻尼
        } else {                                  // ── 多约束：正规方程 ──
            组装 A = J·Jᵀ + λ·I (M×M)，rhs = −g;
            高斯消元（部分主元）解 A·y = rhs;      // 对角 < 1e-12 钳位防奇异
            q[j] += Σ_c J[c][j]·y[c];             // q ← q + Jᵀy
        }
    }
    q_out ← q;
}
```

数学上这是 **Levenberg-Marquardt 阻尼最小二乘**：求 `min ‖g(q)‖²`，每步解 `(JJᵀ+λI)y = −g` 后走 `q + Jᵀy`。λ 大→步子小而稳（梯度下降极限），λ→0→牛顿步（快但可能过冲）。三个实现细节值得注意：**单约束特化成 rank-1 公式**（省掉整个线性方程组，多数控制周期只有一两条活跃约束）；**对角元钳位 1e-12**（退化雅可比不崩，走小步）；**float 单精度**（实时吞吐换精度，配 1e-8 容差实测 1e-4 内与 Eigen 双精度参考一致）。

## 六、算法四：C-RRT-Connect（约束流形上的轨迹规划）

planner.cpp 的规划器是**投影内置的双向 RRT**：

```
1. start/goal 各投影到流形（不可投影 → 直接报失败）
2. 双向树 tree_a / tree_b，循环 max_iterations 次：
     a. 随机采样 q_rand（goal 附近偏置）
     b. extend_tree(tree_a, q_rand)：
          最近邻 q_near → 朝 q_rand 走一步（≤ step_size）
          → project(q_cand) 投影回流形       ← 关键：每个候选点都过投影
          → 关节限位检查 → 入树
     c. extend_tree(tree_b, q_new_a)：b 树朝 a 树新节点延伸
     d. 两树距离 ≤ 1.5×step_size → 连接成功
3. 沿 parent 指针回溯拼接路径 → validate_path 逐点复验（容差内）
```

与普通 RRT-Connect 的唯一本质区别是 extend 里那次 `project_configuration`——**采样空间里的任何折线都被"吸"回流形**，输出轨迹逐点满足约束。这就是"约束运动规划"（Constrained-RRT）的工程实现。

---

## 七、手算例子：planar2r 的一次完整投影

**设置**（取 spec 几何：l₁=1.0, l₂=0.5；约束取教学版"EE 高度 ≥ 0.3"——spec 原文的 z 向平面约束对平面臂是退化的，教学版把法向取在运动平面内）：

```
正运动学：  x = cos q₁ + 0.5·cos(q₁+q₂)
           y = sin q₁ + 0.5·sin(q₁+q₂)
约束：      g(q) = y(q) − 0.3 ≥ 0        （单约束 → rank-1 路径）
雅可比：    J = ∂g/∂q = [ cos q₁ + 0.5·cos(q₁+q₂) ,  0.5·cos(q₁+q₂) ]
```

**VLA 提案**（被带偏到工作台下方）：`q* = (q₁, q₂) = (0, −2.0)` rad。

**第 0 步：评估违规量**

```
x = cos 0 + 0.5·cos(−2) = 1 + 0.5×(−0.4161) = 0.792
y = sin 0 + 0.5·sin(−2) = 0 + 0.5×(−0.9093) = −0.455
g = −0.455 − 0.3 = −0.755          ← 违规 0.755
J = [1 + 0.5×(−0.4161),  0.5×(−0.4161)] = [0.792, −0.208]
```

**第 1 次迭代（λ = 1e-3，rank-1 公式）**

```
denom = λ + ‖J‖² = 0.001 + 0.792² + 0.208² = 0.671
Δq = −g·J / denom = 0.755 × [0.792, −0.208] / 0.671 = [+0.891, −0.234]
q¹ = (0.891, −2.234)      q₁+q₂ = −1.343
y = sin 0.891 + 0.5·sin(−1.343) = 0.777 − 0.487 = 0.290
g = 0.290 − 0.3 = −0.010          ← 一步消掉 98.7% 的违规
```

**第 2 次迭代**

```
J = [0.629 + 0.5×0.226,  0.5×0.226] = [0.742, 0.113]
denom = 0.001 + 0.551 + 0.013 = 0.565
Δq = 0.010 × [0.742, 0.113] / 0.565 = [+0.013, +0.002]
q² = (0.904, −2.232)      y = 0.300 → g ≈ 0     ← 收敛，‖g‖² < tol
```

**输出** `q_safe = (0.904, −2.232)`：EE 位置 (0.742, 0.300)——**在约束边界上离提案 (0.792, −0.455) 最近的合法点**。两步收敛、每步一次 `evaluate_dag`，这就是单次投影 11.6µs（Panda 7-DOF 规模）所包含的全部计算。

值得注意的行为：迭代走的是"最速满足约束"方向，**不是把臂摆回某个预设姿态**——投影保留提案的意图到流形允许的最大程度。这正是"修正而非拒绝"的语义。

## 八、生成的 C 代码骨架（planar2r 规模）

按 codegen_c.cpp 的发射逻辑，planar2r 的输出（骨架，数值为示意）：

```c
// Generated by Cudro Scalar Emitter with Analytical Jacobians - do not edit
static inline void evaluate_dag(const float* q, float* g, float* J) {
    const float s1 = sinf(q[0]), c1 = cosf(q[0]);
    const float s12 = sinf(q[0]+q[1]), c12 = cosf(q[0]+q[1]);
    const float y = s1 + 0.5f*s12;                  // 常量折叠后仅存活的节点
    if (g) g[0] = y - 0.3f;
    if (J) { J[0] = c1 + 0.5f*c12;  J[1] = 0.5f*c12; }
}
static inline void project_single(const float* q_in, int n, float* q_out) {
    float q[2], g[1], J[2];                         // 维度全是字面量
    /* ... 上节的 LM 循环，单约束 rank-1 分支 ... */
}
void project(const float* q_in, int num_inputs, float* q_out)
    { project_single(q_in, num_inputs, q_out); }
void evaluate_constraints(const float* q, int n, float* g) { ... }
void project_batch(const float* qb, int B, int n, float* qob)
    { for (b...) project_single(qb + b*n, n, qob + b*n); }
```

JIT 侧（jit_tcc.cpp 全部 85 行）：`tcc_new() → TCC_OUTPUT_MEMORY → tcc_compile_string(src) → tcc_relocate(AUTO) → tcc_get_symbol("project")`——拿到的就是普通 C 函数指针，控制环直接调用。**部署期切换**：同一份生成的 C 源码改走 LLVM AOT 编译 → 签名 → 度量 → 装安全岛，与 JIT 路径同构。

## 九、事实速查表

| 项 | 值 | 来源 |
|---|---|---|
| JIT 编译延迟 | 5.1–9.5 ms | README 性能表 |
| 单次投影（Panda 7-DOF） | 11.6 µs | 同上（解析雅可比后） |
| 批量投影吞吐 | 8.6–12 万 LM 求解/秒 | 同上 |
| planar2r DAG | 25 节点（降 79.5%） | 同上 |
| LM 参数 | λ=1e-3，max 20 迭代，tol 1e-8 | codegen_c.cpp |
| 数值精度 | float；与 Eigen 双精度差 <1e-4（1 万随机点，30,022 断言） | reference 差分测试 |
| C-RRT 参数 | 双向树 + goal 偏置采样，连接阈值 1.5×step | planner.cpp |

## 十、局限（算法层的诚实清单）

1. **投影不保证可行**：约束互相矛盾时 LM 20 步内不收敛，代码只是返回最后迭代点——**fail-safe 语义（不可投影→停机/缓停）在库层缺失**，由调用方负责（安全岛看门狗正好补这一格）；
2. **等式约束外的世界**：g≥0 的不等式形式处理得好，动态约束（速度/加速度界限、CBF 的 ḣ+αh≥0 时间项）在 DSL 中无表达；
3. **单精度**在病态雅可比（接近奇异位形）时步长可能抖动——对角钳位缓解但不消除；
4. C-RRT 的 completeness 是概率性的，max_iterations 内失败≠无解。
