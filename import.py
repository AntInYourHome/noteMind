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
    dirs = cfg["vault"].get("categories", ["其他"]) + [
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


def archive_source(file_path: str, vault_path: str, archive_dir: str) -> str:
    """将原始文件归档到 Vault。"""
    archive_path = os.path.join(vault_path, archive_dir, os.path.basename(file_path))
    os.makedirs(os.path.dirname(archive_path), exist_ok=True)
    shutil.copy2(file_path, archive_path)
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


def copy_images_to_vault(images: list[str], source_name: str, vault_path: str) -> list[str]:
    """将提取的图片复制到 Vault，返回 vault 内的相对路径列表。"""
    img_folder = os.path.join(vault_path, ".notemind_assets", source_name)
    os.makedirs(img_folder, exist_ok=True)

    vault_paths = []
    for i, img_path in enumerate(images):
        ext = os.path.splitext(img_path)[1].lower()
        safe_name = f"{source_name}_{i}{ext}"
        dest = os.path.join(img_folder, safe_name)
        shutil.copy2(img_path, dest)
        vault_paths.append(os.path.join(".notemind_assets", source_name, safe_name))

    return vault_paths


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
        return {"status": "fail", "error": f"{type(e).__name__}: {e}"}


def _handle_file_impl(file_path, cfg, vault_path, fname, safe_name, cleanup_paths) -> dict:
    """handle_file 的实际实现。"""
    from scripts.analyzer import AnalysisContext
    from scripts.classifier import classify
    from scripts.builder import MarkdownBuilder
    from scripts.parsers import get_parser

    # 1. 解析
    parse_result, error = parse_with_retry(
        file_path, cfg["ai"].get("max_retries", 3), cfg["ai"].get("retry_delay", 1)
    )
    if parse_result is None:
        return {"status": "fail", "error": error}

    text_count = len(parse_result.text) if parse_result.text else 0
    img_count = len(parse_result.images)
    section_count = len(parse_result.sections)
    logger.info(f"  提取: {text_count} 字符, {img_count} 张图片, {section_count} 个章节")

    # 2. AI 分析（自动选择短文档/长文档策略）
    parse_section_count = len(parse_result.sections)
    parse_text_len = len(parse_result.text) if parse_result.text else 0
    split_sections = cfg["import"].get("split_threshold_sections", 5)
    split_chars = cfg["import"].get("split_threshold_chars", 10000)
    should_split = parse_section_count >= split_sections or parse_text_len >= split_chars

    if should_split:
        # 大文档：流式分析，逐章输出即写磁盘
        date_str = datetime.now().strftime("%Y-%m-%d")
        safe_name = Path(fname).stem.replace(" ", "_")

        # 先构建章节链接列表
        section_links = []
        for i, sec in enumerate(parse_result.sections):
            title = sec.title or f"第{i+1}章"
            safe_title = title.replace(" ", "_").replace("/", "_").replace("\\", "_")
            link_name = f"{date_str}-{safe_name}-{i+1:02d}-{safe_title}"
            section_links.append((link_name, title))

        # 临时分类（后续会用 AI 分析后的摘要重新分类）
        classify_input = " ".join(s.title for s in parse_result.sections if s.title)[:300]
        categories = cfg["vault"].get("categories", ["其他"])
        category = classify(classify_input, categories) if classify_input else "其他"

        # 先写索引文件（tags 暂为空，后续回填）
        builder = MarkdownBuilder(fname, date_str)
        builder.add_frontmatter(category, [], source_path=file_path)
        builder.add_file_summary("")
        dest_dir = os.path.join(vault_path, category)
        os.makedirs(dest_dir, exist_ok=True)
        index_filename = f"{date_str}-{safe_name}.md"
        index_path = os.path.join(dest_dir, index_filename)
        cleanup_paths.append(index_path)  # 失败时清理
        index_content = builder.build_index(section_links, source_path=file_path)
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(index_content)
        logger.info(f"  [INDEX] {index_filename} ({len(section_links)} 个章节)")

        # 流式分析：每章完成即写磁盘（tags 暂为空）
        parent_name = f"{date_str}-{safe_name}"
        chapter_paths_list = []  # 记录所有章节文件路径

        def on_section_done(index, total, section_result):
            """每章分析完成后立即写磁盘。"""
            title = section_result.get("title", f"第{index+1}章") or f"第{index+1}章"
            safe_title = title.replace(" ", "_").replace("/", "_").replace("\\", "_")
            link_name = f"{date_str}-{safe_name}-{index+1:02d}-{safe_title}"

            chapter_content = builder.build_section_note(
                section=section_result,
                parent_name=parent_name,
                tags=[],
                source_path=file_path,
            )
            chapter_path = os.path.join(dest_dir, f"{link_name}.md")
            cleanup_paths.append(chapter_path)  # 失败时清理
            chapter_paths_list.append(chapter_path)
            with open(chapter_path, "w", encoding="utf-8") as f:
                f.write(chapter_content)
            logger.info(f"  [OK] 章节 [{index+1}/{total}] {title} → {link_name}.md")

        # 合并章节配置：每 5 页合并为一次 API 调用
        chunk_size = cfg.get("performance", {}).get("chunk_size", 5)

        analysis = AnalysisContext().analyze(
            parse_result.text, parse_result.images, parse_result.sections,
            max_workers=5, callback=on_section_done, chunk_size=chunk_size,
            image_ocr_texts=parse_result.image_ocr_texts
        )

        logger.info(f"  AI 分析完成 (流式，共 {len(analysis.sections)} 章)")

        # === AI 分析完成后，回填标签 ===
        analysis_tags = analysis.tags if analysis.tags else []

        # 重新分类（用 AI 完整摘要）
        classify_input2 = ""
        for sr in analysis.sections:
            if sr.get("summary"):
                classify_input2 += sr["summary"] + "\n"
        if classify_input2.strip():
            category = classify(classify_input2, categories)

        # 更新索引文件 frontmatter 标签
        if analysis_tags:
            _update_frontmatter_tags(index_path, analysis_tags)
            logger.info(f"  索引文件标签已回填: {len(analysis_tags)} 个")

        # 更新所有章节文件 frontmatter 标签
        for cp in chapter_paths_list:
            if os.path.exists(cp):
                _update_frontmatter_tags(cp, analysis_tags)
        logger.info(f"  章节文件标签已回填: {len(chapter_paths_list)} 个文件")

        # 归档原始文件
        archive_source(file_path, vault_path, cfg["import"]["archive_dir"])

        # 复制图片
        vault_image_paths = []
        if parse_result.images:
            vault_image_paths = copy_images_to_vault(parse_result.images, safe_name, vault_path)
            logger.info(f"  复制 {len(vault_image_paths)} 张图片到 Vault")

    else:
        # 短文档：原有逻辑不变
        analysis = AnalysisContext().analyze(
            parse_result.text, parse_result.images, parse_result.sections, max_workers=5,
            image_ocr_texts=parse_result.image_ocr_texts
        )
        logger.info(f"  AI 分析完成 (并发模式)")

        # 3. 分类
        classify_input = ""
        for sr in analysis.sections:
            if sr.get("summary"):
                classify_input += sr["summary"] + "\n"
        if analysis.image_descriptions:
            classify_input += analysis.image_descriptions[0][:200]

        categories = cfg["vault"].get("categories", ["其他"])
        category = classify(classify_input, categories)

        # 4. 归档
        archive_source(file_path, vault_path, cfg["import"]["archive_dir"])

        # 5. 复制图片
        vault_image_paths = []
        if parse_result.images:
            vault_image_paths = copy_images_to_vault(parse_result.images, safe_name, vault_path)
            logger.info(f"  复制 {len(vault_image_paths)} 张图片到 Vault")

        # 6. 构建 Markdown（短文档：单文件输出）
        date_str = datetime.now().strftime("%Y-%m-%d")
        safe_name = Path(fname).stem.replace(" ", "_")
        builder = MarkdownBuilder(fname, date_str)
        builder.add_frontmatter(category, analysis.tags, source_path=file_path).add_title()

        if len(analysis.sections) == 1 and not analysis.sections[0].get("title"):
            builder.add_file_summary(analysis.sections[0].get("summary", ""))

        builder.add_sections(analysis.sections)

        if vault_image_paths:
            builder.add_images(vault_image_paths, analysis.image_descriptions)

        builder.add_tags_section(analysis.tags).add_footer()

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

        cleanup_paths.append(dest_path)  # 失败时清理
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(builder.build())

    # 拆分模式下 dest_path 用索引文件路径
    if should_split:
        dest_path = index_path

    # 8. 更新去重索引
    if cfg["import"].get("dedup", True):
        from scripts.dedup import compute_md5, add_to_index
        dedup_index = cfg["import"].get("dedup_index", ".notemind_index.json")
        md5 = compute_md5(file_path)
        add_to_index(file_path, md5, category, dest_path, vault_path, dedup_index)

    # 成功时清空清理列表（不删除文件）
    cleanup_paths.clear()

    return {
        "status": "ok",
        "path": dest_path,
        "category": category,
        "tags": analysis.tags,
        "summary": analysis.sections[0].get("summary", "") if analysis.sections else "",
    }


def update_moc(vault_path: str, max_tags_per_note: int = 3) -> None:
    """更新知识树 MOC (Map of Content)。

    Args:
        vault_path: Vault 根目录
        max_tags_per_note: 每个笔记最多显示标签数（防止标签过多导致卡顿）
    """
    cfg = load_config()
    categories = cfg["vault"].get("categories", ["其他"])
    moc_path = os.path.join(vault_path, "MOC.md")

    lines = ["# 知识树\n", f"> 自动更新于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"]
    total_notes = 0

    for cat in categories:
        cat_dir = os.path.join(vault_path, cat)
        if not os.path.isdir(cat_dir):
            continue

        notes = sorted([f for f in os.listdir(cat_dir) if f.endswith(".md") and not f.startswith(".")])
        if not notes:
            continue

        # 只统计非拆分章节文件（即排除 parent 字段的章节文件）
        index_notes = []
        for note in notes:
            # 快速检查：索引文件通常没有 parent frontmatter
            full_path = os.path.join(cat_dir, note)
            try:
                with open(full_path, "r", encoding="utf-8") as nf:
                    first_200 = nf.read(200)
                    if "parent:" not in first_200 and "doc_type: index" not in first_200:
                        index_notes.append(note)
                    elif "doc_type: index" in first_200:
                        index_notes.append(note)
            except Exception:
                pass

        if not index_notes:
            continue

        lines.append(f"\n## {cat} ({len(index_notes)} 篇)\n")
        for note in index_notes:
            note_path = Path(cat) / Path(note).stem
            note_tags = ""
            full_path = os.path.join(cat_dir, note)
            try:
                with open(full_path, "r", encoding="utf-8") as nf:
                    # 只读取前 500 字符（frontmatter 区域）
                    content = nf.read(500)
                    for line in content.split("\n"):
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
            lines.append(f"- [[{note_path}]] {note_tags}\n")
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
        from scripts.ai_client import APIProviderPool, init_pool, set_tags_model
        init_pool(providers, concurrency)
        logger.info(f"AI Provider 池: {len(providers)} 个 Key, 并发: {concurrency}")

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

        # Provider 健康报告（多模型配置时）
        pool = get_pool()
        if pool:
            pool.print_health_report()

        # 日志分析（从日志文件中识别限流等问题）
        from scripts.ai_client import print_log_analysis
        print_log_analysis(log_file)

        # 性能报告
        from scripts.ai_client import get_perf_stats, reset_perf_stats
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
