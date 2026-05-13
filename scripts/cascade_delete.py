"""
NoteMind — 级联删除

删除源文件时，智能清理所有关联的 Wiki 页面：
1. 查找 frontmatter sources[] 包含此源的所有 MD 文件
2. 资料摘要页面 → 直接删除
3. 实体/概念页面：
   - 只有一个来源 → 删除
   - 多个来源 → 从 sources[] 中移除此源，保留页面
4. 从 index.md / MOC 中移除被删除页面的条目
5. 从其他 Wiki 页面中移除指向被删除页面的 [[wikilink]]
"""

import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger("notemind")

FRONTMATTER_RE = re.compile(r'^---\n([\s\S]*?)\n---\n?')
SOURCE_PATH_RE = re.compile(r'source_path:\s*["\']?(.+?)["\']?\s*$')
SOURCES_RE = re.compile(r'sources:\s*\[(.*?)\]', re.DOTALL)
WIKILINK_RE = re.compile(r'\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]')


def cascade_delete(source_path: str, vault_path: str) -> dict:
    """
    删除源文件时级联清理关联 Wiki 页面。

    Args:
        source_path: 要删除的源文件绝对路径
        vault_path: Vault 根目录

    Returns:
        {
            "deleted_pages": [...],    # 被删除的 Wiki 页面路径
            "updated_pages": [...],    # 被更新（移除 source）的页面路径
            "cleaned_links": [...],    # 被清理 wikilink 的页面路径
            "error": str | None
        }
    """
    result = {
        "deleted_pages": [],
        "updated_pages": [],
        "cleaned_links": [],
        "error": None,
    }

    source_abs = os.path.realpath(source_path)
    if not os.path.exists(source_abs):
        result["error"] = f"源文件不存在: {source_abs}"
        return result

    # 步骤 1: 扫描所有 MD 文件，找到引用此源的页面
    related_pages = _find_pages_with_source(vault_path, source_abs)

    if not related_pages:
        logger.info(f"  [级联删除] 无 Wiki 页面引用源文件: {os.path.basename(source_abs)}")
        return result

    pages_to_delete = []
    pages_to_update = []

    for page_path in related_pages:
        content = _read_file(page_path)
        if content is None:
            continue

        frontmatter = _parse_frontmatter(content)
        sources = frontmatter.get("sources", [])

        # 规范化 source 路径比较
        sources_normalized = [os.path.realpath(s) for s in sources]
        if source_abs not in sources_normalized:
            # 有些页面的 source 信息在 body 中而非 frontmatter
            # 保守处理：保留页面，只清理 wikilink
            pages_to_update.append(page_path)
            continue

        # 移除当前源
        new_sources = [s for s in sources if os.path.realpath(s) != source_abs]

        if len(new_sources) == 0:
            # 没有其他来源，删除页面
            pages_to_delete.append(page_path)
        else:
            # 还有其他来源，更新 frontmatter
            pages_to_update.append((page_path, new_sources, content))

    # 步骤 2: 删除页面
    for page_path in pages_to_delete:
        try:
            os.remove(page_path)
            result["deleted_pages"].append(page_path)
            logger.info(f"  [删除] {os.path.basename(page_path)}")
        except Exception as e:
            logger.warning(f"  [删除失败] {page_path}: {e}")

    # 步骤 3: 更新页面（移除 source）
    for item in pages_to_update:
        if isinstance(item, str):
            # 仅路径，不做 frontmatter 更新
            continue
        page_path, new_sources, content = item
        new_content = _update_sources_in_frontmatter(content, new_sources)
        if new_content != content:
            try:
                _write_file(page_path, new_content)
                result["updated_pages"].append(page_path)
                logger.info(f"  [更新] {os.path.basename(page_path)} (sources 更新为 {len(new_sources)} 个)")
            except Exception as e:
                logger.warning(f"  [更新失败] {page_path}: {e}")

    # 步骤 4: 从其他页面移除指向已删除页面的 wikilink
    deleted_stems = [Path(p).stem for p in result["deleted_pages"]]
    if deleted_stems:
        cleaned = _remove_broken_wikilinks(vault_path, deleted_stems)
        result["cleaned_links"] = cleaned

    # 步骤 5: 更新 MOC
    try:
        import importlib
        importer = importlib.import_module("import")
        importer.update_moc(vault_path)
    except Exception as e:
        logger.warning(f"  [MOC 更新失败] {e}")

    return result


def _find_pages_with_source(vault_path: str, source_abs: str) -> list[str]:
    """查找 frontmatter 中 sources[] 或 source_path 包含指定源的所有 MD 页面。"""
    results = []
    for root, dirs, files in os.walk(vault_path):
        dirs[:] = [d for d in dirs if d not in {"_failed", ".git", ".obsidian", ".notemind"}]
        for fname in files:
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(root, fname)
            content = _read_file(fpath)
            if content is None:
                continue

            # 检查 source_path
            match = SOURCE_PATH_RE.search(content)
            if match:
                sp = os.path.realpath(match.group(1))
                if sp == source_abs:
                    results.append(fpath)
                    continue

            # 检查 sources[]
            match = SOURCES_RE.search(content)
            if match:
                sources_str = match.group(1)
                sources = [s.strip().strip("'\"") for s in sources_str.split(",")]
                for s in sources:
                    if s and os.path.realpath(s) == source_abs:
                        results.append(fpath)
                        break

    return results


def _parse_frontmatter(content: str) -> dict:
    """解析 YAML frontmatter（简化版，不依赖 yaml 库）。"""
    match = FRONTMATTER_RE.match(content)
    if not match:
        return {}

    fm_text = match.group(1)
    result = {}
    for line in fm_text.split("\n"):
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        # 解析列表 [...]
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            if inner:
                result[key] = [s.strip().strip("'\"") for s in inner.split(",")]
            else:
                result[key] = []
        else:
            result[key] = value.strip("'\"")

    return result


def _update_sources_in_frontmatter(content: str, new_sources: list[str]) -> str:
    """更新 frontmatter 中的 sources[] 字段。"""
    sources_str = ", ".join(f"'{s}'" for s in new_sources) if new_sources else ""

    def replacer(m):
        return f"sources: [{sources_str}]"

    new_content = SOURCES_RE.sub(replacer, content)
    return new_content


def _remove_broken_wikilinks(vault_path: str, deleted_stems: list[str]) -> list[str]:
    """
    扫描所有 MD 文件，移除指向已删除页面的 [[wikilink]]。
    返回被清理的页面路径列表。
    """
    cleaned = []
    deleted_set = set(deleted_stems)

    for root, dirs, files in os.walk(vault_path):
        dirs[:] = [d for d in dirs if d not in {"_failed", ".git", ".obsidian", ".notemind"}]
        for fname in files:
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(root, fname)
            content = _read_file(fpath)
            if content is None:
                continue

            new_content = content
            for stem in deleted_set:
                # 匹配 [[stem]] 或 [[stem|display]]
                pattern = re.compile(r'\[\[' + re.escape(stem) + r'(?:\|[^\]]+?)?\]\]')
                new_content = pattern.sub("", new_content)

            # 清理多余的空行
            new_content = re.sub(r'\n{3,}', '\n\n', new_content)

            if new_content != content:
                try:
                    _write_file(fpath, new_content)
                    cleaned.append(fpath)
                except Exception as e:
                    logger.warning(f"  [wikilink 清理失败] {fpath}: {e}")

    return cleaned


def _read_file(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def _write_file(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
