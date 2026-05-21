"""Vault alignment, migration, and verification operations."""

import logging
import os
import re
import shutil
from pathlib import Path
from typing import Dict

from scripts.path_utils import compute_source_relative_path
from scripts.moc_manager import MOCManager
from scripts.crosslink import DocumentIndex, apply_crosslinks

logger = logging.getLogger("notemind")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg"}


def align_vault_dirs_to_source(vault_path: str, source_dir: str) -> dict:
    """根据 source 目录结构对齐 vault 中的 MD 文件目录。

    扫描 source 下所有文件，在 vault 中查找同名的 MD 文件，
    将其移动到正确的目录（镜像 source 结构）。

    Returns:
        {"moved": int, "skipped": int, "errors": int}
    """
    logger.info(f"对齐 vault 目录到 source 结构: {source_dir}")

    # 扫描 source，建立 {stem: source_rel_dir} 映射
    source_map = {}
    for root, _, files in os.walk(source_dir):
        rel_dir = os.path.relpath(root, source_dir)
        if rel_dir == ".":
            rel_dir = ""
        for f in files:
            stem = Path(f).stem
            source_map[stem] = rel_dir

    # 扫描 vault，匹配并移动
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


def _build_doc_map(vault_path: str) -> dict:
    """扫描 vault 中所有 MD 文件，构建 original_path → vault_rel_path 映射。"""
    doc_map = {}
    for root, _, files in os.walk(vault_path):
        for f in files:
            if not f.endswith(".md") or f.startswith("MOC"):
                continue
            md_path = os.path.join(root, f)
            try:
                with open(md_path, "r", encoding="utf-8") as fh:
                    content = fh.read()
                original_path = ""
                for line in content.split("\n"):
                    if line.startswith("original_path:"):
                        original_path = line[len("original_path:"):].strip()
                        break
                if original_path:
                    vault_rel = os.path.relpath(md_path, vault_path)
                    vault_rel_no_ext = vault_rel.rsplit(".", 1)[0]
                    doc_map[original_path] = vault_rel_no_ext.replace(os.sep, "/")
            except Exception:
                pass
    return doc_map


def _read_frontmatter(md_path: str) -> tuple:
    """仅读取 frontmatter 区域，返回 (original_path, category, tags_raw)。

    不读取整个文件，对于大 MD 文件（含正文/摘要）有显著性能提升。
    """
    original_path = ""
    current_category = ""
    tags_raw = ""
    try:
        with open(md_path, "r", encoding="utf-8") as fh:
            # 只读取前 500 字节（足够覆盖 frontmatter）
            header = fh.read(500)
            for line in header.split("\n"):
                if line.startswith("original_path:"):
                    original_path = line[len("original_path:"):].strip()
                elif line.startswith("category:"):
                    current_category = line[len("category:"):].strip()
                elif line.startswith("tags:"):
                    tags_raw = line[len("tags:"):].strip()
                # frontmatter 结束标记后不再读取
                if line.strip() == "---" and original_path and current_category:
                    break
    except Exception:
        pass
    return original_path, current_category, tags_raw


def _build_source_stem_map(source_dir: str) -> dict:
    """扫描 source 目录，构建 {stem: current_source_rel_path} 映射。

    同时记录 {filename: current_source_rel_path} 用于精确匹配。
    """
    stem_map = {}  # stem → rel_path (relative to source_dir)
    name_map = {}  # filename → rel_path
    for root, _, files in os.walk(source_dir):
        rel_dir = os.path.relpath(root, source_dir)
        if rel_dir == ".":
            rel_dir = ""
        for fn in files:
            full_rel = os.path.join(rel_dir, fn).replace(os.sep, "/") if rel_dir else fn
            stem = Path(fn).stem
            # 优先记录更深层的路径（更具体）
            if stem not in stem_map or full_rel.count("/") > stem_map[stem].count("/"):
                stem_map[stem] = full_rel
            name_map[fn] = full_rel
    return stem_map, name_map


