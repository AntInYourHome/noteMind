#!/usr/bin/env python3
"""快速测试 MiniMind-V CPU 推理性能。"""
import time
import torch
from PIL import Image
from model.model_vlm import MiniMindVLM, VLMConfig
from transformers import AutoTokenizer

print("=== MiniMind-V CPU 性能穿刺 ===")
print(f"PyTorch: {torch.__version__}")
print(f"CPU 可用: {torch.get_num_threads()} threads")

# 1. 加载 SigLIP2
print("\n[1] 加载 SigLIP2 视觉编码器...")
t0 = time.time()
vision_model_path = "./model/siglip2-base-p32-256-ve"
# 检查是否已下载
import os
if not os.path.exists(vision_model_path):
    print(f"  SigLIP2 模型不存在: {vision_model_path}")
    print("  需要先下载: modelscope download --model gongjy/siglip2-base-p32-256-ve --local_dir ./model/siglip2-base-p32-256-ve")
    exit(1)
t1 = time.time()
print(f"  路径存在，耗时 {t1-t0:.1f}s")

# 2. 构建 VLM 模型
print("\n[2] 构建 VLM 模型 (Dense, 160M)...")
t0 = time.time()
model = MiniMindVLM(
    VLMConfig(hidden_size=768, num_hidden_layers=8, use_moe=False),
    vision_model_path=vision_model_path
)
# 加载训练权重
weight_path = "./out/sft_vlm.pth"
if os.path.exists(weight_path):
    state_dict = torch.load(weight_path, map_location='cpu', weights_only=False)
    model.load_state_dict({k: v for k, v in state_dict.items() if 'mask' not in k}, strict=False)
    print(f"  已加载权重: {weight_path}")
else:
    print(f"  权重不存在: {weight_path}，使用随机初始化")
model = model.float()  # CPU 不支持 fp16，转为 float32
model.eval()
print(f"  模型构建完成，耗时 {time.time()-t0:.1f}s")

# 3. 加载 tokenizer
print("\n[3] 加载 tokenizer...")
tokenizer_path = "./model"
tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, trust_remote_code=True)
print(f"  词表大小: {tokenizer.vocab_size}")

# 4. 找一张测试图片
print("\n[4] 准备测试图片...")
test_images = []
for d in ["./dataset/eval_images", "./images"]:
    if os.path.isdir(d):
        for f in os.listdir(d):
            if f.lower().endswith(('.png', '.jpg', '.jpeg')):
                test_images.append(os.path.join(d, f))

if not test_images:
    # 用项目自带的图片
    for d in ["../inbox"]:
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.lower().endswith(('.png', '.jpg', '.jpeg')):
                    test_images.append(os.path.join(d, f))

if not test_images:
    print("  未找到测试图片")
    exit(1)

print(f"  找到 {len(test_images)} 张图片")
test_img_path = test_images[0]
print(f"  使用: {test_img_path}")
img = Image.open(test_img_path).convert('RGB')
print(f"  图片尺寸: {img.size}")

# 5. 图像预处理
print("\n[5] 图像预处理 + 推理...")
processor = model.processor
pixel_values = {k: v for k, v in MiniMindVLM.image2tensor(img, processor).items()}

# 构造 prompt
prompt = "请描述这张图片的内容，包括主要元素和用途。"
msg_template = model.config.image_special_token * model.config.image_token_len + "\n" + prompt
messages = [{"role": "user", "content": msg_template}]
inputs_text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
inputs = tokenizer(inputs_text, return_tensors="pt", truncation=True)

print(f"  Prompt 长度: {inputs['input_ids'].shape[1]} tokens")

# 6. 推理
print("\n[6] 开始推理...")
t0 = time.time()
with torch.no_grad():
    generated_ids = model.generate(
        inputs=inputs["input_ids"],
        attention_mask=inputs["attention_mask"],
        max_new_tokens=256,
        do_sample=False,  # greedy for speed
        temperature=0.7,
        top_p=0.85,
        pad_token_id=tokenizer.pad_token_id,
        eos_token_id=tokenizer.eos_token_id,
        pixel_values=pixel_values,
    )
elapsed = time.time() - t0

# 解码结果
output_text = tokenizer.decode(generated_ids[0], skip_special_tokens=True)
gen_tokens = len(generated_ids[0]) - inputs["input_ids"].shape[1]
speed = gen_tokens / elapsed if elapsed > 0 else 0

print(f"\n=== 结果 ===")
print(f"生成: {output_text[:300]}")
print(f"\n生成 token 数: {gen_tokens}")
print(f"推理耗时: {elapsed:.2f}s")
print(f"推理速度: {speed:.1f} tokens/s")
print(f"\n=== 评估 ===")
if speed < 1:
    print("CPU 推理太慢，不推荐用于生产环境")
elif speed < 5:
    print("CPU 推理勉强可用，适合低频场景")
else:
    print("CPU 推理速度可接受")
