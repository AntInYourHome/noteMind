"""MOC (Map of Content) generation for Obsidian vault."""

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Dict, Optional

logger = logging.getLogger("notemind")


class TreeRenderer:
    """通用树形结构渲染器，消除 MOC/update_moc/update_unsupported_moc 间的重复代码。"""

    @staticmethod
    def build_tree(entries: List[tuple], include_type: bool = False) -> dict:
        """从扁平条目构建嵌套树。

        Args:
            entries: [(category, note_stem, extra), ...]
                extra 通常是标签字符串或文件类型
            include_type: 是否在链接中包含 extra（用于不支持格式的文件）

        Returns:
            {"name": {"_notes": [(note_stem, extra), ...], "_children": {...}}, ...}
        """
        tree = {}
        for category, note_stem, extra in entries:
            if not category:
                continue
            parts = category.split("/")
            current = tree
            for i, part in enumerate(parts):
                if part not in current:
                    current[part] = {"_notes": [], "_children": {}}
                if i == len(parts) - 1:
                    current[part]["_notes"].append((note_stem, extra))
                current = current[part]["_children"]
        return tree

    @staticmethod
    def count_notes(node: dict) -> int:
        """计算节点下所有笔记数（含子节点）。"""
        count = len(node["_notes"])
        for child in node["_children"].values():
            count += TreeRenderer.count_notes(child)
        return count

    @staticmethod
    def render(tree: dict, level: int = 2, include_type: bool = False) -> List[str]:
        """递归渲染树结构为 Markdown 行。

        Args:
            tree: build_tree 返回的树结构
            level: 起始标题级别（2 = ##）
            include_type: 是否在链接中附加 extra（如文件后缀）
        """
        result = []
        heading_prefix = "#" * level
        for name in sorted(tree.keys()):
            node = tree[name]
            notes = node["_notes"]
            children = node["_children"]
            total_count = TreeRenderer.count_notes(node)

            if total_count > 0:
                result.append(f"\n{heading_prefix} {name} ({total_count} 篇)\n")

            for note_stem, extra in notes:
                if include_type and extra:
                    link = f"{note_stem}{extra}"
                elif extra:
                    link = f"{note_stem} {extra}"
                else:
                    link = note_stem
                result.append(f"- [[{link}]]\n")

            if children and level < 6:
                result.extend(TreeRenderer.render(children, level + 1, include_type))

        return result

    @staticmethod
    def render_root_entries(entries: List[tuple], include_type: bool = False,
                            section_title: str = None) -> List[str]:
        """渲染根目录条目（无分类的笔记）。"""
        if not entries:
            return []
        title = section_title or f"根目录 ({len(entries)} 篇)"
        result = [f"\n## {title}\n"]
        for note_stem, extra in entries:
            if include_type and extra:
                link = f"{note_stem}{extra}"
            elif extra:
                link = f"{note_stem} {extra}"
            else:
                link = note_stem
            result.append(f"- [[{link}]]\n")
        return result


