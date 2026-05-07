"""
NoteMind 分类器 — 多级分类树 + 文档类型标签
"""

from scripts.ai_client import _call_api

# 一级分类关键词映射
LEVEL1_KEYWORDS = {
    "安全": [
        "安全", "权限", "攻击", "漏洞", "加密", "防护", "威胁", "风险", "恶意",
        "黑客", "隐私", "SELinux", "防火墙", "审计", "合规", "等保", "ISO27001",
        "CVE", "漏洞", "渗透", "扫描", "加固", "基线", "管控", "管控策略",
        "Capabilities", "零信任", "攻防", "应急响应", "安全评估", "威胁情报",
        "星盾", "微内核安全", "TrustZone", "TEE", "沙箱", "签名", "混淆",
    ],
    "操作系统": [
        "内核", "驱动", "文件系统", "进程调度", "内存管理", "编译", "构建",
        "Makefile", "CMake", "toolchain", "bootloader", "BIOS", "UEFI",
        "ext4", "btrfs", "NTFS", "调度器", "CFS", "OOM", "虚拟内存",
    ],
    "技术": [
        "编程", "Python", "Go", "Rust", "Java", "JavaScript", "TypeScript",
        "架构", "微服务", "分布式", "API", "数据库", "Redis", "MySQL",
        "AI", "机器学习", "深度学习", "大模型", "LLM", "神经网络",
        "Docker", "Kubernetes", "CI/CD", "DevOps",
    ],
    "个人": [
        "笔记", "学习", "总结", "心得", "体会", "记录", "备忘", "思考",
        "课堂", "教程", "考试", "习题", "生物", "医学", "教育", "健康",
        "旅行", "生活", "日记", "计划", "目标",
    ],
}

# 文档类型关键词映射
DOC_TYPE_KEYWORDS = {
    "白皮书": ["白皮书", "whitepaper", "技术白皮书", "安全白皮书", "概述", "展望"],
    "教程": ["教程", "指南", "入门", "上手", "howto", "tutorial", "步骤"],
    "报告": ["报告", "分析", "调研", "市场", "趋势", "review", "report"],
    "架构文档": ["架构", "设计", "系统设计", "架构图", "方案", "architecture"],
    "漏洞分析": ["漏洞", "CVE", "PoC", "exploit", "利用", "溢出", "越权"],
    "渗透测试": ["渗透", "pentest", "扫描", "nmap", "burp", "sqlmap"],
    "配置文档": ["配置", "安装", "部署", "deploy", "config", "setup"],
    "规范标准": ["规范", "标准", "国标", "GB/T", "ISO", "规范文档"],
    "会议记录": ["会议", "纪要", "meeting", "讨论", "决议"],
    "项目计划": ["计划", "排期", "里程碑", "roadmap", "方案", "规划"],
    "学习笔记": ["笔记", "学习", "总结", "知识点", "习题", "试题", "考试"],
}


def _call_ai(prompt: str) -> str:
    """调用 AI 分类接口，返回纯文本结果。"""
    messages = [{"role": "user", "content": prompt}]
    try:
        result = _call_api(messages, max_tokens=30)
        content = result.get("content", "") if isinstance(result, dict) else str(result)
        return content.strip().strip("[]'\"。")
    except Exception:
        return ""


def _keyword_match(text: str, title: str, keywords: list[str]) -> int:
    """关键词匹配得分。"""
    search_text = f"{title} {text[:500]}".lower()
    score = 0
    for kw in keywords:
        if kw.lower() in search_text:
            score += 1
    return score


def _classify_with_ai(text: str, candidates: list[str], level_name: str) -> str:
    """AI 判断应该归到哪个候选分类。"""
    if not candidates:
        return ""
    if len(candidates) == 1:
        return candidates[0]

    cat_list = "、".join(candidates)
    prompt = (
        f"请根据以下内容，将其归类到以下{level_name}之一：{cat_list}。\n"
        f"只返回分类名称，不要返回其他内容。\n\n"
        f"内容：\n{text[:1500]}"
    )
    result = _call_ai(prompt)
    if result in candidates:
        return result
    # 模糊匹配
    for cat in candidates:
        if cat in result or result in cat:
            return cat
    return ""