def update_existing_docs(vault_path: str, source_dir: str) -> None:
    """校验并修复已有 MD 文件的分类和目录映射。

    基于 source 路径重新归类。
    支持检测源文件移动：通过文件名在 source 中匹配当前位置，而非依赖过时的 original_path。
    """
    logger.info(f"开始校验修复 vault: {vault_path}")

    scanned = 0
    category_fixed = 0
    dir_fixed = 0
    wikilink_fixed = 0
    skipped = 0
    errors = 0
    source_moved = 0  # 源文件位置已移动的计数

    # 构建映射
    doc_map = _build_doc_map(vault_path)
    source_stem_map, source_name_map = _build_source_stem_map(source_dir)

    # 逐文件修复
    for root, _, files in os.walk(vault_path):
        for f in files:
            if not f.endswith(".md") or f.startswith("MOC"):
                continue

            md_path = os.path.join(root, f)
            scanned += 1

            try:
                # 仅读取 frontmatter（性能优化：不读全文）
                original_path, current_category, tags_raw = _read_frontmatter(md_path)

                if not original_path:
                    skipped += 1
                    continue

                # 在 source 中查找当前文件位置（按文件名精确匹配，回退到 stem 匹配）
                md_stem = Path(f).stem
                current_source_rel = source_name_map.get(f) or source_stem_map.get(md_stem)

                # 确定源文件的实际路径
                if current_source_rel:
                    # 找到当前源文件位置（可能已移动）
                    full_src_path = os.path.join(source_dir, current_source_rel.replace("/", os.sep))
                    # 检查是否移动了：对比 current_source_rel 与 original_path 去掉 "source/" 前缀
                    old_source_rel = original_path[len("source/"):] if original_path.startswith("source/") else original_path
                    if old_source_rel != current_source_rel:
                        source_moved += 1
                        # 更新 original_path 到最新位置
                        new_original_path = "source/" + current_source_rel
                        original_path = new_original_path
                        logger.info(f"  [源文件移动] {f}: {old_source_rel} → {current_source_rel}")
                elif original_path.startswith("source/"):
                    # 未在 source 中找到，尝试用旧路径
                    src_relative = original_path[len("source/"):]
                    full_src_path = os.path.join(source_dir, src_relative)
                    if not os.path.exists(full_src_path):
                        skipped += 1
                        continue
                else:
                    full_src_path = os.path.join(vault_path, original_path)
                    if not os.path.exists(full_src_path):
                        skipped += 1
                        continue

                correct_category = compute_source_relative_path(full_src_path, source_dir, vault_path)
                needs_category_fix = (current_category != correct_category)
                correct_dir = os.path.join(vault_path, correct_category)
                needs_dir_fix = (os.path.normpath(root) != os.path.normpath(correct_dir))
                # 跟踪是否需要更新 original_path（源文件移动但分类/目录可能不变）
                old_op_for_update = "source/" + old_source_rel if old_source_rel else old_source_rel
                new_op_for_update = "source/" + current_source_rel
                needs_original_path_update = (old_op_for_update != new_op_for_update and
                                              current_source_rel is not None)

                if not needs_category_fix and not needs_dir_fix and not needs_original_path_update:
                    skipped += 1
                    continue

                content_changed = False
                content = None  # 延迟加载

                # 延迟读取全文（仅在需要修改时）
                if content is None:
                    with open(md_path, "r", encoding="utf-8") as fh:
                        content = fh.read()

                # 更新 original_path
                if needs_original_path_update:
                    content = content.replace(f"original_path: {old_op_for_update}",
                                              f"original_path: {new_op_for_update}", 1)
                    content_changed = True

                if needs_category_fix:
                    old_cat_line = f"category: {current_category}"
                    new_cat_line = f"category: {correct_category}"
                    content = content.replace(old_cat_line, new_cat_line, 1)
                    category_fixed += 1
                    content_changed = True
                    logger.info(f"  [分类修复] {f}: {current_category} → {correct_category}")

                if needs_dir_fix:
                    os.makedirs(correct_dir, exist_ok=True)
                    target_path = os.path.join(correct_dir, f)
                    shutil.move(md_path, target_path)
                    dir_fixed += 1
                    content_changed = True
                    logger.info(f"  [目录修复] {f}: {os.path.basename(root)} → {correct_category}/")
                    md_path = target_path

                # 修复 wikilink
                def fix_wikilink(match):
                    link_part = match.group(1)
                    alias_part = match.group(2) if match.group(2) else None
                    has_ext = "." in link_part.split("/")[-1]

                    if has_ext:
                        ext = "." + link_part.split("/")[-1].rsplit(".", 1)[1]
                        if ext.lower() not in IMAGE_EXTS:
                            link_part = link_part.rsplit(".", 1)[0]
                    else:
                        for orig_path, vault_rel in doc_map.items():
                            orig_name = Path(orig_path).stem
                            if link_part.endswith(orig_name) or link_part == orig_name:
                                orig_ext = Path(orig_path).suffix.lower()
                                if orig_ext in IMAGE_EXTS:
                                    orig_fname = Path(orig_path).name
                                    link_part = vault_rel.rsplit("/", 1)[-1] if "/" in vault_rel else vault_rel
                                    link_part = link_part + orig_ext
                                break

                    if alias_part:
                        return f"[[{link_part}|{alias_part}]]"
                    return f"[[{link_part}]]"

                wikilink_pattern = r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]"
                new_content = re.sub(wikilink_pattern, fix_wikilink, content)
                if new_content != content:
                    content = new_content
                    wikilink_fixed += 1
                    content_changed = True

                if content_changed:
                    with open(md_path, "w", encoding="utf-8") as fh:
                        fh.write(content)
                else:
                    skipped += 1

            except Exception as e:
                errors += 1
                logger.warning(f"  校验失败 {md_path}: {e}")

    logger.info(f"扫描 {scanned} 个 MD 文件，源文件移动 {source_moved} 个，修复分类 {category_fixed} 个，修复目录 {dir_fixed} 个，修复链接 {wikilink_fixed} 个，跳过 {skipped} 个，错误 {errors} 个")

    # 重建索引
    moc = MOCManager(vault_path)
    moc.update_all()
    _rebuild_crosslinks(vault_path)


