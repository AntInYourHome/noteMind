"""
真实 PDF 图片 OCR 验证 — 从 HarmonyOS 白皮书提取图片并测试

目标：
1. 从真实 PDF 提取图片
2. 统计图片尺寸分布、大小分布
3. 测试 RapidOCR 中文识别准确度
4. 验证分层过滤策略的实际效果
"""

import time
import os
import fitz  # PyMuPDF
from PIL import Image
from rapidocr_onnxruntime import RapidOCR
from collections import Counter

PDF_PATH = "HarmonyOS+6.0安全技术白皮书.pdf"
OUTPUT_DIR = "/tmp/notemind_ocr_test"

def extract_images_from_pdf():
    """从 PDF 提取图片，按页保存"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    doc = fitz.open(PDF_PATH)
    print(f"PDF 总页数: {len(doc)}")

    image_info = []

    for page_idx in range(min(len(doc), 10)):  # 先测前 10 页
        page = doc[page_idx]
        images = page.get_images(full=True)
        print(f"  第 {page_idx+1} 页: {len(images)} 张图片")

        for img_idx, img in enumerate(images):
            xref = img[0]
            base_image = doc.extract_image(xref)
            if not base_image:
                continue

            image_bytes = base_image["image"]
            image_ext = base_image["ext"]
            image_w = base_image["width"]
            image_h = base_image["height"]

            fname = f"page{page_idx+1}_img{img_idx}.{image_ext}"
            fpath = os.path.join(OUTPUT_DIR, fname)

            with open(fpath, "wb") as f:
                f.write(image_bytes)

            image_info.append({
                "path": fpath,
                "page": page_idx + 1,
                "width": image_w,
                "height": image_h,
                "size_kb": len(image_bytes) / 1024,
                "ext": image_ext,
            })

    doc.close()
    print(f"\n共提取 {len(image_info)} 张图片（前 10 页）")
    return image_info


def analyze_images(image_info):
    """分析图片尺寸/大小分布"""
    print("\n" + "=" * 60)
    print("图片分布分析")
    print("=" * 60)

    sizes = [info["size_kb"] for info in image_info]
    widths = [info["width"] for info in image_info]
    heights = [info["height"] for info in image_info]

    print(f"\n文件大小:")
    print(f"  最小: {min(sizes):.1f}KB")
    print(f"  最大: {max(sizes):.1f}KB")
    print(f"  平均: {sum(sizes)/len(sizes):.1f}KB")
    print(f"  < 10KB: {sum(1 for s in sizes if s < 10)} 张")
    print(f"  < 50KB: {sum(1 for s in sizes if s < 50)} 张")

    print(f"\n尺寸分布:")
    print(f"  最小: {min(widths)}x{min(heights)}")
    print(f"  最大: {max(widths)}x{max(heights)}")

    # 尺寸分段
    tiny = sum(1 for w in widths if w < 50)
    small = sum(1 for w in widths if 50 <= w < 200)
    medium = sum(1 for w in widths if 200 <= w < 800)
    large = sum(1 for w in widths if w >= 800)
    print(f"  < 50px: {tiny} 张 (图标/装饰)")
    print(f"  50-200px: {small} 张")
    print(f"  200-800px: {medium} 张")
    print(f"  >= 800px: {large} 张 (大图)")


def test_ocr_on_images(image_info):
    """在真实图片上测试 OCR"""
    ocr = RapidOCR()

    print(f"\n" + "=" * 60)
    print(f"RapidOCR 测试 ({len(image_info)} 张)")
    print("=" * 60)

    results = []
    total_ocr_time = 0

    for info in image_info:
        path = info["path"]

        t0 = time.time()
        result, elapse = ocr(path)
        elapsed = time.time() - t0
        total_ocr_time += elapsed

        texts = []
        if result:
            for line in result:
                if len(line) >= 2:
                    texts.append(line[1])

        full_text = " ".join(texts)
        has_text = len(texts) > 0

        results.append({
            "path": path,
            "page": info["page"],
            "size": f"{info['width']}x{info['height']} ({info['size_kb']:.0f}KB)",
            "ocr_time": elapsed,
            "has_text": has_text,
            "text_len": len(full_text),
            "text_preview": full_text[:80] if full_text else "(无文字)",
        })

    # 汇总
    has_text_count = sum(1 for r in results if r["has_text"])
    no_text_count = len(results) - has_text_count
    total_text_len = sum(r["text_len"] for r in results)

    print(f"\nOCR 结果汇总:")
    print(f"  有文字: {has_text_count} 张")
    print(f"  无文字: {no_text_count} 张")
    print(f"  总文字量: {total_text_len} 字符")
    print(f"  OCR 总耗时: {total_ocr_time:.2f}s")
    print(f"  平均单张: {total_ocr_time/len(results):.3f}s")

    # 分层过滤模拟
    print(f"\n分层过滤模拟:")

    # 第1层：尺寸过滤 (<50px 跳过)
    layer1_skip = sum(1 for info in image_info if info["width"] < 50)
    layer1_keep = len(image_info) - layer1_skip
    print(f"  层1 尺寸过滤(<50px): 跳过 {layer1_skip} 张, 剩余 {layer1_keep} 张")

    # 第2层：大小过滤 (<10KB 跳过)
    layer2_skip = sum(1 for info in image_info if info["size_kb"] < 10 and info["width"] >= 50)
    layer2_keep = layer1_keep - layer2_skip
    print(f"  层2 大小过滤(<10KB): 跳过 {layer2_skip} 张, 剩余 {layer2_keep} 张")

    # 第3层：OCR 文字检测
    ocr_text = has_text_count
    ocr_no_text = no_text_count
    print(f"  层3 OCR文字检测: {ocr_text} 张有文字, {ocr_no_text} 张无文字")

    # 最终：有文字的图片才进入 AI 分析
    print(f"\n  → 最终需要 AI 分析的: {ocr_text} 张 (OCR 提取文字后送文本模型)")
    print(f"  → 跳过纯图片: {ocr_no_text} 张")

    # 逐张详细结果
    print(f"\n逐张结果:")
    print("-" * 60)
    for r in results:
        tag = "有文字" if r["has_text"] else "无文字"
        print(f"  P{r['page']:2d} {r['size']:>20s} | {tag} | {r['text_len']:4d}字 | "
              f"{r['ocr_time']:.3f}s | {r['text_preview']}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    print("=" * 60)
    print("真实 PDF 图片 OCR 验证")
    print(f"文件: {PDF_PATH}")
    print("=" * 60)

    image_info = extract_images_from_pdf()
    analyze_images(image_info)
    test_ocr_on_images(image_info)

    print("\n清理: rm -rf", OUTPUT_DIR)
