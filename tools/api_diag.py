#!/usr/bin/env python3
"""
NoteMind API 调试工具 — 测试模型可用性、稳定性、并发能力和性能
用法:
    python tools/api_diag.py                  # 使用 config.json 中配置
    python tools/api_diag.py --model gpt-4o   # 指定模型
    python tools/api_diag.py --concurrency 10  # 测试 10 并发
    python tools/api_diag.py --quick           # 快速模式（少样本）
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# 支持项目根目录导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# --- 测试用例 ---

TEST_PROMPTS = {
    "summary": {
        "name": "摘要能力",
        "messages": [
            {
                "role": "user",
                "content": (
                    "请用中文总结以下内容的核心要点（3-5条），控制在200字以内：\n\n"
                    "人工智能（Artificial Intelligence, AI）是计算机科学的一个分支，"
                    "致力于创建能够模拟、延伸和扩展人类智能的系统。自 1956 年达特茅斯会议以来，"
                    "AI 经历了多次热潮和低谷。当前，以深度学习和大语言模型为代表的 AI 技术"
                    "正在深刻改变各行各业。主要技术路线包括：监督学习、无监督学习、强化学习、"
                    "以及近年来兴起的多模态学习和通用人工智能（AGI）探索。"
                    "AI 面临的挑战包括：算力需求、数据隐私、算法偏见、可解释性不足，"
                    "以及伦理和安全问题。未来，AI 有望在医疗、教育、交通、科研等领域发挥更大作用。"
                ),
            }
        ],
        "max_tokens": 300,
    },
    "tags": {
        "name": "标签提取",
        "messages": [
            {
                "role": "user",
                "content": (
                    "请从以下内容中提取 3-8 个中文标签（关键词），用逗号分隔，只返回标签：\n\n"
                    "RISC-V 是一种开源指令集架构（ISA），起源于加州大学伯克利分校的研究项目。"
                    "与 x86 和 ARM 等商业 ISA 不同，RISC-V 采用开源许可证，允许任何人自由使用、"
                    "修改和分发。其模块化设计支持基础整数指令集（RV32I/RV64I）和可选扩展（M/A/F/D/C），"
                    "使其能够灵活应用于嵌入式系统、服务器和超级计算机等不同场景。"
                    "近年来，RISC-V 在物联网（IoT）和边缘计算领域获得了广泛支持，"
                    "多家芯片厂商推出了基于 RISC-V 的处理器。"
                ),
            }
        ],
        "max_tokens": 100,
    },
    "reasoning": {
        "name": "逻辑推理",
        "messages": [
            {
                "role": "user",
                "content": (
                    "请解答以下问题并简要说明推理过程：\n\n"
                    "一个房间里有 100 盏灯，编号 1-100，初始都是关闭的。"
                    "有 100 个人依次进入房间：\n"
                    "第 1 个人按下所有编号是 1 的倍数的灯的开关；\n"
                    "第 2 个人按下所有编号是 2 的倍数的灯的开关；\n"
                    "...第 n 个人按下所有编号是 n 的倍数的灯的开关。\n"
                    "最后有多少盏灯是亮着的？请给出编号和原因。"
                ),
            }
        ],
        "max_tokens": 500,
    },
    "code": {
        "name": "代码生成",
        "messages": [
            {
                "role": "user",
                "content": (
                    "请用 Python 写一个函数，实现判断一个字符串是否为有效回文（忽略空格、"
                    "标点符号和大小写）。只返回代码，不要解释。"
                ),
            }
        ],
        "max_tokens": 200,
    },
}


# --- 单请求测试 ---

def test_single_call(provider: dict, prompt_key: str = "summary", timeout: int = 30) -> dict:
    """单次 API 调用测试。"""
    prompt = TEST_PROMPTS[prompt_key]
    url = f"{provider['base_url']}/chat/completions"
    payload = json.dumps({
        "model": provider["model"],
        "messages": prompt["messages"],
        "max_tokens": prompt["max_tokens"],
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {provider.get('api_key', '')}",
        },
        method="POST",
    )

    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed = time.time() - start
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"].strip()
            usage = data.get("usage", {})
            return {
                "success": True,
                "elapsed": elapsed,
                "content_length": len(content),
                "tokens_input": usage.get("prompt_tokens", "N/A"),
                "tokens_output": usage.get("completion_tokens", "N/A"),
                "content_preview": content[:120],
            }
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"success": False, "elapsed": time.time() - start, "error": f"HTTP {e.code}: {body}"}
    except Exception as e:
        return {"success": False, "elapsed": time.time() - start, "error": str(e)}


# --- 并发测试 ---

def test_concurrency(provider: dict, concurrency: int = 5, rounds: int = 3) -> dict:
    """并发性能测试。

    每轮发送 concurrency 个请求，共 rounds 轮。
    """
    all_results = []
    total_success = 0
    total_fail = 0

    for round_num in range(1, rounds + 1):
        tasks = [{"messages": TEST_PROMPTS["summary"]["messages"],
                  "max_tokens": 300, "retries": 0}
                 for _ in range(concurrency)]

        def run_task(idx: int, task: dict):
            return test_single_call(provider, "summary")

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(run_task, i, t) for i, t in enumerate(tasks)]
            round_results = [f.result() for f in as_completed(futures)]

        all_results.extend(round_results)
        round_ok = sum(1 for r in round_results if r["success"])
        round_fail = concurrency - round_ok
        total_success += round_ok
        total_fail += round_fail

        round_times = [r["elapsed"] for r in round_results if r["success"]]
        avg_time = sum(round_times) / len(round_times) if round_times else 0

        print(f"  轮次 {round_num}/{rounds}: "
              f"成功 {round_ok}/{concurrency}, "
              f"平均响应 {avg_time:.2f}s")

    success_times = [r["elapsed"] for r in all_results if r.get("success")]
    return {
        "total_requests": len(all_results),
        "total_success": total_success,
        "total_fail": total_fail,
        "success_rate": total_success / len(all_results) if all_results else 0,
        "avg_latency": sum(success_times) / len(success_times) if success_times else 0,
        "min_latency": min(success_times) if success_times else 0,
        "max_latency": max(success_times) if success_times else 0,
        "p95_latency": sorted(success_times)[int(len(success_times) * 0.95)] if success_times else 0,
        "throughput": total_success / sum(r["elapsed"] for r in all_results) if all_results else 0,
    }


# --- 能力评估 ---

def test_capabilities(provider: dict) -> list[dict]:
    """多维度能力测试。"""
    results = []
    for key, prompt in TEST_PROMPTS.items():
        r = test_single_call(provider, key)
        results.append({
            "test": prompt["name"],
            "key": key,
            "success": r["success"],
            "elapsed": r.get("elapsed", 0),
            "content_length": r.get("content_length", 0),
            "preview": r.get("content_preview", ""),
            "error": r.get("error", ""),
        })
    return results


# --- 主流程 ---

def load_providers(config_path: str = None) -> list[dict]:
    """加载 provider 配置。"""
    if config_path and os.path.exists(config_path):
        with open(config_path) as f:
            cfg = json.load(f)
        return cfg.get("ai", {}).get("providers", [])

    # 默认路径
    default = Path(__file__).resolve().parent.parent / "config.json"
    if default.exists():
        with open(default) as f:
            cfg = json.load(f)
        return cfg.get("ai", {}).get("providers", [])

    # 环境变量
    key = os.environ.get("QWEN_API_KEY")
    if key:
        return [{
            "api_key": key,
            "model": "qwen3.6-flash",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        }]

    raise ValueError("未找到 config.json 且 QWEN_API_KEY 环境变量未设置")


def run_diagnosis(providers: list[dict], concurrency: int = 5, quick: bool = False):
    """执行完整的诊断流程。"""
    print("\n" + "=" * 60)
    print("  NoteMind API 诊断工具")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Provider 数量: {len(providers)}")
    print(f"  并发数: {concurrency}")
    print("=" * 60)

    for i, provider in enumerate(providers):
        model = provider.get("model", "unknown")
        base_url = provider.get("base_url", "")
        key_preview = provider.get("api_key", "")[:6] + "***"
        print(f"\n{'─' * 60}")
        print(f"  Provider [{i+1}/{len(providers)}]")
        print(f"  模型: {model}")
        print(f"  地址: {base_url}")
        print(f"  Key: {key_preview}")
        print(f"{'─' * 60}")

        # 1. 连通性测试
        print("\n  [1/3] 连通性测试...")
        r = test_single_call(provider, "summary")
        if r["success"]:
            print(f"  ✅ 连接成功 | 响应 {r['elapsed']:.2f}s | "
                  f"输出 {r['content_length']} 字符 | "
                  f"Token: 输入={r['tokens_input']}, 输出={r['tokens_output']}")
            print(f"  预览: {r['content_preview']}...")
        else:
            print(f"  ❌ 连接失败 | {r['error']}")
            continue  # 跳过后续测试

        # 2. 能力评估（快速模式跳过）
        if not quick:
            print("\n  [2/3] 多维度能力测试...")
            cap_results = test_capabilities(provider)
            for cr in cap_results:
                status = "✅" if cr["success"] else "❌"
                print(f"  {status} {cr['test']:<12} | {cr['elapsed']:.2f}s | "
                      f"{cr['content_length']} 字符"
                      + (f" | {cr['error'][:40]}" if cr["error"] else ""))

        # 3. 并发测试（快速模式跳过）
        if not quick:
            print(f"\n  [3/3] 并发测试 ({concurrency} 并发 x 3 轮)...")
            perf = test_concurrency(provider, concurrency, rounds=3)
            print(f"\n  汇总:")
            print(f"  成功率: {perf['success_rate']:.0%} ({perf['total_success']}/{perf['total_requests']})")
            print(f"  平均延迟: {perf['avg_latency']:.2f}s")
            print(f"  最小延迟: {perf['min_latency']:.2f}s")
            print(f"  最大延迟: {perf['max_latency']:.2f}s")
            print(f"  P95 延迟: {perf['p95_latency']:.2f}s")
            print(f"  吞吐量: {perf['throughput']:.2f} 请求/秒")
        else:
            print("\n  [2/2] 跳过能力测试和并发测试（快速模式）")

    # 总结
    print(f"\n{'=' * 60}")
    print("  诊断完成")
    print(f"{'=' * 60}\n")


def main():
    parser = argparse.ArgumentParser(description="NoteMind API 调试工具")
    parser.add_argument("--config", "-c", type=str, help="config.json 路径")
    parser.add_argument("--concurrency", "-C", type=int, default=5, help="并发数（默认 5）")
    parser.add_argument("--rounds", "-r", type=int, default=3, help="并发测试轮数（默认 3）")
    parser.add_argument("--quick", "-q", action="store_true", help="快速模式（仅连通性）")
    parser.add_argument("--model", "-m", type=str, help="覆盖配置中的模型名")
    args = parser.parse_args()

    try:
        providers = load_providers(args.config)
    except ValueError as e:
        print(f"错误: {e}")
        sys.exit(1)

    # 覆盖模型名
    if args.model:
        for p in providers:
            p["model"] = args.model

    run_diagnosis(providers, args.concurrency, args.quick)


if __name__ == "__main__":
    main()
