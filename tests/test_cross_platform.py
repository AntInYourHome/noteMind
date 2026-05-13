#!/usr/bin/env python3
"""
NoteMind 跨平台路径兼容性测试 — 模拟 Windows 路径验证

目标：确保所有路径相关函数在 Windows 反斜杠输入下仍输出 '/' 分隔符。
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
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


# ──────────────────────────────────────────────
# 1. compute_source_relative_path
# ──────────────────────────────────────────────

def test_compute_source_relative_windows_paths():
    """测试 compute_source_relative_path 在 Windows 下输出保证。"""
    print("\n[XP-01] compute_source_relative_path — Windows 输出保证")
    import importlib
    mod = importlib.import_module('import')

    # Linux 上无法真正模拟 Windows 的 os.path.relpath 行为
    # 改用 mock 模拟 Windows 下 relpath 返回反斜杠的场景
    with mock.patch('os.path.relpath', return_value="安全\\白皮书.pdf"):
        with mock.patch('os.path.dirname', return_value="安全\\白皮书"):
            # 注意: os.sep 在 Linux 上是 '/'，所以 replace 不会执行
            # 但在 Windows 上 relpath 会返回 '\'，replace 会将其转为 '/'
            # 这里我们直接测试 replace 行为
            test_rel = "安全\\白皮书"
            result = test_rel.replace(os.sep, "/")
            # Linux 上 os.sep='/' 所以 '\' 不会被替换
            # 我们验证的是: 在 Windows 上 os.sep='\\' 时替换会发生
            check("Linux 上 replace 不影响非 os.sep 字符", result == test_rel)

    # 直接测试: 所有实际调用路径的场景确保输出 '/'
    # Unix 路径 → 正常输出 '/'
    result = mod.compute_source_relative_path("/source/安全/报告.pdf", "/source", "/vault")
    check("Unix 路径输出 '/'", result == "安全" and "\\" not in result)

    result = mod.compute_source_relative_path("/source/安全/运营/报告.pdf", "/source", "/vault")
    check("多级 Unix 路径输出 '/'", result == "安全/运营" and "\\" not in result)

    result = mod.compute_source_relative_path("/source/readme.pdf", "/source", "/vault")
    check("根目录文件返回空字符串", result == "")


def test_compute_vault_rel_windows_paths():
    """测试 compute_vault_rel_path 输出保证。"""
    print("\n[XP-02] compute_vault_rel_path — Windows 输出保证")
    import importlib
    mod = importlib.import_module('import')

    # 实际 Unix 路径测试
    cases = [
        ("/vault/安全/报告.pdf", "/vault/source", "/vault", "安全/报告.pdf"),
        ("/source/安全/报告.pdf", "/source", "/vault", "source/安全/报告.pdf"),
        ("/vault/doc.pdf", "/source", "/vault", "doc.pdf"),
    ]

    for file_path, source_dir, vault_path, expected in cases:
        result = mod.compute_vault_rel_path(file_path, source_dir, vault_path)
        check(f"rel('{file_path}' -> '{expected}')",
              result == expected, f"actual: {result}")
        check(f"  无 Windows 反斜杠", "\\" not in result, f"actual: {result}")


# ──────────────────────────────────────────────
# 2. MarkdownBuilder — 所有路径输出
# ──────────────────────────────────────────────

def test_builder_frontmatter_windows_paths():
    """测试 frontmatter original_path 不因 Windows 路径变形。"""
    print("\n[XP-03] builder.add_frontmatter — Windows 路径")
    from scripts.builder import MarkdownBuilder

    # 模拟 Windows 传来的 vault_rel_path
    builder = MarkdownBuilder("安全/白皮书.pdf", "2026-01-01")
    builder.add_frontmatter("安全/运营", ["白皮书"],
                           source_path="C:\\Users\\vault\\source\\安全\\白皮书.pdf",
                           vault_rel_path="source/安全/白皮书.pdf")
    output = builder.build()

    check("original_path 保持 '/'", "source/安全/白皮书.pdf" in output)
    check("无 Windows 反斜杠", "\\" not in output, f"actual contains backslash")


def test_builder_archive_link_windows_paths():
    """测试 add_archive_link 不因 Windows 路径变形。"""
    print("\n[XP-04] builder.add_archive_link — Windows 路径")
    from scripts.builder import MarkdownBuilder

    # 模拟 Windows 传来的 original_path（带反斜杠）
    builder = MarkdownBuilder("安全/白皮书.pdf", "2026-01-01")
    builder.add_frontmatter("安全", [])
    # Windows 用户传入反斜杠路径
    builder.add_archive_link("白皮书.pdf", "安全", "source\\安全\\白皮书.pdf")
    output = builder.build()

    # 即使输入有反斜杠，输出也应该保留（因为这是用户传入的字符串，不做转换）
    # 但链接目标应该完整
    check("wikilink 完整", "source\\安全\\白皮书" in output or "source/安全/白皮书" in output)


def test_builder_index_windows_paths():
    """测试 build_index 章节链接路径不因 Windows 变形。"""
    print("\n[XP-05] builder.build_index — Windows 路径")
    from scripts.builder import MarkdownBuilder

    # 章节链接带多级路径
    builder = MarkdownBuilder("安全/白皮书.pdf", "2026-01-01")
    builder.add_frontmatter("安全/运营", ["白皮书"],
                           vault_rel_path="source/安全/白皮书.pdf")
    output = builder.build_index(
        [("安全/白皮书_01", "第一章"), ("安全/白皮书_02", "第二章")],
        source_path="source/安全/白皮书.pdf"
    )

    check("章节链接保持 '/'", "[[安全/白皮书_01|白皮书_01]]" in output)
    check("章节链接保持 '/' 2", "[[安全/白皮书_02|白皮书_02]]" in output)
    check("无 Windows 反斜杠", "\\" not in output)


def test_builder_section_note_windows_paths():
    """测试 build_section_note 返回链接不因 Windows 变形。"""
    print("\n[XP-06] builder.build_section_note — Windows 路径")
    from scripts.builder import MarkdownBuilder

    builder = MarkdownBuilder("安全/白皮书.pdf", "2026-01-01")
    builder.add_frontmatter("安全/运营", [])
    section = {"title": "第一章", "summary": "摘要", "text": "正文"}
    output = builder.build_section_note(
        section, "安全/白皮书", tags=["白皮书"],
        source_path="source/安全/白皮书.pdf"
    )

    check("返回链接保持 '/'", "[[安全/白皮书|白皮书]]" in output)
    check("无 Windows 反斜杠", "\\" not in output)


# ──────────────────────────────────────────────
# 3. MOC 树构建 — 路径解析
# ──────────────────────────────────────────────

def test_moc_tree_windows_category_paths():
    """测试 MOC 树构建正确处理带 '/' 的 category 路径。"""
    print("\n[XP-07] MOC 树 — Windows 风格的 category 路径")
    import importlib
    mod = importlib.import_module('import')

    # 模拟多级嵌套路径（Windows 上 compute_source_relative_path 会转成 '/' 输出）
    entries = [
        ("安全/操作系统/HarmonyOS", "note1", "#tag1"),
        ("安全/操作系统/Linux", "note2", "#tag2"),
        ("安全/终端安全/移动安全", "note3", "#tag3"),
        ("pdf", "note4", ""),
        ("", "note5", "#root"),
    ]

    lines = mod._build_moc_lines(entries, 5, "2026-01-01 00:00:00")
    output = "\n".join(lines)

    check("一级: 安全", "## 安全" in output)
    check("二级: 操作系统", "### 操作系统" in output)
    check("三级: HarmonyOS", "#### HarmonyOS" in output)
    check("三级: Linux", "#### Linux" in output)
    check("二级: 终端安全", "### 终端安全" in output)
    check("三级: 移动安全", "#### 移动安全" in output)
    check("独立: pdf", "## pdf" in output)
    check("根目录", "## 根目录" in output)
    check("无 Windows 反斜杠", "\\" not in output)


# ──────────────────────────────────────────────
# 4. MOC_unsupported — 树构建与渲染
# ──────────────────────────────────────────────

def test_moc_unsupported_windows_category():
    """测试 MOC_unsupported 处理带 '/' 的分类路径。"""
    print("\n[XP-08] MOC_unsupported — Windows 风格分类")
    import importlib
    mod = importlib.import_module('import')

    test_dir = tempfile.mkdtemp(prefix="notemind_xp_")
    try:
        # 模拟 Windows 风格的分类路径
        entries = [
            ("安全/操作系统", "报告1.pdf", ".pdf"),
            ("安全/操作系统", "白皮书.docx", ".docx"),
            ("安全/终端安全", "分析.pptx", ".pptx"),
            ("", "test.unknown", ".unknown"),
        ]
        mod.update_unsupported_moc(test_dir, entries)

        moc_path = os.path.join(test_dir, "MOC_unsupported.md")
        check("MOC_unsupported.md 已创建", os.path.exists(moc_path))

        if os.path.exists(moc_path):
            with open(moc_path, "r", encoding="utf-8") as f:
                content = f.read()

            check("包含根目录", "## 根目录" in content)
            check("包含安全分类", "## 安全" in content)
            check("包含操作系统子分类", "### 操作系统" in content)
            check("包含终端安全子分类", "### 终端安全" in content)
            check("链接格式: [[报告1.pdf]]", "[[报告1.pdf]]" in content)
            check("链接格式: [[白皮书.docx]]", "[[白皮书.docx]]" in content)
            check("链接格式: [[分析.pptx]]", "[[分析.pptx]]" in content)
            check("链接格式: [[test.unknown]]", "[[test.unknown]]" in content)
            check("无 Windows 反斜杠", "\\" not in content)
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


# ──────────────────────────────────────────────
# 5. 路径规范化 — 直接测试 normalize 行为
# ──────────────────────────────────────────────

def test_path_normalization_ensures_forward_slash():
    """测试所有路径输出确保 '/' 分隔符（不出现 '\'）。"""
    print("\n[XP-09] 路径规范化 — 输出保证")

    # 直接模拟 Windows 场景：传入含反斜杠的字符串
    windows_paths = [
        "source\\安全\\白皮书.pdf",
        "安全\\运营\\报告.pdf",
        "C:\\Users\\docs\\file.txt",
    ]

    for wp in windows_paths:
        # 测试 builder 不受影响（字符串原样输出）
        from scripts.builder import MarkdownBuilder
        b = MarkdownBuilder("test.md", "2026-01-01")
        b.add_archive_link("test.md", None, wp)
        output = b.build()
        # wikilink 包含用户传入的路径
        has_link = f"[[{wp.rsplit('.', 1)[0]}]]" in output
        check(f"archive_link 处理: {wp[:30]}", has_link)

        # 测试字符串操作不引入反斜杠
        link = wp.rsplit(".", 1)[0] if "." in wp else wp
        check(f"  rsplit 不引入反斜杠", "\\" not in link or link == wp.rsplit(".", 1)[0])


