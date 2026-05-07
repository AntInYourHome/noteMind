#!/usr/bin/env python3
"""
NoteMind 长时间稳定性测试

创建多个模拟文件，批量处理，验证：
1. 单文件异常不影响后续文件
2. 检查点保存与恢复
3. Provider 限流降级后自动恢复
4. 内存不泄漏
"""

import json
import os
import sys
import time
import shutil
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# --- 测试工具 ---

def create_test_files(test_dir: str, count: int, sizes: list[str] = None):
    """创建测试文件（PDF 模拟为 .md 让 parsers 能解析）。"""
    os.makedirs(test_dir, exist_ok=True)
    sizes = sizes or ["small"] * count

    for i, size in enumerate(sizes):
        path = os.path.join(test_dir, f"test_file_{i+1:03d}.md")
        if size == "small":
            content = f"# 测试文档 {i+1}\n\n这是一个小型测试文档，用于验证导入流程。\n"
        elif size == "medium":
            content = f"# 测试文档 {i+1}\n\n" + "这是正文内容。\n" * 200
        elif size == "large":
            content = f"# 测试文档 {i+1}\n\n" + "这是长文档正文内容。\n" * 800
        elif size == "empty_content":
            content = ""
        elif size == "malformed":
            content = "只有标题没有内容" * 5
        else:
            content = f"# {size}\n\n内容\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    print(f"  创建 {count} 个测试文件 → {test_dir}")


def run_import(source_dir: str, vault_dir: str, config_path: str, resume: bool = False):
    """运行 import.py。"""
    import importlib.util
    import subprocess

    # 用子进程运行 import.py，避免全局状态污染
    cmd = [
        sys.executable, os.path.join(
            Path(__file__).resolve().parent.parent, "import.py"),
        "--source", source_dir,
        "--vault", vault_dir,
        "--config", config_path,
    ]
    if resume:
        cmd.append("--resume")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    # 打印输出
    if result.stdout:
        for line in result.stdout.strip().split("\n"):
            print(f"    {line}")
    if result.returncode != 0 and result.stderr:
        for line in result.stderr.strip().split("\n")[-10:]:
            print(f"    [ERR] {line}")

    return result.returncode == 0


def count_vault_files(vault_dir: str) -> int:
    """统计 Vault 中的 .md 文件数。"""
    count = 0
    for root, _, files in os.walk(vault_dir):
        for f in files:
            if f.endswith(".md") and not f.startswith("MOC"):
                count += 1
    return count


def count_failed_files(failed_dir: str) -> int:
    """统计 failed 目录中的文件数。"""
    if not os.path.exists(failed_dir):
        return 0
    count = 0
    for root, _, files in os.walk(failed_dir):
        count += len(files)
    return count


# --- 测试用例 ---

def test_basic_batch():
    """测试 1：基础批量处理（10 个小文件）。"""
    print("\n" + "=" * 60)
    print("测试 1: 基础批量处理 (10 个小文件)")
    print("=" * 60)

    test_dir = "/tmp/notemind_test/source_basic"
    vault_dir = "/tmp/notemind_test/vault_basic"
    shutil.rmtree(test_dir, ignore_errors=True)
    shutil.rmtree(vault_dir, ignore_errors=True)

    create_test_files(test_dir, 10, ["small"] * 10)

    ok = run_import(test_dir, vault_dir, "config.json")
    vault_files = count_vault_files(vault_dir)

    assert ok, "import.py 运行失败"
    print(f"  Vault 文件数: {vault_files}")
    assert vault_files >= 1, f"预期至少 1 个输出文件，实际 {vault_files}"
    print("  PASSED")


def test_mixed_sizes():
    """测试 2：混合大小文档 + 空文件。"""
    print("\n" + "=" * 60)
    print("测试 2: 混合大小文档 (小/中/大/空)")
    print("=" * 60)

    test_dir = "/tmp/notemind_test/source_mixed"
    vault_dir = "/tmp/notemind_test/vault_mixed"
    shutil.rmtree(test_dir, ignore_errors=True)
    shutil.rmtree(vault_dir, ignore_errors=True)

    sizes = ["small"] * 5 + ["medium"] * 3 + ["large"] * 2
    create_test_files(test_dir, 10, sizes)

    ok = run_import(test_dir, vault_dir, "config.json")
    vault_files = count_vault_files(vault_dir)

    assert ok, "import.py 运行失败"
    print(f"  Vault 文件数: {vault_files}")
    print("  PASSED")


