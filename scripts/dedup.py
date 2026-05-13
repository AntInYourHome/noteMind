"""
NoteMind 去重模块 — 基于 MD5 的文件去重 + Wiki 页面级重复检测

用法:
    python import.py --dedup --vault PATH        # 检测并提示
    python import.py --dedup --vault PATH --merge # 检测并自动合并
"""

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger("notemind")

WIKILINK_RE = re.compile(r'\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]')
FRONTMATTER_RE = re.compile(r'^---\n([\s\S]*?)\n---\n')
TITLE_RE = re.compile(r'title:\s*["\']?(.+?)["\']?\s*$', re.MULTILINE)

# 排除的目录
EXCLUDE_DIRS = {"_failed", "_archive", ".git", ".obsidian", ".notemind"}
# 排除的文件
EXCLUDE_FILES = {"MOC.md", "MOC_unsupported.md", "MOC_fail.md", "index.md", "log.md", "overview.md"}


# ── 文件级 MD5 去重（原有功能）────────────────────────────────

def compute_md5(file_path: str, chunk_size: int = 8192) -> str:
    """计算文件的 MD5 值。"""
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            md5.update(chunk)
    return md5.hexdigest()


def load_dedup_index(vault_path: str, index_name: str) -> dict:
    """加载去重索引 {md5: {filename, date, category, note_path}}。"""
    index_file = os.path.join(vault_path, index_name)
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_dedup_index(vault_path: str, index_name: str, index: dict) -> None:
    """保存去重索引。"""
    index_file = os.path.join(vault_path, index_name)
    os.makedirs(os.path.dirname(index_file), exist_ok=True)
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def check_duplicate(file_path: str, vault_path: str, index_name: str) -> dict | None:
    """
    检查文件是否已处理过。
    返回 None 表示不重复；返回 dict 表示已处理的记录。
    """
    md5 = compute_md5(file_path)
    index = load_dedup_index(vault_path, index_name)
    return index.get(md5, None)


def add_to_index(file_path: str, md5: str, category: str, note_path: str, vault_path: str, index_name: str) -> None:
    """将新处理的文件加入索引。"""
    index = load_dedup_index(vault_path, index_name)
    index[md5] = {
        "filename": os.path.basename(file_path),
        "category": category,
        "note_path": note_path,
    }
    save_dedup_index(vault_path, index_name, index)


# ── Wiki 页面级重复检测 ──────────────────────────────────────

def extract_stem_info(filepath: str) -> tuple[str, str]:
    """
    从文件路径提取 (目录相对路径, 名称前缀)。

    例如: vault/cat/2024-05-01-elon-musk.md → ("cat", "elon-musk")
          vault/2024-05-01-test.md → ("", "test")
    """
    stem = Path(filepath).stem
    # 去掉日期前缀
    parts = stem.split("-", 2)
    if len(parts) == 3 and len(parts[0]) == 10 and parts[0][4] == '-' and parts[0][7] == '-':
        name = parts[2]
    else:
        name = stem
    # 获取相对于 vault 的目录路径
    return name.lower()


def get_frontmatter_field(content: str, field: str) -> str:
    """从 frontmatter 提取指定字段。"""
    fm_match = FRONTMATTER_RE.match(content)
    if not fm_match:
        return ""
    # 尝试提取字段
    field_re = re.compile(rf'{field}:\s*["\']?(.+?)["\']?\s*$', re.MULTILINE)
    m = field_re.search(fm_match.group(1))
    return m.group(1).strip() if m else ""


