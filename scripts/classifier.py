"""
NoteMind 分类器 — AI 自动分类
简单工厂模式
"""

from scripts.ai_client import _call_api


def classify(summary_text: str, categories: list[str]) -> str:
    """根据摘要内容，AI 推荐分类。"""
    if not summary_text.strip():
        return "其他"

    cat_text = ", ".join(categories)
    messages = [
        {
            "role": "user",
            "content": (
                f"请将以下内容归类到以下分类之一：[{cat_text}]。\n\n"
                f"只返回分类名称，不要返回其他内容。\n\n"
                f"内容摘要：{summary_text[:300]}"
            ),
        }
    ]

    result = _call_api(messages, max_tokens=20)
    if result in categories:
        return result
    return "其他"
