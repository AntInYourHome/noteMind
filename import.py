#!/usr/bin/env python3
"""NoteMind — 导入文件到 Obsidian Vault

流程编排：解析 → AI 分析 → 构建 Markdown → 写入 Vault

用法：
    ./import.py --source /path/to/files
    ./import.py --source /path/to/files --vault ~/my-vault
    ./import.py --source /path/to/files --dry-run
    ./import.py --source /path/to/files --resume  # 从上次中断处继续
"""

import argparse
import logging
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from scripts.config import load_config, get_vault_path, get_source_path
from scripts.status_db import StatusDB, _get_status_db, _close_status_db, _reset_status_db
from scripts.file_collector import collect_all_files
from scripts.file_processor import FileProcessor, parse_with_retry, update_frontmatter_tags
from scripts.moc_manager import MOCManager
from scripts.vault_ops import align_vault_dirs_to_source, update_existing_docs, migrate_existing_docs, verify_output_source_alignment
from scripts.handlers import UnsupportedHandler, create_failed_record
from scripts.ingest_cache import IngestCache, compute_sha256

# 初始化日志
logger = logging.getLogger("notemind")


# --- 兼容旧接口的 stub（过渡期保留，供外部调用）---
STATUS_DB = ".notemind_status.db"

def _build_moc_lines(entries: list, total_notes: int, timestamp: str,
                     part: int = 0, total_parts: int = 0) -> list[str]:
    moc = MOCManager(vault_path=".")  # 临时实例，只用内容构建
    return moc._build_moc_content(entries, total_notes, timestamp, part, total_parts)
def compute_file_hash(file_path: str) -> str:
    return StatusDB.compute_hash(file_path)

def compute_source_relative_path(file_path: str, source_dir: str, vault_path: str) -> str:
    from scripts.path_utils import compute_source_relative_path as _fn
    return _fn(file_path, source_dir, vault_path)

def compute_vault_rel_path(file_path: str, source_dir: str, vault_path: str) -> str:
    from scripts.path_utils import compute_vault_rel_path as _fn
    return _fn(file_path, source_dir, vault_path)

def collect_files(source: str) -> list:
    from scripts.file_collector import collect_files as _fn
    return _fn(source)

def check_file_updated(vault_path: str, file_path: str) -> tuple:
    db = StatusDB(vault_path)
    db.connect()
    return db.check_updated(file_path)

def record_status(vault_path: str, file_path: str, status_type: str, md_path: str = None, category: str = None, error: str = None):
    db = StatusDB(vault_path)
    db.connect()
    db.record(file_path, status_type, md_path, category, error)

def get_status_summary(vault_path: str) -> dict:
    db = StatusDB(vault_path)
    db.connect()
    return db.summary()

def close_status_db():
    _close_status_db()

def reset_status_db():
    _reset_status_db()

def init_vault(vault_path: str) -> None:
    cfg = load_config()
    categories = cfg["vault"].get("categories", ["其他"])
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

def handle_unsupported_file(file_path: str, cfg: dict, vault_path: str, source_dir: str = None) -> dict:
    handler = UnsupportedHandler(vault_path, source_dir)
    return handler.handle(file_path)

def handle_file(file_path: str, cfg: dict, vault_path: str, source_dir: str = None) -> dict:
    status_db = StatusDB(vault_path)
    status_db.connect()
    cache = IngestCache(vault_path)
    processor = FileProcessor(cfg, vault_path, source_dir, status_db, cache)
    return processor.process(file_path)

def update_moc(vault_path: str, max_tags_per_note: int = 3, moc_max_entries: int = 500) -> None:
    moc = MOCManager(vault_path)
    moc.MAX_TAGS_PER_NOTE = max_tags_per_note
    moc.MAX_ENTRIES = moc_max_entries
    moc.update_main_moc()

def update_failed_moc(vault_path: str) -> None:
    moc = MOCManager(vault_path)
    moc.update_failed_moc()