def migrate_existing_docs(vault_path: str, source_dir: str) -> None:
    """快速迁移已有文档到新格式，不重新解析源文件。"""
    logger.info(f"开始迁移 vault: {vault_path}")

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

                # 更新"原文位置"/"原始文件"段落为 wikilink 格式
                old_ref_pattern = r"\n## 原文位置\n- 原文：`[^`]+`\n- 路径：`[^`]+`\n"
                if re.search(old_ref_pattern, content):
                    old_path_match = re.search(r"原文：`([^`]+)`", content)
                    if old_path_match:
                        old_file = old_path_match.group(1)
                        is_image = any(old_file.lower().endswith(ext) for ext in IMAGE_EXTS)
                        link_text = old_file if is_image else Path(old_file).stem
                    else:
                        link_text = Path(f).stem
                    content = re.sub(old_ref_pattern, f"\n## 原始文件\n- 原文：[[{link_text}]]\n\n", content)
                    changed = True

                old_archive_pattern = r"\n## 原始文件\n- 文件名：`[^`]+`\n- 源路径：`[^`]+`\n\n"
                if re.search(old_archive_pattern, content):
                    stem_match = re.search(r"文件名：`([^`]+)`", content)
                    old_file = stem_match.group(1) if stem_match else f
                    is_image = any(old_file.lower().endswith(ext) for ext in IMAGE_EXTS)
                    link_text = old_file if is_image else Path(old_file).stem
                    content = re.sub(old_archive_pattern, f"\n## 原始文件\n- 原文：[[{link_text}]]\n\n", content)
                    changed = True

                old_archive_simple = r"\n## 原始文件\n- 文件名：`([^`]+)`\n\n"
                if re.search(old_archive_simple, content):
                    stem_match = re.search(r"文件名：`([^`]+)`", content)
                    old_file = stem_match.group(1) if stem_match else f
                    is_image = any(old_file.lower().endswith(ext) for ext in IMAGE_EXTS)
                    link_text = old_file if is_image else Path(old_file).stem
                    content = re.sub(old_archive_simple, f"\n## 原始文件\n- 原文：[[{link_text}]]\n\n", content)
                    changed = True

                if changed:
                    with open(md_path, "w", encoding="utf-8") as fh:
                        fh.write(content)
                    updated_count += 1
                md_count += 1

            except Exception as e:
                logger.warning(f"  迁移失败 {md_path}: {e}")

    logger.info(f"扫描 {md_count} 个 MD 文件，更新 {updated_count} 个")

    moc = MOCManager(vault_path)
    moc.update_all()
    _rebuild_crosslinks(vault_path)


