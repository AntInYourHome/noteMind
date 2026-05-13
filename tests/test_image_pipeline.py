"""
图片处理链路验证测试

验证两个核心场景：
1. 纯图片文件：OCR + VLM 组合 → LLM 生成标签
2. 文档内嵌图片：OCR + VLM 组合 → 混入章节文本 → LLM 生成摘要
"""

import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

import pytest

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts.analyzer import (
    _describe_image,
    AnalysisResult,
    AnalysisContext,
    LongDocStrategy,
    ShortDocStrategy,
    chunk_sections,
)


# ── 场景 1: 纯图片文件 ──────────────────────────────────────

class TestDescribeImage:
    """验证 _describe_image 的 OCR + VLM 组合行为。"""

    def test_ocr_only_vlm_fails(self):
        """当有 OCR 文字但 VLM 不可用时，应返回 OCR 文字。"""
        with patch('scripts.ai_client.analyze_image') as mock_vlm:
            mock_vlm.side_effect = ValueError("VLM 不可用")
            result = _describe_image("/fake/path.jpg", ocr_text="图片中的文字")
            assert result == "图片中的文字"

    def test_vlm_only_no_ocr(self):
        """当无 OCR 文字但 VLM 可用时，应返回 VLM 描述。"""
        with patch('scripts.ai_client.analyze_image') as mock_vlm:
            mock_vlm.return_value = "类型：架构图\n主体：三层架构\n文字：无\n场景：系统设计"
            result = _describe_image("/fake/path.jpg", ocr_text="")
            assert "架构图" in result
            assert "三层架构" in result

    def test_ocr_and_vlm_combined(self):
        """当 OCR 和 VLM 都有内容时，应组合输出。"""
        with patch('scripts.ai_client.analyze_image') as mock_vlm:
            mock_vlm.return_value = "类型：截图\n主体：错误提示框"
            result = _describe_image("/fake/path.jpg", ocr_text="Error: Connection refused")
            # 应包含 OCR 和 VLM 两部分
            assert "Error: Connection refused" in result
            assert "截图" in result
            assert "错误提示框" in result

    def test_neither_ocr_nor_vlm_raises(self):
        """当 OCR 和 VLM 都无内容时，应抛出异常。"""
        with patch('scripts.ai_client.analyze_image') as mock_vlm:
            mock_vlm.side_effect = ValueError("VLM 不可用")
            with pytest.raises(ValueError, match="VLM 不可用"):
                _describe_image("/fake/path.jpg", ocr_text="")

    def test_empty_ocr_skipped(self):
        """空 OCR 文字应被跳过。"""
        with patch('scripts.ai_client.analyze_image') as mock_vlm:
            mock_vlm.return_value = "类型：照片"
            result = _describe_image("/fake/path.jpg", ocr_text="   ")
            assert result == "类型：照片"

    def test_whitespace_only_ocr_skipped(self):
        """纯空白 OCR 文字应被跳过。"""
        with patch('scripts.ai_client.analyze_image') as mock_vlm:
            mock_vlm.return_value = "类型：图表"
            result = _describe_image("/fake/path.jpg", ocr_text="\n  ")
            assert result == "类型：图表"


# ── 场景 2: 文档内嵌图片 ────────────────────────────────────