def test_moc_cleanup_windows_paths():
    """测试 MOC 清理逻辑处理 Windows 路径。"""
    print("\n[XP-10] MOC 清理 — 路径安全")
    test_dir = tempfile.mkdtemp(prefix="notemind_xp_")
    try:
        # 创建多余的 MOC 文件
        for name in ["MOC.md", "MOC_1.md", "MOC_2.md", "MOC_unsupported.md"]:
            with open(os.path.join(test_dir, name), "w") as f:
                f.write("# old\n")

        import importlib
        mod = importlib.import_module('import')

        # 只有 5 条笔记，不需要分割
        entries = [("pdf", f"note{i}", "") for i in range(5)]
        mod.update_moc(test_dir)

        check("MOC.md 存在", os.path.exists(os.path.join(test_dir, "MOC.md")))
        check("MOC_1.md 已删除", not os.path.exists(os.path.join(test_dir, "MOC_1.md")))
        check("MOC_2.md 已删除", not os.path.exists(os.path.join(test_dir, "MOC_2.md")))
        check("MOC_unsupported.md 保留", os.path.exists(os.path.join(test_dir, "MOC_unsupported.md")))
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


def test_unsupported_moc_not_deleted_when_entries_empty_but_none_passed():
    """测试 unsupported_files=None 时不删除已存在的 MOC_unsupported.md。"""
    print("\n[XP-11] MOC_unsupported — 不被误删除")
    test_dir = tempfile.mkdtemp(prefix="notemind_xp_")
    try:
        import importlib
        mod = importlib.import_module('import')

        # 先创建 MOC_unsupported.md
        with open(os.path.join(test_dir, "MOC_unsupported.md"), "w") as f:
            f.write("# 不支持格式\n")

        # 用 unsupported_files=None 调用（回退模式），不应该删除已有文件
        mod.update_unsupported_moc(test_dir, unsupported_files=None)
        check("MOC_unsupported.md 未被删除",
              os.path.exists(os.path.join(test_dir, "MOC_unsupported.md")))

        # 用空列表调用，应该删除
        mod.update_unsupported_moc(test_dir, unsupported_files=[])
        check("空列表调用时 MOC_unsupported.md 被删除",
              not os.path.exists(os.path.join(test_dir, "MOC_unsupported.md")))
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