def get_page_title(filepath: str) -> str:
    """获取页面标题（frontmatter title 或文件名）。"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read(2000)
    except Exception:
        return ""
    title = get_frontmatter_field(content, "title")
    if title:
        return title
    # 回退到文件名
    return Path(filepath).stem


def find_duplicate_pages(vault_path: str, similarity_threshold: float = 0.7) -> list[dict]:
    """
    扫描 vault，查找可能重复的 Wiki 页面。

    策略:
    1. 按文件 stem 分组（去掉日期前缀后相同的名称）
    2. 同一组内比较 frontmatter title 的相似度
    3. 返回相似度超过阈值的候选组

    Returns:
        [{"name": "页面名", "paths": ["path1", "path2", ...], "titles": ["title1", ...]}]
    """
    from difflib import SequenceMatcher

    # 收集所有 MD 文件
    pages = []  # [(filepath, stem, title), ...]
    for root, dirs, files in os.walk(vault_path):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]
        for fname in files:
            if fname in EXCLUDE_FILES or not fname.endswith(".md"):
                continue
            fpath = os.path.join(root, fname)
            stem = extract_stem_info(fpath)
            title = get_page_title(fpath)
            pages.append((fpath, stem, title))

    # 按 stem 分组
    from collections import defaultdict
    stem_groups = defaultdict(list)
    for fpath, stem, title in pages:
        stem_groups[stem].append((fpath, title))

    # 找候选重复组
    candidates = []
    for stem, group in sorted(stem_groups.items()):
        if len(group) < 2:
            continue

        # 同一组内两两比较标题相似度
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                fp1, t1 = group[i]
                fp2, t2 = group[j]
                if not t1 or not t2:
                    # 无标题时，用 stem 判断
                    sim = 1.0 if stem else 0.0
                else:
                    sim = SequenceMatcher(None, t1.lower(), t2.lower()).ratio()

                if sim >= similarity_threshold:
                    candidates.append({
                        "name": stem,
                        "paths": [fp1, fp2],
                        "titles": [t1, t2],
                        "similarity": sim,
                    })

    # 去重（同一文件可能出现在多个对中）
    seen_pairs = set()
    unique = []
    for c in candidates:
        key = tuple(sorted(c["paths"]))
        if key not in seen_pairs:
            seen_pairs.add(key)
            unique.append(c)

    return unique


def merge_duplicate_pages(vault_path: str, candidates: list[dict], dry_run: bool = False) -> dict:
    """
    合并重复的 Wiki 页面。

    策略:
    1. 选择最早创建的页面（frontmatter created 字段）作为 canonical
    2. 合并内容（sources[] union, tags union, body 保留 canonical）
    3. 重写其他页面中对被删除页面的 wikilink
    4. 删除多余页面

    Returns:
        {"merged": int, "deleted": int, "rewritten": int}
    """
    stats = {"merged": 0, "deleted": 0, "rewritten": 0}

    for c in candidates:
        paths = c["paths"]
        if len(paths) < 2:
            continue

        # 选择 canonical（按路径排序取第一个）
        sorted_paths = sorted(paths)
        canonical = sorted_paths[0]
        to_delete = sorted_paths[1:]

        # 读取 canonical 的 frontmatter
        try:
            with open(canonical, "r", encoding="utf-8") as f:
                canonical_content = f.read()
        except Exception as e:
            logger.warning(f"  读取 canonical 失败: {canonical}: {e}")
            continue

        # 合并 sources[] 和 tags[]
        all_sources = set()
        all_tags = set()

        # 从 canonical 提取
        fm_match = FRONTMATTER_RE.match(canonical_content)
        if fm_match:
            sources_m = re.search(r'sources:\s*\[([^\]]*)\]', fm_match.group(1))
            if sources_m:
                all_sources.update(s.strip().strip("\"'") for s in sources_m.group(1).split(",") if s.strip())
            tags_m = re.search(r'tags:\s*\[([^\]]*)\]', fm_match.group(1))
            if tags_m:
                all_tags.update(s.strip().strip("\"'") for s in tags_m.group(1).split(",") if s.strip())

        # 从被删除页面中提取并合并
        for dp in to_delete:
            try:
                with open(dp, "r", encoding="utf-8") as f:
                    del_content = f.read()
            except Exception:
                continue
            fm_match2 = FRONTMATTER_RE.match(del_content)
            if fm_match2:
                sources_m = re.search(r'sources:\s*\[([^\]]*)\]', fm_match2.group(1))
                if sources_m:
                    all_sources.update(s.strip().strip("\"'") for s in sources_m.group(1).split(",") if s.strip())
                tags_m = re.search(r'tags:\s*\[([^\]]*)\]', fm_match2.group(1))
                if tags_m:
                    all_tags.update(s.strip().strip("\"'") for s in tags_m.group(1).split(",") if s.strip())

        # 更新 canonical 的 frontmatter
        new_content = canonical_content
        if all_sources:
            sources_str = ", ".join(f'"{s}"' for s in sorted(all_sources))
            if "sources:" in new_content[:500]:
                new_content = re.sub(r'sources:\s*\[[^\]]*\]', f'sources: [{sources_str}]', new_content)

        if all_tags:
            tags_str = ", ".join(f'"{s}"' for s in sorted(all_tags))
            if "tags:" in new_content[:500]:
                new_content = re.sub(r'tags:\s*\[[^\]]*\]', f'tags: [{tags_str}]', new_content)

        # 添加合并说明
        merge_note = f"\n> 合并自: " + ", ".join(Path(p).name for p in to_delete) + "\n"
        if merge_note not in new_content:
            # 在 frontmatter 后面添加
            fm_end = new_content.find("---\n", 4)
            if fm_end != -1:
                new_content = new_content[:fm_end + 4] + merge_note + new_content[fm_end + 4:]

        if not dry_run:
            with open(canonical, "w", encoding="utf-8") as f:
                f.write(new_content)
            stats["merged"] += 1

        logger.info(f"  [MERGE] canonical: {Path(canonical).name}")
        logger.info(f"    合并自: {', '.join(Path(p).name for p in to_delete)}")

        # 删除多余页面
        for dp in to_delete:
            if not dry_run:
                os.remove(dp)
                stats["deleted"] += 1
            logger.info(f"  [DELETE] {Path(dp).name}")

        # 重写其他页面中的 wikilink
        deleted_stems = [extract_stem_info(dp) for dp in to_delete]
        canonical_stem = extract_stem_info(canonical)
        stats["rewritten"] += _rewrite_wikilinks(vault_path, deleted_stems, canonical_stem, dry_run)

    return stats


def _rewrite_wikilinks(vault_path: str, deleted_stems: list[str], canonical_stem: str, dry_run: bool) -> int:
    """重写 vault 中指向被删除页面的 wikilink。"""
    count = 0
    deleted_lower = [s.lower() for s in deleted_stems]

    for root, dirs, files in os.walk(vault_path):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]
        for fname in files:
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(root, fname)

            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                continue

            new_content = content
            for del_stem in deleted_stems:
                # 替换 [[old-stem]] → [[new-stem]]
                pattern = re.compile(r'\[\[' + re.escape(del_stem) + r'(\|[^\]]+)?\]\]')
                if pattern.search(new_content):
                    new_content = pattern.sub(f'[[{canonical_stem}\\1]]', new_content)

            if new_content != content:
                if not dry_run:
                    with open(fpath, "w", encoding="utf-8") as f:
                        f.write(new_content)
                count += 1

    return count
