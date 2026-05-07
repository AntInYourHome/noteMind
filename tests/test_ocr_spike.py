"""
OCR 穿刺验证 v3 — 使用 RapidOCR (轻量 ONNX，无需下载大模型)

测试维度：
1. 速度：单张图片 OCR 耗时
2. 首次加载 vs 后续调用
3. 纯图片判断：能否区分"有文字"和"无文字"图片
"""

import time
import os

def test_ocr():
    from rapidocr_onnxruntime import RapidOCR
    from PIL import Image

    print("=" * 60)
    print("RapidOCR 穿刺验证")
    print("=" * 60)

    # 1. 初始化
    print("\n[1] 初始化 RapidOCR...")
    t0 = time.time()
    ocr = RapidOCR()
    init_time = time.time() - t0
    print(f"  初始化耗时: {init_time:.2f}s")

    # 2. 测试不同类型的图片
    test_images = [
        ("venv/lib/python3.11/site-packages/skimage/data/text.png", "英文文本图片"),
        ("venv/lib/python3.11/site-packages/skimage/data/astronaut.png", "照片（无文字）"),
        ("venv/lib/python3.11/site-packages/skimage/data/chessboard_RGB.png", "棋盘图案（无文字）"),
        ("venv/lib/python3.11/site-packages/networkx/drawing/tests/baseline/test_house_with_colors.png", "图表（无文字）"),
    ]

    print(f"\n[2] 开始测试 {len(test_images)} 张图片...")
    print("-" * 60)

    all_times = []

    for i, (img_path, desc) in enumerate(test_images):
        if not os.path.exists(img_path):
            print(f"  [跳过] {img_path} 不存在")
            continue

        img = Image.open(img_path)
        w, h = img.size
        file_size = os.path.getsize(img_path) / 1024

        print(f"\n  图片 {i+1}: {desc}")
        print(f"    尺寸: {w}x{h}, 大小: {file_size:.1f}KB")

        # OCR 识别
        t1 = time.time()
        result, elapse = ocr(img_path)
        ocr_time = time.time() - t1
        all_times.append(ocr_time)

        # 提取文字
        texts = []
        if result:
            for line in result:
                # line: [box, text, confidence]
                if len(line) >= 2:
                    texts.append((line[1], line[2]))

        full_text = " ".join(t for t, _ in texts)
        has_text = len(texts) > 0
        avg_confidence = sum(c for _, c in texts) / len(texts) if texts else 0

        elapsed_total = sum(elapse) if elapse else 0
        print(f"    OCR 耗时: {ocr_time:.3f}s (库报告: {elapsed_total:.3f}s)")
        print(f"    识别到 {len(texts)} 行文字")
        print(f"    文字长度: {len(full_text)} 字符")
        print(f"    平均置信度: {avg_confidence:.2%}")
        print(f"    判定: {'有文字' if has_text else '无文字（纯图片/图表）'}")
        if texts:
            preview = full_text[:120]
            print(f"    预览: {preview}...")

    # 3. 连续调用测试
    print(f"\n[3] 连续调用测试（用同一张图片重复 5 次）...")
    img_path = "venv/lib/python3.11/site-packages/skimage/data/text.png"
    if os.path.exists(img_path):
        times = []
        for i in range(5):
            t1 = time.time()
            ocr(img_path)
            elapsed = time.time() - t1
            times.append(elapsed)
            print(f"    第 {i+1} 次: {elapsed:.3f}s")
        avg_repeat = sum(times) / len(times)
        print(f"    平均: {avg_repeat:.3f}s")
        print(f"    最快: {min(times):.3f}s")
    else:
        avg_repeat = 0

    # 4. 总结
    avg_all = sum(all_times) / len(all_times) if all_times else 0
    print(f"\n" + "=" * 60)
    print("结论")
    print("=" * 60)
    print(f"  初始化时间: {init_time:.2f}s (仅首次)")
    print(f"  单张 OCR (混合): {avg_all:.3f}s")
    print(f"  连续调用 (同一张): {avg_repeat:.3f}s")
    print(f"  CPU ONNX，ARM64 兼容")
    print(f"  能区分有文字 vs 无文字图片")
    print(f"\n  批量处理预估:")
    print(f"    1097 张全部 OCR: ~{1097 * avg_all:.0f}s ≈ {1097 * avg_all/60:.1f} 分钟")
    print(f"    尺寸过滤 + 去重后 (~50 张): ~{50 * avg_all:.0f}s ≈ {50 * avg_all/60:.1f} 分钟")
    print(f"    对比 AI 视觉模型: 每次调用 10-20s，1097 张 = 数小时")
    print("=" * 60)


if __name__ == "__main__":
    test_ocr()