class MOCManager:
    """生成和管理 vault 的 MOC 文件。"""

    MAX_ENTRIES = 500
    MAX_TAGS_PER_NOTE = 3

    def __init__(self, vault_path: str):
        self.vault_path = vault_path
        self.renderer = TreeRenderer()

    def _scan_notes(self, dir_path: str, rel_path: str,
                    exclude_dirs: set = None) -> List[tuple]:
        """递归扫描目录，返回 [(note_stem, full_rel_path, content_preview), ...]。"""
        results = []
        if not os.path.isdir(dir_path):
            return results
        if exclude_dirs is None:
            exclude_dirs = {"_failed", "_archive"}
        for entry in sorted(os.listdir(dir_path)):
            full_entry = os.path.join(dir_path, entry)
            entry_rel = os.path.join(rel_path, entry) if rel_path else entry
            if entry in exclude_dirs or entry.startswith("."):
                continue
            if os.path.isdir(full_entry):
                results.extend(self._scan_notes(full_entry, entry_rel, exclude_dirs))
            elif entry.endswith(".md") and not entry.startswith("MOC"):
                try:
                    with open(full_entry, "r", encoding="utf-8") as nf:
                        preview = nf.read(500)
                    if "parent:" not in preview or "doc_type: index" in preview:
                        results.append((Path(entry).stem, entry_rel, preview))
                except Exception:
                    pass
        return results

    def update_main_moc(self) -> None:
        """生成主 MOC.md。"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        notes = self._scan_notes(self.vault_path, "", {"_failed", "_archive"})

        all_entries = []
        total_notes = 0
        for note_stem, note_rel, preview in notes:
            # 提取完整目录路径作为 category
            note_category = os.path.dirname(note_rel).replace(os.sep, "/") if os.sep in note_rel else ""

            # 检查是否为不支持格式
            is_unsupported = False
            note_tags = ""
            try:
                for line in preview.split("\n"):
                    if line.startswith("tags:"):
                        tags_raw = line[len("tags:"):].strip().strip("[]")
                        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
                        if "未识别格式" in tags:
                            is_unsupported = True
                        display_tags = tags[:self.MAX_TAGS_PER_NOTE]
                        note_tags = ", ".join([f"`#{t}`" for t in display_tags])
                        if len(tags) > self.MAX_TAGS_PER_NOTE:
                            note_tags += f" 等{len(tags)}个"
                        break
            except Exception:
                pass

            if is_unsupported:
                continue

            all_entries.append((note_category, note_stem, note_tags))
            total_notes += 1

        self._write_moc_files(all_entries, total_notes, timestamp, prefix="MOC")

    def update_failed_moc(self) -> None:
        """生成 MOC_fail.md。"""
        failed_dir = os.path.join(self.vault_path, "_failed")
        moc_fail_path = os.path.join(self.vault_path, "MOC_fail.md")
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        failed_entries = []
        if os.path.isdir(failed_dir):
            for entry in sorted(os.listdir(failed_dir)):
                if not entry.endswith(".md"):
                    continue
                fp = os.path.join(failed_dir, entry)
                try:
                    with open(fp, "r", encoding="utf-8") as f:
                        preview = f.read(500)
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
            if os.path.exists(moc_fail_path):
                os.remove(moc_fail_path)
                logger.info("无失败文件，已移除 MOC_fail.md")
            return

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
                short_err = error_msg[:80] + ("..." if len(error_msg) > 80 else "")
                lines.append(f"  - 原因: {short_err}\n")
        lines.append(f"\n> 由 NoteMind 自动生成于 {timestamp}\n")

        with open(moc_fail_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        logger.info(f"失败文件索引已更新: {moc_fail_path} ({len(failed_entries)} 个)")

    def update_unsupported_moc(self, unsupported_files: Optional[List] = None) -> None:
        """生成 MOC_unsupported.md。

        Args:
            unsupported_files: [(category, file_name, file_type), ...] 可选
        """
        moc_unsupported_path = os.path.join(self.vault_path, "MOC_unsupported.md")
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 收集条目
        from scripts.handlers import UnsupportedHandler
        handler = UnsupportedHandler(self.vault_path)
        entries = handler.collect_unsupported_entries(unsupported_files)

        if not entries:
            if unsupported_files is not None and os.path.exists(moc_unsupported_path):
                os.remove(moc_unsupported_path)
                logger.info("无不支持格式文件，已移除 MOC_unsupported.md")
            return

        # 分离根目录和树形条目
        root_entries = [(n, t) for c, n, t in entries if not c]
        tree_entries = [(c, n, t) for c, n, t in entries if c]

        total = len(entries)
        if total <= self.MAX_ENTRIES:
            moc_paths = [moc_unsupported_path]
            contents = [self._build_unsupported_moc_content(root_entries, tree_entries, total, timestamp)]
        else:
            num_parts = (total + self.MAX_ENTRIES - 1) // self.MAX_ENTRIES
            moc_paths = []
            contents = []
            for i in range(num_parts):
                start = i * self.MAX_ENTRIES
                end = min(start + self.MAX_ENTRIES, total)
                part_entries = entries[start:end]
                part_root = [(n, t) for c, n, t in part_entries if not c]
                part_tree = [(c, n, t) for c, n, t in part_entries if c]
                moc_path_i = os.path.join(self.vault_path, f"MOC_unsupported_{i + 1}.md")
                moc_paths.append(moc_path_i)
                contents.append(self._build_unsupported_moc_content(
                    part_root, part_tree, total, timestamp,
                    part=i + 1, total_parts=num_parts
                ))

        # 清理旧文件
        preserve_mocs = {"MOC_fail.md"}
        for old_moc in os.listdir(self.vault_path):
            if old_moc.startswith("MOC_unsupported") and old_moc.endswith(".md"):
                if old_moc in preserve_mocs:
                    continue
                old_path = os.path.join(self.vault_path, old_moc)
                if old_path not in moc_paths:
                    try:
                        os.remove(old_path)
                    except Exception:
                        pass

        for moc_path, content_lines in zip(moc_paths, contents):
            with open(moc_path, "w", encoding="utf-8") as f:
                f.writelines(content_lines)

        if len(moc_paths) == 1:
            logger.info(f"不支持格式索引已更新: {moc_unsupported_path} ({total} 个文件)")
        else:
            logger.info(f"不支持格式索引已更新: {len(moc_paths)} 个文件, 共 {total} 个文件")

    def update_all(self) -> None:
        """更新所有 MOC 文件。"""
        self.update_main_moc()
        self.update_unsupported_moc()
        self.update_failed_moc()

    # --- Internal helpers ---

    def _build_moc_content(self, entries: list, total_notes: int, timestamp: str,
                           part: int = 0, total_parts: int = 0) -> List[str]:
        """构建 MOC 文件内容（使用 TreeRenderer）。"""
        lines = ["# 知识树\n", f"> 自动更新于 {timestamp}\n"]
        if total_parts > 1:
            lines.append(f"\n> 第 {part}/{total_parts} 部分 | 总计 {total_notes} 篇笔记\n")

        # 分离空 category 和有 category 的条目
        root_entries = [(n, t) for c, n, t in entries if not c]
        tree_entries = [(c, n, t) for c, n, t in entries if c]

        # 根目录文件
        if root_entries:
            lines.append(f"\n## 根目录 ({len(root_entries)} 篇)\n")
            for note_stem, note_tags in root_entries:
                lines.append(f"- [[{note_stem}]] {note_tags}\n" if note_tags else f"- [[{note_stem}]]\n")

        # 树形结构
        tree = self.renderer.build_tree(tree_entries)
        lines.extend(self.renderer.render(tree, level=2))

        lines.append(f"\n---\n**总计：{total_notes} 篇笔记**\n")
        return lines

    def _write_moc_files(self, entries: list, total_notes: int, timestamp: str,
                         prefix: str = "MOC") -> None:
        """根据总数量决定单文件还是分割写入。"""
        if total_notes <= self.MAX_ENTRIES:
            moc_paths = [os.path.join(self.vault_path, f"{prefix}.md")]
            parts_list = [self._build_moc_content(entries, total_notes, timestamp)]
        else:
            num_parts = (total_notes + self.MAX_ENTRIES - 1) // self.MAX_ENTRIES
            moc_paths = []
            parts_list = []
            for i in range(num_parts):
                start = i * self.MAX_ENTRIES
                end = min(start + self.MAX_ENTRIES, total_notes)
                part_entries = entries[start:end]
                moc_path_i = os.path.join(self.vault_path, f"{prefix}_{i + 1}.md")
                moc_paths.append(moc_path_i)
                parts_list.append(self._build_moc_content(part_entries, total_notes, timestamp,
                                                          part=i + 1, total_parts=num_parts))

        # 清理旧文件（保留 MOC_unsupported*.md 和 MOC_fail*.md）
        def is_preserved_moc(name: str) -> bool:
            return name in ("MOC_unsupported.md", "MOC_fail.md") or \
                   name.startswith("MOC_unsupported_") or \
                   name.startswith("MOC_fail_")

        for old_moc in os.listdir(self.vault_path):
            if old_moc.startswith("MOC") and old_moc.endswith(".md"):
                if is_preserved_moc(old_moc):
                    continue
                old_path = os.path.join(self.vault_path, old_moc)
                if old_path not in moc_paths:
                    try:
                        os.remove(old_path)
                    except Exception:
                        pass

        for moc_path, content_lines in zip(moc_paths, parts_list):
            with open(moc_path, "w", encoding="utf-8") as f:
                f.writelines(content_lines)

        if len(moc_paths) == 1:
            logger.info(f"知识树已更新: {moc_paths[0]} ({total_notes} 篇笔记)")
        else:
            logger.info(f"知识树已更新: {len(moc_paths)} 个文件, 共 {total_notes} 篇笔记")

    def _build_unsupported_moc_content(self, root_entries, tree_entries, total,
                                       timestamp, part=0, total_parts=0) -> List[str]:
        """构建 MOC_unsupported.md 内容（使用 TreeRenderer）。"""
        lines = [
            "# 不支持格式文件\n",
            f"> 自动更新于 {timestamp}\n",
        ]
        if total_parts > 1:
            lines.append(f"\n> 第 {part}/{total_parts} 部分 | 总计 {total} 个文件\n")
        lines.append(f"\n共 {total} 个文件格式不支持。\n")

        # 根目录文件
        if root_entries:
            lines.append(f"\n## 根目录 ({len(root_entries)} 篇)\n")
            for note_stem, file_type in root_entries:
                link = f"{note_stem}{file_type}" if file_type else note_stem
                lines.append(f"- [[{link}]]\n")

        # 树形结构（include_type=True 以显示文件后缀）
        tree = self.renderer.build_tree(tree_entries)
        lines.extend(self.renderer.render(tree, level=2, include_type=True))

        lines.append(f"\n> 由 NoteMind 自动生成于 {timestamp}\n")
        return lines