def verify_output_source_alignment(vault_path: str, source_dir: str) -> None:
    """校验 vault 输出的 MD 文件是否与 source 源文件一一对应。"""
    md_map = {}
    for root, _, files in os.walk(vault_path):
        if "_failed" in root or "_archive" in root:
            continue
        for f in files:
            if not f.endswith(".md") or f.startswith("MOC"):
                continue
            fp = os.path.join(root, f)
            try:
                with open(fp, "r", encoding="utf-8") as fh:
                    preview = fh.read(300)
                orig = ""
                category = ""
                for line in preview.split("\n"):
                    if line.startswith("original_path:"):
                        orig = line[len("original_path:"):].strip()
                    elif line.startswith("category:"):
                        category = line[len("category:"):].strip()
                if orig:
                    md_map[orig] = (fp, category)
            except Exception:
                pass

    source_files = set()
    for root, _, files in os.walk(source_dir):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, source_dir).replace(os.sep, "/")
            source_files.add(rel)

    orphan_md = []
    for orig_path, (md_path, _) in md_map.items():
        if orig_path.startswith("source/"):
            src_rel = orig_path[len("source/"):]
        else:
            src_rel = orig_path
        if src_rel not in source_files:
            orphan_md.append((os.path.basename(md_path), src_rel))

    if orphan_md:
        logger.warning(f"  ⚠ {len(orphan_md)} 个 MD 文件在 source 中无对应源文件:")
        for name, src_rel in orphan_md[:10]:
            logger.warning(f"    {name} → {src_rel}")
        if len(orphan_md) > 10:
            logger.warning(f"    ... 还有 {len(orphan_md) - 10} 个")
    else:
        logger.info("  ✅ 所有 MD 文件在 source 中都有对应源文件")

    category_md = {}
    for orig_path, (md_path, category) in md_map.items():
        cat = category or "(根目录)"
        category_md[cat] = category_md.get(cat, 0) + 1

    if category_md:
        logger.info("  📊 分类统计:")
        for cat, count in sorted(category_md.items()):
            logger.info(f"    {cat}: {count} 篇")


def _rebuild_crosslinks(vault_path: str) -> None:
    """重建文档双链。"""
    try:
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
                    category = ""
                    for line in preview.split("\n"):
                        if line.startswith("tags:"):
                            tags_raw = line[len("tags:"):].strip().strip("[]")
                            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
                        elif line.startswith("category:"):
                            category = line[len("category:"):].strip()
                    note_name = Path(f).stem
                    doc_index.add(note_name, fp, tags, category, preview)
                except Exception:
                    pass

        applied = apply_crosslinks(vault_path, doc_index)
        logger.info(f"双链更新: {applied} 个文件")
    except Exception as e:
        logger.warning(f"双链重建失败: {e}")
