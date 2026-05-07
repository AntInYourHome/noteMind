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

        import torch
        from PIL import Image
        from model.model_vlm import MiniMindVLM, VLMConfig
        from transformers import AutoTokenizer

        # 模型路径
        weight_path = os.path.join(minimind_dir, 'out', 'sft_vlm.pth')
        vision_path = os.path.join(minimind_dir, 'model', 'siglip2-base-p32-256-ve')

        if not os.path.exists(weight_path):
            raise FileNotFoundError(f"VLM 权重不存在: {weight_path}")
        if not os.path.exists(vision_path):
            raise FileNotFoundError(f"Vision encoder 不存在: {vision_path}")

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

    # 构造 prompt
    prompt = "请用简洁的中文描述这张图片的内容，包括图片类型、主要元素、可能的用途。控制在 200 字以内。"
    messages = [{
        "role": "user",
        "content": vlm.config.image_special_token * vlm.config.image_token_len + "\n" + prompt
    }]
    inputs_text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(inputs_text, return_tensors="pt", truncation=True)

    torch = model_data['torch']

    # 推理
    with torch.no_grad():
        generated_ids = vlm.generate(
            inputs=inputs["input_ids"],
            attention_mask=inputs["attention_mask"],
            max_new_tokens=max_tokens,
            do_sample=False,
            temperature=0.7,
            top_p=0.85,
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
    """检查本地 VLM 是否可用（不加载模型，仅检查文件是否存在）。"""
    base_dir = os.path.dirname(os.path.abspath(__file__))  # .../noteMind/scripts/
    project_dir = os.path.dirname(base_dir)  # .../noteMind/
    minimind_dir = os.path.join(project_dir, 'minimind-v')
    if not os.path.isdir(minimind_dir):
        return False
    weight_path = os.path.join(minimind_dir, 'out', 'sft_vlm.pth')
    vision_path = os.path.join(minimind_dir, 'model', 'siglip2-base-p32-256-ve')
    return os.path.exists(weight_path) and os.path.exists(vision_path)
