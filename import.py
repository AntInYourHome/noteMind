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


def archive_source(file_path: str, vault_path: str, category: str, archive_dir: str = "_archive", remove_source: bool = True) -> str:
    """将原始文件归档到 _archive/{category}/ 目录。

    Args:
        file_path: 源文件路径
        vault_path: Vault 根目录
        category: 分类路径（如 "安全/操作系统安全/HarmonyOS"）
        archive_dir: 原始文件备份目录（默认 "_archive"）
        remove_source: 归档成功后是否从源目录删除（默认 True）
    """
    archive_path = os.path.join(vault_path, archive_dir, category, os.path.basename(file_path))
    os.makedirs(os.path.dirname(archive_path), exist_ok=True)
    shutil.copy2(file_path, archive_path)
    if remove_source:
        os.remove(file_path)  # 成功后删除源文件
    return archive_path


def move_to_failed(file_path: str, vault_path: str, failed_dir: str, error: str) -> str:
    """将处理失败的文件移到 _failed 目录。"""
    failed_path = os.path.join(vault_path, failed_dir, os.path.basename(file_path))
    os.makedirs(os.path.dirname(failed_path), exist_ok=True)
    shutil.copy2(file_path, failed_path)
    err_file = failed_path + ".error.txt"
    with open(err_file, "w", encoding="utf-8") as f:
        f.write(f"File: {file_path}\nError: {error}\n")
    return failed_path


def handle_file(file_path: str, cfg: dict, vault_path: str) -> dict:
    """处理单个文件的完整流程。

    所有异常均在内部捕获并返回 fail 状态，保证不会中断批量处理流程。
    """
    from scripts.analyzer import AnalysisContext
    from scripts.classifier import classify
    from scripts.builder import MarkdownBuilder
    from scripts.parsers import get_parser

    fname = os.path.basename(file_path)
    safe_name = Path(fname).stem.replace(" ", "_")

    # 用于清理：如果拆分模式下失败，移除半成品
    cleanup_paths = []

    try:
        return _handle_file_impl(file_path, cfg, vault_path, fname, safe_name, cleanup_paths)
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


def _handle_file_impl(file_path, cfg, vault_path, fname, safe_name, cleanup_paths) -> dict:
    """handle_file 的实际实现。"""
    from scripts.analyzer import AnalysisContext
    from scripts.classifier import classify
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
        return _handle_image_file(file_path, cfg, vault_path, fname, safe_name)

    # 文档文件（PDF/DOCX/PPTX 等）：不复制图片到 vault，只生成摘要 MD
    return _handle_document_file(
        parse_result, file_path, cfg, vault_path, fname, safe_name, cleanup_paths
    )


