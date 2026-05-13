"""
NoteMind — 两步思维链摄入（第一步：分析）

在生成摘要和标签之前，先对文档进行结构化分析：
1. 关键实体（人物、组织、产品、地点）
2. 关键概念（理论、方法、技术）
3. 核心论点/发现
4. 文档类型推断（技术文档、报告、论文、新闻...）

第二步（生成）仍在 analyzer.py 中，使用第一步的分析结果作为上下文。
"""

import logging

from scripts.ai_client import _call_api, _perf_stats

logger = logging.getLogger("notemind")

_DOCUMENT_ANALYSIS_SYSTEM = """你是文档结构分析专家。始终用中文输出。

分析以下文档，提取以下信息（JSON 格式）：
{
  "entities": ["关键实体（人物、组织、产品、地点）"],
  "concepts": ["关键概念（理论、方法、技术）"],
  "key_points": ["核心论点/发现（3-5条）"],
  "doc_type": "文档类型（技术文档/学术论文/新闻报道/会议纪要/项目报告/培训资料/其他）",
  "summary_hint": "一句话概述文档核心内容（50字以内）"
}

只输出 JSON，不要其他内容。"""


def analyze_document_structure(text: str, max_tokens: int = 500) -> dict:
    """
    第一步：结构化分析文档。返回实体、概念、论点、文档类型等。

    Args:
        text: 文档全文
        max_tokens: 最大输出 token 数

    Returns:
        {
            "entities": [...],
            "concepts": [...],
            "key_points": [...],
            "doc_type": "...",
            "summary_hint": "..."
        }
    """
    if len(text) < 100:
        return {
            "entities": [],
            "concepts": [],
            "key_points": [],
            "doc_type": "短文本",
            "summary_hint": text[:50],
        }

    messages = [
        {"role": "system", "content": _DOCUMENT_ANALYSIS_SYSTEM},
        {"role": "user", "content": text[:6000]},  # 截断避免超长
    ]

    try:
        import json
        result = _call_api(messages, max_tokens=max_tokens)
        _perf_stats["api_calls"] += 1
        _perf_stats["input_tokens"] += result.get("input_tokens", 0)
        _perf_stats["output_tokens"] += result.get("output_tokens", 0)
        _perf_stats["total_latency"] += result.get("latency", 0)
        raw = result.get("content", "").strip()

        # 尝试解析 JSON（容忍 ```json ... ``` 包裹）
        if raw.startswith("```"):
            # 去除代码块标记
            lines = raw.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            raw = "\n".join(lines)

        parsed = json.loads(raw)
        return {
            "entities": parsed.get("entities", []),
            "concepts": parsed.get("concepts", []),
            "key_points": parsed.get("key_points", []),
            "doc_type": parsed.get("doc_type", "未知"),
            "summary_hint": parsed.get("summary_hint", ""),
        }
    except Exception as e:
        logger.warning(f"  文档结构分析失败: {e}")
        # 回退：返回空分析
        return {
            "entities": [],
            "concepts": [],
            "key_points": [],
            "doc_type": "未知",
            "summary_hint": text[:50] if text else "",
        }


def build_analysis_context_for_summary(structure: dict, original_text: str) -> str:
    """
    将第一步的分析结果构建为第二步（摘要生成）的增强上下文。

    Args:
        structure: analyze_document_structure 返回的分析结果
        original_text: 文档原文

    Returns:
        增强后的摘要生成 prompt 文本
    """
    context_parts = []

    if structure.get("summary_hint"):
        context_parts.append(f"文档核心概述: {structure['summary_hint']}")

    if structure.get("key_points"):
        points = "\n".join(f"- {p}" for p in structure["key_points"])
        context_parts.append(f"关键论点:\n{points}")

    if structure.get("entities"):
        entities = ", ".join(structure["entities"])
        context_parts.append(f"涉及实体: {entities}")

    if structure.get("concepts"):
        concepts = ", ".join(structure["concepts"])
        context_parts.append(f"涉及概念: {concepts}")

    if context_parts:
        return f"【结构分析结果】\n" + "\n\n".join(context_parts) + f"\n\n【文档原文】\n{original_text}"

    return original_text
