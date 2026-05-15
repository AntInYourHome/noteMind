"""Collect files from source directory."""

from pathlib import Path
from typing import List, Tuple

from scripts.parsers import IMAGE_EXTS, PARSERS


def collect_files(source: str) -> List[str]:
    """递归收集源目录下所有可处理的文件。"""
    all_exts = set(PARSERS.keys()) | IMAGE_EXTS

    files = []
    source_path = Path(source)
    for f in sorted(source_path.rglob("*")):
        if f.is_file() and f.suffix.lower() in all_exts:
            files.append(str(f))
    return files


def collect_all_files(source: str) -> Tuple[List[str], List[str]]:
    """递归收集所有文件，区分可解析和不可解析。

    Returns:
        (parseable_files, unsupported_files)
    """
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
