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
from scripts.metrics import MetricsCollector


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
    """处理单个文件的完整流程。"""
    from scripts.analyzer import AnalysisContext
    from scripts.classifier import classify
    from scripts.builder import MarkdownBuilder
    from scripts.parsers import get_parser

    fname = os.path.basename(file_path)
    safe_name = Path(fname).stem.replace(" ", "_")

    # 1. 解析
    parse_result, error = parse_with_retry(
        file_path, cfg["import"]["max_retries"], cfg["import"]["retry_delay"]
    )
    if parse_result is None:
        return {"status": "fail", "error": error}

    text_count = len(parse_result.text) if parse_result.text else 0
    img_count = len(parse_result.images)
    section_count = len(parse_result.sections)
    logger.info(f"  提取: {text_count} 字符, {img_count} 张图片, {section_count} 个章节")

    # 2. AI 分析（自动选择短文档/长文档策略）
    try:
        analysis = AnalysisContext().analyze(
            parse_result.text, parse_result.images, parse_result.sections
        )
    except Exception as e:
        return {"status": "fail", "error": f"AI 分析失败: {e}"}

    # 3. 分类
    classify_input = ""
    for sr in analysis.sections:
        if sr.get("summary"):
            classify_input += sr["summary"][:100] + " "
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

    # 6. 构建 Markdown
    date_str = datetime.now().strftime("%Y-%m-%d")
    builder = (
        MarkdownBuilder(fname, date_str)
        .add_frontmatter(category, analysis.tags)
        .add_title()
    )

    # 短文档：显示全文摘要
    if len(analysis.sections) == 1 and not analysis.sections[0].get("title"):
        builder.add_file_summary(analysis.sections[0].get("summary", ""))

    # 章节内容
    builder.add_sections(analysis.sections)

    # 图片
    if vault_image_paths:
        builder.add_images(vault_image_paths, analysis.image_descriptions)

    # 标签 + 页脚
    builder.add_tags_section(analysis.tags).add_footer()

    # 7. 写入文件
    dest_dir = os.path.join(vault_path, category)
    os.makedirs(dest_dir, exist_ok=True)
    filename = f"{date_str}-{safe_name}.md"
    dest_path = os.path.join(dest_dir, filename)

    # 处理文件名冲突
    if os.path.exists(dest_path):
        base, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(dest_path):
            dest_path = os.path.join(dest_dir, f"{base}_{counter}{ext}")
            counter += 1

    with open(dest_path, "w", encoding="utf-8") as f:
        f.write(builder.build())

    # 8. 更新去重索引
    if cfg["import"].get("dedup", True):
        from scripts.dedup import compute_md5, add_to_index
        dedup_index = cfg["import"].get("dedup_index", ".notemind_index.json")
        md5 = compute_md5(file_path)
        add_to_index(file_path, md5, category, dest_path, vault_path, dedup_index)

    return {
        "status": "ok",
        "path": dest_path,
        "category": category,
        "tags": analysis.tags,
    }


def update_moc(vault_path: str) -> None:
    """更新知识树 MOC (Map of Content)。"""
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

        lines.append(f"\n## {cat} ({len(notes)} 篇)\n")
        for note in notes:
            note_path = Path(cat) / Path(note).stem
            note_tags = ""
            full_path = os.path.join(cat_dir, note)
            try:
                with open(full_path, "r", encoding="utf-8") as nf:
                    for line in nf:
                        if line.startswith("tags:"):
                            tags_raw = line[len("tags:"):].strip().strip("[]")
                            note_tags = ", ".join([f"`#{t.strip()}`" for t in tags_raw.split(",") if t.strip()])
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
    metrics = MetricsCollector(log_dir=cfg.get("logging", {}).get("log_dir", "logs"))

    # 检查点恢复
    processed_set = set()
    if args.resume:
        checkpoint = MetricsCollector.load_checkpoint(log_dir, logger=logger)
        if checkpoint and os.path.realpath(checkpoint["source"]) == os.path.realpath(source):
            processed_set = set(checkpoint["processed"])
            restored_metrics = checkpoint["metrics"]
            metrics.metrics = restored_metrics
            metrics.metrics["run_id"] = datetime.now().strftime("%Y%m%d_%H%M%S")
            skip_count = len(processed_set)
            logger.info(f"[恢复] 从检查点恢复，已处理 {skip_count} 个文件")
            logger.info(f"[恢复] 成功: {restored_metrics['succeeded']}, 失败: {restored_metrics['failed']}")
        else:
            logger.info("[恢复] 未找到匹配的检查点，从头开始")

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
                metrics.end_file("skip", "重复文件")
            else:
                unique_files.append(f)
        files = unique_files
        if not files:
            logger.info("所有文件均为重复文件，无需处理")
            return

    # 过滤已处理的文件（恢复模式下）
    if args.resume and processed_set:
        files = [f for f in files if f not in processed_set]
        logger.info(f"[恢复] 过滤掉 {len(processed_set)} 个已处理文件，剩余 {len(files)} 个待处理")

    logger.info(f"找到 {len(files)} 个新文件待处理")

    for i, file_path in enumerate(files, 1):
        fname = os.path.basename(file_path)
        logger.info(f"[{i}/{len(files)}] 处理: {fname}")

        if args.dry_run:
            logger.info(f"  [DRY-RUN] 将处理: {fname}")
            stats["skipped"] += 1
            continue

        metrics.start_file(file_path)

        try:
            result = handle_file(file_path, cfg, vault_path)
        except Exception as e:
            # 捕获 handle_file 内部未处理的异常
            result = {"status": "fail", "error": f"未处理异常: {type(e).__name__}: {e}"}
            logger.exception(f"  [EXCEPTION] {fname}: {e}")

        if result["status"] == "ok":
            logger.info(f"  [OK] {fname} → {result['path']}")
            logger.info(f"  分类: {result['category']} | 标签: {result['tags']}")
            stats["ok"] += 1
            metrics.end_file("ok", f"{result['category']}")
        else:
            move_to_failed(file_path, vault_path, cfg["import"]["failed_dir"], result["error"])
            logger.error(f"  [FAIL] {fname}: {result['error']}")
            stats["failed"] += 1
            metrics.end_file("fail", result["error"])

        # 进度日志（每 10 个文件打印一次）
        metrics.log_progress(logger, interval=10)

        # 健康检查：失败率过高时警告
        health = metrics.get_health()
        if not health["healthy"] and metrics.metrics["processed"] >= 5:
            logger.warning(f"[健康检查] {health['message']}")

        # 保存检查点（每处理一个文件）
        if not args.dry_run:
            metrics.save_checkpoint(source, files,
                set(m["file"] for m in metrics.metrics["file_details"]))

    # 健康检查
    health = metrics.get_health()
    logger.info(f"健康状态: {health['message']}")

    try:
        if not args.dry_run:
            update_moc(vault_path)
            # 清除检查点（处理完成）
            MetricsCollector.clear_checkpoint(log_dir)
            # 保存指标报告
            report_path = metrics.save_report()
            logger.info(f"指标报告已保存: {report_path}")

        metrics.print_summary(logger)
    except Exception as e:
        # 确保即使报告生成失败也能保存指标
        try:
            report_path = metrics.save_report()
            logger.error(f"报告生成失败，但指标已保存: {report_path} — {e}")
        except Exception:
            logger.error(f"指标保存也失败: {e}")


if __name__ == "__main__":
    main()