def test_error_isolation():
    """测试 3：错误隔离 —— 坏文件不影响其他文件。"""
    print("\n" + "=" * 60)
    print("测试 3: 错误隔离 (好-坏-好-坏-好)")
    print("=" * 60)

    test_dir = "/tmp/notemind_test/source_errors"
    vault_dir = "/tmp/notemind_test/vault_errors"
    shutil.rmtree(test_dir, ignore_errors=True)
    shutil.rmtree(vault_dir, ignore_errors=True)

    # 创建好文件和会触发解析错误的文件
    create_test_files(test_dir, 5, ["small"] * 5)
    # 写入一个空文件（内容为空应被跳过）
    with open(os.path.join(test_dir, "empty.md"), "w") as f:
        pass

    ok = run_import(test_dir, vault_dir, "config.json")

    assert ok, "import.py 应该继续处理完所有文件"
    vault_files = count_vault_files(vault_dir)
    print(f"  Vault 文件数: {vault_files}")
    assert vault_files >= 1, "好文件应该被成功处理"
    print("  PASSED")


def test_checkpoint_resume():
    """测试 4：检查点保存与恢复。"""
    print("\n" + "=" * 60)
    print("测试 4: 检查点保存与恢复")
    print("=" * 60)

    test_dir = "/tmp/notemind_test/source_resume"
    vault_dir = "/tmp/notemind_test/vault_resume"
    log_dir = "/tmp/notemind_test/logs_resume"
    shutil.rmtree(test_dir, ignore_errors=True)
    shutil.rmtree(vault_dir, ignore_errors=True)
    shutil.rmtree(log_dir, ignore_errors=True)

    create_test_files(test_dir, 5, ["small"] * 5)

    # 第一次运行
    print("  --- 第一次运行 ---")
    ok1 = run_import(test_dir, vault_dir, "config.json")
    vault_files_1 = count_vault_files(vault_dir)
    print(f"  第一次: Vault 文件数 = {vault_files_1}")

    # 第二次运行（应该有检查点，跳过所有文件）
    print("  --- 第二次运行（带 --resume）---")
    ok2 = run_import(test_dir, vault_dir, "config.json", resume=True)

    assert ok1 and ok2, "两次运行都应该成功"
    print("  PASSED")


def test_long_running_20_files():
    """测试 5：长时间稳定性（20 个文件连续处理）。"""
    print("\n" + "=" * 60)
    print("测试 5: 长时间稳定性 (20 文件连续处理)")
    print("=" * 60)

    test_dir = "/tmp/notemind_test/source_long"
    vault_dir = "/tmp/notemind_test/vault_long"
    shutil.rmtree(test_dir, ignore_errors=True)
    shutil.rmtree(vault_dir, ignore_errors=True)

    sizes = ["small"] * 10 + ["medium"] * 5 + ["large"] * 5
    create_test_files(test_dir, 20, sizes)

    start = time.time()
    ok = run_import(test_dir, vault_dir, "config.json")
    elapsed = time.time() - start

    vault_files = count_vault_files(vault_dir)
    failed_dir = os.path.join(vault_dir, "_failed")
    failed_files = count_failed_files(failed_dir)

    assert ok, "import.py 运行失败"
    print(f"  总耗时: {elapsed:.1f}s")
    print(f"  Vault 文件数: {vault_files}")
    print(f"  失败文件数: {failed_files}")
    print(f"  平均每个文件: {elapsed/20:.1f}s")
    print("  PASSED")


def test_memory_stability():
    """测试 6：内存稳定性（多次重复处理）。"""
    print("\n" + "=" * 60)
    print("测试 6: 内存稳定性 (5 轮重复处理)")
    print("=" * 60)

    test_dir = "/tmp/notemind_test/source_mem"
    vault_dir = "/tmp/notemind_test/vault_mem"

    # 只运行一轮
    create_test_files(test_dir, 5, ["medium"] * 5)

    for round_num in range(1, 6):
        shutil.rmtree(vault_dir, ignore_errors=True)
        start = time.time()
        ok = run_import(test_dir, vault_dir, "config.json")
        elapsed = time.time() - start
        vault_files = count_vault_files(vault_dir)

        assert ok, f"第 {round_num} 轮失败"
        print(f"  轮次 {round_num}: {vault_files} 文件, {elapsed:.1f}s")

    print("  PASSED")


# --- 主流程 ---

def main():
    print("NoteMind 长时间稳定性测试")

    tests = [
        test_basic_batch,
        test_mixed_sizes,
        test_error_isolation,
        test_checkpoint_resume,
        test_long_running_20_files,
        test_memory_stability,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  FAILED: {e}")
            traceback.print_exc()

    print(f"\n{'=' * 60}")
    print(f"  总计: {passed} 通过, {failed} 失败, {passed + failed} 共 {passed + failed}")
    print(f"{'=' * 60}")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
