#!/usr/bin/env python3
"""
NoteMind — 文件导入到 Obsidian Vault
流程编排：解析 → AI 分析 → 构建 Markdown → 写入 Vault

用法：
    ./import.py --source /path/to/files
    ./import.py --source /path/to/files --vault ~/my-vault
    ./import.py --source /path/to/files --dry-run
    ./import.py --source /path/to/files --resume  # 从上次中断处继续
"""

import argparse
import json
import logging
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

# 初始化日志
logger = logging.getLogger("notemind")


def load_config(override_vault: str = None, config_path: str = None) -> dict:
    """加载配置文件。"""
    if config_path is None:
        config_path = Path(__file__).parent / "config.json"
    cfg_path = Path(config_path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {cfg_path}")
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    vault_path = override_vault or cfg["vault"]["path"]
    cfg["vault"]["path"] = os.path.expanduser(vault_path)
    return cfg


# 处理状态记录（SQLite）- 跟踪文件更新
STATUS_DB = ".notemind_status.db"
_status_db_conn = None


def _get_status_db(vault_path: str):
    """获取状态数据库连接（单例）。"""
    global _status_db_conn
    if _status_db_conn is not None:
        return _status_db_conn

    import sqlite3
    db_path = os.path.join(vault_path, STATUS_DB)
    # 确保目录存在
    os.makedirs(vault_path, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS file_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_path TEXT UNIQUE,  -- 源文件路径（--source），UNIQUE 保证 INSERT OR REPLACE 生效
            file_name TEXT,
            status TEXT,  -- 'success', 'failed', 'updated', 'unchanged'
            md_path TEXT,
            category TEXT,
            error TEXT,
            file_size INTEGER,
            file_mtime TEXT,  -- 文件修改时间
            file_md5 TEXT,  -- 文件 MD5（检测变化）
            processed_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON file_status(source_path)")
    conn.commit()
    _status_db_conn = conn
    return conn


def compute_file_hash(file_path: str) -> str:
    """计算文件 MD5。"""
    import hashlib
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_source_relative_path(file_path: str, source_dir: str, vault_path: str) -> str:
    """计算 vault 内镜像 source 结构的相对目录路径。

    例如: source=/vault/source, file=/vault/source/安全/白皮书.pdf → "安全"
    文件在 source 根目录时返回 "其他"。
    source 不在 vault 下时返回 "其他/外部文件"。
    """
    rel = os.path.relpath(file_path, source_dir)  # e.g., "安全/白皮书.pdf"
    rel_dir = os.path.dirname(rel)                 # e.g., "安全"
    if not rel_dir:
        return "其他"
    # 安全检查：防止路径穿越
    abs_dest = os.path.normpath(os.path.join(vault_path, rel_dir))
    abs_vault = os.path.normpath(vault_path)
    if not abs_dest.startswith(abs_vault + os.sep) and abs_dest != abs_vault:
        return "其他/外部文件"
    return rel_dir


def compute_vault_rel_path(file_path: str, source_dir: str, vault_path: str) -> str:
    """计算源文件相对于 vault 的路径，用于 MD 文档的 original_path。

    如果 source 在 vault 下，返回 vault 内相对路径。
    否则返回 source_dir 内的相对路径（带 source/ 前缀）。
    """
    try:
        rel = os.path.relpath(file_path, vault_path)
        if not rel.startswith(".."):
            return rel
    except (ValueError, OSError):
        pass
    # source 在 vault 外，使用 source 内相对路径
    try:
        src_rel = os.path.relpath(file_path, source_dir)
        return f"source/{src_rel}"
    except (ValueError, OSError):
        return os.path.basename(file_path)


def check_file_updated(vault_path: str, file_path: str) -> tuple[str, bool]:
    """检查文件是否有更新。

    Returns:
        (previous_status, is_updated)
        - previous_status: 之前的状态 ('success', 'failed', 'unchanged', None)
        - is_updated: True 如果文件有变化
    """
    import sqlite3
    conn = _get_status_db(vault_path)

    file_size = os.path.getsize(file_path)
    file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path)).strftime("%Y-%m-%d %H:%M:%S")
    current_md5 = compute_file_hash(file_path)

    # 查询之前的状态
    row = conn.execute(
        "SELECT status, file_size, file_mtime, file_md5 FROM file_status WHERE source_path = ?",
        (file_path,)
    ).fetchone()

    if row is None:
        return None, True  # 新文件

    prev_status, prev_size, prev_mtime, prev_md5 = row

    # 检测变化：MD5 或大小变化
    is_updated = (prev_md5 != current_md5) or (prev_size != file_size)

    return prev_status, is_updated