class TestImageContextInjection:
    """验证图片上下文混入章节文本的行为。"""

    def test_build_image_context_combines_all_images(self):
        """_build_image_context 应组合所有图片的 OCR+VLM 描述。"""
        strategy = LongDocStrategy()
        images = ["/img1.jpg", "/img2.png"]
        ocr_texts = ["OCR 文字 1", "OCR 文字 2"]

        with patch('scripts.ai_client.analyze_image') as mock_vlm:
            mock_vlm.side_effect = ["VLM 描述 1", "VLM 描述 2"]
            context = strategy._build_image_context(images, ocr_texts)

            assert "[图片1]" in context
            assert "[图片2]" in context
            assert "OCR 文字 1" in context
            assert "VLM 描述 1" in context
            assert "OCR 文字 2" in context
            assert "VLM 描述 2" in context

    def test_build_image_context_skips_failed_images(self):
        """_build_image_context 应跳过无法描述的图片。"""
        strategy = LongDocStrategy()
        images = ["/img1.jpg", "/img2.png"]
        ocr_texts = ["OCR 文字 1", ""]

        with patch('scripts.ai_client.analyze_image') as mock_vlm:
            mock_vlm.side_effect = [ValueError("VLM 失败"), "VLM 描述 2"]
            context = strategy._build_image_context(images, ocr_texts)

            # img1 有 OCR，应包含
            assert "OCR 文字 1" in context
            # img2 有 VLM，应包含
            assert "VLM 描述 2" in context

    def test_chunked_analysis_enriches_text_with_image_context(self):
        """_analyze_chunked 应将图片上下文混入章节文本后调用 LLM。"""
        strategy = LongDocStrategy()

        sections = [
            MagicMock(title="第 1 页", text="第 1 页内容"),
            MagicMock(title="第 2 页", text="第 2 页内容"),
            MagicMock(title="第 3 页", text="第 3 页内容"),
        ]
        images = ["/img1.jpg"]
        ocr_texts = ["图片 OCR 文字"]

        result = AnalysisResult()
        captured_summary_input = []

        def mock_generate_summary(text):
            captured_summary_input.append(text)
            return "AI 摘要"

        # _describe_image 内部 late import analyze_image，所以 patch ai_client 路径
        with patch('scripts.ai_client.analyze_image') as mock_vlm, \
             patch('scripts.analyzer.generate_summary', side_effect=mock_generate_summary), \
             patch('scripts.analyzer.generate_tags', return_value=[]):
            mock_vlm.return_value = "VLM 描述"
            strategy._analyze_chunked(sections, images, callback=None, chunk_size=3,
                                      result=result, image_ocr_texts=ocr_texts)

        # 验证 LLM 摘要的输入包含了图片上下文
        assert len(captured_summary_input) == 1
        summary_text = captured_summary_input[0]
        assert "第 1 页内容" in summary_text
        assert "第 2 页内容" in summary_text
        assert "第 3 页内容" in summary_text
        assert "[文档图片]" in summary_text
        assert "图片 OCR 文字" in summary_text
        assert "VLM 描述" in summary_text

    def test_concurrent_analysis_enriches_text_with_image_context(self):
        """_analyze_concurrent 应将图片上下文混入章节文本后调用 LLM。"""
        strategy = LongDocStrategy()

        sections = [
            MagicMock(title="第 1 页", text="第 1 页内容"),
            MagicMock(title="第 2 页", text="第 2 页内容"),
        ]
        images = ["/img1.jpg"]
        ocr_texts = ["图片 OCR 文字"]

        result = AnalysisResult()

        with patch('scripts.ai_client.analyze_image') as mock_vlm, \
             patch('scripts.analyzer.generate_summary', return_value="AI 摘要"), \
             patch('scripts.analyzer.generate_tags', return_value=[]):
            mock_vlm.return_value = "VLM 描述"
            strategy._analyze_concurrent(sections, images, max_workers=2, result=result,
                                         callback=None, image_ocr_texts=ocr_texts)

        # 验证图片描述被正确处理
        assert len(result.image_descriptions) == 1
        desc = result.image_descriptions[0]
        assert "图片 OCR 文字" in desc
        assert "VLM 描述" in desc

        # 验证章节被处理
        assert len(result.sections) == 2

    def test_concurrent_analysis_no_images(self):
        """无图片时，_analyze_concurrent 不应包含 [文档图片] 标记。"""
        strategy = LongDocStrategy()

        sections = [
            MagicMock(title="第 1 页", text="第 1 页内容"),
        ]
        result = AnalysisResult()
        captured_summary_input = []

        def mock_generate_summary(text):
            captured_summary_input.append(text)
            return "AI 摘要"

        with patch('scripts.analyzer.generate_summary', side_effect=mock_generate_summary), \
             patch('scripts.analyzer.generate_tags', return_value=[]):
            strategy._analyze_concurrent(sections, [], max_workers=2, result=result,
                                         callback=None, image_ocr_texts=None)

        assert len(captured_summary_input) == 1
        assert "[文档图片]" not in captured_summary_input[0]


