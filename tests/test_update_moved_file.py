#!/usr/bin/env python3
"""
NoteMind 测试：源文件移动后 --update 更新 MOC 分类

Bug: 当 moc 文档已创建后，将源文件移动到另一个目录，
运行 --update 无法更新 moc 中的目录分类。

用法：python tests/test_update_moved_file.py
"""

import os
import sys
import shutil
import tempfile
from pathlib import Path

# 项目根目录
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
    test_dir = tempfile.mkdtemp(prefix="notemind_update_test_")
    source = os.path.join(test_dir, "source")
    vault = os.path.join(test_dir, "vault")
    os.makedirs(source)
    return test_dir, source, vault


def cleanup(test_dir):
    shutil.rmtree(test_dir, ignore_errors=True)


def create_mock_md(vault_path: str, category: str, stem: str, original_path: str) -> str:
    """在 vault 中创建模拟 MD 文件。"""
    dir_path = os.path.join(vault_path, category) if category else vault_path
    os.makedirs(dir_path, exist_ok=True)
    md_path = os.path.join(dir_path, f"{stem}.md")
    content = f"""---
source: {stem}.txt
date: 2026-05-21
category: {category}
tags: [测试]
original_path: {original_path}
---
# {stem}

## AI 摘要
这是测试内容。

## 原始文件
- 原文：[[{stem}]]

"""
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)
    return md_path


def test_update_moves_file_to_new_category():
    """测试：源文件从 dirA 移动到 dirB 后，update_existing_docs 应更新分类和目录。"""
    print("\n[T01] 源文件移动后 --update 更新分类")

    from scripts.vault_ops import update_existing_docs

    test_dir, source, vault = setup_test_env()
    try:
        # Step 1: 在 source/dirA/ 下创建源文件（模拟导入时的状态）
        dir_a = os.path.join(source, "dirA")
        os.makedirs(dir_a)
        original_file = os.path.join(dir_a, "test_article.txt")
        with open(original_file, "w", encoding="utf-8") as f:
            f.write("这是测试文章内容。")

        # Step 2: 在 vault/dirA/ 创建对应的 MD 文件（模拟已导入状态）
        md_path = create_mock_md(vault, "dirA", "test_article", "source/dirA/test_article.txt")
        check("模拟 MD 文件已创建", os.path.exists(md_path))

        # 验证初始状态
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
        initial_category = ""
        for line in content.split("\n"):
            if line.startswith("category:"):
                initial_category = line[len("category:"):].strip()
        check(f"初始分类为 dirA（实际: {initial_category}）", initial_category == "dirA")

        # Step 3: 移动源文件到 source/dirB/（模拟用户在源端移动了文件）
        dir_b = os.path.join(source, "dirB")
        os.makedirs(dir_b)
        new_file_path = os.path.join(dir_b, "test_article.txt")
        shutil.move(original_file, new_file_path)
        check("源文件已移动到 dirB", os.path.exists(new_file_path))
        check("源文件不再在 dirA", not os.path.exists(original_file))

        # Step 4: 运行 update_existing_docs（即 --update 的核心逻辑）
        update_existing_docs(vault, source)

        # Step 5: 验证 MD 文件已移动到 vault/dirB/
        moved_md = os.path.join(vault, "dirB", "test_article.md")
        old_md = os.path.join(vault, "dirA", "test_article.md")
        check("MD 文件移动到 dirB 目录",
              os.path.exists(moved_md),
              f"期望: {moved_md}")
        check("旧 dirA 目录下的 MD 已不存在",
              not os.path.exists(old_md),
              f"旧文件仍存在: {old_md}")

        # Step 6: 验证 frontmatter 中的 category 已更新
        if os.path.exists(moved_md):
            with open(moved_md, "r", encoding="utf-8") as f:
                updated_content = f.read()
            updated_category = ""
            updated_original_path = ""
            for line in updated_content.split("\n"):
                if line.startswith("category:"):
                    updated_category = line[len("category:"):].strip()
                elif line.startswith("original_path:"):
                    updated_original_path = line[len("original_path:"):].strip()

            check(f"分类更新为 dirB（实际: {updated_category}）",
                  updated_category == "dirB",
                  f"category={updated_category}")

        # Step 7: 验证 MOC.md 中的分类已更新
        moc_path = os.path.join(vault, "MOC.md")
        if os.path.exists(moc_path):
            with open(moc_path, "r", encoding="utf-8") as f:
                moc_content = f.read()
            check("MOC.md 中包含 dirB 分类", "dirB" in moc_content)
            check("MOC.md 中不再包含 dirA 分类",
                  "dirA" not in moc_content,
                  "dirA 仍在 MOC 中")

    finally:
        cleanup(test_dir)