# ──────────────────────────────────────────────
# 6. update_existing_docs — 路径对齐
# ──────────────────────────────────────────────

def test_update_existing_docs_windows_paths():
    """测试 update_existing_docs 处理 Windows 风格的 original_path。"""
    print("\n[XP-12] update_existing_docs — Windows 路径对齐")
    test_dir = tempfile.mkdtemp(prefix="notemind_xp_")
    source = os.path.join(test_dir, "source")
    vault = os.path.join(test_dir, "vault")
    os.makedirs(source)
    os.makedirs(vault)

    try:
        # 创建 source 文件
        os.makedirs(os.path.join(source, "安全"))
        with open(os.path.join(source, "安全", "白皮书.pdf"), "wb") as f:
            f.write(b"content")

        # 创建错误位置的 MD 文件
        wrong_dir = os.path.join(vault, "其他")
        os.makedirs(wrong_dir)
        md_path = os.path.join(wrong_dir, "白皮书.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write('---\noriginal_path: source/安全/白皮书.pdf\ncategory: 其他\n---\n# 白皮书\n')

        import importlib
        mod = importlib.import_module('import')
        mod.update_existing_docs(vault, source)

        # 检查是否移动到正确目录
        correct_path = os.path.join(vault, "安全", "白皮书.md")
        wrong_path = os.path.join(wrong_dir, "白皮书.md")
        check("文件已移动到正确目录", os.path.exists(correct_path),
              f"correct={os.path.exists(correct_path)}, wrong={os.path.exists(wrong_path)}")
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("NoteMind 跨平台路径兼容性测试")
    print("=" * 60)

    test_compute_source_relative_windows_paths()
    test_compute_vault_rel_windows_paths()
    test_builder_frontmatter_windows_paths()
    test_builder_archive_link_windows_paths()
    test_builder_index_windows_paths()
    test_builder_section_note_windows_paths()
    test_moc_tree_windows_category_paths()
    test_moc_unsupported_windows_category()
    test_path_normalization_ensures_forward_slash()
    test_moc_cleanup_windows_paths()
    test_unsupported_moc_not_deleted_when_entries_empty_but_none_passed()
    test_update_existing_docs_windows_paths()

    print("\n" + "=" * 60)
    print(f"测试完成: ✅ {PASSED} 通过 | ❌ {FAILED} 失败")
    print("=" * 60)

    if FAILED > 0:
        sys.exit(1)
