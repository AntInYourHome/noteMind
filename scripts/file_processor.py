"""Core file processing pipeline: parse → analyze → build → write."""

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from scripts.parsers import get_parser, ParseResult, IMAGE_EXTS
from scripts.analyzer import AnalysisContext
from scripts.builder import MarkdownBuilder
from scripts.ai_client import analyze_image, generate_tags, generate_outline, generate_summary
from scripts.ingest_analyzer import analyze_document_structure, build_analysis_context_for_summary
from scripts.path_utils import compute_source_relative_path, compute_vault_rel_path
from scripts.status_db import StatusDB
from scripts.ingest_cache import IngestCache, compute_sha256
from scripts.handlers import create_failed_record

logger = logging.getLogger("notemind")


def parse_with_retry(file_path: str, max_retries: int = 3, retry_delay: int = 1):
    """解析文件，返回 ParseResult 或 (None, error_msg)。"""
    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            parser = get_parser(file_path)
            if parser == "image":
                return ParseResult("", [file_path]), ""
            if parser is None:
                return None, "不支持的文件格式"

            result = parser(file_path)
            if not result.has_content:
                return None, "文件内容为空"
            return result, ""
        except PermissionError as e:
            logger.warning(f"  [跳过] 文件被占用: {file_path} — 关闭后下次导入可处理")
            return None, f"文件被占用，跳过（关闭文件后下次导入可处理）"
        except OSError as e:
            if e.errno in (13, 16, 32):
                logger.warning(f"  [跳过] 文件被占用: {file_path} — 关闭后下次导入可处理")
                return None, f"文件被占用，跳过（关闭文件后下次导入可处理）"
            last_error = f"{type(e).__name__}: {e}"
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            if attempt < max_retries:
                logger.warning(f"解析失败 (第 {attempt}/{max_retries} 次): {file_path} — {last_error}")
                time.sleep(retry_delay)
            else:
                logger.error(f"解析失败，已达最大重试次数: {file_path} — {last_error}")

    return None, last_error


def update_frontmatter_tags(file_path: str, tags: list[str]):
    """更新 Markdown 文件 frontmatter 中的 tags 字段。"""
    if not tags:
        return
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        tags_str = ", ".join(tags[:20])
        new_tags_line = f"tags: [{tags_str}]"
        content = content.replace("tags: []", new_tags_line, 1)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        logger.warning(f"  更新标签失败 {file_path}: {e}")


