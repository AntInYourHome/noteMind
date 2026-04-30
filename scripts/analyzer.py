"""
NoteMind AI 分析策略 — 短文档单摘要 vs 长文档逐章摘要
支持流式输出：逐章分析完成即返回，防止中间失败导致全部丢失
支持章节合并：减少 API 调用次数，降低成本
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
    """长文档策略：逐章摘要 + 流式输出。

    支持合并章节减少 API 调用。
    """

    def analyze(self, sections: list, images: list[str], scheduler=None,
                callback=None, chunk_size: int = 1) -> AnalysisResult:
        """逐章分析。

        Args:
            sections: 章节列表
            images: 图片路径列表
            scheduler: 可选，AgentScheduler 实例（批量并发模式）
            callback: 可选，每章分析完成后调用
                      callback(index, total, section_result)
                      section_result = {"title": "...", "summary": "...", "text": "..."}
            chunk_size: 合并章节数，默认 1（不合并），建议 3-5

        Returns:
            完整的 AnalysisResult（包含所有章节结果）
        """
        result = AnalysisResult()

        if chunk_size > 1:
            # 合并模式：先按 chunk 分析，再拆分回原章节
            self._analyze_chunked(sections, images, scheduler, callback, chunk_size, result)
        elif scheduler:
            # 并发模式：逐章提交，完成一个就回调一个
            self._analyze_concurrent(sections, images, scheduler, result, callback)
        else:
            # 串行模式：逐章分析 + 进度日志 + 回调
            self._analyze_serial(sections, images, result, callback)

        return result

    def _analyze_chunked(self, sections, images, scheduler, callback, chunk_size, result):
        """合并章节分析：每 chunk_size 页合并一次 API 调用。

        每个 chunk 分析完成后，将摘要平均分配给该 chunk 内的所有章节。
        """
        chunks = chunk_sections(sections, chunk_size)
        total_sections = len(sections)
        total_chunks = len(chunks)
        logger.info(f"  [合并] {total_sections} 章合并为 {total_chunks} 组（每组 {chunk_size} 章）")

        for i, chunk in enumerate(chunks):
            chunk_start = sections.index(chunk["sections"][0])
            logger.info(f"  AI 分析组 [{i+1}/{total_chunks}] (含 {len(chunk['sections'])} 章)")
            try:
                summary = generate_summary(chunk["combined_text"])
                tags = generate_tags(chunk["combined_text"])
            except Exception as e:
                logger.error(f"  [FAIL] 分析组 {i+1} 失败: {e}")
                summary = f"（分析失败: {e}）"
                tags = []

            # 将摘要分配给该 chunk 内的所有章节
            for sec in chunk["sections"]:
                section_result = {
                    "title": sec.title,
                    "summary": summary,
                    "text": sec.text,
                }
                result.sections.append(section_result)
                result.tags.extend(tags)

                idx = sections.index(sec)
                if callback:
                    callback(idx, total_sections, section_result)

        logger.info(f"  AI 分组分析完成 (共 {total_chunks} 组 → {total_sections} 章)")

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

    def _analyze_serial(self, sections, images, result, callback):
        """串行逐章分析。"""
        total_sections = len(sections)
        for i, section in enumerate(sections):
            if section.text.strip():
                title = section.title or f"章节 {i+1}"
                logger.info(f"  AI 分析章节 [{i+1}/{total_sections}]: {title}")
                try:
                    summary = generate_summary(section.text)
                    tags = generate_tags(section.text)
                except Exception as e:
                    logger.error(f"  [FAIL] 章节 {title} AI 分析失败: {e}")
                    summary = f"（分析失败: {e}）"
                    tags = []

                section_result = {
                    "title": section.title,
                    "summary": summary,
                    "text": section.text,
                }
                result.sections.append(section_result)
                result.tags.extend(tags)

                # 每章完成即回调
                if callback:
                    callback(i, total_sections, section_result)
            else:
                section_result = {"title": section.title, "summary": "", "text": ""}
                result.sections.append(section_result)
                if callback:
                    callback(i, total_sections, section_result)

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

    def _analyze_concurrent(self, sections, images, scheduler, result, callback):
        """并发分析：逐章完成即回调。

        不再使用 scheduler.analyze_batch() 的"全部等待"模式，
        而是直接提交任务，按完成顺序逐个处理。
        """
        section_texts = [(i, s.text) for i, s in enumerate(sections) if s.text.strip()]
        total_sections = len(sections)

        if not section_texts:
            # 无文本内容，直接返回
            for section in sections:
                result.sections.append({"title": section.title, "summary": "", "text": ""})
            return

        # 构建摘要和标签任务
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
            tasks.append({
                "messages": [{
                    "role": "user",
                    "content": f"请从以下内容中提取 3-8 个中文标签（关键词），用逗号分隔，只返回标签：\n\n{text[:3000]}"
                }],
                "max_tokens": 100,
                "section_index": idx,
                "task_type": "tags",
                "text": text,
            })

        # 图片任务
        for img_path in images:
            tasks.append({
                "task_type": "image",
                "img_path": img_path,
            })

        # 并发执行，逐完成即处理
        pool_size = scheduler.max_workers
        results_map = {}  # section_index -> {"summary": ..., "tags": ...}
        pending = {}  # future -> task

        def run_summary(task):
            return task, generate_summary(task["text"])

        def run_tags(task):
            return task, generate_tags(task["text"])

        def run_image(task):
            return task, analyze_image(task["img_path"])

        with ThreadPoolExecutor(max_workers=pool_size) as executor:
            # 先提交所有文本任务
            for task in tasks:
                if task["task_type"] == "summary":
                    future = executor.submit(run_summary, task)
                elif task["task_type"] == "tags":
                    future = executor.submit(run_tags, task)
                else:
                    future = executor.submit(run_image, task)
                pending[future] = task

            # 逐完成处理
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
                        results_map[idx] = {"summary": "", "tags": []}
                    results_map[idx]["summary"] = result_value

                    # 如果标签也已就绪，输出完整章节
                    if "tags_ready" in results_map.get(idx, {}):
                        self._emit_section(idx, sections, results_map[idx], result, callback)
                        completed_sections.add(idx)

                elif task["task_type"] == "tags":
                    idx = task["section_index"]
                    if idx not in results_map:
                        results_map[idx] = {"summary": "", "tags": []}
                    if isinstance(result_value, list):
                        results_map[idx]["tags"] = result_value
                    else:
                        results_map[idx]["tags"] = []
                    results_map[idx]["tags_ready"] = True

                    # 如果摘要也已就绪，输出完整章节
                    if results_map[idx]["summary"]:
                        self._emit_section(idx, sections, results_map[idx], result, callback)
                        completed_sections.add(idx)

                else:  # image
                    result.image_descriptions.append(result_value)
                    if result_value and not str(result_value).startswith("（"):
                        try:
                            result.tags.extend(generate_tags(result_value))
                        except Exception:
                            pass

        # 处理未完成的章节（比如标签成功但摘要失败的）
        for idx, text in section_texts:
            if idx not in completed_sections:
                data = results_map.get(idx, {"summary": "", "tags": []})
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
        result.tags.extend(data.get("tags", []))

        if callback:
            callback(index, len(sections), section_result)


class AnalysisContext:
    """分析上下文：选择策略。"""

    TEXT_THRESHOLD = 3000      # 字数阈值
    SECTION_THRESHOLD = 3      # 章节数阈值

    def analyze(self, text: str, images: list[str], sections: list, scheduler=None,
                callback=None, chunk_size: int = 1) -> AnalysisResult:
        """根据文档特征选择策略。

        Args:
            callback: 可选，每章分析完成后回调
            chunk_size: 合并章节数，默认 1（不合并），建议 3-5
        """
        # 有结构化章节 → 长文档策略
        if len(sections) >= self.SECTION_THRESHOLD:
            return LongDocStrategy().analyze(sections, images, scheduler, callback, chunk_size)

        # 文字量大 → 长文档策略
        if len(text) >= self.TEXT_THRESHOLD and sections:
            return LongDocStrategy().analyze(sections, images, scheduler, callback, chunk_size)

        # 否则 → 短文档策略
        return ShortDocStrategy().analyze(text, images)