def test_update_nested_directory_move():
    """测试：源文件从嵌套目录 a/b/ 移动到 c/d/ 后，--update 正确更新。"""
    print("\n[T02] 嵌套目录移动后 --update 更新分类")

    from scripts.vault_ops import update_existing_docs

    test_dir, source, vault = setup_test_env()
    try:
        # Step 1: 在 source/a/b/ 下创建源文件
        deep_dir = os.path.join(source, "a", "b")
        os.makedirs(deep_dir)
        original_file = os.path.join(deep_dir, "deep_note.txt")
        with open(original_file, "w", encoding="utf-8") as f:
            f.write("深层目录测试内容。")

        # Step 2: 在 vault/a/b/ 创建对应 MD 文件
        vault_deep_dir = os.path.join(vault, "a", "b")
        os.makedirs(vault_deep_dir)
        md_path = os.path.join(vault_deep_dir, "deep_note.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("""---
source: deep_note.txt
date: 2026-05-21
category: a/b
tags: [测试]
original_path: source/a/b/deep_note.txt
---
# deep_note

## AI 摘要
测试内容。
""")
        check("嵌套 MD 文件已创建", os.path.exists(md_path))

        # Step 3: 移动源文件到 source/c/d/
        new_deep_dir = os.path.join(source, "c", "d")
        os.makedirs(new_deep_dir)
        new_file_path = os.path.join(new_deep_dir, "deep_note.txt")
        shutil.move(original_file, new_file_path)
        check("源文件已移动到 c/d", os.path.exists(new_file_path))

        # Step 4: 运行 update
        update_existing_docs(vault, source)

        # Step 5: 验证
        moved_md = os.path.join(vault, "c", "d", "deep_note.md")
        check("MD 文件移动到 c/d 目录",
              os.path.exists(moved_md),
              f"期望: {moved_md}")

        if os.path.exists(moved_md):
            with open(moved_md, "r", encoding="utf-8") as f:
                updated = f.read()
            cat = ""
            for line in updated.split("\n"):
                if line.startswith("category:"):
                    cat = line[len("category:"):].strip()
                elif line.startswith("original_path:"):
                    orig = line[len("original_path:"):].strip()

            check(f"分类更新为 c/d（实际: {cat}）", cat == "c/d")
            check(f"original_path 更新为 source/c/d/deep_note.txt",
                  orig == "source/c/d/deep_note.txt")

    finally:
        cleanup(test_dir)


def test_update_no_move_no_change():
    """测试：源文件未移动时，--update 不应做任何修改。"""
    print("\n[T03] 源文件未移动时不修改")

    from scripts.vault_ops import update_existing_docs

    test_dir, source, vault = setup_test_env()
    try:
        # 创建源文件和 MD 文件
        dir_a = os.path.join(source, "dirA")
        os.makedirs(dir_a)
        src_file = os.path.join(dir_a, "stable.txt")
        with open(src_file, "w", encoding="utf-8") as f:
            f.write("稳定内容。")

        md_path = create_mock_md(vault, "dirA", "stable", "source/dirA/stable.txt")
        with open(md_path, "r", encoding="utf-8") as f:
            before_content = f.read()

        # 运行 update（源文件未移动）
        update_existing_docs(vault, source)

        # MD 文件应在原位置，内容不变
        check("MD 文件仍在原位置", os.path.exists(md_path))
        with open(md_path, "r", encoding="utf-8") as f:
            after_content = f.read()
        check("内容未改变", before_content == after_content)

    finally:
        cleanup(test_dir)


def test_update_same_category_only_path_change():
    """测试：源文件在同目录内移动但文件名改变，分类不变，仅更新 original_path。"""
    print("\n[T04] 同目录内移动（分类不变，仅更新 original_path）")

    from scripts.vault_ops import update_existing_docs

    test_dir, source, vault = setup_test_env()
    try:
        # 创建源文件在 source/dirA/ 下
        dir_a = os.path.join(source, "dirA")
        os.makedirs(dir_a)
        src_file = os.path.join(dir_a, "my_note.txt")
        with open(src_file, "w", encoding="utf-8") as f:
            f.write("内容不变。")

        # MD 文件在 vault/dirA/，分类已是 dirA
        md_path = create_mock_md(vault, "dirA", "my_note", "source/dirA/my_note.txt")
        with open(md_path, "r", encoding="utf-8") as f:
            before = f.read()

        # 源文件在同一目录，但改为不同的文件名（相同 stem）
        new_src = os.path.join(dir_a, "my_note.md")
        shutil.move(src_file, new_src)
        check("源文件已重命名（同 stem）", os.path.exists(new_src))

        # 运行 update
        update_existing_docs(vault, source)

        # 分类和目录应不变，但 original_path 应更新
        with open(md_path, "r", encoding="utf-8") as f:
            after = f.read()

        has_new_path = "original_path: source/dirA/my_note.md" in after
        check("original_path 已更新", has_new_path)
        cat = ""
        for line in after.split("\n"):
            if line.startswith("category:"):
                cat = line[len("category:"):].strip()
        check("分类保持 dirA", cat == "dirA")

    finally:
        cleanup(test_dir)


if __name__ == "__main__":
    print("=" * 50)
    print("NoteMind --update 移动文件测试")
    print("=" * 50)

    try:
        test_update_moves_file_to_new_category()
        test_update_nested_directory_move()
        test_update_no_move_no_change()
        test_update_same_category_only_path_change()
    except Exception as e:
        print(f"\n⚠️  测试异常: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 50)
    print(f"测试完成: ✅ {PASSED} 通过 | ❌ {FAILED} 失败")
    print("=" * 50)

    if FAILED > 0:
        sys.exit(1)