class FileProcessor:
    """处理单个文件的完整流水线。"""

    def __init__(self, cfg: dict, vault_path: str, source_dir: Optional[str],
                 status_db: StatusDB, cache: IngestCache):
        self.cfg = cfg
        self.vault_path = vault_path
        self.source_dir = source_dir
        self.status_db = status_db
        self.cache = cache

    def process(self, file_path: str) -> dict:
        """处理单个文件，返回结果字典。"""
        fname = os.path.basename(file_path)
        safe_name = Path(fname).stem.replace(" ", "_")
        cleanup_paths = []

        try:
            return self._process_impl(file_path, fname, safe_name, cleanup_paths)
        except Exception as e:
            logger.exception(f"  [EXCEPTION] {fname} 处理异常: {e}")
            for p in cleanup_paths:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                        logger.info(f"  [CLEANUP] 移除半成品: {p}")
                except Exception:
                    pass
            return {"status": "fail", "error": f"{type(e).__name__}: {e}", "doc_type_tags": []}

    def _process_impl(self, file_path, fname, safe_name, cleanup_paths) -> dict:
        is_image_file = Path(fname).suffix.lower() in IMAGE_EXTS

        parse_result, error = parse_with_retry(
            file_path,
            self.cfg["ai"].get("max_retries", 3),
            self.cfg["ai"].get("retry_delay", 1),
        )
        if parse_result is None:
            return {"status": "fail", "error": error}

        if is_image_file:
            return self._process_image(file_path, fname, safe_name)

        return self._process_document(parse_result, file_path, fname, safe_name, cleanup_paths)

    def _process_image(self, file_path: str, fname: str, safe_name: str) -> dict:
        """处理纯图片文件。"""
        cache = self.cache
        cache_entry = cache.get(file_path)
        if cache_entry and cache_entry["sha256"] == compute_sha256(file_path):
            logger.info(f"  [CACHE HIT] {fname} — 跳过图片处理")
            return {
                "status": "ok",
                "path": cache_entry["output_files"][0] if cache_entry["output_files"] else "",
                "category": cache_entry.get("category", ""),
                "tags": cache_entry.get("tags", []),
                "summary": "",
            }

        # 分析图片
        try:
            desc = analyze_image(file_path)
        except Exception as e:
            desc = f"（图片分析失败: {e}）"

        # 提取标签
        try:
            tags = generate_tags(desc)
        except Exception:
            tags = []
        all_tags = tags or []

        # 创建 MD 文档
        if self.source_dir:
            source_rel = compute_source_relative_path(file_path, self.source_dir, self.vault_path)
        else:
            source_rel = ""
        vault_rel = compute_vault_rel_path(file_path, self.source_dir or "", self.vault_path)
        dest_dir = os.path.join(self.vault_path, source_rel) if source_rel else self.vault_path
        os.makedirs(dest_dir, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        builder = MarkdownBuilder(fname, date_str)
        builder.add_frontmatter(source_rel, all_tags, source_path=file_path, vault_rel_path=vault_rel).add_title()
        builder.add_file_summary(desc)
        builder.add_archive_link(fname, source_rel, vault_rel)
        builder.add_tags_section(all_tags).add_footer()

        md_name = f"{date_str}-{safe_name}.md"
        dest_path = os.path.join(dest_dir, md_name)
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(builder.build())

        self.status_db.record(file_path, "success", dest_path, source_rel)
        cache.put(file_path, compute_sha256(file_path), [dest_path], source_rel, all_tags)

        return {
            "status": "ok",
            "path": dest_path,
            "category": source_rel,
            "tags": all_tags,
            "summary": desc,
        }

    def _process_document(self, parse_result: ParseResult, file_path: str,
                          fname: str, safe_name: str, cleanup_paths: list) -> dict:
        """处理文档文件（PDF/DOCX/PPTX 等）。"""
        text_count = len(parse_result.text) if parse_result.text else 0
        img_count = len(parse_result.images)
        section_count = len(parse_result.sections)
        logger.info(f"  提取: {text_count} 字符, {img_count} 张内嵌图片, {section_count} 个章节")

        # 两步思维链：分析文档结构
        doc_structure = analyze_document_structure(parse_result.text)
        enhanced_text = build_analysis_context_for_summary(doc_structure, parse_result.text)
        logger.info(f"  [两步分析] 文档类型: {doc_structure['doc_type']}, "
                     f"实体: {len(doc_structure['entities'])}, 概念: {len(doc_structure['concepts'])}")

        chunk_size = self.cfg.get("performance", {}).get("chunk_size", 5)
        analysis = AnalysisContext().analyze(
            enhanced_text, parse_result.images, parse_result.sections,
            max_workers=5, callback=None, chunk_size=chunk_size,
            image_ocr_texts=parse_result.image_ocr_texts
        )
        logger.info(f"  AI 分析完成 (共 {len(analysis.sections)} 章)")

        # 分类
        category = compute_source_relative_path(file_path, self.source_dir, self.vault_path) if self.source_dir else ""
        all_tags = analysis.tags or []

        date_str = datetime.now().strftime("%Y-%m-%d")

        # 构建文档大纲
        section_summaries = [
            {"title": sr.get("title"), "summary": sr.get("summary")}
            for sr in analysis.sections
        ]
        outline_sections = generate_outline(section_summaries)
        if not outline_sections:
            seen = set()
            for sr in analysis.sections:
                t = sr.get("title") or ""
                if t and t not in seen and len(t) > 3:
                    seen.add(t)
                    outline_sections.append(f"- {t}")

        # 全文概述
        overview = ""
        overview_input = "".join(sr.get("summary", "") + "\n" for sr in analysis.sections if sr.get("summary"))
        if overview_input.strip():
            try:
                overview = generate_summary(overview_input[:5000])
            except Exception as e:
                logger.warning(f"  全文概述生成失败: {e}")
                overview = overview_input[:500]

        vault_rel = compute_vault_rel_path(file_path, self.source_dir, self.vault_path)
        builder = MarkdownBuilder(fname, date_str)
        builder.add_frontmatter(category, all_tags, source_path=file_path, vault_rel_path=vault_rel).add_title()
        builder.add_file_summary(overview)
        builder.add_section_title("文档大纲")
        builder.add_paragraph("\n".join(outline_sections))
        builder.add_archive_link(fname, category, vault_rel)
        builder.add_tags_section(all_tags).add_footer()

        # 写入
        dest_dir = os.path.join(self.vault_path, category)
        os.makedirs(dest_dir, exist_ok=True)
        filename = f"{date_str}-{safe_name}.md"
        dest_path = os.path.join(dest_dir, filename)

        if os.path.exists(dest_path):
            base, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(dest_path):
                dest_path = os.path.join(dest_dir, f"{base}_{counter}{ext}")
                counter += 1

        cleanup_paths.append(dest_path)
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(builder.build())

        # 去重索引
        if self.cfg["import"].get("dedup", True):
            from scripts.dedup import compute_md5, add_to_index
            dedup_index = self.cfg["import"].get("dedup_index", ".notemind_index.json")
            md5 = compute_md5(file_path)
            add_to_index(file_path, md5, category, dest_path, self.vault_path, dedup_index)

        self.status_db.record(file_path, "success", dest_path, category)
        cleanup_paths.clear()

        return {
            "status": "ok",
            "path": dest_path,
            "category": category,
            "tags": all_tags,
            "summary": overview,
        }
