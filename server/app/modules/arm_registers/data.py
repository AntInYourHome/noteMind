"""AArch64 常用寄存器速查数据集。

encoding 为 MRS/MSR 指令的系统寄存器编码（op0_op1_CRn_CRm_op2），
通用寄存器/PC 等无编码（以指令操作数形式访问）。
"""

CLASSES = ["通用寄存器", "PSTATE", "系统寄存器", "浮点/NEON"]


def _general():
    out = []
    for i in range(31):
        if i == 0:
            desc = "第 1 个参数寄存器，兼作子程序返回值；caller-saved"
        elif i <= 7:
            desc = f"第 {i + 1} 个参数寄存器；caller-saved"
        elif i == 8:
            desc = "间接结果寄存器（如聚合类型返回地址）；caller-saved"
        elif i <= 15:
            desc = "临时寄存器（caller-saved），跨调用不保留"
        elif i <= 17:
            desc = f"内部调用寄存器 IP{i - 15}，链接器 veneer/PLT 会改写，勿存跨调用数据"
        elif i == 18:
            desc = "平台保留寄存器（Linux 保留作 shadow stack），应用不要使用"
        elif i == 29:
            desc = "帧指针 FP，指向当前栈帧基址"
        elif i == 30:
            desc = "链接寄存器 LR，保存 BL 调用的返回地址"
        else:
            desc = "callee-saved 寄存器，函数使用前须压栈保存"
        out.append((f"X{i}", "通用寄存器", "通用", None, desc))
    return out