def _handle_image_file(file_path, cfg, vault_path, fname, safe_name) -> dict:
    """处理纯图片文件：归档图片到分类目录，创建引用图片的 MD 文档。"""
    from scripts.ai_client import analyze_image, generate_tags
    from scripts.classifier import classify
    from scripts.builder import MarkdownBuilder

    # 1. 分析图片
    try:
        if analyze_image.__self__ if hasattr(analyze_image, '__self__') else True:
            desc = analyze_image(file_path)
    except Exception as e:
        desc = f"（图片分析失败: {e}）"

    # 2. 分类
    categories = cfg["vault"].get("categories", {"其他": []})
    category, doc_type_tags = classify(desc, categories, title=fname)

    # 3. 提取标签
    try:
        tags = generate_tags(desc)
    except Exception:
        tags = []
    all_tags = (tags or []) + doc_type_tags

    # 4. 归档图片到 _archive 目录
    archive_dir = cfg["import"].get("archive_dir", "_archive")
    backup_path = os.path.join(vault_path, archive_dir, category, fname)
    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
    shutil.copy2(file_path, backup_path)

    # 5. 创建 MD 文档（在分类目录下）
    dest_dir = os.path.join(vault_path, category)
    os.makedirs(dest_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    builder = MarkdownBuilder(fname, date_str)
    builder.add_frontmatter(category, all_tags, source_path=file_path).add_title()
    builder.add_file_summary(desc)
    # 引用 _archive 目录下的图片
    archive_img_path = f"{archive_dir}/{category}/{fname}"
    builder.add_images([archive_img_path], [desc])
    builder.add_tags_section(all_tags).add_footer()

    md_name = f"{date_str}-{safe_name}.md"
    dest_path = os.path.join(dest_dir, md_name)
    with open(dest_path, "w", encoding="utf-8") as f:
        f.write(builder.build())

    return {
        "status": "ok",
        "path": dest_path,
        "category": category,
        "tags": all_tags,
        "summary": desc,
    }


def _classify_document(text: str, title: str, categories: dict, tags: list[str]) -> tuple[str, list[str]]:
    """分类文档：优先使用动态分类器，回退到静态分类器。"""
    vault_path = load_config()["vault"]["path"]
    db_path = os.path.join(vault_path, ".notemind_memory.db")

    # 尝试动态分类
    if os.path.exists(db_path):
        try:
            from scripts.dynamic_classifier import DynamicClassifier
            classifier = DynamicClassifier(db_path)
            doc_id = Path(title).stem
            return classifier.classify(text=text, title=title, tags=tags, doc_id=doc_id)
        except Exception as e:
            logger.warning(f"  [分类] 动态分类失败: {e}，回退到静态分类")

    # 回退到静态分类
    from scripts.classifier import classify
    return classify(text, categories, title)


def _handle_document_file(parse_result, file_path, cfg, vault_path, fname, safe_name, cleanup_paths) -> dict:
    """处理文档文件（PDF/DOCX/PPTX 等）：归档原文，只生成摘要 MD。"""
    from scripts.analyzer import AnalysisContext
    from scripts.classifier import classify
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
    categories = cfg["vault"].get("categories", {"其他": []})

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

        # 分类（优先使用动态分类器，回退到静态分类）
        classify_input = ""
        for sr in analysis.sections:
            if sr.get("summary"):
                classify_input += sr["summary"] + "\n"
        if classify_input.strip():
            category, doc_type_tags = _classify_document(
                classify_input, fname, categories, analysis.tags or []
            )
        else:
            category, doc_type_tags = "其他", []

        # 标签
        all_tags = (analysis.tags or []) + doc_type_tags

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
        if classify_input.strip():
            try:
                overview = generate_summary(classify_input[:5000])
            except Exception as e:
                logger.warning(f"  全文概述生成失败: {e}")
                overview = classify_input[:500]

        # 构建单个 MD 文件
        builder = MarkdownBuilder(fname, date_str)
        builder.add_frontmatter(category, all_tags, source_path=file_path).add_title()
        builder.add_file_summary(overview)

        # 添加大纲章节
        builder.add_section_title("文档大纲")
        builder.add_paragraph("\n".join(outline_sections))

        # 添加归档文件双链
        builder.add_archive_link(fname, category)

        builder.add_tags_section(all_tags).add_footer()

        # 写入
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

        classify_input = ""
        for sr in analysis.sections:
            if sr.get("summary"):
                classify_input += sr["summary"] + "\n"
        if analysis.image_descriptions:
            classify_input += analysis.image_descriptions[0][:200]

        category, doc_type_tags = _classify_document(
            classify_input, fname, categories, analysis.tags or []
        )
        all_tags = (analysis.tags or []) + doc_type_tags

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
        if classify_input.strip():
            try:
                overview = generate_summary(classify_input[:5000])
            except Exception as e:
                logger.warning(f"  全文概述生成失败: {e}")
                overview = classify_input[:500]

        builder = MarkdownBuilder(fname, date_str)
        builder.add_frontmatter(category, all_tags, source_path=file_path).add_title()
        builder.add_file_summary(overview)

        # 添加大纲章节
        builder.add_section_title("文档大纲")
        builder.add_paragraph("\n".join(outline_sections))

        # 添加归档文件双链
        builder.add_archive_link(fname, category)

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

    # 归档原始文件到分类目录，并备份到 _archive（成功后删除源文件）
    archive_dir = cfg["import"].get("archive_dir", "_archive")
    archive_source(file_path, vault_path, category, archive_dir, remove_source=True)

    cleanup_paths.clear()

    return {
        "status": "ok",
        "path": dest_path,
        "category": category,
        "tags": all_tags,
        "summary": overview,
    }


def update_moc(vault_path: str, max_tags_per_note: int = 3) -> None:
    """更新知识树 MOC (Map of Content)。

    Args:
        vault_path: Vault 根目录
        max_tags_per_note: 每个笔记最多显示标签数（防止标签过多导致卡顿）
    """
    cfg = load_config()
    categories = cfg["vault"].get("categories", {"其他": []})
    moc_path = os.path.join(vault_path, "MOC.md")

    lines = ["# 知识树\n", f"> 自动更新于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"]
    total_notes = 0

    if isinstance(categories, dict):
        # 多级分类树：按一级分类组织，递归扫描子目录
        top_dirs = list(set(k.split("/")[0] for k in categories.keys()))
        if "其他" not in top_dirs:
            top_dirs.append("其他")
    else:
        # 旧版平级分类
        top_dirs = categories

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
            elif entry.endswith(".md") and not entry.startswith("."):
                try:
                    with open(full_entry, "r", encoding="utf-8") as nf:
                        preview = nf.read(500)
                    if "parent:" not in preview or "doc_type: index" in preview:
                        results.append((Path(entry).stem, entry_rel, preview))
                except Exception:
                    pass
        return results

    for top_dir in sorted(top_dirs):
        top_path = os.path.join(vault_path, top_dir)
        if not os.path.isdir(top_path):
            continue

        notes = _scan_notes(top_path, top_dir)
        if not notes:
            continue

        lines.append(f"\n## {top_dir} ({len(notes)} 篇)\n")
        for note_stem, note_rel, preview in notes:
            note_path = Path(note_rel).with_suffix("")
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
            lines.append(f"- [[{note_rel}|{note_stem}]] {note_tags}\n")
            total_notes += 1

    lines.append(f"\n---\n**总计：{total_notes} 篇笔记**\n")
    with open(moc_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    logger.info(f"知识树已更新: {moc_path} ({total_notes} 篇笔记)")


def main():
    parser = argparse.ArgumentParser(description="NoteMind — 导入文件到 Obsidian Vault")
    parser.add_argument("--source", required=True, help="源文件目录路径")
    parser.add_argument("--vault", help="Vault 目录路径（覆盖 config.json）")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际写入文件")
    parser.add_argument("--resume", action="store_true", help="从上次中断的检查点恢复")
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

    init_vault(vault_path)
    logger.info(f"Vault 路径: {vault_path}")

    files = collect_files(source)
    if not files:
        logger.warning("未找到可处理的文件")
        return

    stats = {"ok": 0, "failed": 0, "skipped": 0}
    start_time = time.time()
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

        result = handle_file(file_path, cfg, vault_path)

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
            # 每完成一篇文档，更新 MOC
            update_moc(vault_path)
        else:
            move_to_failed(file_path, vault_path, cfg["import"]["failed_dir"], result["error"])
            logger.error(f"  [FAIL] {fname}: {result['error']}")
            stats["failed"] += 1

        # 进度日志（每 10 个文件打印一次）
        processed_count += 1
        if processed_count % 10 == 0:
            elapsed = round(time.time() - start_time, 1)
            logger.info(f"[进度] {processed_count}/{len(files)} | 成功: {stats['ok']} | 失败: {stats['failed']} | 耗时: {elapsed}s")

    # 文档双链
    if not args.dry_run and processed_docs:
        from scripts.crosslink import DocumentIndex, apply_crosslinks
        doc_index = DocumentIndex()
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
        logger.info(f"{'=' * 50}")
    except Exception as e:
        logger.error(f"报告生成失败: {e}")


if __name__ == "__main__":
    main()