def update_unsupported_moc(vault_path: str, unsupported_files: list = None) -> None:
    moc = MOCManager(vault_path)
    moc.update_unsupported_moc(unsupported_files)


def _process_images_only(source: str, cfg: dict, vault_path: str, dry_run: bool) -> None:
    """--update-image 模式：强制重新处理所有图片。"""
    from scripts.parsers import IMAGE_EXTS

    cache = IngestCache(vault_path)
    cache.invalidate_all()

    img_files = [f for f in collect_files(source) if Path(f).suffix.lower() in IMAGE_EXTS]
    logger.info(f"缓存已清除，找到 {len(img_files)} 张图片待处理")

    if not img_files:
        logger.info("没有找到图片文件")
        return

    stats = {"ok": 0, "failed": 0}
    for i, file_path in enumerate(img_files, 1):
        fname = os.path.basename(file_path)
        logger.info(f"[{i}/{len(img_files)}] 重新处理图片: {fname}")

        try:
            result = handle_file(file_path, cfg, vault_path, source)
        except PermissionError:
            logger.warning(f"  [跳过] 文件被占用: {fname}")
            stats["failed"] += 1
            continue

        if result["status"] == "ok":
            logger.info(f"  [OK] {fname} → {result['path']}")
            logger.info(f"  分类: {result['category']} | 标签: {result['tags']}")
            stats["ok"] += 1
            update_moc(vault_path)
        else:
            logger.error(f"  [FAIL] {fname}: {result['error']}")
            stats["failed"] += 1
            if not dry_run:
                create_failed_record(vault_path, file_path, result.get("error", "未知错误"), source)
                update_failed_moc(vault_path)

    logger.info(f"图片重新处理完成: 成功 {stats['ok']}, 失败 {stats['failed']}")


