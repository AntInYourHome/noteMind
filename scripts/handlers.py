"""Handlers for unsupported and failed files."""

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from scripts.path_utils import compute_source_relative_path

logger = logging.getLogger("notemind")


class UnsupportedHandler:
    """处理不支持的文件格式：不创建 MD 文档，仅记录索引。"""

    def __init__(self, vault_path: str, source_dir: Optional[str] = None):
        self.vault_path = vault_path
        self.source_dir = source_dir

    def handle(self, file_path: str, status_db_record: bool = True) -> dict:
        """处理不支持的文件。

        Args:
            file_path: 源文件路径
            status_db_record: 是否记录到 SQLite

        Returns:
            {"status": "ok", "path": None, "category": category, "file_type": ext}
        """
        fname = os.path.basename(file_path)
        file_ext = Path(fname).suffix.lower()

        if self.source_dir:
            source_rel = compute_source_relative_path(file_path, self.source_dir, self.vault_path)
        else:
            source_rel = ""

        logger.info(f"  [UNSUPPORTED] {fname} (类型: {file_ext})，仅记录索引")

        if status_db_record:
            from scripts.status_db import StatusDB
            db = StatusDB(self.vault_path)
            db.connect()
            db.record(file_path, "unsupported", None, source_rel)

        return {
            "status": "ok",
            "path": None,
            "category": source_rel,
            "file_type": file_ext,
            "file_name": fname,
        }

    def collect_unsupported_entries(self, unsupported_files: List = None) -> List[tuple]:
        """收集不支持的文件条目。

        Args:
            unsupported_files: [(category, file_name, file_type), ...] 内存中的列表

        Returns:
            [(category, note_stem, file_type), ...]
        """
        entries = []
        if unsupported_files is not None:
            for entry in unsupported_files:
                if isinstance(entry, dict):
                    cat = entry.get("category", "")
                    name = entry.get("file_name", entry.get("path", ""))
                    ftype = entry.get("file_type", "")
                else:
                    cat, name, ftype = entry[0], entry[1], entry[2] if len(entry) > 2 else ""
                stem = Path(name).stem.replace(" ", "_")
                entries.append((cat, stem, ftype))
        else:
            # 从 SQLite 读取
            from scripts.status_db import StatusDB
            db = StatusDB(self.vault_path)
            rows = db.get_unsupported_entries()
            for orig_path, category in rows:
                if orig_path:
                    stem = Path(orig_path).stem.replace(" ", "_")
                    ftype = Path(orig_path).suffix.lower()
                    entries.append((category, stem, ftype))
        return entries


def create_failed_record(vault_path: str, source_file: str, error_msg: str,
                         source_dir: Optional[str] = None) -> str:
    """为失败文件创建 MD 记录到 _failed 目录。

    Args:
        vault_path: Vault 根目录
        source_file: 源文件完整路径
        error_msg: 失败原因
        source_dir: 源目录（用于计算相对路径）

    Returns:
        创建的 MD 文件路径
    """
    fname = Path(source_file).name
    stem = Path(fname).stem
    safe_name = stem.replace(" ", "_")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_name = f"FAIL_{safe_name}_{ts}.md"

    failed_dir = os.path.join(vault_path, "_failed")
    os.makedirs(failed_dir, exist_ok=True)
    md_path = os.path.join(failed_dir, md_name)

    # 计算 vault 相对路径
    if source_dir:
        try:
            vault_rel = os.path.relpath(source_file, source_dir).replace(os.sep, "/")
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