# ── 场景 3: 端到端（mock LLM + VLM）──────────────────────────

class TestEndToEnd:
    """端到端测试：完整分析链路。"""

    def test_short_doc_with_images(self):
        """短文档 + 图片：图片描述应混入 image_descriptions，摘要应正常生成。"""
        ctx = AnalysisContext()
        result = ctx.analyze(
            text="这是一段短文本",
            images=["/img1.jpg"],
            sections=[],
            max_workers=1,
            chunk_size=1,
            image_ocr_texts=["OCR 文字"]
        )

        # 短文档走 ShortDocStrategy
        assert len(result.image_descriptions) == 1
        desc = result.image_descriptions[0]
        assert "OCR 文字" in desc

    def test_long_doc_with_images_and_chunking(self):
        """长文档 + 图片 + chunk_size > 1：图片上下文应混入摘要。"""
        ctx = AnalysisContext()
        sections = [
            MagicMock(title="章节 1", text="章节 1 内容" * 100),  # 300 字
            MagicMock(title="章节 2", text="章节 2 内容" * 100),
            MagicMock(title="章节 3", text="章节 3 内容" * 100),
        ]
        images = ["/img1.jpg", "/img2.png"]
        ocr_texts = ["图片 1 OCR", "图片 2 OCR"]

        captured_inputs = []

        def mock_generate_summary(text):
            captured_inputs.append(text)
            return "摘要"

        with patch('scripts.ai_client.analyze_image') as mock_vlm, \
             patch('scripts.analyzer.generate_summary', side_effect=mock_generate_summary), \
             patch('scripts.analyzer.generate_tags', return_value=["标签1", "标签2"]):
            mock_vlm.side_effect = ["VLM 1", "VLM 2"]

            result = ctx.analyze(
                text="全文",
                images=images,
                sections=sections,
                max_workers=5,
                chunk_size=3,  # 触发 chunked 路径
                image_ocr_texts=ocr_texts
            )

        # 验证图片描述包含 OCR
        assert len(result.image_descriptions) == 2
        assert "图片 1 OCR" in result.image_descriptions[0]
        assert "图片 2 OCR" in result.image_descriptions[1]

        # 验证 LLM 摘要输入包含图片上下文
        for inp in captured_inputs:
            assert "[文档图片]" in inp
            assert "图片 1 OCR" in inp

    def test_image_limited_count(self):
        """超过 MAX_VLM_IMAGES 的图片，超出部分只使用 OCR。"""
        ctx = AnalysisContext()
        # 创建 15 张图片，超出 MAX_VLM_IMAGES=10
        images = [f"/img{i}.jpg" for i in range(15)]
        ocr_texts = [f"OCR {i}" for i in range(15)]
        sections = []

        vlm_calls = []

        def mock_analyze_image(path):
            vlm_calls.append(path)
            return f"VLM for {path}"

        with patch('scripts.analyzer.analyze_image', side_effect=mock_analyze_image), \
             patch('scripts.analyzer.generate_summary', return_value="摘要"), \
             patch('scripts.analyzer.generate_tags', return_value=["标签1"]):
            result = ctx.analyze(
                text="文本" * 100,  # 触发短文档策略
                images=images,
                sections=sections,
                max_workers=1,
                chunk_size=1,
                image_ocr_texts=ocr_texts
            )

        # VLM 调用不应超过 MAX_VLM_IMAGES
        assert len(vlm_calls) <= ctx.MAX_VLM_IMAGES

        # 但 image_descriptions 应包含所有有 OCR 的图片
        assert len(result.image_descriptions) == 15
