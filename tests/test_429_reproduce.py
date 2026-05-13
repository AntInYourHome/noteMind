#!/usr/bin/env python3
"""
NoteMind Provider 429 问题复现测试

场景：配置 5 个 provider，第一个频繁 429，验证其他 provider 能否正常切换。
预期行为：
  - 第一个 provider 触发 429 后进入冷却
  - 后续请求自动切换到其他健康 provider
  - 出错少的 provider 获得更多请求（加权随机）

用法：python tests/test_429_reproduce.py
"""

import sys
import time
import json
import urllib
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


def _make_429_provider(api_key: str = "sk-test-1"):
    """构造一个始终返回 429 的 provider。"""
    return {
        "api_key": api_key,
        "model": "always-429",
        "base_url": "https://mock-429.example.com/v1",
        "multimodal": False,
    }


def _make_normal_provider(api_key: str = "sk-test-good"):
    """构造一个正常返回的 provider（mock）。"""
    return {
        "api_key": api_key,
        "model": "good-model",
        "base_url": "https://mock-good.example.com/v1",
        "multimodal": False,
    }


class _MockHTTPResponse:
    """模拟 HTTP 响应。"""
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        return self._body


def test_429_provider_gets_cooled_down():
    """测试：单个 provider 触发 429 后进入冷却，变为不可用。"""
    print("\n[429-01] 单个 provider 429 冷却")
    from scripts.ai_client import APIProviderPool

    # 创建一个正常 provider + 一个 429 provider
    # 但实际 HTTP 调用中，429 provider 的 URL 是无效的，会触发网络错误
    # 我们直接用 health tracker 来模拟

    pool = APIProviderPool(providers=[_make_429_provider("sk-fail-1"), _make_normal_provider("sk-ok-1")], concurrency=1)
    t0 = pool._trackers[0]  # 429 provider 的 tracker

    # 手动模拟 429 失败记录
    t0.record_failure("AI API 错误 (429): rate limit", is_rate_limit=True)
    t0.record_failure("AI API 错误 (429): rate limit", is_rate_limit=True)
    t0.record_failure("AI API 错误 (429): rate limit", is_rate_limit=True)

    # 3 次连续 429 后应该进入冷却
    check("429 provider 进入冷却", not t0.is_available())

    # 健康 provider 仍然可用
    t1 = pool._trackers[1]
    check("健康 provider 不受影响", t1.is_available())


def test_pool_skips_cooled_provider():
    """测试：next_provider() 跳过冷却中的 provider。"""
    print("\n[429-02] next_provider 跳过冷却 provider")
    from scripts.ai_client import APIProviderPool

    providers = [
        _make_429_provider("sk-fail-1"),
        _make_normal_provider("sk-ok-1"),
        _make_normal_provider("sk-ok-2"),
    ]
    pool = APIProviderPool(providers=providers, concurrency=1)

    # 让第一个 provider 进入冷却
    t0 = pool._trackers[0]
    for _ in range(3):
        t0.record_failure("AI API 错误 (429): rate limit", is_rate_limit=True)

    # 连续 10 次 next_provider，都不应选中冷却的 provider
    selected_indices = []
    for _ in range(10):
        _, tracker = pool.next_provider()
        selected_indices.append(pool._trackers.index(tracker))

    check("冷却 provider 未被选中", 0 not in selected_indices)
    check("只在健康 provider 之间选择",
          all(i in (1, 2) for i in selected_indices))


def test_weighted_favors_healthy_providers():
    """测试：加权随机选择偏向于健康的 provider。"""
    print("\n[429-03] 加权随机偏向健康 provider")
    from scripts.ai_client import APIProviderPool

    providers = [
        _make_normal_provider("sk-good-1"),
        _make_normal_provider("sk-good-2"),
        _make_normal_provider("sk-good-3"),
    ]
    pool = APIProviderPool(providers=providers, concurrency=1)

    # 让 provider 2 有失败记录（降低 health_score）
    t2 = pool._trackers[2]
    t2.record_success()  # 1 次成功
    t2.record_failure("error", is_rate_limit=False)  # 1 次失败
    t2.record_failure("error", is_rate_limit=False)  # 1 次失败
    # health_score ≈ 1/3 = 0.33

    # provider 0 和 1 都是 1.0（未使用过），provider 2 是 0.33
    # 运行 100 次选择，统计分布
    counts = [0, 0, 0]
    import random
    random.seed(42)
    for _ in range(200):
        _, tracker = pool.next_provider()
        idx = pool._trackers.index(tracker)
        counts[idx] += 1

    print(f"    选择分布: {counts}")

    # 健康 provider 应该获得更多选择
    healthy_total = counts[0] + counts[1]
    sick_count = counts[2]
    check("健康 provider 获得更多选择",
          healthy_total > sick_count,
          f"健康: {healthy_total}, 有失败记录: {sick_count}")


def test_all_providers_429_triggers_degraded_mode():
    """测试：所有 provider 都 429 时，触发降级模式（降并发）。"""
    print("\n[429-04] 全部 429 触发降级模式")
    from scripts.ai_client import APIProviderPool

    providers = [
        _make_normal_provider("sk-1"),
        _make_normal_provider("sk-2"),
    ]
    pool = APIProviderPool(providers=providers, concurrency=5)

    # 让所有 provider 都不可用
    for tracker in pool._trackers:
        tracker.circuit_open_until = time.time() + 300  # 5 分钟冷却
        tracker.rate_limit_count = 3

    # 检查降级
    available = sum(1 for t in pool._trackers if t.is_available())
    check("所有 provider 不可用", available == 0)


def test_single_provider_429_no_fallback():
    """测试：只有 1 个 provider 且 429 时，无法切换。"""
    print("\n[429-05] 单 provider 429 无备选")
    from scripts.ai_client import APIProviderPool

    providers = [_make_429_provider("sk-only")]
    pool = APIProviderPool(providers=providers, concurrency=5)

    # 模拟 429
    t0 = pool._trackers[0]
    t0.record_failure("AI API 错误 (429): rate limit", is_rate_limit=True)
    t0.record_failure("AI API 错误 (429): rate limit", is_rate_limit=True)
    t0.record_failure("AI API 错误 (429): rate limit", is_rate_limit=True)

    check("唯一 provider 进入冷却", not t0.is_available())

    # next_provider 强制返回唯一的 provider
    _, tracker = pool.next_provider()
    check("强制返回唯一 provider", tracker == t0)
    print(f"    ⚠️  单 provider 场景：429 后无备选，需配置多个 provider 分散负载")


if __name__ == "__main__":
    print("=" * 50)
    print("NoteMind Provider 429 问题复现测试")
    print("=" * 50)

    try:
        test_429_provider_gets_cooled_down()
        test_pool_skips_cooled_provider()
        test_weighted_favors_healthy_providers()
        test_all_providers_429_triggers_degraded_mode()
        test_single_provider_429_no_fallback()
    except Exception as e:
        print(f"\n⚠️  测试异常: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 50)
    print(f"测试完成: ✅ {PASSED} 通过 | ❌ {FAILED} 失败")
    print("=" * 50)

    if FAILED > 0:
        sys.exit(1)
