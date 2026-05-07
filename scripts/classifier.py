"""
NoteMind 分类器 — AI 自动分类
"""

from scripts.ai_client import _call_api

# 分类提示词模板 — 强化指令，避免返回"其他"
CLASSIFY_PROMPT = """你是一个文档分类助手。请根据以下分类体系和文档内容，选择最匹配的分类。

可用分类：{categories}

文档内容摘要：
---
{text}
---

请只返回一个分类名称（必须从上述分类中选择），不要返回其他任何内容。"""

# 每个分类的关键词映射，用于辅助判断
CATEGORY_KEYWORDS = {
    "芯片": ["芯片", "半导体", "SoC", "CPU", "GPU", "NPU", "制程", "晶体管", "封装", "晶圆", "IP", "核"],
    "安全": ["安全", "权限", "攻击", "漏洞", "加密", "漏洞", "防护", "威胁", "风险", "恶意", "黑客", "隐私"],
    "项目": ["项目", "计划", "方案", "需求", "开发", "交付", "里程碑", "评审", "迭代", "排期", "架构"],
    "笔记": ["笔记", "总结", "学习", "心得", "体会", "记录", "备忘", "思考", "课堂", "教程"],
}


def classify(summary_text: str, categories: list[str], title: str = "") -> str:
    """根据摘要内容，AI 推荐分类。

    Args:
        summary_text: 文档摘要文本
        categories: 可用分类列表
        title: 文档标题/文件名，辅助判断
    """
    if not summary_text.strip() or not categories:
        return "其他"

    # 先做关键词匹配（快速路径）
    search_text = f"{title} {summary_text[:500]}".lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if cat in categories:
            for kw in keywords:
                if kw.lower() in search_text:
                    # 找到关键词，增加置信度
                    break

    # AI 分类
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
        # _call_api 返回 dict: {"content": str, ...}
        content = result.get("content", "") if isinstance(result, dict) else str(result)
        result = content.strip().strip("[]'\"。")
        if result in categories:
            return result
        # 模糊匹配
        for cat in categories:
            if cat in result or result in cat:
                return cat
        return "其他"
    except Exception:
        return "其他"
