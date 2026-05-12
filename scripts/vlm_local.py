"""
MiniMind-V 本地图片描述 — NoteMind 集成适配器
纯 CPU 推理，~3s/张，无需 API Key。
"""

import logging
import os
import time
from threading import Lock

logger = logging.getLogger("notemind")

_model = None
_model_lock = Lock()


def _load_model():
    """懒加载 VLM 模型（线程安全单例）。"""
    global _model
    with _model_lock:
        if _model is not None:
            return _model

        # 解析路径：相对于 NoteMind 项目根目录
        base_dir = os.path.dirname(os.path.abspath(__file__))  # .../noteMind/scripts/
        project_dir = os.path.dirname(base_dir)  # .../noteMind/
        minimind_dir = os.path.join(project_dir, 'minimind-v')
        if not os.path.isdir(minimind_dir):
            raise FileNotFoundError(f"minimind-v 目录不存在: {minimind_dir}")

        import sys
        if minimind_dir not in sys.path:
            sys.path.insert(0, minimind_dir)

        # 检查模型文件是否存在
        weight_path = os.path.join(minimind_dir, 'out', 'sft_vlm.pth')
        vision_path = os.path.join(minimind_dir, 'model', 'siglip2-base-p32-256-ve')

        if not os.path.exists(weight_path):
            raise FileNotFoundError(f"VLM 权重不存在: {weight_path}")
        if not os.path.exists(vision_path):
            raise FileNotFoundError(f"Vision encoder 不存在: {vision_path}")

        # 动态导入模型模块（捕获 ImportError）
        try:
            import torch
            from PIL import Image
            from model.model_vlm import MiniMindVLM, VLMConfig
            from transformers import AutoTokenizer
        except ImportError as e:
            raise ImportError(f"VLM 模型模块导入失败: {e}。请确保 minimind-v 依赖已安装。")

        logger.info("[VLM] 正在加载 MiniMind-V 模型...")
        t0 = time.time()

        model = MiniMindVLM(
            VLMConfig(hidden_size=768, num_hidden_layers=8, use_moe=False),
            vision_model_path=vision_path
        )
        state_dict = torch.load(weight_path, map_location='cpu', weights_only=False)
        model.load_state_dict(
            {k: v for k, v in state_dict.items() if 'mask' not in k}, strict=False
        )
        model = model.float()  # CPU 必须用 float32
        model.eval()

        tokenizer_path = os.path.join(minimind_dir, 'model')
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, trust_remote_code=True)

        _model = {
            'vlm': model,
            'tokenizer': tokenizer,
            'pil': Image,
            'torch': torch,
        }

        elapsed = time.time() - t0
        logger.info(f"[VLM] 模型加载完成，耗时 {elapsed:.1f}s")
        return _model


def describe_image(image_path: str, max_tokens: int = 100) -> str:
    """分析图片内容，返回中文描述。

    Args:
        image_path: 图片文件路径
        max_tokens: 最大生成 token 数（默认 100）

    Returns:
        图片描述的中文文本
    """
    model_data = _load_model()
    vlm = model_data['vlm']
    tokenizer = model_data['tokenizer']
    Image = model_data['pil']

    # 加载图片
    img = Image.open(image_path).convert('RGB')

    # 图像预处理（image2tensor 是静态方法）
    pixel_values = {k: v for k, v in type(vlm).image2tensor(img, vlm.processor).items()}

    # 构造 prompt — 针对小模型优化，聚焦关键信息，避免幻觉
    prompt = (
        "请直接按以下格式回复，每行一个标签，不要解释：\n"
        "类型：[截图/照片/图表/表格/文档/海报/示意图/其他]\n"
        "主体：[1-3个核心关键词]\n"
        "文字：[图片中可见的文字，如无则写无]\n"
        "场景：[用途或领域]\n"
        "注意：只描述图片中实际看到的内容，不要推测。"
    )
    messages = [{
        "role": "user",
        "content": vlm.config.image_special_token * vlm.config.image_token_len + "\n" + prompt
    }]
    inputs_text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(inputs_text, return_tensors="pt", truncation=True)

    torch = model_data['torch']

    # 推理 — 降低 temperature 减少幻觉
    with torch.no_grad():
        generated_ids = vlm.generate(
            inputs=inputs["input_ids"],
            attention_mask=inputs["attention_mask"],
            max_new_tokens=max_tokens,
            do_sample=True,
            temperature=0.3,
            top_p=0.9,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
            pixel_values=pixel_values,
        )

    # 解码，去掉 prompt 部分
    full_text = tokenizer.decode(generated_ids[0], skip_special_tokens=True)
    # 去掉 prompt 前缀，只保留 AI 回复
    if "assistant" in full_text:
        full_text = full_text.split("assistant", 1)[1].strip()

    # 过滤 <think> 推理标签
    import re
    full_text = re.sub(r'<think>.*?</think>', '', full_text, flags=re.DOTALL).strip()
    full_text = full_text.replace('</think>', '').strip()

    return full_text


