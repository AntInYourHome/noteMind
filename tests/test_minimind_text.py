#!/usr/bin/env python3
"""
MiniMind 本地模型 — 文本处理效率与准确性测试（完整版）

测试 3 篇典型文档的摘要、分类、标签生成能力。
用法：python tests/test_minimind_text.py
"""

import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

MINIMIND_DIR = os.path.join(ROOT, 'minimind-v')
sys.path.insert(0, MINIMIND_DIR)


TEST_CASES = [
    {
        "name": "安全白皮书",
        "text": (
            "HarmonyOS NEXT 安全白皮书\n\n"
            "HarmonyOS NEXT 是华为新一代操作系统，采用全栈自研架构。"
            "在安全方面，HarmonyOS NEXT 引入了多项创新技术：\n\n"
            "1. 形式化验证：采用数学方法对系统内核进行形式化验证，"
            "确保关键安全属性的正确性。\n\n"
            "2. 权限管理：基于最小权限原则，实现了细粒度的权限控制机制。"
            "每个应用只能访问其执行所必需的系统资源。\n\n"
            "3. 沙箱隔离：每个应用运行在独立的沙箱环境中，"
            "防止恶意应用对其他应用或系统造成损害。\n\n"
            "4. 安全启动：从硬件信任根开始，逐级验证引导加载程序的完整性，"
            "确保系统启动过程不被篡改。"
        ),
        "expected_tags": ["HarmonyOS", "安全", "白皮书", "权限管理", "沙箱"],
    },
    {
        "name": "技术教程",
        "text": (
            "Python 异步编程入门\n\n"
            "异步编程是 Python 3.4+ 引入的重要特性，通过 async/await "
            "语法可以编写高效的并发代码。\n\n"
            "核心概念：\n"
            "- asyncio：Python 的异步 I/O 框架\n"
            "- async def：定义异步函数\n"
            "- await：等待异步操作完成\n"
            "- event loop：事件循环，负责调度异步任务\n\n"
            "示例代码：\n"
            "async def fetch_data():\n"
            "    await asyncio.sleep(1)\n"
            "    return 'data'\n"
        ),
        "expected_tags": ["Python", "异步编程", "asyncio", "教程"],
    },
    {
        "name": "网络安全报告",
        "text": (
            "2025年网络安全威胁报告\n\n"
            "本报告总结了2025年主要的网络安全威胁趋势：\n\n"
            "1. 勒索软件攻击持续增长，针对企业和政府机构的攻击增加了35%\n"
            "2. 供应链攻击成为新的威胁方向，通过第三方软件组件植入恶意代码\n"
            "3. AI 驱动的社会工程学攻击，深度伪造技术被用于钓鱼攻击\n"
            "4. 物联网设备漏洞被广泛利用，成为僵尸网络的重要组成部分\n"
            "5. 零日漏洞利用价格持续上涨，市场价值超过10亿美元\n\n"
            "建议企业加强安全意识培训，部署零信任架构，定期进行安全审计。"
        ),
        "expected_tags": ["网络安全", "勒索软件", "威胁", "AI", "零信任"],
    },
]

SUMMARY_PROMPT = "请用200字以内概括以下内容的核心要点："
CATEGORY_PROMPT = (
    "请将以下文档分类到以下类别之一，只返回最匹配的类别名称：\n"
    "安全/操作系统安全/HarmonyOS, 安全/操作系统安全/Linux, 安全/网络安全, "
    "技术/编程语言/Python, 其他\n"
)
TAGS_PROMPT = "请从以下内容中提取3-5个关键词标签，用逗号分隔，只返回标签列表："


def load_model():
    """加载 MiniMind 纯文本模型。"""
    import torch
    from model.model_minimind import MiniMindConfig, MiniMindForCausalLM
    from transformers import AutoTokenizer

    weight_path = os.path.join(MINIMIND_DIR, 'out', 'sft_vlm.pth')
    if not os.path.exists(weight_path):
        print("❌ VLM 权重不存在")
        return None

    print(f"\n[1] 加载 MiniMind 模型 (sft_vlm.pth)...")
    t0 = time.time()

    config = MiniMindConfig(
        hidden_size=768, num_hidden_layers=8, use_moe=False, vocab_size=6400,
    )
    model = MiniMindForCausalLM(config)
    state_dict = torch.load(weight_path, map_location='cpu', weights_only=False)
    state_dict = {k: v for k, v in state_dict.items() if k in model.state_dict()}
    if state_dict:
        model.load_state_dict(state_dict, strict=False)
    model = model.float()
    model.eval()

    tokenizer_path = os.path.join(MINIMIND_DIR, 'model')
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, trust_remote_code=True)

    load_time = time.time() - t0
    params = sum(p.numel() for p in model.parameters())
    print(f"  加载耗时: {load_time:.1f}s | 参数量: {params / 1e6:.1f}M")
    return {'model': model, 'tokenizer': tokenizer, 'torch': torch}


