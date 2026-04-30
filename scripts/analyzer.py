"""
NoteMind AI 分析策略 — 短文档单摘要 vs 长文档逐章摘要
策略模式：根据文档结构选择处理方式
"""

from scripts.ai_client import analyze_image, generate_summary, generate_tags


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
    """长文档策略：逐章摘要。"""

    def analyze(self, sections: list, images: list[str]) -> AnalysisResult:
        result = AnalysisResult()

        # 逐章处理
        for section in sections:
            if section.text.strip():
                summary = generate_summary(section.text)
                result.sections.append({
                    "title": section.title,
                    "summary": summary,
                    "text": section.text,
                })
                result.tags.extend(generate_tags(section.text))
            else:
                result.sections.append({"title": section.title, "summary": "", "text": ""})

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


class AnalysisContext:
    """分析上下文：选择策略。"""

    TEXT_THRESHOLD = 3000      # 字数阈值
    SECTION_THRESHOLD = 3      # 章节数阈值

    def analyze(self, text: str, images: list[str], sections: list) -> AnalysisResult:
        """根据文档特征选择策略。"""
        # 有结构化章节 → 长文档策略
        if len(sections) >= self.SECTION_THRESHOLD:
            return LongDocStrategy().analyze(sections, images)

        # 文字量大 → 长文档策略
        if len(text) >= self.TEXT_THRESHOLD and sections:
            return LongDocStrategy().analyze(sections, images)

        # 否则 → 短文档策略
        return ShortDocStrategy().analyze(text, images)
