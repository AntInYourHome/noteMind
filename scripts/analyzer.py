"""
NoteMind AI 分析策略 — 短文档单摘要 vs 长文档逐章摘要
标签优化：一篇文档只生成一次标签，从全文生成，不逐章/逐图片生成
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from scripts.ai_client import analyze_image, generate_summary, generate_tags

logger = logging.getLogger("notemind")

# --- 章节合并 ---

def chunk_sections(sections, chunk_size: int = 5):
    """将章节按 chunk_size 合并为组，减少 API 调用次数。

    Args:
        sections: 原始章节列表
        chunk_size: 每组包含的章节数（默认 5）

    Returns:
        [{"sections": [原始章节...], "combined_text": "合并后的文本"}, ...]
    """
    chunks = []
    for i in range(0, max(len(sections), 1), chunk_size):
        group = sections[i:i + chunk_size]
        combined_text = "\n\n---\n\n".join(s.text for s in group if s.text)
        if combined_text.strip():
            chunks.append({
                "sections": group,
                "combined_text": combined_text,
            })
    return chunks


class AnalysisResult:
    """AI 分析结果。"""
    def __init__(self):
        self.sections = []  # [{"title": "...", "summary": "...", "text": "..."}]
        self.tags = []
        self.image_descriptions = []


class ShortDocStrategy:
    """短文档策略：全文一个摘要 + 一次标签。"""

    def analyze(self, text: str, images: list[str], image_ocr_texts: list[str] = None) -> AnalysisResult:
        result = AnalysisResult()

        if text.strip():
            summary = generate_summary(text)
            result.sections.append({"title": "", "summary": summary, "text": text})
            # 标签从全文生成，不是逐图片生成
            result.tags = _clean_tags(generate_tags(text))

        # 图片只生成描述，不生成标签
        for i, img_path in enumerate(images):
            try:
                ocr_text = ""
                if image_ocr_texts and i < len(image_ocr_texts):
                    ocr_text = image_ocr_texts[i]

                if ocr_text and ocr_text.strip():
                    result.image_descriptions.append(ocr_text)
                else:
                    desc = analyze_image(img_path)
                    result.image_descriptions.append(desc)
            except Exception as e:
                result.image_descriptions.append(f"（图片识别失败: {e}）")

        return result


class LongDocStrategy:
    """长文档策略：逐章摘要 + 全文一次标签。"""

    def analyze(self, sections: list, images: list[str], max_workers: int = 5,
                callback=None, chunk_size: int = 1,
                image_ocr_texts: list[str] = None) -> AnalysisResult:
        """逐章分析。

        Args:
            sections: 章节列表
            images: 图片路径列表
            max_workers: 最大并发数，默认 5
            callback: 可选，每章分析完成后调用
                      callback(index, total, section_result)
                      section_result = {"title": "...", "summary": "...", "text": "..."}
            chunk_size: 合并章节数，默认 1（不合并），建议 3-5
            image_ocr_texts: 可选，图片的 OCR 文本列表（与 images 一一对应）

        Returns:
            完整的 AnalysisResult（包含所有章节结果）
        """
        result = AnalysisResult()

        if chunk_size > 1:
            self._analyze_chunked(sections, images, callback, chunk_size, result,
                                  image_ocr_texts)
        elif max_workers > 1:
            self._analyze_concurrent(sections, images, max_workers, result, callback,
                                     image_ocr_texts)
        else:
            self._analyze_serial(sections, images, result, callback, image_ocr_texts)

        # 标签从所有章节文本合并生成，不是逐章生成
        all_text = "\n\n".join(s["text"] for s in result.sections if s.get("text"))
        if all_text.strip():
            result.tags = _clean_tags(generate_tags(all_text))
        # 图片只生成描述，不生成标签

        return result

    def _analyze_chunked(self, sections, images, callback, chunk_size, result,
                         image_ocr_texts=None):
        """合并章节分析：每 chunk_size 页合并一次 API 调用。"""
        chunks = chunk_sections(sections, chunk_size)
        total_sections = len(sections)
        total_chunks = len(chunks)
        logger.info(f"  [合并] {total_sections} 章合并为 {total_chunks} 组（每组 {chunk_size} 章）")

        for i, chunk in enumerate(chunks):
            logger.info(f"  AI 分析组 [{i+1}/{total_chunks}] (含 {len(chunk['sections'])} 章)")
            try:
                summary = generate_summary(chunk["combined_text"])
            except Exception as e:
                logger.error(f"  [FAIL] 分析组 {i+1} 失败: {e}")
                summary = f"（分析失败: {e}）"

            # 将摘要分配给该 chunk 内的所有章节
            for sec in chunk["sections"]:
                section_result = {
                    "title": sec.title,
                    "summary": summary,
                    "text": sec.text,
                }
                result.sections.append(section_result)

                idx = sections.index(sec)
                if callback:
                    callback(idx, total_sections, section_result)

        logger.info(f"  AI 分组分析完成 (共 {total_chunks} 组 → {total_sections} 章)")

        # 图片只生成描述
        for i, img_path in enumerate(images):
            ocr_text = ""
            if image_ocr_texts and i < len(image_ocr_texts):
                ocr_text = image_ocr_texts[i]
            try:
                if ocr_text and ocr_text.strip():
                    result.image_descriptions.append(ocr_text)
                else:
                    desc = analyze_image(img_path)
                    result.image_descriptions.append(desc)
            except Exception as e:
                result.image_descriptions.append(f"（图片识别失败: {e}）")

    def _analyze_serial(self, sections, images, result, callback, image_ocr_texts=None):
        """串行逐章分析。"""
        total_sections = len(sections)
        for i, section in enumerate(sections):
            if section.text.strip():
                title = section.title or f"章节 {i+1}"
                logger.info(f"  AI 分析章节 [{i+1}/{total_sections}]: {title}")
                try:
                    summary = generate_summary(section.text)
                except Exception as e:
                    logger.error(f"  [FAIL] 章节 {title} AI 分析失败: {e}")
                    summary = f"（分析失败: {e}）"

                section_result = {
                    "title": section.title,
                    "summary": summary,
                    "text": section.text,
                }
                result.sections.append(section_result)

                # 每章完成即回调
                if callback:
                    callback(i, total_sections, section_result)
            else:
                section_result = {"title": section.title, "summary": "", "text": ""}
                result.sections.append(section_result)
                if callback:
                    callback(i, total_sections, section_result)

        logger.info(f"  AI 章节分析完成 (共 {total_sections} 章)")

        # 图片只生成描述
        for i, img_path in enumerate(images):
            ocr_text = ""
            if image_ocr_texts and i < len(image_ocr_texts):
                ocr_text = image_ocr_texts[i]
            try:
                if ocr_text and ocr_text.strip():
                    result.image_descriptions.append(ocr_text)
                else:
                    desc = analyze_image(img_path)
                    result.image_descriptions.append(desc)
            except Exception as e:
                result.image_descriptions.append(f"（图片识别失败: {e}）")

    def _analyze_concurrent(self, sections, images, max_workers: int = 5, result=None, callback=None,
                            image_ocr_texts=None):
        """并发分析：逐章完成即回调。"""
        section_texts = [(i, s.text) for i, s in enumerate(sections) if s.text.strip()]
        total_sections = len(sections)

        if not section_texts:
            for section in sections:
                result.sections.append({"title": section.title, "summary": "", "text": ""})
            return

        # 只构建摘要任务（标签最后从全文生成）
        tasks = []
        for idx, text in section_texts:
            tasks.append({
                "messages": [{
                    "role": "user",
                    "content": f"请用中文总结以下内容，提取核心要点（3-5 条），控制在 300 字以内：\n\n{text[:5000]}"
                }],
                "max_tokens": 300,
                "section_index": idx,
                "task_type": "summary",
                "text": text,
            })

        # 图片任务
        for i, img_path in enumerate(images):
            ocr_text = ""
            if image_ocr_texts and i < len(image_ocr_texts):
                ocr_text = image_ocr_texts[i]
            if ocr_text and ocr_text.strip():
                result.image_descriptions.append(ocr_text)
            else:
                tasks.append({
                    "task_type": "image",
                    "img_path": img_path,
                })

        # 并发执行
        pool_size = max_workers
        results_map = {}  # section_index -> {"summary": ...}
        pending = {}

        def run_summary(task):
            return task, generate_summary(task["text"])

        def run_image(task):
            return task, analyze_image(task["img_path"])

        with ThreadPoolExecutor(max_workers=pool_size) as executor:
            for task in tasks:
                if task["task_type"] == "summary":
                    future = executor.submit(run_summary, task)
                else:
                    future = executor.submit(run_image, task)
                pending[future] = task

            completed_sections = set()
            for future in as_completed(pending):
                task = pending[future]
                try:
                    _, result_value = future.result()
                except Exception as e:
                    result_value = f"（失败: {e}）"

                if task["task_type"] == "summary":
                    idx = task["section_index"]
                    if idx not in results_map:
                        results_map[idx] = {"summary": ""}
                    results_map[idx]["summary"] = result_value
                    self._emit_section(idx, sections, results_map[idx], result, callback)
                    completed_sections.add(idx)

                else:  # image
                    result.image_descriptions.append(result_value)

        for idx, text in section_texts:
            if idx not in completed_sections:
                data = results_map.get(idx, {"summary": ""})
                self._emit_section(idx, sections, data, result, callback)

    def _emit_section(self, index: int, sections: list, data: dict,
                      result: AnalysisResult, callback):
        """输出一个已完成的章节。"""
        section = sections[index]
        section_result = {
            "title": section.title,
            "summary": data.get("summary", ""),
            "text": section.text,
        }
        result.sections.append(section_result)

        if callback:
            callback(index, len(sections), section_result)


class AnalysisContext:
    """分析上下文：选择策略。"""

    TEXT_THRESHOLD = 3000      # 字数阈值
    SECTION_THRESHOLD = 3      # 章节数阈值

    def analyze(self, text: str, images: list[str], sections: list, max_workers: int = 5,
                callback=None, chunk_size: int = 1,
                image_ocr_texts: list[str] = None) -> AnalysisResult:
        """根据文档特征选择策略。

        Args:
            max_workers: 最大并发数，默认 5
            callback: 可选，每章分析完成后回调
            chunk_size: 合并章节数，默认 1（不合并），建议 3-5
            image_ocr_texts: 可选，图片的 OCR 文本列表（与 images 一一对应）
        """
        # 有结构化章节 → 长文档策略
        if len(sections) >= self.SECTION_THRESHOLD:
            return LongDocStrategy().analyze(sections, images, max_workers, callback, chunk_size,
                                             image_ocr_texts)

        # 文字量大 → 长文档策略
        if len(text) >= self.TEXT_THRESHOLD and sections:
            return LongDocStrategy().analyze(sections, images, max_workers, callback, chunk_size,
                                             image_ocr_texts)

        # 否则 → 短文档策略
        return ShortDocStrategy().analyze(text, images, image_ocr_texts)


def _clean_tags(tags: list[str]) -> list[str]:
    """清理和去重标签。

    - 去重
    - 过滤单字标签
    - 过滤太长的标签（>20 字）
    - 最多保留 8 个
    """
    seen = set()
    cleaned = []
    for tag in tags:
        tag = tag.strip()
        if not tag or len(tag) < 2 or len(tag) > 20:
            continue
        if tag in seen:
            continue
        seen.add(tag)
        cleaned.append(tag)
        if len(cleaned) >= 8:
            break
    return cleaned
