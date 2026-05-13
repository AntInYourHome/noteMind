#!/usr/bin/env python3
"""
NoteMind Release Packager

创建 release zip 包，自动排除：
- config.json（含 API key）
- 测试数据文件（inbox/, test_source/）
- VLM 模型权重和图片资源
- 开发目录（.git, venv, __pycache__, logs 等）
"""

import os
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # scripts/release_packager.py -> project root
VERSION = "2.0.0"
OUTPUT = ROOT / "release" / f"noteMind-v{VERSION}.zip"

# 排除的顶层目录
EXCLUDE_DIRS = {
    ".git", "venv", "__pycache__", ".pytest_cache", "logs",
    "knowledge-base", "release", ".claude", "llm_wiki",
    "llm_wiki_analysis",  # 分析文档，不需要
    "inbox", "test_source",
    # v1.10 后已删除的目录
    "tools",
}

# 排除的文件名
EXCLUDE_FILES = {
    "config.json",              # 只保留 .example
    ".notemind_index.json",
    ".notemind_status.db",
    ".notemind_gui_config.json",
    "minimind-v-models.tar.gz",
    "使用教程.md",
    "TEST_PLAN.md",
}

# minimind-v 下排除的子目录
MINIMIND_V_EXCLUDE = {"images", "out", "modelscope_cache", "modelscope_cache_weights",
                      "dataset", "trainer"}


def should_exclude(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    parts = rel.parts

    # 排除顶层目录
    if len(parts) >= 1 and parts[0] in EXCLUDE_DIRS:
        return True

    # 排除隐藏目录
    if any(p.startswith(".") for p in parts):
        return True

    # 排除根目录的 config.json（含 API key）
    if len(parts) == 1 and rel.name == "config.json":
        return True

    # 排除编译文件
    if rel.suffix in {".pyc", ".pyo"}:
        return True

    # 排除 notemind 打包产物
    if "notemind.egg-info" in parts:
        return True

    # 排除 scripts/release/ 目录
    if parts[0] == "scripts" and len(parts) > 1 and parts[1] == "release":
        return True

    # minimind-v 排除子目录
    if parts[0] == "minimind-v" and len(parts) > 1 and parts[1] in MINIMIND_V_EXCLUDE:
        return True

    # minimind-v 下 siglip2 目录：只保留配置文件，排除大文件
    if parts[0] == "minimind-v" and "siglip2" in str(rel):
        if rel.suffix in {".safetensors", ".bin"}:
            return True
        # 允许 config.json（from_pretrained 必需）
        if rel.name in {"config.json", "configuration.json", "preprocessor_config.json",
                        "README.md"}:
            return False

    return False


def main():
    os.makedirs(OUTPUT.parent, exist_ok=True)

    count = 0
    total_size = 0

    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(ROOT):
            # 过滤目录（in-place 修改阻止递归进入）
            dirs[:] = sorted([d for d in dirs if not should_exclude(Path(root) / d)])

            for f in sorted(files):
                fp = Path(root) / f
                if should_exclude(fp):
                    continue

                arcname = fp.relative_to(ROOT)
                zf.write(fp, arcname)
                count += 1
                total_size += fp.stat().st_size

    size_kb = OUTPUT.stat().st_size / 1024
    print(f"Release v{VERSION} 打包完成: {OUTPUT}")
    print(f"  文件数: {count}")
    print(f"  压缩包大小: {size_kb:.0f} KB")
    print(f"  原始大小: {total_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
