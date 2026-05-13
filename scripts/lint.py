"""
NoteMind — Wiki 健康检查 (Lint)

扫描 vault 目录，检测知识结构问题：
1. 孤立页（无入链的 MD 文件）
2. 断链（[[wikilink]] 指向不存在的文件）
3. 无外链页（没有指向其他页面的 wikilink）

输出结构化报告，供用户或自动化流程使用。
"""

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("notemind")

WIKILINK_RE = re.compile(r'\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]')

# 排除的目录和文件
EXCLUDE_DIRS = {"_failed", "_archive", ".git", ".obsidian", ".notemind", ".claude"}
EXCLUDE_FILES = {"MOC_*.md", "index.md", "log.md", "overview.md", ".DS_Store"}


@dataclass
class LintResult:
    type: str           # "orphan" | "broken-link" | "no-outlinks"
    severity: str       # "warning" | "info"
    file_path: str
    detail: str
    related_files: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        sev_icon = {"warning": "⚠️", "info": "ℹ️"}.get(self.severity, "•")
        return f"  {sev_icon} [{self.type.upper()}] {self.file_path}: {self.detail}"


def run_lint(vault_path: str) -> list[LintResult]:
    """
    执行 Wiki 健康检查。

    Args:
        vault_path: Vault 根目录

    Returns:
        LintResult 列表
    """
    results = []

    # 步骤 1: 收集所有 MD 文件和 wikilink 信息
    md_files = {}       # stem -> full_path
    outlinks = {}       # stem -> [target_stem, ...]
    inlink_count = {}   # stem -> count of pages linking to it

    for root, dirs, files in os.walk(vault_path):
        # 排除目录
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]

        for fname in files:
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(root, fname)
            stem = Path(fname).stem
            md_files[stem] = fpath
            inlink_count[stem] = 0

            # 提取 wikilink
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read(10000)  # 只读前 10K 足够检测
                links = WIKILINK_RE.findall(content)
                outlinks[stem] = [normalize_stem(l) for l in links]
            except Exception:
                outlinks[stem] = []

    # 统计入链
    for stem, targets in outlinks.items():
        for target in targets:
            if target in inlink_count:
                inlink_count[target] = inlink_count.get(target, 0) + 1

    # 步骤 2: 检测孤立页（入链 <= 1）
    for stem, fpath in sorted(md_files.items()):
        if stem.startswith("MOC_"):
            continue  # MOC 文件本身是索引，不需要入链
        count = inlink_count.get(stem, 0)
        if count <= 1:
            results.append(LintResult(
                type="orphan",
                severity="warning",
                file_path=fpath,
                detail=f"仅有 {count} 个入链（或无入链）",
            ))

    # 步骤 3: 检测断链
    for stem, targets in sorted(outlinks.items()):
        broken = []
        for target in targets:
            if target and target not in md_files:
                broken.append(target)
        if broken:
            fpath = md_files[stem]
            results.append(LintResult(
                type="broken-link",
                severity="warning",
                file_path=fpath,
                detail=f"{len(broken)} 个断链: {', '.join(sorted(set(broken))[:5])}",
                related_files=[md_files.get(t, f"未知: {t}") for t in sorted(set(broken))[:5]],
            ))

    # 步骤 4: 检测无外链页
    for stem, fpath in sorted(md_files.items()):
        if stem.startswith("MOC_"):
            continue
        targets = [t for t in outlinks.get(stem, []) if t]  # 过滤空链接
        if not targets:
            results.append(LintResult(
                type="no-outlinks",
                severity="info",
                file_path=fpath,
                detail="没有指向其他页面的 wikilink",
            ))

    return results


def normalize_stem(link_text: str) -> str:
    """
    规范化 wikilink 文本为文件 stem。

    例如: "2024-05-01-my-doc" → "2024-05-01-my-doc"
         "my doc" → "my_doc" (如果文件名用下划线)
    """
    s = link_text.strip()
    # 尝试匹配常见的日期前缀格式: "2024-05-01-xxx" → "xxx"
    # 但保留日期前缀，因为文件名通常也包含日期
    s = s.replace(" ", "_")
    return s


def print_lint_report(results: list[LintResult]) -> None:
    """打印 Lint 报告。"""
    if not results:
        logger.info("  Lint: 未发现问题")
        return

    by_type = {}
    for r in results:
        by_type.setdefault(r.type, []).append(r)

    logger.info(f"  Lint: 发现 {len(results)} 个问题")
    for ltype, items in sorted(by_type.items()):
        severity = items[0].severity
        logger.info(f"    {severity.upper()} {ltype}: {len(items)} 个")
        for item in items[:10]:  # 每类最多显示 10 个
            logger.info(f"      {item}")
        if len(items) > 10:
            logger.info(f"      ... 还有 {len(items) - 10} 个")


def run_lint_cli(vault_path: str) -> int:
    """CLI 入口。返回问题数量。"""
    results = run_lint(vault_path)
    print_lint_report(results)
    return len(results)