def record_status(vault_path: str, file_path: str, status_type: str, md_path: str = None, category: str = None, error: str = None):
    """记录单个文件的处理状态到 SQLite。

    Args:
        vault_path: Vault 根目录
        file_path: 源文件路径
        status_type: "success" | "failed" | "updated"
        md_path: 生成的 MD 文件路径
        category: 分类路径
        error: 错误信息（失败时）
    """
    import sqlite3
    conn = _get_status_db(vault_path)
    file_name = os.path.basename(file_path)
    processed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 记录文件元信息
    try:
        file_size = os.path.getsize(file_path)
        file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path)).strftime("%Y-%m-%d %H:%M:%S")
        file_md5 = compute_file_hash(file_path)
    except Exception:
        file_size = 0
        file_mtime = ""
        file_md5 = ""

    try:
        conn.execute("""
            INSERT OR REPLACE INTO file_status
            (source_path, file_name, status, md_path, category, error, file_size, file_mtime, file_md5, processed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (file_path, file_name, status_type, md_path, category, error, file_size, file_mtime, file_md5, processed_at))
        conn.commit()
    except sqlite3.Error as e:
        logger.warning(f"  状态记录失败: {e}")


def get_status_summary(vault_path: str) -> dict:
    """获取处理状态统计。"""
    import sqlite3
    conn = _get_status_db(vault_path)

    summary = {"success": 0, "failed": 0, "updated": 0, "unchanged": 0}
    for row in conn.execute("SELECT status, COUNT(*) FROM file_status GROUP BY status"):
        status, count = row
        summary[status] = count

    return summary


def close_status_db():
    """关闭数据库连接。"""
    global _status_db_conn
    if _status_db_conn:
        _status_db_conn.close()
        _status_db_conn = None


def reset_status_db():
    """重置数据库连接（用于新 vault）。"""
    close_status_db()


def init_vault(vault_path: str) -> None:
    """初始化 Vault 目录结构。"""
    cfg = load_config()
    categories = cfg["vault"].get("categories", ["其他"])
    # 提取所有一级目录
    if isinstance(categories, dict):
        top_dirs = list(set(k.split("/")[0] for k in categories.keys()))
    else:
        top_dirs = categories
    dirs = top_dirs + [
        cfg["import"]["archive_dir"],
        cfg["import"]["failed_dir"],
    ]
    for d in dirs:
        os.makedirs(os.path.join(vault_path, d), exist_ok=True)


def collect_files(source: str) -> list[str]:
    """递归收集源目录下所有可处理的文件。"""
    from scripts.parsers import PARSERS, IMAGE_EXTS
    all_exts = set(PARSERS.keys()) | IMAGE_EXTS

    files = []
    source_path = Path(source)
    for f in sorted(source_path.rglob("*")):
        if f.is_file() and f.suffix.lower() in all_exts:
            files.append(str(f))
    return files


def collect_all_files(source: str) -> tuple[list[str], list[str]]:
    """递归收集所有文件，区分可解析和不可解析。

    Returns:
        (parseable_files, unsupported_files)
    """
    from scripts.parsers import PARSERS, IMAGE_EXTS
    all_exts = set(PARSERS.keys()) | IMAGE_EXTS

    parseable = []
    unsupported = []
    source_path = Path(source)
    for f in sorted(source_path.rglob("*")):
        if f.is_file():
            if f.suffix.lower() in all_exts:
                parseable.append(str(f))
            elif not f.name.startswith("."):
                unsupported.append(str(f))
    return parseable, unsupported


def handle_unsupported_file(file_path: str, cfg: dict, vault_path: str, source_dir: str = None) -> dict:
    """处理不支持的文件格式：创建简单的 MD 文档记录。

    Args:
        file_path: 源文件路径
        cfg: 配置字典
        vault_path: Vault 根目录
        source_dir: 源文件根目录（用于计算镜像路径）

    Returns:
        {"status": "ok", "path": md_path, "category": category}
    """
    from scripts.builder import MarkdownBuilder

    fname = os.path.basename(file_path)
    safe_name = Path(fname).stem.replace(" ", "_")
    date_str = datetime.now().strftime("%Y-%m-%d")

    # 计算镜像源目录的路径
    if source_dir:
        source_rel = compute_source_relative_path(file_path, source_dir, vault_path)
    else:
        source_rel = "其他"
    vault_rel = compute_vault_rel_path(file_path, source_dir or "", vault_path)

    # 创建简单的 MD 文档
    dest_dir = os.path.join(vault_path, source_rel)
    os.makedirs(dest_dir, exist_ok=True)

    builder = MarkdownBuilder(fname, date_str)
    builder.add_frontmatter(source_rel, ["未识别格式"], source_path=file_path, vault_rel_path=vault_rel).add_title()
    builder.add_paragraph(f"文件格式: {Path(fname).suffix}")
    builder.add_archive_link(fname, source_rel, file_path)
    builder.add_footer()

    md_name = f"{date_str}-{safe_name}.md"
    dest_path = os.path.join(dest_dir, md_name)

    # 处理文件名冲突
    if os.path.exists(dest_path):
        base, ext = os.path.splitext(md_name)
        counter = 1
        while os.path.exists(dest_path):
            dest_path = os.path.join(dest_dir, f"{base}_{counter}{ext}")
            counter += 1

    with open(dest_path, "w", encoding="utf-8") as f:
        f.write(builder.build())

    logger.info(f"  [UNSUPPORTED] {fname} → {dest_path}")

    # 记录处理状态
    record_status(vault_path, file_path, "success", dest_path, source_rel)

    return {
        "status": "ok",
        "path": dest_path,
        "category": source_rel,
        "tags": ["未识别格式"],
    }


def parse_with_retry(file_path: str, max_retries: int, retry_delay: int):
    """解析文件，返回 ParseResult 或 (None, error_msg)。"""
    from scripts.parsers import get_parser
    last_error = ""

    for attempt in range(1, max_retries + 1):
        try:
            parser = get_parser(file_path)
            if parser == "image":
                from scripts.parsers import ParseResult
                return ParseResult("", [file_path]), ""
            if parser is None:
                return None, "不支持的文件格式"

            result = parser(file_path)
            if not result.has_content:
                return None, "文件内容为空"
            return result, ""
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            if attempt < max_retries:
                logger.warning(f"解析失败 (第 {attempt}/{max_retries} 次): {file_path} — {last_error}")
                time.sleep(retry_delay)
            else:
                logger.error(f"解析失败，已达最大重试次数: {file_path} — {last_error}")

    return None, last_error


def _update_frontmatter_tags(file_path: str, tags: list[str]):
    """更新 Markdown 文件 frontmatter 中的 tags 字段。"""
    if not tags:
        return
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 替换 tags 行：tags: [] -> tags: [tag1, tag2, ...]
        tags_str = ", ".join(tags[:20])  # 最多 20 个标签
        new_tags_line = f"tags: [{tags_str}]"
        content = content.replace("tags: []", new_tags_line, 1)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        logger.warning(f"  更新标签失败 {file_path}: {e}")


def handle_file(file_path: str, cfg: dict, vault_path: str, source_dir: str = None) -> dict:
    """处理单个文件的完整流程。

    所有异常均在内部捕获并返回 fail 状态，保证不会中断批量处理流程。
    """
    from scripts.analyzer import AnalysisContext
    from scripts.builder import MarkdownBuilder
    from scripts.parsers import get_parser

    fname = os.path.basename(file_path)
    safe_name = Path(fname).stem.replace(" ", "_")

    # 用于清理：如果拆分模式下失败，移除半成品
    cleanup_paths = []

    try:
        return _handle_file_impl(file_path, cfg, vault_path, source_dir, fname, safe_name, cleanup_paths)
    except Exception as e:
        logger.exception(f"  [EXCEPTION] {fname} 处理异常: {e}")
        # 清理半成品
        for p in cleanup_paths:
            try:
                if os.path.exists(p):
                    os.remove(p)
                    logger.info(f"  [CLEANUP] 移除半成品: {p}")
            except Exception:
                pass
        return {"status": "fail", "error": f"{type(e).__name__}: {e}", "doc_type_tags": []}


def _handle_file_impl(file_path, cfg, vault_path, source_dir, fname, safe_name, cleanup_paths) -> dict:
    """handle_file 的实际实现。"""
    from scripts.analyzer import AnalysisContext
    from scripts.builder import MarkdownBuilder
    from scripts.parsers import get_parser, IMAGE_EXTS

    # 判断是否为纯图片文件
    is_image_file = Path(fname).suffix.lower() in IMAGE_EXTS

    # 1. 解析
    parse_result, error = parse_with_retry(
        file_path, cfg["ai"].get("max_retries", 3), cfg["ai"].get("retry_delay", 1)
    )
    if parse_result is None:
        return {"status": "fail", "error": error}

    # 纯图片文件：走不同的处理流程（归档图片到分类目录，创建引用图片的 MD）
    if is_image_file:
        return _handle_image_file(file_path, cfg, vault_path, source_dir, fname, safe_name)

    # 文档文件（PDF/DOCX/PPTX 等）：不复制图片到 vault，只生成摘要 MD
    return _handle_document_file(
        parse_result, file_path, cfg, vault_path, source_dir, fname, safe_name, cleanup_paths
    )


def _handle_image_file(file_path, cfg, vault_path, source_dir, fname, safe_name) -> dict:
    """处理纯图片文件：创建 MD 文档记录图片信息，不归档文件。"""
    from scripts.ai_client import analyze_image, generate_tags
    from scripts.builder import MarkdownBuilder

    # 1. 分析图片
    try:
        if analyze_image.__self__ if hasattr(analyze_image, '__self__') else True:
            desc = analyze_image(file_path)
    except Exception as e:
        desc = f"（图片分析失败: {e}）"

    # 2. 提取标签
    try:
        tags = generate_tags(desc)
    except Exception:
        tags = []
    all_tags = tags or []

    # 3. 创建 MD 文档（镜像 source 目录结构）
    if source_dir:
        source_rel = compute_source_relative_path(file_path, source_dir, vault_path)
    else:
        source_rel = "其他"
    vault_rel = compute_vault_rel_path(file_path, source_dir or "", vault_path)
    dest_dir = os.path.join(vault_path, source_rel)
    os.makedirs(dest_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    builder = MarkdownBuilder(fname, date_str)
    builder.add_frontmatter(source_rel, all_tags, source_path=file_path, vault_rel_path=vault_rel).add_title()
    builder.add_file_summary(desc)
    builder.add_archive_link(fname, source_rel, file_path)
    builder.add_tags_section(all_tags).add_footer()

    md_name = f"{date_str}-{safe_name}.md"
    dest_path = os.path.join(dest_dir, md_name)
    with open(dest_path, "w", encoding="utf-8") as f:
        f.write(builder.build())

    # 记录处理状态
    record_status(vault_path, file_path, "success", dest_path, source_rel)

    return {
        "status": "ok",
        "path": dest_path,
        "category": source_rel,
        "tags": all_tags,
        "summary": desc,
    }


def _handle_document_file(parse_result, file_path, cfg, vault_path, source_dir, fname, safe_name, cleanup_paths) -> dict:
    """处理文档文件（PDF/DOCX/PPTX 等）：归档原文，只生成摘要 MD。"""
    from scripts.analyzer import AnalysisContext
    from scripts.builder import MarkdownBuilder

    text_count = len(parse_result.text) if parse_result.text else 0
    img_count = len(parse_result.images)
    section_count = len(parse_result.sections)
    logger.info(f"  提取: {text_count} 字符, {img_count} 张内嵌图片, {section_count} 个章节")

    # AI 分析（图片仅用 OCR 文本，不复制到 vault）
    parse_section_count = len(parse_result.sections)
    parse_text_len = len(parse_result.text) if parse_result.text else 0
    split_sections = cfg["import"].get("split_threshold_sections", 5)
    split_chars = cfg["import"].get("split_threshold_chars", 10000)
    should_split = parse_section_count >= split_sections or parse_text_len >= split_chars

    if should_split:
        # 大文档：AI 分析后只生成一个 MD（大纲 + 概述），不逐章拆分
        date_str = datetime.now().strftime("%Y-%m-%d")
        safe_name = Path(fname).stem.replace(" ", "_")

        # AI 分析
        chunk_size = cfg.get("performance", {}).get("chunk_size", 5)
        analysis = AnalysisContext().analyze(
            parse_result.text, parse_result.images, parse_result.sections,
            max_workers=5, callback=None, chunk_size=chunk_size,
            image_ocr_texts=parse_result.image_ocr_texts
        )
        logger.info(f"  AI 分析完成 (共 {len(analysis.sections)} 章)")

        # 分类：使用 source 路径作为分类（镜像 source 目录结构）
        category = compute_source_relative_path(file_path, source_dir, vault_path) if source_dir else "其他"
        all_tags = (analysis.tags or [])

        # 构建文档大纲（AI 从章节摘要中提取真正的章节标题）
        from scripts.ai_client import generate_outline
        section_summaries = [
            {"title": sr.get("title"), "summary": sr.get("summary")}
            for sr in analysis.sections
        ]
        outline_sections = generate_outline(section_summaries)
        if not outline_sections:
            # fallback：去重后的标题
            seen = set()
            for sr in analysis.sections:
                t = sr.get("title") or ""
                if t and t not in seen and len(t) > 3:
                    seen.add(t)
                    outline_sections.append(f"- {t}")

        # 生成全文概述（AI 综合所有章节摘要）
        from scripts.ai_client import generate_summary
        overview = ""
        overview_input = "".join(sr.get("summary", "") + "\n" for sr in analysis.sections if sr.get("summary"))
        if overview_input.strip():
            try:
                overview = generate_summary(overview_input[:5000])
            except Exception as e:
                logger.warning(f"  全文概述生成失败: {e}")
                overview = overview_input[:500]

        # 构建单个 MD 文件
        vault_rel = compute_vault_rel_path(file_path, source_dir, vault_path)
        builder = MarkdownBuilder(fname, date_str)
        builder.add_frontmatter(category, all_tags, source_path=file_path, vault_rel_path=vault_rel).add_title()
        builder.add_file_summary(overview)

        # 添加大纲章节
        builder.add_section_title("文档大纲")
        builder.add_paragraph("\n".join(outline_sections))

        # 添加源文件链接
        builder.add_archive_link(fname, category, file_path)

        builder.add_tags_section(all_tags).add_footer()

        # 写入（镜像 source 目录结构）
        dest_dir = os.path.join(vault_path, category)
        os.makedirs(dest_dir, exist_ok=True)
        filename = f"{date_str}-{safe_name}.md"
        dest_path = os.path.join(dest_dir, filename)
        cleanup_paths.append(dest_path)
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(builder.build())

    else:
        # 短文档：同样只生成大纲 + 概述
        analysis = AnalysisContext().analyze(
            parse_result.text, parse_result.images, parse_result.sections, max_workers=5,
            image_ocr_texts=parse_result.image_ocr_texts
        )
        logger.info(f"  AI 分析完成 (并发模式)")

        # 分类：使用 source 路径作为分类（镜像 source 目录结构）
        category = compute_source_relative_path(file_path, source_dir, vault_path) if source_dir else "其他"
        all_tags = (analysis.tags or [])

        date_str = datetime.now().strftime("%Y-%m-%d")
        safe_name = Path(fname).stem.replace(" ", "_")

        # 构建文档大纲（AI 从章节摘要中提取真正的章节标题）
        from scripts.ai_client import generate_outline
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

        # 生成全文概述（AI 综合所有章节摘要）
        from scripts.ai_client import generate_summary
        overview = ""
        overview_input = "".join(sr.get("summary", "") + "\n" for sr in analysis.sections if sr.get("summary"))
        if overview_input.strip():
            try:
                overview = generate_summary(overview_input[:5000])
            except Exception as e:
                logger.warning(f"  全文概述生成失败: {e}")
                overview = overview_input[:500]

        vault_rel = compute_vault_rel_path(file_path, source_dir, vault_path)
        builder = MarkdownBuilder(fname, date_str)
        builder.add_frontmatter(category, all_tags, source_path=file_path, vault_rel_path=vault_rel).add_title()
        builder.add_file_summary(overview)

        # 添加大纲章节
        builder.add_section_title("文档大纲")
        builder.add_paragraph("\n".join(outline_sections))

        # 添加源文件链接
        builder.add_archive_link(fname, category, file_path)

        builder.add_tags_section(all_tags).add_footer()

        dest_dir = os.path.join(vault_path, category)
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

    # 更新去重索引（源文件还在）
    if cfg["import"].get("dedup", True):
        from scripts.dedup import compute_md5, add_to_index
        dedup_index = cfg["import"].get("dedup_index", ".notemind_index.json")
        md5 = compute_md5(file_path)
        add_to_index(file_path, md5, category, dest_path, vault_path, dedup_index)

    # 记录处理状态（成功）
    record_status(vault_path, file_path, "success", dest_path, category)

    cleanup_paths.clear()

    return {
        "status": "ok",
        "path": dest_path,
        "category": category,
        "tags": all_tags,
        "summary": overview,
    }


def update_moc(vault_path: str, max_tags_per_note: int = 3, moc_max_entries: int = 500) -> None:
    """更新知识树 MOC (Map of Content)。

    扫描整个 vault 目录（不再按 config categories 分组），
    按 source 镜像目录结构组织 MOC 条目。

    Args:
        vault_path: Vault 根目录
        max_tags_per_note: 每个笔记最多显示标签数（防止标签过多导致卡顿）
        moc_max_entries: 单个 MOC 文件最大条目数，超过时自动分割
    """
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def _scan_notes(dir_path: str, rel_path: str) -> list[tuple[str, str, str]]:
        """递归扫描目录，返回 [(note_stem, full_rel_path, content_preview), ...]。"""
        results = []
        if not os.path.isdir(dir_path):
            return results
        for entry in sorted(os.listdir(dir_path)):
            full_entry = os.path.join(dir_path, entry)
            entry_rel = os.path.join(rel_path, entry) if rel_path else entry
            if os.path.isdir(full_entry) and not entry.startswith("."):
                results.extend(_scan_notes(full_entry, entry_rel))
            elif entry.endswith(".md") and not entry.startswith(".") and not entry.startswith("MOC"):
                try:
                    with open(full_entry, "r", encoding="utf-8") as nf:
                        preview = nf.read(500)
                    if "parent:" not in preview or "doc_type: index" in preview:
                        results.append((Path(entry).stem, entry_rel, preview))
                except Exception:
                    pass
        return results

    # 扫描整个 vault，不再按 config categories 分组
    all_entries = []  # (top_dir, note_stem, note_rel, note_tags)
    total_notes = 0
    notes = _scan_notes(vault_path, "")

    for note_stem, note_rel, preview in notes:
        # 从 note_rel 提取第一级目录作为分组
        top_dir = note_rel.split("/")[0] if "/" in note_rel else "其他"

        note_tags = ""
        try:
            for line in preview.split("\n"):
                if line.startswith("tags:"):
                    tags_raw = line[len("tags:"):].strip().strip("[]")
                    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
                    display_tags = tags[:max_tags_per_note]
                    note_tags = ", ".join([f"`#{t}`" for t in display_tags])
                    if len(tags) > max_tags_per_note:
                        note_tags += f" 等{len(tags)}个"
                    break
        except Exception:
            pass
        all_entries.append((top_dir, note_stem, note_rel, note_tags))
        total_notes += 1

    # 根据总数量决定分割策略
    if total_notes <= moc_max_entries:
        # 不分割，单文件
        moc_paths = [os.path.join(vault_path, "MOC.md")]
        parts_list = [_build_moc_lines(all_entries, total_notes, timestamp)]
    else:
        # 分割为多个文件
        num_parts = (total_notes + moc_max_entries - 1) // moc_max_entries
        moc_paths = []
        parts_list = []
        for i in range(num_parts):
            start = i * moc_max_entries
            end = min(start + moc_max_entries, total_notes)
            part_entries = all_entries[start:end]
            moc_path_i = os.path.join(vault_path, f"MOC_{i+1}.md")
            moc_paths.append(moc_path_i)
            parts_list.append(_build_moc_lines(part_entries, total_notes, timestamp,
                                               part=i+1, total_parts=num_parts))

    # 清理旧的 MOC 文件（可能是不需要的分割文件）
    for old_moc in os.listdir(vault_path):
        if old_moc.startswith("MOC") and old_moc.endswith(".md"):
            old_path = os.path.join(vault_path, old_moc)
            if old_path not in moc_paths:
                try:
                    os.remove(old_path)
                except Exception:
                    pass

    # 写入文件
    for moc_path, content_lines in zip(moc_paths, parts_list):
        with open(moc_path, "w", encoding="utf-8") as f:
            f.writelines(content_lines)

    if len(moc_paths) == 1:
        logger.info(f"知识树已更新: {moc_paths[0]} ({total_notes} 篇笔记)")
    else:
        logger.info(f"知识树已更新: {len(moc_paths)} 个文件, 共 {total_notes} 篇笔记")


def _build_moc_lines(entries: list, total_notes: int, timestamp: str,
                     part: int = 0, total_parts: int = 0) -> list[str]:
    """构建 MOC 文件的行。

    新格式: - [[文件名]] 父目录 标签
    例如:   - [[2026-05-07-白皮书]] 安全/操作系统安全/HarmonyOS `#白皮书` `#架构`
    """
    lines = ["# 知识树\n", f"> 自动更新于 {timestamp}\n"]

    if total_parts > 1:
        lines.append(f"\n> 第 {part}/{total_parts} 部分 | 总计 {total_notes} 篇笔记\n")

    # 按 top_dir 分组
    grouped = {}
    for top_dir, note_stem, note_rel, note_tags in entries:
        grouped.setdefault(top_dir, []).append((note_stem, note_rel, note_tags))

    for top_dir in sorted(grouped.keys()):
        notes = grouped[top_dir]
        lines.append(f"\n## {top_dir} ({len(notes)} 篇)\n")
        for note_stem, note_rel, note_tags in notes:
            note_parent = os.path.dirname(note_rel)  # e.g., "安全/操作系统安全"
            if note_parent:
                lines.append(f"- [[{note_stem}]] {note_parent} {note_tags}\n")
            else:
                lines.append(f"- [[{note_stem}]] {note_tags}\n")

    lines.append(f"\n---\n**总计：{total_notes} 篇笔记**\n")
    return lines


def _create_failed_record(vault_path: str, source_file: str, error_msg: str, source_dir: str = None) -> str:
    """为失败文件创建 MD 记录到 _failed 目录。

    Args:
        vault_path: Vault 根目录
        source_file: 源文件完整路径
        error_msg: 失败原因
        source_dir: 源目录（用于计算相对路径）

    Returns:
        创建的 MD 文件路径
    """
    from pathlib import Path
    from datetime import datetime

    fname = Path(source_file).name
    stem = Path(fname).stem
    safe_name = stem.replace(" ", "_")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_name = f"FAIL_{safe_name}_{ts}.md"

    failed_dir = os.path.join(vault_path, "_failed")
    os.makedirs(failed_dir, exist_ok=True)
    md_path = os.path.join(failed_dir, md_name)

    # 计算 vault 相对路径
    vault_rel = ""
    if source_dir:
        try:
            vault_rel = os.path.relpath(source_file, source_dir)
        except (ValueError, OSError):
            vault_rel = fname
    else:
        vault_rel = fname

    lines = [
        "---\n",
        f"source: {fname}\n",
        f"date: {datetime.now().strftime('%Y-%m-%d')}\n",
        "category: _failed\n",
        f"original_path: {vault_rel}\n",
        "status: failed\n",
        "---\n",
        f"# {fname}\n",
        "\n",
        "## 处理状态\n",
        f"- **状态**: 失败\n",
        f"- **原因**: {error_msg}\n",
        f"- **源文件**: `{vault_rel}`\n",
        "\n",
        "## 说明\n",
        "该文件在导入过程中处理失败。请检查源文件是否损坏或格式不兼容，\n",
        "修复后重新运行导入命令即可。\n",
        "\n",
    ]

    with open(md_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    return md_path


def update_failed_moc(vault_path: str) -> None:
    """生成 _failed 目录的 MOC 索引（MOC_fail.md）。

    扫描 _failed 目录下所有 MD 文件，生成失败文件总览。
    如果没有失败文件，则删除已有的 MOC_fail.md。
    """
    from pathlib import Path

    failed_dir = os.path.join(vault_path, "_failed")
    moc_fail_path = os.path.join(vault_path, "MOC_fail.md")
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 扫描 _failed 目录下的 MD 文件
    failed_entries = []
    if os.path.isdir(failed_dir):
        for entry in sorted(os.listdir(failed_dir)):
            if not entry.endswith(".md"):
                continue
            fp = os.path.join(failed_dir, entry)
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    preview = f.read(500)
                # 提取 source 和 error
                source_name = ""
                error_msg = ""
                for line in preview.split("\n"):
                    if line.startswith("source:"):
                        source_name = line[len("source:"):].strip()
                    elif line.startswith("- **原因**:"):
                        error_msg = line[len("- **原因**:"):].strip()
                failed_entries.append((entry, source_name, error_msg, preview))
            except Exception:
                pass

    if not failed_entries:
        # 没有失败文件，清理已有的 MOC_fail.md
        if os.path.exists(moc_fail_path):
            os.remove(moc_fail_path)
            logger.info("无失败文件，已移除 MOC_fail.md")
        return

    # 生成 MOC_fail.md
    lines = [
        "# 失败文件\n",
        f"> 自动更新于 {timestamp}\n",
        f"\n共 {len(failed_entries)} 个文件处理失败。\n",
        "\n",
    ]

    for md_name, source_name, error_msg, _ in failed_entries:
        note_stem = Path(md_name).stem
        lines.append(f"- [[{note_stem}]] {source_name}\n")
        if error_msg:
            # 截断过长的错误信息
            short_err = error_msg[:80] + ("..." if len(error_msg) > 80 else "")
            lines.append(f"  - 原因: {short_err}\n")

    lines.append(f"\n> 由 NoteMind 自动生成于 {timestamp}\n")

    with open(moc_fail_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    logger.info(f"失败文件索引已更新: {moc_fail_path} ({len(failed_entries)} 个)")


def align_vault_dirs_to_source(vault_path: str, source_dir: str) -> dict:
    """根据 source 目录结构对齐 vault 中的 MD 文件目录。

    扫描 source 下所有文件，在 vault 中查找同名的 MD 文件，
    将其移动到正确的目录（镜像 source 结构）。

    Returns:
        {"moved": int, "skipped": int, "errors": int}
    """
    import re
    from pathlib import Path

    logger.info(f"对齐 vault 目录到 source 结构: {source_dir}")

    # 1. 扫描 source 下所有文件，建立 {stem: source_rel_dir} 映射
    source_map = {}  # {filename_stem: source_relative_dir}
    for root, _, files in os.walk(source_dir):
        rel_dir = os.path.relpath(root, source_dir)
        if rel_dir == ".":
            rel_dir = "其他"
        for f in files:
            stem = Path(f).stem
            source_map[stem] = rel_dir

    # 2. 扫描 vault 下所有 MD 文件，尝试匹配并移动
    moved = 0
    skipped = 0
    errors = 0

    for root, _, files in os.walk(vault_path):
        for f in files:
            if not f.endswith(".md") or f.startswith("MOC"):
                continue

            stem = Path(f).stem
            if stem not in source_map:
                skipped += 1
                continue

            src_path = os.path.join(root, f)
            target_dir = os.path.join(vault_path, source_map[stem])

            # 已在正确目录中
            if os.path.normpath(root) == os.path.normpath(target_dir):
                skipped += 1
                continue

            try:
                os.makedirs(target_dir, exist_ok=True)
                target_path = os.path.join(target_dir, f)
                shutil.move(src_path, target_path)
                moved += 1
                logger.debug(f"  移动: {f} → {source_map[stem]}/")
            except Exception as e:
                errors += 1
                logger.warning(f"  移动失败 {f}: {e}")

    logger.info(f"目录对齐: 移动 {moved} 个文件, 跳过 {skipped} 个, 失败 {errors} 个")
    return {"moved": moved, "skipped": skipped, "errors": errors}


def update_existing_docs(vault_path: str, source_dir: str) -> None:
    """校验并修复已有 MD 文件的分类和目录映射。

    基于 source 路径重新归类：
    1. 扫描 vault 中所有 MD 文件，提取 original_path
    2. 根据 original_path 计算正确的 source 相对路径
    3. 校验 frontmatter 中的 category 是否正确，不正确则更新
    4. 校验文件目录位置是否正确，不正确则移动
    5. 重建 MOC
    """
    import re
    from pathlib import Path

    logger.info(f"开始校验修复 vault: {vault_path}")

    scanned = 0
    category_fixed = 0
    dir_fixed = 0
    skipped = 0
    errors = 0

    for root, _, files in os.walk(vault_path):
        for f in files:
            if not f.endswith(".md") or f.startswith("MOC"):
                continue

            md_path = os.path.join(root, f)
            scanned += 1

            try:
                with open(md_path, "r", encoding="utf-8") as fh:
                    content = fh.read()

                # 提取 original_path 和 category
                original_path = ""
                current_category = ""
                for line in content.split("\n"):
                    if line.startswith("original_path:"):
                        original_path = line[len("original_path:"):].strip()
                    elif line.startswith("category:"):
                        current_category = line[len("category:"):].strip()

                if not original_path:
                    skipped += 1
                    continue

                # 根据 original_path 计算正确的 category
                # original_path 可能是 vault 相对路径或 source/ 前缀路径
                if original_path.startswith("source/"):
                    # source 在 vault 外，去掉 source/ 前缀后从 source_dir 定位
                    src_relative = original_path[len("source/"):]
                    full_src_path = os.path.join(source_dir, src_relative)
                else:
                    # vault 相对路径，尝试在 vault 下找到源文件
                    full_src_path = os.path.join(vault_path, original_path)
                    if not os.path.exists(full_src_path):
                        # 源文件可能已被删除或移动
                        skipped += 1
                        continue

                # 计算正确的 category（source 相对路径）
                correct_category = compute_source_relative_path(full_src_path, source_dir, vault_path)

                # 检查 category 是否需要修复
                needs_category_fix = (current_category != correct_category)

                # 检查目录位置是否需要修复
                correct_dir = os.path.join(vault_path, correct_category)
                needs_dir_fix = (os.path.normpath(root) != os.path.normpath(correct_dir))

                if needs_category_fix or needs_dir_fix:
                    if needs_category_fix:
                        # 更新 frontmatter 中的 category
                        old_cat_line = f"category: {current_category}"
                        new_cat_line = f"category: {correct_category}"
                        content = content.replace(old_cat_line, new_cat_line, 1)
                        category_fixed += 1
                        logger.info(f"  [分类修复] {f}: {current_category} → {correct_category}")

                    if needs_dir_fix:
                        # 移动文件到正确的目录
                        os.makedirs(correct_dir, exist_ok=True)
                        target_path = os.path.join(correct_dir, f)
                        shutil.move(md_path, target_path)
                        dir_fixed += 1
                        logger.info(f"  [目录修复] {f}: {os.path.basename(root)} → {correct_category}/")
                        md_path = target_path
                    else:
                        # 只更新 category，目录没变
                        with open(md_path, "w", encoding="utf-8") as fh:
                            fh.write(content)
                else:
                    skipped += 1

            except Exception as e:
                errors += 1
                logger.warning(f"  校验失败 {md_path}: {e}")

    logger.info(f"扫描 {scanned} 个 MD 文件，修复分类 {category_fixed} 个，修复目录 {dir_fixed} 个，跳过 {skipped} 个，错误 {errors} 个")

    # 重建 MOC
    logger.info("重建 MOC...")
    update_moc(vault_path)
    update_failed_moc(vault_path)

    # 重建双链
    logger.info("重建文档双链...")
    try:
        from scripts.crosslink import DocumentIndex, apply_crosslinks
        from pathlib import Path as P

        doc_index = DocumentIndex(vault_path)
        for root, _, files in os.walk(vault_path):
            for f in files:
                if not f.endswith(".md") or f.startswith("MOC"):
                    continue
                fp = os.path.join(root, f)
                try:
                    with open(fp, "r", encoding="utf-8") as fh:
                        preview = fh.read(500)
                    tags = []
                    category = "其他"
                    for line in preview.split("\n"):
                        if line.startswith("tags:"):
                            tags_raw = line[len("tags:"):].strip().strip("[]")
                            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
                        elif line.startswith("category:"):
                            category = line[len("category:"):].strip()
                    note_name = P(f).stem
                    doc_index.add(note_name, fp, tags, category, preview)
                except Exception:
                    pass

        applied = apply_crosslinks(vault_path, doc_index)
        logger.info(f"双链更新: {applied} 个文件")
    except Exception as e:
        logger.warning(f"双链重建失败: {e}")


def migrate_existing_docs(vault_path: str, source_dir: str) -> None:
    """快速迁移已有文档到新格式。

    当同时提供 --source 时：
    1. 先对齐 vault 目录结构到 source（移动 MD 文件到正确目录）
    2. 再更新文档内容（MOC/链接/路径）

    不重新解析源文件、不调用 AI、不重新分类。
    """
    import re
    from pathlib import Path

    logger.info(f"开始迁移 vault: {vault_path}")

    # 扫描所有 MD 文件
    md_count = 0
    updated_count = 0

    for root, _, files in os.walk(vault_path):
        for f in files:
            if not f.endswith(".md") or f.startswith("MOC"):
                continue

            md_path = os.path.join(root, f)
            try:
                with open(md_path, "r", encoding="utf-8") as fh:
                    content = fh.read()

                changed = False

                # 1. 更新 "原文位置" / "原始文件" 段落为 wikilink 格式
                # 匹配旧格式: ## 原文位置\n- 原文：`xxx`\n- 路径：`yyy`
                old_ref_pattern = r"\n## 原文位置\n- 原文：`[^`]+`\n- 路径：`[^`]+`\n"
                if re.search(old_ref_pattern, content):
                    content = re.sub(old_ref_pattern, "\n## 原始文件\n- 原文：[[{}]]\n\n", content)
                    # Extract stem from old path
                    old_path_match = re.search(r"原文：`([^`]+)`", content)
                    if old_path_match:
                        stem = Path(old_path_match.group(1)).stem
                        content = content.replace("[[{}]]", f"[[{stem}]]", 1)
                    else:
                        content = content.replace("[[{}]]", f"[[{Path(f).stem}]]", 1)
                    changed = True

                # 匹配旧 add_archive_link 格式: ## 原始文件\n- 文件名：`xxx`\n- 源路径：`yyy`
                old_archive_pattern = r"\n## 原始文件\n- 文件名：`[^`]+`\n- 源路径：`[^`]+`\n\n"
                if re.search(old_archive_pattern, content):
                    stem_match = re.search(r"文件名：`([^`]+)`", content)
                    stem = Path(stem_match.group(1)).stem if stem_match else Path(f).stem
                    content = re.sub(old_archive_pattern, f"\n## 原始文件\n- 原文：[[{stem}]]\n\n", content)
                    changed = True

                # 匹配只有文件名的旧格式: ## 原始文件\n- 文件名：`xxx`\n\n
                old_archive_simple = r"\n## 原始文件\n- 文件名：`([^`]+)`\n\n"
                if re.search(old_archive_simple, content):
                    stem_match = re.search(r"文件名：`([^`]+)`", content)
                    stem = Path(stem_match.group(1)).stem if stem_match else Path(f).stem
                    content = re.sub(old_archive_simple, f"\n## 原始文件\n- 原文：[[{stem}]]\n\n", content)
                    changed = True

                if changed:
                    with open(md_path, "w", encoding="utf-8") as fh:
                        fh.write(content)
                    updated_count += 1
                md_count += 1

            except Exception as e:
                logger.warning(f"  迁移失败 {md_path}: {e}")

    logger.info(f"扫描 {md_count} 个 MD 文件，更新 {updated_count} 个")

    # 2. 重建 MOC
    logger.info("重建 MOC...")
    update_moc(vault_path)
    update_failed_moc(vault_path)

    # 3. 重建双链
    logger.info("重建文档双链...")
    try:
        from scripts.crosslink import DocumentIndex, apply_crosslinks
        from pathlib import Path as P

        doc_index = DocumentIndex(vault_path)
        # 扫描所有 MD 文件建立索引
        for root, _, files in os.walk(vault_path):
            for f in files:
                if not f.endswith(".md") or f.startswith("MOC"):
                    continue
                fp = os.path.join(root, f)
                try:
                    with open(fp, "r", encoding="utf-8") as fh:
                        preview = fh.read(500)
                    # 提取 frontmatter 信息
                    tags = []
                    category = "其他"
                    for line in preview.split("\n"):
                        if line.startswith("tags:"):
                            tags_raw = line[len("tags:"):].strip().strip("[]")
                            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
                        elif line.startswith("category:"):
                            category = line[len("category:"):].strip()
                    note_name = P(f).stem
                    doc_index.add(note_name, fp, tags, category, preview)
                except Exception:
                    pass

        applied = apply_crosslinks(vault_path, doc_index)
        logger.info(f"双链更新: {applied} 个文件")
    except Exception as e:
        logger.warning(f"双链重建失败: {e}")


def main():
    parser = argparse.ArgumentParser(description="NoteMind — 导入文件到 Obsidian Vault")
    parser.add_argument("--source", required=True, help="源文件目录路径")
    parser.add_argument("--vault", help="Vault 目录路径（覆盖 config.json）")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际写入文件")
    parser.add_argument("--resume", action="store_true", help="从上次中断的检查点恢复")
    parser.add_argument("--migrate", action="store_true", help="快速迁移已有文档到新格式（更新 MOC/链接/路径，不重新导入）")
    parser.add_argument("--update", action="store_true", help="校验并修复已有 MD 文件的分类、目录映射、MOC（基于 source 路径重新归类）")
    parser.add_argument("--config", help="配置文件路径（默认 config.json）")
    args = parser.parse_args()

    cfg = load_config(args.vault, args.config)
    vault_path = cfg["vault"]["path"]

    # 确保日志目录存在
    log_dir = cfg.get("logging", {}).get("log_dir", "logs")
    os.makedirs(log_dir, exist_ok=True)

    # 配置日志
    log_level = getattr(logging, cfg.get("logging", {}).get("level", "INFO"))
    log_file = cfg["logging"].get("file", "logs/import.log")
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )

    if cfg.get("ai", {}).get("api_key"):
        os.environ["QWEN_API_KEY"] = cfg["ai"]["api_key"]

    # 初始化多 Provider 池
    ai_cfg = cfg.get("ai", {})
    providers = ai_cfg.get("providers")

    # 向后兼容：单 key 格式转 providers
    if not providers and ai_cfg.get("api_key"):
        providers = [{
            "api_key": ai_cfg["api_key"],
            "model": ai_cfg.get("model", "qwen3.6-flash"),
            "base_url": ai_cfg.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        }]
        ai_cfg["providers"] = providers

    concurrency = ai_cfg.get("concurrency", 5)
    max_retries = ai_cfg.get("max_retries", 3)
    retry_delay = ai_cfg.get("retry_delay", 1)
    if providers:
        from scripts.ai_client import APIProviderPool, init_pool, set_tags_model, get_pool, test_api_availability, print_api_test_report
        init_pool(providers, concurrency)
        logger.info(f"AI Provider 池: {len(providers)} 个 Key, 并发: {concurrency}")

        # 测试 API 可用性
        pool = get_pool()
        api_results = test_api_availability(pool)
        print_api_test_report(api_results)

        # Level 3: 模型路由 — 标签提取使用更便宜模型
        tags_model_cfg = ai_cfg.get("tags_model")
        if tags_model_cfg:
            set_tags_model(tags_model_cfg)
            logger.info(f"标签模型: {tags_model_cfg.get('model')} (Level 3 模型路由)")
    else:
        logger.warning("未配置 providers，使用单 API Key（环境变量）")

    source = os.path.realpath(args.source)
    if not os.path.isdir(source):
        logger.error(f"源目录不存在: {args.source}")
        sys.exit(1)

    # --migrate 模式：快速迁移已有文档到新格式，不重新导入
    if args.migrate:
        logger.info("=== 快速迁移模式 ===")
        # 先对齐目录结构
        align_result = align_vault_dirs_to_source(vault_path, source)
        if align_result["moved"] > 0:
            logger.info(f"目录已对齐，移动了 {align_result['moved']} 个文件")
        # 再更新文档内容
        migrate_existing_docs(vault_path, source)
        logger.info("迁移完成！")
        return

    # --update 模式：校验并修复已有 MD 文件的分类和目录映射
    if args.update:
        logger.info("=== 校验修复模式 ===")
        update_existing_docs(vault_path, source)
        logger.info("校验修复完成！")
        return

    init_vault(vault_path)
    logger.info(f"Vault 路径: {vault_path}")

    # 收集所有文件：区分可解析和不支持的格式
    parseable_files, unsupported_files = collect_all_files(source)
    total_files = len(parseable_files) + len(unsupported_files)

    if total_files == 0:
        logger.warning("未找到可处理的文件")
        return

    logger.info(f"找到 {len(parseable_files)} 个可解析文件, {len(unsupported_files)} 个不支持的格式")

    stats = {"ok": 0, "failed": 0, "skipped": 0}
    start_time = time.time()

    # 先处理不支持的文件格式：创建链接和简单 MD 文档
    if unsupported_files:
        logger.info("=== 处理不支持的文件格式 ===")
        for i, file_path in enumerate(unsupported_files, 1):
            fname = os.path.basename(file_path)
            logger.info(f"[{i}/{len(unsupported_files)}] 不支持的格式: {fname}")
            if not args.dry_run:
                result = handle_unsupported_file(file_path, cfg, vault_path, source)
                if result["status"] == "ok":
                    stats["ok"] += 1
                    update_moc(vault_path)  # 实时更新 MOC
        logger.info(f"不支持的格式处理完成: {len(unsupported_files)} 个文件已创建链接")

    files = parseable_files
    if not files:
        logger.info("所有可解析文件为空，仅处理了不支持的格式")
        update_moc(vault_path)
        update_failed_moc(vault_path)
        return

    # 测试图片模型解析能力（仅当有图片文件时）
    from scripts.ai_client import APIProviderPool, get_pool, test_image_analysis, print_image_test_report
    img_files = [f for f in files if Path(f).suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp')]
    if img_files and providers:
        pool = get_pool()
        img_results = test_image_analysis(pool, img_files[0])
        print_image_test_report(img_results)

    # 测试本地 VLM 可用性（MiniMind-V）- 进程启动时验证
    from scripts.vlm_local import test_local_vlm, print_local_vlm_test_report
    test_img_path = img_files[0] if img_files else None
    local_vlm_results = test_local_vlm(test_img_path)
    print_local_vlm_test_report(local_vlm_results)

    processed_count = 0

    # MD5 去重
    if cfg["import"].get("dedup", True):
        from scripts.dedup import check_duplicate
        dedup_index = cfg["import"].get("dedup_index", ".notemind_index.json")
        unique_files = []
        for f in files:
            dup = check_duplicate(f, vault_path, dedup_index)
            if dup:
                logger.info(f"  [SKIP] 重复文件: {os.path.basename(f)} (已存在于 {dup.get('category', '?')}/{dup.get('filename', '?')})")
                stats["skipped"] += 1
            else:
                unique_files.append(f)
        files = unique_files
        if not files:
            logger.info("所有文件均为重复文件，无需处理")
            return

    logger.info(f"找到 {len(files)} 个新文件待处理")

    # 收集已处理文档元数据（用于双链）
    processed_docs = []

    for i, file_path in enumerate(files, 1):
        fname = os.path.basename(file_path)
        logger.info(f"[{i}/{len(files)}] 处理: {fname}")

        if args.dry_run:
            logger.info(f"  [DRY-RUN] 将处理: {fname}")
            stats["skipped"] += 1
            continue

        result = handle_file(file_path, cfg, vault_path, source)

        if result["status"] == "ok":
            logger.info(f"  [OK] {fname} → {result['path']}")
            logger.info(f"  分类: {result['category']} | 标签: {result['tags']}")
            stats["ok"] += 1
            processed_docs.append({
                "name": Path(result["path"]).stem,
                "path": result["path"],
                "tags": result["tags"],
                "category": result["category"],
                "summary": result.get("summary", ""),
            })
            # 实时更新 MOC（每处理完一个文件）
            if not args.dry_run:
                update_moc(vault_path)

        else:
            record_status(vault_path, file_path, "failed", None, None, result["error"])
            logger.error(f"  [FAIL] {fname}: {result['error']}")
            stats["failed"] += 1
            # 为失败文件创建 MD 记录到 _failed 目录
            if not args.dry_run:
                _create_failed_record(vault_path, file_path, result.get("error", "未知错误"), source)
                update_failed_moc(vault_path)  # 实时更新失败文件索引

        # 进度日志（每 10 个文件打印一次）
        processed_count += 1
        if processed_count % 10 == 0:
            elapsed = round(time.time() - start_time, 1)
            logger.info(f"[进度] {processed_count}/{len(files)} | 成功: {stats['ok']} | 失败: {stats['failed']} | 耗时: {elapsed}s")

    # 文档双链
    if not args.dry_run and processed_docs:
        from scripts.crosslink import DocumentIndex, apply_crosslinks
        doc_index = DocumentIndex(vault_path)
        for doc in processed_docs:
            if os.path.exists(doc["path"]):
                with open(doc["path"], "r", encoding="utf-8") as f:
                    first_500 = f.read(500)
                if "parent:" not in first_500:
                    doc_index.add(doc["name"], doc["path"], doc["tags"],
                                  doc["category"], doc["summary"])
        if len(doc_index.documents) > 1:
            count = apply_crosslinks(vault_path, doc_index)
            logger.info(f"双链已建立: {count} 个文件更新了相关文档链接")

    # 最终统计
    elapsed = round(time.time() - start_time, 1)
    logger.info(f"健康状态: 正常")

    try:
        if not args.dry_run:
            update_moc(vault_path)
            update_failed_moc(vault_path)

        from scripts.ai_client import get_pool, print_log_analysis, get_perf_stats, reset_perf_stats
        pool = get_pool()
        if pool:
            pool.print_health_report()

        # 日志分析（从日志文件中识别限流等问题）
        print_log_analysis(log_file)

        # 性能报告
        perf = get_perf_stats()
        if perf["api_calls"] > 0:
            avg_latency = perf["total_latency"] / perf["api_calls"]
            total_tokens = perf["input_tokens"] + perf["output_tokens"]
            logger.info(f"\n{'=' * 60}")
            logger.info(f"  性能报告")
            logger.info(f"{'=' * 60}")
            logger.info(f"  API 调用次数:     {perf['api_calls']}")
            logger.info(f"  Token 消耗:       {total_tokens:,} (输入: {perf['input_tokens']:,} + 输出: {perf['output_tokens']:,})")
            logger.info(f"  AI 总耗时:        {perf['total_latency']:.1f}s")
            logger.info(f"  API 平均延迟:     {avg_latency:.2f}s")
            logger.info(f"  API 错误次数:     {perf['errors']}")
            logger.info(f"{'=' * 60}\n")
            reset_perf_stats()

        logger.info(f"{'=' * 50}")
        logger.info(f"=== NoteMind 处理完成 ===")
        logger.info(f"成功: {stats['ok']} | 失败: {stats['failed']} | 跳过: {stats['skipped']} | 总耗时: {elapsed}s")

        # 打印 SQLite 状态汇总
        status_summary = get_status_summary(vault_path)
        logger.info(f"数据库状态: 成功={status_summary['success']} | 失败={status_summary['failed']} | 更新={status_summary['updated']} | 未变化={status_summary['unchanged']}")
        logger.info(f"{'=' * 50}")

        # 关闭数据库
        close_status_db()
    except Exception as e:
        logger.error(f"报告生成失败: {e}")


if __name__ == "__main__":
    main()