def _normal_import(source: str, cfg: dict, vault_path: str, stats: dict,
                   unsupported_file_records: list, dry_run: bool) -> list:
    """正常导入模式（非队列）。"""
    # 初始化组件
    status_db = StatusDB(vault_path)
    status_db.connect()
    cache = IngestCache(vault_path)
    processor = FileProcessor(cfg, vault_path, source, status_db, cache)
    moc = MOCManager(vault_path)

    cache_stats = cache.stats()
    logger.info(f"增量缓存: {cache_stats['total']} 个条目 ({cache_stats['cache_size_bytes']} bytes)")

    processed_docs = []

    # MD5 去重
    if cfg["import"].get("dedup", True):
        from scripts.dedup import check_duplicate
        dedup_index = cfg["import"].get("dedup_index", ".notemind_index.json")
        unique_files = []
        for f in collect_all_files(source)[0]:
            dup = check_duplicate(f, vault_path, dedup_index)
            if dup:
                logger.info(f"  [SKIP] 重复文件: {os.path.basename(f)} (已存在于 {dup.get('category', '?')}/{dup.get('filename', '?')})")
                stats["skipped"] += 1
            else:
                unique_files.append(f)
        files = unique_files
    else:
        files = collect_all_files(source)[0]

    if not files:
        if stats.get("ok", 0) == 0:
            logger.info("所有文件均为重复文件，无需处理")
        return processed_docs

    # 测试图片模型
    from scripts.ai_client import APIProviderPool, get_pool, test_image_analysis, print_image_test_report
    img_files = [f for f in files if Path(f).suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp')]
    ai_cfg = cfg.get("ai", {})
    providers = ai_cfg.get("providers")
    if img_files and providers:
        pool = get_pool()
        img_results = test_image_analysis(pool, img_files[0])
        print_image_test_report(img_results)

    logger.info(f"找到 {len(files)} 个新文件待处理")

    start_time = time.time()
    processed_count = 0

    for i, file_path in enumerate(files, 1):
        fname = os.path.basename(file_path)
        logger.info(f"[{i}/{len(files)}] 处理: {fname}")

        if dry_run:
            logger.info(f"  [DRY-RUN] 将处理: {fname}")
            stats["skipped"] += 1
            continue

        # 增量缓存检查
        cache_entry = cache.get(file_path)
        if cache_entry and cache_entry["sha256"] == compute_sha256(file_path):
            stats["skipped"] += 1
            processed_docs.append({
                "name": Path(cache_entry["output_files"][0]).stem if cache_entry["output_files"] else fname,
                "path": cache_entry["output_files"][0] if cache_entry["output_files"] else "",
                "tags": cache_entry.get("tags", []),
                "category": cache_entry.get("category", ""),
                "summary": "",
                "_cache_hit": True,
            })
            continue

        result = processor.process(file_path)

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
            # 写入增量缓存
            cache.put(file_path, compute_sha256(file_path), [result["path"]],
                      result.get("category", ""), result.get("tags", []))
            # 实时更新 MOC
            if not dry_run:
                moc.update_main_moc()
        else:
            record_status(vault_path, file_path, "failed", None, None, result["error"])
            logger.error(f"  [FAIL] {fname}: {result['error']}")
            stats["failed"] += 1
            if not dry_run:
                create_failed_record(vault_path, file_path, result.get("error", "未知错误"), source)
                update_failed_moc(vault_path)

        processed_count += 1
        if processed_count % 10 == 0:
            elapsed = round(time.time() - start_time, 1)
            logger.info(f"[进度] {processed_count}/{len(files)} | 成功: {stats['ok']} | 失败: {stats['failed']} | 耗时: {elapsed}s")

    return processed_docs


def _queue_import(source: str, cfg: dict, vault_path: str, stats: dict,
                  unsupported_file_records: list, dry_run: bool, resume: bool) -> list:
    """队列导入模式。"""
    from scripts.ingest_queue import IngestQueue

    files = collect_all_files(source)[0]
    if not files:
        logger.info("所有可解析文件为空，仅处理了不支持的格式")
        return []

    queue = IngestQueue(vault_path)
    cache = IngestCache(vault_path)
    moc = MOCManager(vault_path)
    processor = FileProcessor(cfg, vault_path, source, StatusDB(vault_path).connect(), cache)

    if resume:
        retried = queue.retry_failed()
        logger.info(f"=== 队列恢复模式 === 重置 {retried} 个失败任务")

    new_count = queue.enqueue_batch(files)
    logger.info(f"队列: {new_count} 个新文件入队, {queue.summary()}")

    if dry_run:
        logger.info(f"  [DRY-RUN] 队列中有 {queue.summary()['pending']} 个待处理任务")
        return []

    processed_docs = []
    interrupted = False

    def _sigint_handler(sig, frame):
        nonlocal interrupted
        logger.info("\n收到中断信号，保存队列状态...")
        interrupted = True

    signal.signal(signal.SIGINT, _sigint_handler)

    logger.info("=== 队列处理开始 ===")
    while not interrupted:
        task = queue.get_next_pending()
        if task is None:
            break

        queue.mark_processing(task.id)
        fname = os.path.basename(task.path)
        summary = queue.summary()
        logger.info(f"[{summary['done'] + 1}/{queue.summary()['total']}] 处理: {fname} (任务 {task.id})")

        result = processor.process(task.path)

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
            cache.put(task.path, compute_sha256(task.path), [result["path"]],
                      result.get("category", ""), result.get("tags", []))
            queue.mark_done(task.id)
            moc.update_main_moc()
        else:
            record_status(vault_path, task.path, "failed", None, None, result["error"])
            logger.error(f"  [FAIL] {fname}: {result['error']}")
            stats["failed"] += 1
            if not dry_run:
                create_failed_record(vault_path, task.path, result.get("error", "未知错误"), source)
                update_failed_moc(vault_path)
            queue.mark_failed(task.id)

    if interrupted:
        logger.info("处理被中断，队列状态已保存。使用 --resume 继续。")
    else:
        logger.info(f"队列处理完成: {queue.summary()}")
        queue.clear_completed()

    return processed_docs


def _post_processing(vault_path: str, cfg: dict, source: str, processed_docs: list,
                     unsupported_file_records: list, dry_run: bool) -> None:
    """导入后处理：双链、MOC、统计。"""
    # 文档双链
    if not dry_run and processed_docs:
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

    if not dry_run:
        update_moc(vault_path)
        update_failed_moc(vault_path)


def main():
    parser = argparse.ArgumentParser(description="NoteMind — 导入文件到 Obsidian Vault")
    parser.add_argument("--source", default=None, help="源文件目录路径（默认 <vault>/myfiles）")
    parser.add_argument("--vault", help="Vault 目录路径（覆盖 config.json）")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际写入文件")
    parser.add_argument("--resume", action="store_true", help="从上次中断的检查点恢复")
    parser.add_argument("--migrate", action="store_true", help="快速迁移已有文档到新格式")
    parser.add_argument("--update", action="store_true", help="校验并修复已有 MD 文件的分类和目录映射")
    parser.add_argument("--config", help="配置文件路径（默认 config.json）")
    parser.add_argument("--queue", action="store_true", help="使用持久化队列模式")
    parser.add_argument("--lint", action="store_true", help="运行 Wiki 健康检查")
    parser.add_argument("--delete", help="删除指定源文件并级联清理关联 Wiki 页面")
    parser.add_argument("--dedup", action="store_true", help="检测并合并重复的 Wiki 页面")
    parser.add_argument("--dedup-merge", action="store_true", help="检测并自动合并重复的 Wiki 页面")
    parser.add_argument("--update-image", action="store_true", help="强制重新处理所有图片")
    args = parser.parse_args()

    cfg = load_config(args.vault, args.config)
    vault_path = get_vault_path(cfg)

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
    if not providers and ai_cfg.get("api_key"):
        providers = [{
            "api_key": ai_cfg["api_key"],
            "model": ai_cfg.get("model", "qwen3.6-flash"),
            "base_url": ai_cfg.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        }]
        ai_cfg["providers"] = providers

    if providers:
        for p in providers:
            if "api_key_env" in p and "api_key" not in p:
                env_name = p.pop("api_key_env")
                key = os.environ.get(env_name)
                if key:
                    p["api_key"] = key
                else:
                    logger.warning(f"  ⚠️  环境变量 {env_name} 未设置")

    concurrency = ai_cfg.get("concurrency", 5)
    if providers:
        from scripts.ai_client import init_pool, set_tags_model, get_pool, test_api_availability, print_api_test_report
        init_pool(providers, concurrency)
        logger.info(f"AI Provider 池: {len(providers)} 个 Key, 并发: {concurrency}")

        pool = get_pool()
        api_results = test_api_availability(pool)
        print_api_test_report(api_results)

        tags_model_cfg = ai_cfg.get("tags_model")
        if tags_model_cfg:
            set_tags_model(tags_model_cfg)
            logger.info(f"标签模型: {tags_model_cfg.get('model')} (Level 3 模型路由)")
    else:
        logger.warning("未配置 providers，使用单 API Key（环境变量）")

    source = get_source_path(cfg, vault_path, args.source)

    # source 存在性校验
    if not args.lint and not args.delete and not args.dedup and not args.dedup_merge:
        if not os.path.isdir(source):
            logger.error(f"源目录不存在: {args.source}")
            sys.exit(1)

    # --- 模式分发 ---
    if args.lint:
        logger.info("=== Wiki 健康检查 ===")
        from scripts.lint import run_lint, print_lint_report
        results = run_lint(vault_path)
        print_lint_report(results)
        return

    if args.delete:
        delete_path = os.path.realpath(args.delete)
        if not os.path.exists(delete_path):
            logger.error(f"源文件不存在: {delete_path}")
            sys.exit(1)
        logger.info(f"=== 级联删除: {delete_path} ===")
        from scripts.cascade_delete import cascade_delete, print_cascade_report
        stats = cascade_delete(delete_path, vault_path)
        print_cascade_report(stats)
        return

    if args.dedup or args.dedup_merge:
        logger.info("=== 去重检测 ===")
        from scripts.dedup import find_duplicate_pages, merge_duplicate_pages
        candidates = find_duplicate_pages(vault_path)
        if not candidates:
            logger.info("未发现重复页面")
            return
        logger.info(f"发现 {len(candidates)} 组候选重复页面:")
        for c in candidates:
            logger.info(f"  {c['name']} ({c['similarity']:.0%}): {', '.join(os.path.basename(p) for p in c['paths'])}")
        if args.dedup_merge:
            stats = merge_duplicate_pages(vault_path, candidates, dry_run=args.dry_run)
            logger.info(f"合并: {stats['merged']} | 删除: {stats['deleted']} | 重写: {stats['rewritten']}")
        return

    if args.migrate:
        logger.info("=== 快速迁移模式 ===")
        align_result = align_vault_dirs_to_source(vault_path, source)
        if align_result["moved"] > 0:
            logger.info(f"目录已对齐，移动了 {align_result['moved']} 个文件")
        migrate_existing_docs(vault_path, source)
        logger.info("迁移完成！")
        return

    if args.update:
        logger.info("=== 校验修复模式 ===")
        update_existing_docs(vault_path, source)
        update_unsupported_moc(vault_path)
        verify_output_source_alignment(vault_path, source)
        logger.info("校验修复完成！")
        return

    if args.update_image:
        _process_images_only(source, cfg, vault_path, args.dry_run)
        return

    # --- 导入模式 ---
    init_vault(vault_path)
    logger.info(f"Vault 路径: {vault_path}")

    parseable_files, unsupported_files = collect_all_files(source)
    total_files = len(parseable_files) + len(unsupported_files)

    if total_files == 0:
        logger.warning("未找到可处理的文件")
        return

    logger.info(f"找到 {len(parseable_files)} 个可解析文件, {len(unsupported_files)} 个不支持的格式")

    stats = {"ok": 0, "failed": 0, "skipped": 0}
    start_time = time.time()

    # 先处理不支持的文件格式
    unsupported_file_records = []
    if unsupported_files:
        logger.info("=== 处理不支持的文件格式 ===")
        handler = UnsupportedHandler(vault_path, source)
        for i, file_path in enumerate(unsupported_files, 1):
            fname = os.path.basename(file_path)
            logger.info(f"[{i}/{len(unsupported_files)}] 不支持的格式: {fname}")
            if not args.dry_run:
                result = handler.handle(file_path)
                if result["status"] == "ok":
                    stats["ok"] += 1
                    unsupported_file_records.append((
                        result.get("category", ""),
                        result.get("file_name", fname),
                        result.get("file_type", ""),
                    ))
        logger.info(f"不支持的格式处理完成: {len(unsupported_files)} 个文件已记录索引")
        if not args.dry_run:
            update_moc(vault_path)
            update_unsupported_moc(vault_path)

    # 导入模式分发
    if args.queue or args.resume:
        processed_docs = _queue_import(source, cfg, vault_path, stats,
                                        unsupported_file_records, args.dry_run, args.resume)
    else:
        processed_docs = _normal_import(source, cfg, vault_path, stats,
                                         unsupported_file_records, args.dry_run)

    # 后处理
    _post_processing(vault_path, cfg, source, processed_docs,
                     unsupported_file_records, args.dry_run)

    # 最终统计
    elapsed = round(time.time() - start_time, 1)
    logger.info(f"健康状态: 正常")

    try:
        from scripts.ai_client import get_pool, print_log_analysis, get_perf_stats, reset_perf_stats
        pool = get_pool()
        if pool:
            pool.print_health_report()

        print_log_analysis(log_file)

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

        status_summary = get_status_summary(vault_path)
        logger.info(f"数据库状态: 成功={status_summary['success']} | 失败={status_summary['failed']} | 更新={status_summary['updated']} | 未变化={status_summary['unchanged']}")
        logger.info(f"{'=' * 50}")

        close_status_db()
    except Exception as e:
        logger.error(f"报告生成失败: {e}")


if __name__ == "__main__":
    main()