_RAW = _general() + [
    # --- 通用（续） ---
    ("SP", "通用寄存器", "通用", None, "栈指针（当前 EL 的 SP 或 SP_EL0，见 SPSel）；作基址访问内存时须 16 字节对齐"),
    ("PC", "通用寄存器", "通用", None, "程序计数器，不能直接读写；读地址用 ADR X0, .，跳转用 B/BR/BL/BLR/RET"),
    ("XZR/WZR", "通用寄存器", "通用", None, "零寄存器：读恒为 0，写入被丢弃；常用于比较后丢弃结果 CMP X0, #0"),

    # --- PSTATE ---
    ("PSTATE", "PSTATE", "-", None, "处理器状态集合：NZCV、DAIF、异常级别、SP 选择等，经专用系统寄存器访问"),
    ("NZCV", "PSTATE", "EL0", "S3_3_C4_C2_1", "条件标志 N(负) Z(零) C(进位) V(溢出)，供 B.cond/CSEL/CSINC 等使用"),
    ("DAIF", "PSTATE", "EL1", "S3_3_C4_C2_2", "异常屏蔽位：D(Debug) A(SError) I(IRQ) F(FIQ)；置 1 屏蔽对应异常"),
    ("CurrentEL", "PSTATE", "EL1", "S3_0_C4_C1_2", "当前异常级别 EL0-EL3（只读），位 [3:2]"),
    ("SPSel", "PSTATE", "EL0", "S3_4_C4_C2_0", "为 EL1 及以上选择使用 SP_ELx 还是 SP_EL0"),
    ("SP_EL0", "PSTATE", "EL1", "S3_0_C4_C1_0", "EL0 栈指针，EL1+ 经 MRS X0, SP_EL0 读取"),

    # --- 系统寄存器 ---
    ("MIDR_EL1", "系统寄存器", "EL1", "S3_0_C0_C0_0", "主 ID：实现者/架构版本/部分号/R0 修订号"),
    ("MPIDR_EL1", "系统寄存器", "EL1", "S3_0_C0_C0_5", "多处理器亲和性 Aff0-Aff2 与多线程位，识别核 ID"),
    ("ID_AA64PFR0_EL1", "系统寄存器", "EL1", "S3_0_C0_C4_0", "处理器特性：各 EL 支持、SVE/SEL2/RAS 等"),
    ("ID_AA64DFR0_EL1", "系统寄存器", "EL1", "S3_0_C0_C5_0", "调试特性：断点/观察点数量、Trace"),
    ("ID_AA64ISAR0_EL1", "系统寄存器", "EL1", "S3_0_C0_C6_0", "指令集特性：AES/SHA1/SHA256/CRC32/原子操作"),
    ("ID_AA64MMFR0_EL1", "系统寄存器", "EL1", "S3_0_C0_C7_0", "内存模型特性：物理地址位宽/ASID 位宽/大端支持"),
    ("CTR_EL0", "系统寄存器", "EL0", "S3_3_C0_C0_1", "缓存类型：I/D 缓存最小行大小（做 cache 维护时用）"),
    ("DCZID_EL0", "系统寄存器", "EL0", "S3_3_C0_C0_7", "DC ZVA 指令的行为与允许的操作大小"),
    ("CSSELR_EL1", "系统寄存器", "EL1", "S3_2_C0_C0_0", "缓存大小 ID 选择器：选 level/类型后读 CCSIDR"),
    ("CCSIDR_EL1", "系统寄存器", "EL1", "S3_1_C0_C0_2", "当前所选缓存的几何：组数/相联度/行大小"),
    ("CLIDR_EL1", "系统寄存器", "EL1", "S3_1_C0_C0_1", "缓存层级 ID：各级缓存类型（统一/I/D）汇总"),
    ("SCTLR_EL1", "系统寄存器", "EL1", "S3_1_C1_C0_0", "系统控制：M(MMU) C(D-cache) I(I-cache) SA0/SA SP 对齐等总开关"),
    ("SCTLR_EL2", "系统寄存器", "EL2", "S3_4_C1_C0_0", "EL2 系统控制寄存器"),
    ("ACTLR_EL1", "系统寄存器", "EL1", "S3_0_C1_C0_1", "辅助控制，实现定义（顺序控制/预取等）"),
    ("CPACR_EL1", "系统寄存器", "EL1", "S3_0_C1_C0_2", "FP/SIMD 访问控制 FPEN；未使能时触发 Trap"),
    ("TTBR0_EL1", "系统寄存器", "EL1", "S3_0_C2_C0_0", "翻译表基址 0：用户低地址空间页表指针 + ASID"),
    ("TTBR1_EL1", "系统寄存器", "EL1", "S3_0_C2_C0_1", "翻译表基址 1：内核高地址空间页表指针"),
    ("TCR_EL1", "系统寄存器", "EL1", "S3_0_C2_C0_2", "翻译控制：T0SZ/T1SZ 地址宽度、TG 粒度、ASID 8/16、IRGN/ORGN"),
    ("MAIR_EL1", "系统寄存器", "EL1", "S3_0_C10_C2_0", "内存属性间接寄存器：8 组 attr 供页表 descriptor 索引"),
    ("ESR_EL1", "系统寄存器", "EL1", "S3_0_C5_C2_0", "异常综合征：EC 异常类别 + ISS 子信息，异常处理必读"),
    ("FAR_EL1", "系统寄存器", "EL1", "S3_0_C6_C0_0", "出错虚拟地址（取指/数据 abort 写入）"),
    ("AFSR0_EL1", "系统寄存器", "EL1", "S3_0_C5_C1_0", "辅助出错状态（实现定义，与 ESR 配合）"),
    ("ELR_EL1", "系统寄存器", "EL1", "S3_0_C4_C0_1", "异常链接寄存器：返回地址，ERET 从此取 PC"),
    ("SPSR_EL1", "系统寄存器", "EL1", "S3_0_C4_C0_0", "异常发生时保存的 PSTATE，ERET 恢复"),
    ("VBAR_EL1", "系统寄存器", "EL1", "S3_0_C12_C0_0", "异常向量基址，16 个向量槽按 EL/类型/A64 偏移"),
    ("CONTEXTIDR_EL1", "系统寄存器", "EL1", "S3_0_C13_C0_1", "上下文 ID（PROCID/ASID），配合 BTI/调试"),
    ("TPIDR_EL0", "系统寄存器", "EL0", "S3_3_C13_C0_2", "EL0 线程指针（TLS 基址，TPIDRRO 为只读版本）"),
    ("TPIDR_EL1", "系统寄存器", "EL1", "S3_0_C13_C0_4", "EL1 线程指针"),
    ("HCR_EL2", "系统寄存器", "EL2", "S3_4_C1_C1_0", "Hypervisor 控制：把各类 EL1 访问 trap 到 EL2（TGE/E2H/VM）"),
    ("VTTBR_EL2", "系统寄存器", "EL2", "S3_4_C2_C1_0", "阶段 2 翻译表基址（IPA→PA）"),
    ("VTCR_EL2", "系统寄存器", "EL2", "S3_4_C2_C1_2", "阶段 2 翻译控制"),
    ("CNTFRQ_EL0", "系统寄存器", "EL0", "S3_3_C14_C0_0", "系统计数器频率（Hz），换算定时器用"),
    ("CNTPCT_EL0", "系统寄存器", "EL0", "S3_3_C14_C0_1", "物理计数器当前值（64 位单调递增）"),
    ("CNTKCTL_EL1", "系统寄存器", "EL1", "S3_0_C14_C1_0", "内核定时器控制：EL0PCT/EL0VCT 是否允许 EL0 访问"),
    ("CNTV_CTL_EL0", "系统寄存器", "EL0", "S3_3_C14_C3_3", "虚拟定时器控制：ENABLE/IMASK/ISTATUS"),
    ("CNTV_CVAL_EL0", "系统寄存器", "EL0", "S3_3_C14_C3_2", "虚拟定时器比较值，计数达到即触发中断"),
    ("PMCR_EL0", "系统寄存器", "EL0", "S3_3_C9_C12_0", "性能监视控制：E 使能/计数器数/事件复位"),

    # --- 浮点/SIMD ---
    ("V0-V31", "浮点/NEON", "通用", None, "128 位 SIMD&FP 向量寄存器；B/H/S/D/Q 多视图；V0-V7 参数、V8-V15 callee-saved（低 64 位）"),
    ("FPCR", "浮点/NEON", "EL0", "S3_3_C4_C4_0", "FP 控制：舍入模式 RMode、FZ flush-to-zero、异常 trap 使能"),
    ("FPSR", "浮点/NEON", "EL0", "S3_3_C4_C4_1", "FP 状态：IOC/IXC/UFC/OFC/DZC/IDC 异常标志与 SIMD QC 饱和标志"),
]

REGISTERS = [
    dict(zip(("name", "klass", "el", "encoding", "desc"), r)) for r in _RAW
]
