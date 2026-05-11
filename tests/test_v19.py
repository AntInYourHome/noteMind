#!/usr/bin/env python3
"""
NoteMind v1.9.0 专项测试 — wikilink 路径 + 双路径归档
用法：python tests/test_v19.py
"""

import os
import sys
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

PASSED = 0
FAILED = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASSED, FAILED
    if condition:
        print(f"  ✅ {name}")
        PASSED += 1
    else:
        print(f"  ❌ {name}" + (f" — {detail}" if detail else ""))
        FAILED += 1


def setup_test_env():
    test_dir = tempfile.mkdtemp(prefix="notemind_v19_")
    source = os.path.join(test_dir, "source")
    vault = os.path.join(test_dir, "vault")
    os.makedirs(source)
    return test_dir, source, vault


def cleanup(test_dir):
    shutil.rmtree(test_dir, ignore_errors=True)


def test_builder_archive_link_with_path():
    """测试 MarkdownBuilder.add_archive_link 带分类路径。"""
    print("\n[V19-01] builder.py — 归档链接带路径")
    from scripts.builder import MarkdownBuilder

    builder = MarkdownBuilder("test.pdf", "2026-05-11")
    builder.add_frontmatter("安全/操作系统安全/HarmonyOS", ["白皮书"])
    builder.add_archive_link("HarmonyOS白皮书.pdf", "安全/操作系统安全/HarmonyOS")

    output = builder.build()
    check("归档链接指向 _archive 且包含分类路径",
          "[[_archive/安全/操作系统安全/HarmonyOS/HarmonyOS白皮书.pdf|HarmonyOS白皮书.pdf]]" in output,
          f"实际输出片段: {[l for l in output.split(chr(10)) if '归档' in l]}")


def test_builder_index_links_with_path():
    """测试 build_index 目录链接带完整路径。"""
    print("\n[V19-02] builder.py — build_index 链接带路径")
    from scripts.builder import MarkdownBuilder

    builder = MarkdownBuilder("test.pdf", "2026-05-11")
    builder.add_frontmatter("安全/操作系统安全/HarmonyOS", ["白皮书"])

    section_links = [
        ("安全/操作系统安全/HarmonyOS/test_章节1", "第一章 概述"),
        ("test_章节2", "第二章 详情"),
    ]
    output = builder.build_index(section_links)

    check("章节链接包含完整路径",
          "[[安全/操作系统安全/HarmonyOS/test_章节1|test_章节1]] 第一章 概述" in output)
    check("无路径的章节保持原名",
          "[[test_章节2|test_章节2]] 第二章 详情" in output)


def test_builder_section_note_backlink():
    """测试 build_section_note 返回链接带完整路径。"""
    print("\n[V19-03] builder.py — 返回链接带路径")
    from scripts.builder import MarkdownBuilder

    builder = MarkdownBuilder("test.pdf", "2026-05-11")
    output = builder.build_section_note(
        {"title": "第一章", "summary": "概述"},
        parent_name="安全/操作系统安全/HarmonyOS/test_index",
        tags=["白皮书"],
    )

    check("返回链接包含完整路径",
          "[[安全/操作系统安全/HarmonyOS/test_index|test_index]]" in output,
          f"实际输出: {[l for l in output.split(chr(10)) if '返回' in l]}")


def test_dual_archive_paths():
    """测试原始文件只归档到 _archive/{category}/，不在分类目录。"""
    print("\n[V19-04] import.py — 文件只归档到 _archive/{category}/")
    test_dir, source, vault = setup_test_env()
    try:
        import importlib
        import_module = importlib.import_module('import')

        # 创建测试文件
        test_file = os.path.join(source, "test_doc.txt")
        with open(test_file, "w") as f:
            f.write("归档到 _archive 测试内容" * 100)

        category = "安全/操作系统安全/HarmonyOS"

        # 调用 archive_source
        import_module.archive_source(test_file, vault, category, "_archive", remove_source=True)

        # 检查分类目录不应有原始文件
        category_path = os.path.join(vault, category, "test_doc.txt")
        check("分类目录不存在原始文件", not os.path.exists(category_path))

        # 检查 _archive 目录
        archive_path = os.path.join(vault, "_archive", category, "test_doc.txt")
        check("_archive 存在文件", os.path.exists(archive_path))

        # 源文件已删除
        check("源文件已删除", not os.path.exists(test_file))

    finally:
        cleanup(test_dir)


