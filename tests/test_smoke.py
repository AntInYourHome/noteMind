#!/usr/bin/env python3
"""
NoteMind 冒烟测试 — P0 核心功能快速验证
用法：python tests/test_smoke.py
"""

import json
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
WARNED = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASSED, FAILED
    if condition:
        print(f"  ✅ {name}")
        PASSED += 1
    else:
        print(f"  ❌ {name}" + (f" — {detail}" if detail else ""))
        FAILED += 1


def setup_test_env():
    """创建测试环境。"""
    test_dir = tempfile.mkdtemp(prefix="notemind_test_")
    source = os.path.join(test_dir, "source")
    vault = os.path.join(test_dir, "vault")
    os.makedirs(source)
    return test_dir, source, vault


def cleanup(test_dir):
    shutil.rmtree(test_dir, ignore_errors=True)


def test_config_loads():
    """测试配置文件可正确加载。"""
    print("\n[T00] 配置文件加载")
    cfg_path = ROOT / "config.json"
    check("config.json 存在", cfg_path.exists())

    with open(cfg_path, "r") as f:
        cfg = json.load(f)
    check("JSON 格式正确", "ai" in cfg and "vault" in cfg and "import" in cfg)
    # 支持两种 config 格式：旧版 api_key 直接放在 ai 下，新版在 providers 数组中
    providers = cfg["ai"].get("providers", [])
    has_api_key = cfg["ai"].get("api_key", "").startswith("sk-")
    if providers:
        has_api_key = any(p.get("api_key", "").startswith("sk-") for p in providers)
    check("API key 已配置", has_api_key)
    check("分类列表非空", len(cfg["vault"]["categories"]) > 0)


def test_dedup_module():
    """测试 MD5 去重模块。"""
    print("\n[T04] MD5 去重模块")
    from scripts.dedup import compute_md5, load_dedup_index, save_dedup_index, check_duplicate

    test_dir, source, vault = setup_test_env()
    try:
        # 创建测试文件
        test_file = os.path.join(source, "test.txt")
        with open(test_file, "w") as f:
            f.write("hello world")

        md5 = compute_md5(test_file)
        check("MD5 计算正常", len(md5) == 32)

        # 空索引
        index = load_dedup_index(vault, ".test_index.json")
        check("空索引返回空 dict", index == {})

        # 保存索引
        index[md5] = {"filename": "test.txt", "category": "笔记", "note_path": "笔记/test.md"}
        save_dedup_index(vault, ".test_index.json", index)
        check("索引保存成功", os.path.exists(os.path.join(vault, ".test_index.json")))

        # 加载并验证
        loaded = load_dedup_index(vault, ".test_index.json")
        check("索引可回读", md5 in loaded)

        # 重复检测
        dup = check_duplicate(test_file, vault, ".test_index.json")
        check("重复文件被识别", dup is not None)
        check("重复信息正确", dup.get("category") == "笔记")

    finally:
        cleanup(test_dir)


def test_parsers_text():
    """测试纯文本和 Markdown 解析。"""
    print("\n[T02] 文本解析器")
    from scripts.parsers import parse_markdown, parse_text, get_parser

    test_dir, source, _ = setup_test_env()
    try:
        # 纯文本
        txt = os.path.join(source, "test.txt")
        with open(txt, "w") as f:
            f.write("这是一段测试文本\n包含多行内容")
        result = parse_text(txt)
        check("纯文本解析", "测试文本" in result.text)

        # Markdown
        md = os.path.join(source, "test.md")
        with open(md, "w") as f:
            f.write("# 标题\n\n这是一段**粗体**文本\n\n- 列表项1\n- 列表项2\n\n[链接](http://example.com)")
        result = parse_markdown(md)
        check("Markdown 解析", "粗体文本" in result.text and "列表项" in result.text)
        check("Markdown 链接被清洗", "http://" not in result.text)
        check("Markdown 粗体标记被去除", "**" not in result.text)

        # 格式识别
        check("图片格式识别", get_parser("test.jpg") == "image")
        check("PDF 格式可识别", get_parser("test.pdf") is not None)
        check("未知格式返回 None", get_parser("test.xyz") is None)

    finally:
        cleanup(test_dir)


