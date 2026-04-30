"""
NoteMind AI 分析策略 — 短文档单摘要 vs 长文档逐章摘要
支持并发调度（AgentScheduler）加速长文档处理
"""

import logging

from scripts.ai_client import analyze_image, generate_summary, generate_tags

logger = logging.getLogger("notemind")


class AnalysisResult:
    """AI 分析结果。"""
    def __init__(self):
        self.sections = []  # [{"title": "...", "summary": "...", "text": "..."}]
        self.tags = []
        self.image_descriptions = []


class ShortDocStrategy:
    """短文档策略：全文一个摘要。"""

    def analyze(self, text: str, images: list[str]) -> AnalysisResult:
        result = AnalysisResult()

        if text.strip():
            summary = generate_summary(text)
            result.sections.append({"title": "", "summary": summary, "text": text})
            result.tags = generate_tags(text)

        # 图片识别
        for img_path in images:
            try:
                desc = analyze_image(img_path)
                result.image_descriptions.append(desc)
                if desc:
                    result.tags.extend(generate_tags(desc))
            except Exception as e:
                result.image_descriptions.append(f"（图片识别失败: {e}）")

        return result


class LongDocStrategy:
    """长文档策略：逐章摘要（支持并发）。"""

    def analyze(self, sections: list, images: list[str], scheduler=None) -> AnalysisResult:
        result = AnalysisResult()

        if scheduler:
            # 并发模式：批量提交所有章节摘要和标签任务
            section_texts = [s.text for s in sections if s.text.strip()]
            batch = scheduler.analyze_batch(section_texts, images)

            ti = 0
            for section in sections:
                if section.text.strip():
                    summary = batch["summaries"][ti] if ti < len(batch["summaries"]) else ""
                    result.sections.append({
                        "title": section.title,
                        "summary": summary,
                        "text": section.text,
                    })
                    tags = batch["tags"][ti] if ti < len(batch["tags"]) else []
                    result.tags.extend(tags)
                    ti += 1
                else:
                    result.sections.append({"title": section.title, "summary": "", "text": ""})

            result.image_descriptions = batch["image_descs"]
            for desc in batch["image_descs"]:
                if desc and not desc.startswith("（"):
                    result.tags.extend(generate_tags(desc))
        else:
            # 串行模式（向后兼容）— 带进度日志
            total_sections = len(sections)
            for i, section in enumerate(sections):
                if section.text.strip():
                    title = section.title or f"章节 {i+1}"
                    logger.info(f"  AI 分析章节 [{i+1}/{total_sections}]: {title}")
                    summary = generate_summary(section.text)
                    result.sections.append({
                        "title": section.title,
                        "summary": summary,
                        "text": section.text,
                    })
                    result.tags.extend(generate_tags(section.text))
                else:
                    result.sections.append({"title": section.title, "summary": "", "text": ""})

            logger.info(f"  AI 章节分析完成 (共 {total_sections} 章)")

            # 图片识别
            for i, img_path in enumerate(images):
                logger.info(f"  AI 识别图片 [{i+1}/{len(images)}]: {img_path}")
                try:
                    desc = analyze_image(img_path)
                    result.image_descriptions.append(desc)
                    if desc:
                        result.tags.extend(generate_tags(desc))
                except Exception as e:
                    result.image_descriptions.append(f"（图片识别失败: {e}）")

        return result


class AnalysisContext:
    """分析上下文：选择策略。"""

    TEXT_THRESHOLD = 3000      # 字数阈值
    SECTION_THRESHOLD = 3      # 章节数阈值

    def analyze(self, text: str, images: list[str], sections: list, scheduler=None) -> AnalysisResult:
        """根据文档特征选择策略。"""
        # 有结构化章节 → 长文档策略
        if len(sections) >= self.SECTION_THRESHOLD:
            return LongDocStrategy().analyze(sections, images, scheduler)

        # 文字量大 → 长文档策略
        if len(text) >= self.TEXT_THRESHOLD and sections:
            return LongDocStrategy().analyze(sections, images, scheduler)

        # 否则 → 短文档策略
        return ShortDocStrategy().analyze(text, images)
