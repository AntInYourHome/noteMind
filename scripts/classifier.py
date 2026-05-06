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


def classify(summary_text: str, categories: list[str]) -> str:
    """根据摘要内容，AI 推荐分类。

    改进：
    - 使用完整摘要而非截断文本
    - 强化 prompt 指令，确保返回有效分类
    - 如果无法匹配则返回"其他"
    """
    if not summary_text.strip() or not categories:
        return "其他"

    messages = [
        {
            "role": "user",
            "content": CLASSIFY_PROMPT.format(
                categories="、".join(categories),
                text=summary_text[:1500]  # 增加到 1500 字符
            ),
        },
    ]

    try:
        result = _call_api(messages, max_tokens=20)
        result = result.strip().strip("[]'\"。")
        if result in categories:
            return result
        # 模糊匹配
        for cat in categories:
            if cat in result or result in cat:
                return cat
        return "其他"
    except Exception:
        return "其他"