def classify(summary_text: str, categories: dict, title: str = "") -> tuple:
    """多级分类。

    Args:
        summary_text: 文档摘要文本
        categories: 分类树 dict，格式：{"一级/二级/三级": ["标签1", "标签2"], ...}
        title: 文档标题/文件名

    Returns:
        (完整分类路径, 文档类型标签列表)
    """
    if not summary_text.strip() or not categories:
        return "其他", []

    # 兼容旧格式：如果 categories 是 list，降级为平级分类
    if isinstance(categories, list):
        return _classify_flat(summary_text, categories, title)

    # 获取所有一级分类（从 keys 中提取）
    level1_candidates = list(set(k.split("/")[0] for k in categories.keys()))
    # 确保"其他"在候选中
    if "其他" not in level1_candidates:
        level1_candidates.append("其他")

    # 步骤1: 一级分类
    level1_score = {}
    for cat, kws in LEVEL1_KEYWORDS.items():
        if cat in level1_candidates:
            level1_score[cat] = _keyword_match(summary_text, title, kws)

    # 关键词得分 + AI 判断
    if level1_score:
        best_l1 = max(level1_score, key=level1_score.get)
        if level1_score[best_l1] > 0:
            level1 = best_l1
        else:
            level1 = _classify_with_ai(summary_text, level1_candidates, "领域")
    else:
        level1 = _classify_with_ai(summary_text, level1_candidates, "领域")

    if not level1 or level1 == "其他":
        return "其他", []

    # 步骤2: 二级分类
    level2_candidates = [k for k in categories if k.startswith(level1 + "/")]
    # 提取二级名称
    level2_names = list(set(
        k.split("/")[1] for k in level2_candidates if len(k.split("/")) > 1
    ))

    if not level2_names:
        return f"{level1}", []

    if len(level2_names) == 1:
        level2 = level2_names[0]
    else:
        level2 = _classify_with_ai(summary_text, level2_names, "子领域")

    if not level2:
        return f"{level1}", []

    # 步骤3: 三级分类
    level3_candidates = [k for k in categories if k == f"{level1}/{level2}" or k.startswith(f"{level1}/{level2}/")]
    # 提取三级名称
    level3_names = list(set(
        k.split("/")[2] for k in level3_candidates if len(k.split("/")) > 2
    ))

    if level3_names:
        level3 = _classify_with_ai(summary_text, level3_names, "具体系统")
        if level3:
            full_path = f"{level1}/{level2}/{level3}"
        else:
            full_path = f"{level1}/{level2}"
    else:
        full_path = f"{level1}/{level2}"

    # 步骤4: 文档类型标签
    type_keywords = categories.get(full_path, [])
    # 合并该分类路径下所有层级的 keywords
    for kw in ("白皮书", "教程", "报告", "架构文档", "漏洞分析", "渗透测试",
               "配置文档", "规范标准", "会议记录", "项目计划", "学习笔记"):
        if kw in DOC_TYPE_KEYWORDS:
            type_keywords.extend(DOC_TYPE_KEYWORDS[kw])

    doc_type_tags = _classify_doc_type(summary_text, title, type_keywords)

    return full_path, doc_type_tags


def _classify_doc_type(text: str, title: str, type_keywords: list[str]) -> list[str]:
    """从内容中提取文档类型标签。"""
    if not text.strip():
        return []

    search_text = f"{title} {text[:800]}".lower()
    matched = []
    for kw in type_keywords:
        if kw.lower() in search_text:
            matched.append(kw)

    # 去重 + 限制数量
    seen = set()
    result = []
    for tag in matched:
        if tag not in seen and len(tag) >= 2 and len(tag) <= 20:
            seen.add(tag)
            result.append(tag)
            if len(result) >= 5:
                break
    return result


def _classify_flat(summary_text: str, categories: list[str], title: str) -> tuple:
    """旧版平级分类兼容。"""
    CLASSIFY_PROMPT = """你是一个文档分类助手。请根据以下分类体系和文档内容，选择最匹配的分类。

可用分类：{categories}

文档内容摘要：
---
{text}
---

请只返回一个分类名称（必须从上述分类中选择），不要返回其他任何内容。"""

    messages = [
        {
            "role": "user",
            "content": CLASSIFY_PROMPT.format(
                categories="、".join(categories),
                text=summary_text[:1500]
            ),
        },
    ]
    try:
        result = _call_api(messages, max_tokens=20)
        content = result.get("content", "") if isinstance(result, dict) else str(result)
        result = content.strip().strip("[]'\"。")
        if result in categories:
            return result, []
        for cat in categories:
            if cat in result or result in cat:
                return cat, []
        return "其他", []
    except Exception:
        return "其他", []