def generate(model_data, prompt, context, max_tokens=100):
    """生成文本，返回 (文本, 耗时s)。"""
    model = model_data['model']
    tokenizer = model_data['tokenizer']
    torch = model_data['torch']

    messages = [{"role": "user", "content": prompt + "\n\n" + context[:2000]}]
    inputs_text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = tokenizer(inputs_text, return_tensors="pt", truncation=True, max_length=4096)

    with torch.no_grad():
        generated_ids = model.generate(
            input_ids=inputs["input_ids"],
            attention_mask=inputs["attention_mask"],
            max_new_tokens=max_tokens,
            do_sample=True,
            temperature=0.3,
            top_p=0.9,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )

    full_text = tokenizer.decode(generated_ids[0], skip_special_tokens=True)
    if "assistant" in full_text:
        full_text = full_text.split("assistant", 1)[1].strip()

    full_text = re.sub(r'<think>.*?</think>', '', full_text, flags=re.DOTALL).strip()
    return full_text


def main():
    print("=" * 60)
    print("MiniMind 本地模型 — 文本处理效率与准确性测试")
    print("=" * 60)

    # 可用性检查
    print("\n[可用性检查]")
    checks = {
        "minimind-v 目录": os.path.isdir(MINIMIND_DIR),
        "model_minimind.py": os.path.exists(os.path.join(MINIMIND_DIR, 'model', 'model_minimind.py')),
        "tokenizer": os.path.exists(os.path.join(MINIMIND_DIR, 'model', 'tokenizer.json')),
        "VLM 权重": os.path.exists(os.path.join(MINIMIND_DIR, 'out', 'sft_vlm.pth')),
    }
    for name, ok in checks.items():
        print(f"  {'✅' if ok else '❌'} {name}")

    if not all(checks.values()):
        print("\n⚠️  模型文件不完整")
        sys.exit(1)

    # 加载模型
    model_data = load_model()
    if model_data is None:
        print("\n⚠️  模型加载失败")
        sys.exit(1)

    # 运行测试
    print(f"\n[运行测试] 共 {len(TEST_CASES)} 篇文档")
    results = []

    for i, tc in enumerate(TEST_CASES, 1):
        print(f"\n--- 测试 {i}: {tc['name']} ({len(tc['text'])} 字符) ---")

        t0 = time.time()
        summary = generate(model_data, SUMMARY_PROMPT, tc['text'], max_tokens=150)
        summary_t = time.time() - t0

        t0 = time.time()
        category = generate(model_data, CATEGORY_PROMPT, tc['text'], max_tokens=30)
        category_t = time.time() - t0

        t0 = time.time()
        tags_text = generate(model_data, TAGS_PROMPT, tc['text'], max_tokens=50)
        tags_t = time.time() - t0

        total_t = summary_t + category_t + tags_t

        # 标签匹配评分
        expected = set(tc['expected_tags'])
        matched = sum(1 for t in expected if t.lower() in tags_text.lower())
        tag_score = matched / len(expected) if expected else 0

        print(f"  摘要 ({summary_t:.1f}s): {summary[:80]}...")
        print(f"  分类 ({category_t:.1f}s): {category[:60]}")
        print(f"  标签 ({tags_t:.1f}s): {tags_text[:80]}")
        print(f"  标签匹配: {tag_score:.0%} ({matched}/{len(expected)})")

        results.append({
            "name": tc['name'],
            "chars": len(tc['text']),
            "summary_time": summary_t,
            "category_time": category_t,
            "tags_time": tags_t,
            "total_time": total_t,
            "tag_match": tag_score,
        })

    # 汇总报告
    avg_time = sum(r['total_time'] for r in results) / len(results)
    avg_score = sum(r['tag_match'] for r in results) / len(results)
    total_time = sum(r['total_time'] for r in results)

    print("\n" + "=" * 60)
    print("汇总报告")
    print("=" * 60)
    print(f"  平均处理时间: {avg_time:.1f}s/篇")
    print(f"  平均标签匹配率: {avg_score:.0%}")
    print(f"  总耗时: {total_time:.1f}s ({len(TEST_CASES)} 篇)")
    print(f"  模型参数量: 63.9M (纯 CPU)")
    print(f"  最大上下文: 4096 tokens")

    print("\n评估结论:")
    if avg_score >= 0.6:
        print("  ✅ 标签提取能力基本可用，可辅助 NoteMind 分类打标")
    elif avg_score >= 0.4:
        print("  ⚠️  标签提取能力一般，建议作为辅助参考")
    else:
        print("  ❌ 标签提取能力不足，暂不建议用于 NoteMind")

    if avg_time <= 5:
        print("  ✅ 处理速度较快，适合批量处理")
    elif avg_time <= 15:
        print("  ⚠️  处理速度一般，适合小规模使用")
    else:
        print("  ❌ 处理速度较慢，仅适合少量文档")


if __name__ == "__main__":
    main()