def test_wikilink_format_in_moc():
    """测试 MOC 中 wikilink 使用 [[路径|显示名]] 格式。"""
    print("\n[V19-05] import.py — MOC wikilink 格式")
    import subprocess

    test_dir, source, vault = setup_test_env()
    try:
        # 创建测试文件
        test_file = os.path.join(source, "test_article.txt")
        with open(test_file, "w") as f:
            f.write("OpenHarmony 安全架构测试" * 50)

        result = subprocess.run(
            ["python3", str(ROOT / "import.py"), "--source", source, "--vault", vault],
            capture_output=True, text=True, timeout=120,
        )

        moc_path = os.path.join(vault, "MOC.md")
        check("MOC.md 已生成", os.path.exists(moc_path),
              f"stderr: {result.stderr[:200]}")

        if os.path.exists(moc_path):
            with open(moc_path, "r") as f:
                moc_content = f.read()

            # 检查 wikilink 格式：[[路径|显示名]]
            import re
            wikilinks = re.findall(r'\[\[(.+?)\]\]', moc_content)
            if wikilinks:
                has_pipe = any("|" in wl for wl in wikilinks)
                check(f"MOC wikilink 使用管道符格式 ({len(wikilinks)} 个链接中有管道的 {sum(1 for w in wikilinks if '|' in w)} 个)",
                      has_pipe,
                      f"样例: {wikilinks[0][:80]}")
                # 检查是否包含路径（不仅仅是文件名）
                has_path = any("/" in wl.split("|")[0] for wl in wikilinks if "|" in wl)
                check("MOC wikilink 包含分类路径", has_path,
                      f"样例: {wikilinks[0][:80]}")

    finally:
        cleanup(test_dir)


def test_reasoning_content_filtering():
    """测试 reasoning 模型思考过程过滤。"""
    print("\n[V19-06] ai_client.py — reasoning 思考过程过滤")
    from scripts.ai_client import _extract_reasoning

    # qwen3-reasoning 格式
    qwen_raw = "<|begin_of_thought|>一些思考过程...<|end_of_thought|>最终结论是ABC"
    check("过滤 qwen3-reasoning 标记",
          _extract_reasoning(qwen_raw) == "最终结论是ABC",
          f"实际: {_extract_reasoning(qwen_raw)}")

    # DeepSeek R1 格式
    deepseek_raw = "<think>思考...</think>最终结论是XYZ"
    check("过滤 DeepSeek R1 标记",
          _extract_reasoning(deepseek_raw) == "最终结论是XYZ",
          f"实际: {_extract_reasoning(deepseek_raw)}")

    # 普通文本（无标记）
    normal = "这是一段普通回复"
    check("普通文本不变",
          _extract_reasoning(normal) == normal)

    # 空字符串
    check("空字符串不变",
          _extract_reasoning("") == "")


if __name__ == "__main__":
    print("=" * 50)
    print("NoteMind v1.9.0 专项测试")
    print("=" * 50)

    try:
        test_builder_archive_link_with_path()
        test_builder_index_links_with_path()
        test_builder_section_note_backlink()
        test_dual_archive_paths()
        test_wikilink_format_in_moc()
        test_reasoning_content_filtering()
    except Exception as e:
        print(f"\n⚠️  测试异常: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 50)
    print(f"测试完成: ✅ {PASSED} 通过 | ❌ {FAILED} 失败")
    print("=" * 50)

    if FAILED > 0:
        sys.exit(1)
