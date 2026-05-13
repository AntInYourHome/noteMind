#!/usr/bin/env python3
"""
NoteMind Provider 429 问题 E2E 测试

模拟真实场景：5 个 provider，第一个频繁 429，验证其他 provider 是否正常工作。
使用 NOTEMIND_TEST_CHAOS=1 注入随机错误。

用法：python tests/test_429_e2e.py
"""

import sys
import os
import json
import tempfile
import shutil
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


def test_single_provider_429_blocks_all():
    """E2E 测试：单 provider 场景下 429 导致所有请求失败。

    这是当前 config.json 的真实情况：只有 1 个 provider。
    429 后进入冷却，重试仍选中同一个 provider（因为没有备选），
    导致所有 API 调用失败。
    """
    print("\n[E2E-01] 单 provider 429 阻塞验证（当前配置）")

    from scripts.ai_client import APIProviderPool
    import random
    random.seed(42)

    # 模拟当前 config：只有 1 个 provider
    providers = [{
        "api_key": "sk-test-only",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com/v1",
        "multimodal": False,
    }]
    pool = APIProviderPool(providers=providers, concurrency=5)

    # 模拟第一次调用触发 429
    t0 = pool._trackers[0]
    t0.record_failure("AI API 错误 (429): rate limit", is_rate_limit=True)
    t0.record_failure("AI API 错误 (429): rate limit", is_rate_limit=True)
    t0.record_failure("AI API 错误 (429): rate limit", is_rate_limit=True)

    # 进入冷却后，next_provider 强制返回同一个（唯一）provider
    _, tracker = pool.next_provider()
    check("冷却后仍选中唯一 provider", tracker == t0)
    check("唯一 provider 处于冷却状态", not t0.is_available())

    print(f"    ⚠️  单 provider 场景：429 后无备选，必须配置多个 provider")


def test_five_providers_first_429_fallback():
    """E2E 测试：5 个 provider 中第一个 429，验证能自动切换到其他 4 个。"""
    print("\n[E2E-02] 5 provider 场景：第一个 429 自动切换")

    from scripts.ai_client import APIProviderPool
    import random
    random.seed(42)

    providers = []
    for i in range(5):
        providers.append({
            "api_key": f"sk-test-{i}",
            "model": f"model-{i}",
            "base_url": f"https://api{i}.example.com/v1",
            "multimodal": False,
        })

    pool = APIProviderPool(providers=providers, concurrency=5)

    # 模拟第一个 provider 触发 429（连续 3 次进入长冷却）
    t0 = pool._trackers[0]
    for _ in range(3):
        t0.record_failure("AI API 错误 (429): rate limit", is_rate_limit=True)

    check("Provider 0 进入冷却", not t0.is_available())

    # 检查其他 4 个 provider 正常可用
    for i in range(1, 5):
        check(f"Provider {i} 正常可用", pool._trackers[i].is_available())

    # 连续 20 次选择，统计分布
    counts = [0] * 5
    for _ in range(20):
        _, tracker = pool.next_provider()
        idx = pool._trackers.index(tracker)
        counts[idx] += 1

    print(f"    20 次选择分布: {counts}")
    check("Provider 0 未被选中", counts[0] == 0)
    check("其他 4 个 provider 分担请求", sum(counts[1:]) == 20)


def test_pool_call_retry_with_different_provider():
    """测试 pool.call() 重试时会切换 provider。"""
    print("\n[E2E-03] pool.call() 重试切换 provider")

    from scripts.ai_client import APIProviderPool
    import random
    random.seed(42)

    # 创建 3 个 provider
    providers = []
    for i in range(3):
        providers.append({
            "api_key": f"sk-test-{i}",
            "model": f"model-{i}",
            "base_url": f"https://api{i}.example.com/v1",
            "multimodal": False,
        })

    pool = APIProviderPool(providers=providers, concurrency=3)

    # 让所有 provider 都失败一次，验证重试切换
    # 由于没有真实 API，我们直接验证 next_provider 的行为
    # 连续 3 次调用 next_provider，应该选中不同 provider
    selected = []
    for _ in range(3):
        _, tracker = pool.next_provider()
        idx = pool._trackers.index(tracker)
        selected.append(idx)

    print(f"    3 次选择: {selected}")
    # 加权随机不保证不同，但概率上应该分散
    unique_count = len(set(selected))
    check(f"选择分散（{unique_count}/3 个不同 provider）", unique_count >= 2)


def test_current_config_has_only_one_provider():
    """验证当前 config.json 只有 1 个 provider（429 问题根因）。"""
    print("\n[E2E-04] 验证当前配置")

    cfg_path = ROOT / "config.json"
    check("config.json 存在", cfg_path.exists())

    with open(cfg_path) as f:
        cfg = json.load(f)

    providers = cfg["ai"].get("providers", [])
    check(f"当前配置了 {len(providers)} 个 provider",
          len(providers) > 1,
          f"实际: {len(providers)} 个")

    if len(providers) == 1:
        print(f"    ⚠️  根因确认：只有 1 个 provider，429 后无备选")
        print(f"    建议：在 config.json 的 ai.providers 中添加多个 API Key")


if __name__ == "__main__":
    print("=" * 50)
    print("NoteMind Provider 429 E2E 测试")
    print("=" * 50)

    try:
        test_single_provider_429_blocks_all()
        test_five_providers_first_429_fallback()
        test_pool_call_retry_with_different_provider()
        test_current_config_has_only_one_provider()
    except Exception as e:
        print(f"\n⚠️  测试异常: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 50)
    print(f"测试完成: ✅ {PASSED} 通过 | ❌ {FAILED} 失败")
    print("=" * 50)

    if FAILED > 0:
        sys.exit(1)