def is_available() -> bool:
    """检查本地 VLM 是否可用（不加载模型，仅检查文件和模块）。"""
    base_dir = os.path.dirname(os.path.abspath(__file__))  # .../noteMind/scripts/
    project_dir = os.path.dirname(base_dir)  # .../noteMind/
    minimind_dir = os.path.join(project_dir, 'minimind-v')

    # 检查目录和文件是否存在
    if not os.path.isdir(minimind_dir):
        return False
    weight_path = os.path.join(minimind_dir, 'out', 'sft_vlm.pth')
    vision_path = os.path.join(minimind_dir, 'model', 'siglip2-base-p32-256-ve')
    if not os.path.exists(weight_path) or not os.path.exists(vision_path):
        return False

    # 检查 model.model_vlm 模块是否存在
    model_vlm_path = os.path.join(minimind_dir, 'model', 'model_vlm.py')
    if not os.path.exists(model_vlm_path):
        logger.warning("[VLM] model_vlm.py 不存在，本地 VLM 不可用")
        return False

    return True


def test_local_vlm(test_image_path: str = None) -> dict:
    """测试本地 VLM (MiniMind-V) 可用性。

    Args:
        test_image_path: 测试图片路径（可选）

    Returns:
        {"available": bool, "model_loaded": bool, "latency": float, "error": str, "preview": str}
    """
    results = {
        "available": False,
        "model_loaded": False,
        "latency": 0,
        "error": None,
        "preview": None,
    }

    # 检查环境变量是否启用本地 VLM
    env_val = os.environ.get("NOTEMIND_LOCAL_VLM", "auto")
    if env_val == "0" or env_val.lower() == "false":
        results["error"] = "NOTEMIND_LOCAL_VLM=0，已禁用"
        return results

    # 检查文件是否存在
    try:
        if not is_available():
            results["error"] = "模型文件不存在 (minimind-v/out/sft_vlm.pth)"
            return results
    except Exception as e:
        results["error"] = f"is_available() 检查失败: {e}"
        return results

    results["available"] = True  # 文件存在，理论上可用

    # 如果没有测试图片，只返回可用性检查结果
    if not test_image_path or not os.path.exists(test_image_path):
        results["error"] = "无测试图片，跳过推理测试"
        return results

    # 实际加载模型并推理测试
    try:
        t0 = time.time()
        desc = describe_image(test_image_path)
        latency = time.time() - t0

        if desc and desc.strip():
            results["model_loaded"] = True
            results["latency"] = latency
            results["preview"] = desc[:100]
        else:
            results["error"] = "模型推理返回空结果"
    except Exception as e:
        results["error"] = f"模型加载/推理失败: {e}"

    return results


def print_local_vlm_test_report(results: dict):
    """打印本地 VLM 测试报告。"""
    logger.info("=" * 50)
    logger.info("本地 VLM (MiniMind-V) 可用性测试")
    logger.info("=" * 50)

    if results.get("available"):
        if results.get("model_loaded"):
            logger.info(f"  ✅ 状态: 可用 | 推理延迟: {results['latency']:.1f}s")
            if results.get("preview"):
                logger.info(f"     预览: {results['preview']}")
        else:
            logger.info(f"  ⏳ 状态: 文件存在但未测试推理")
            if results.get("error"):
                logger.info(f"     原因: {results['error']}")
    else:
        logger.info(f"  ❌ 状态: 不可用")
        if results.get("error"):
            logger.info(f"     原因: {results['error']}")

    logger.info("=" * 50)