def test_ai_client_import():
    """测试 AI 客户端调用（需要网络）。"""
    print("\n[T01/T02/T03] AI 客户端集成")

    test_dir, source, vault = setup_test_env()
    try:
        # 准备测试文件
        test_txt = os.path.join(source, "test_article.txt")
        with open(test_txt, "w") as f:
            f.write("""OpenHarmony 是一个面向全场景的开源分布式操作系统。
它支持多种设备类型，从 128KB 到 GB 级别的内存。
OpenHarmony 采用组件化设计，支持软总线、分布式数据管理、分布式任务调度等能力。
在安全方面，OpenHarmony 提供了从内核态到用户态的完整安全体系。""")

        # 运行导入
        import subprocess
        result = subprocess.run(
            ["python3", str(ROOT / "import.py"), "--source", source, "--vault", vault],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "QWEN_API_KEY": ""}  # 会从 config.json 读取
        )

        check("导入进程退出码为 0", result.returncode == 0, f"stderr: {result.stderr[:200]}")
        # 日志在 stderr
        output = result.stdout + result.stderr

        # 检查生成的文件
        moc_path = os.path.join(vault, "MOC.md")
        check("MOC.md 已生成", os.path.exists(moc_path))

        # 检查笔记文件
        notes_found = []
        for root_dir, dirs, files in os.walk(vault):
            for f in files:
                if f.endswith(".md") and f != "MOC.md":
                    notes_found.append(os.path.join(root_dir, f))

        check("至少生成 1 篇笔记", len(notes_found) > 0)

        if notes_found:
            with open(notes_found[0], "r") as f:
                content = f.read()
            check("笔记包含 AI 摘要", "## AI 摘要" in content)
            check("笔记包含标签", "## 标签" in content)
            check("笔记包含原始内容", "## 完整内容" in content)

        # 检查归档
        archive_files = os.listdir(os.path.join(vault, "_archive"))
        check("原始文件已归档", len(archive_files) > 0)

        # 检查去重索引
        index_path = os.path.join(vault, ".notemind_index.json")
        check("去重索引已创建", os.path.exists(index_path))

    finally:
        cleanup(test_dir)


def test_image_recognition():
    """测试图片 AI 识别。"""
    print("\n[T01] 图片 AI 识别")

    test_dir, source, vault = setup_test_env()
    try:
        # 使用项目自带的图片
        img = ROOT / "1.jpg"
        if img.exists():
            shutil.copy2(str(img), os.path.join(source, "test_code.jpg"))

            import subprocess
            result = subprocess.run(
                ["python3", str(ROOT / "import.py"), "--source", source, "--vault", vault],
                capture_output=True, text=True, timeout=120,
            )

            check("图片导入完成", result.returncode == 0)

            # 检查生成的笔记
            for root_dir, dirs, files in os.walk(vault):
                for f in files:
                    if f.endswith(".md") and f != "MOC.md":
                        with open(os.path.join(root_dir, f), "r") as nf:
                            content = nf.read()
                        check("图片概要已生成", "[IMAGE_FILE]" in content and "## AI 摘要" in content)
        else:
            print("  ⚠️  跳过（测试图片不存在）")

    finally:
        cleanup(test_dir)


def test_dedup_integration():
    """测试去重集成（二次导入跳过）。"""
    print("\n[T04] 去重集成测试")

    test_dir, source, vault = setup_test_env()
    try:
        test_txt = os.path.join(source, "test.txt")
        with open(test_txt, "w") as f:
            f.write("去重测试内容")

        import subprocess

        # 第一次导入
        r1 = subprocess.run(
            ["python3", str(ROOT / "import.py"), "--source", source, "--vault", vault],
            capture_output=True, text=True, timeout=120,
        )
        check("第一次导入成功", r1.returncode == 0)

        # 第二次导入（应该跳过）
        r2 = subprocess.run(
            ["python3", str(ROOT / "import.py"), "--source", source, "--vault", vault],
            capture_output=True, text=True, timeout=120,
        )
        # 日志输出在 stderr（Python logging 默认行为）
        output = r2.stdout + r2.stderr
        check("第二次导入无新文件", "SKIP" in output or "重复" in output or "无需处理" in output, f"output: {output[:300]}")

    finally:
        cleanup(test_dir)


if __name__ == "__main__":
    print("=" * 50)
    print("NoteMind 冒烟测试")
    print("=" * 50)

    try:
        test_config_loads()
        test_dedup_module()
        test_parsers_text()
        test_image_recognition()
        test_ai_client_import()
        test_dedup_integration()
    except Exception as e:
        print(f"\n⚠️  测试异常: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 50)
    print(f"测试完成: ✅ {PASSED} 通过 | ❌ {FAILED} 失败")
    print("=" * 50)

    if FAILED > 0:
        sys.exit(1)
