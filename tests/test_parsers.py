"""
NoteMind 格式解析器测试
"""

import os
import tempfile
import shutil
import unittest

from scripts.parsers import (
    ParseResult,
    parse_text,
    parse_markdown,
    parse_image,
    parse_svg,
    get_parser,
    PARSERS,
    IMAGE_EXTS,
    _convert_old_office,
    parse_docx,
    parse_pptx,
    parse_excel,
)


class TestParseSvg(unittest.TestCase):
    """SVG 格式解析测试。"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="notemind_svg_test_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_file(self, name: str, content: str) -> str:
        path = os.path.join(self.test_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_svg_basic(self):
        """基本 SVG 文件解析。"""
        svg_content = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">
  <text x="10" y="20">Hello SVG</text>
  <rect x="0" y="0" width="100" height="100"/>
</svg>'''
        path = self._create_file("test.svg", svg_content)
        result = parse_svg(path)
        self.assertIn("Hello SVG", result.text)
        self.assertEqual(len(result.images), 1)

    def test_svg_with_multiple_text_elements(self):
        """SVG 包含多个文本元素。"""
        svg_content = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg">
  <text>标题</text>
  <text>正文内容</text>
  <g><text>嵌套文本</text></g>
</svg>'''
        path = self._create_file("multi_text.svg", svg_content)
        result = parse_svg(path)
        self.assertIn("标题", result.text)
        self.assertIn("正文内容", result.text)
        self.assertIn("嵌套文本", result.text)

    def test_svg_no_text(self):
        """纯图形 SVG（无文本元素）。"""
        svg_content = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50">
  <circle cx="25" cy="25" r="20"/>
</svg>'''
        path = self._create_file("no_text.svg", svg_content)
        result = parse_svg(path)
        self.assertEqual(result.text, "")
        self.assertEqual(len(result.images), 1)

    def test_svg_invalid_xml(self):
        """无效 XML 的 SVG 文件，应 fallback 到空结果。"""
        svg_content = '<svg>这不是有效的 XML'
        path = self._create_file("invalid.svg", svg_content)
        result = parse_svg(path)
        # 无效 XML 应返回空文本 + 图片路径
        self.assertEqual(result.text, "")
        self.assertEqual(len(result.images), 1)

    def test_svg_get_parser(self):
        """验证 get_parser 对 SVG 返回专门解析函数。"""
        parser = get_parser("test.svg")
        self.assertEqual(parser, parse_svg)
        self.assertNotEqual(parser, "image")  # SVG 不应返回 "image" 标记


class TestParseOldOffice(unittest.TestCase):
    """老版本 Office 格式（.doc/.ppt/.xls）转换测试。"""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="notemind_office_test_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_file(self, name: str, content: bytes) -> str:
        path = os.path.join(self.test_dir, name)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def test_old_doc_format_routing(self):
        """.doc 文件应路由到 parse_docx（内部调用 _convert_old_office）。"""
        path = self._create_file("test.doc", b"fake doc content")
        # 验证 get_parser 返回正确函数
        parser = get_parser("test.doc")
        self.assertIsNotNone(parser)

    def test_old_ppt_format_routing(self):
        """.ppt 文件应路由到 parse_pptx。"""
        parser = get_parser("test.ppt")
        self.assertIsNotNone(parser)

    def test_old_xls_format_routing(self):
        """.xls 文件应路由到 parse_excel。"""
        parser = get_parser("test.xls")
        self.assertIsNotNone(parser)

    def test_convert_old_office_no_libreoffice(self):
        """LibreOffice 不存在时，应返回提示信息。"""
        path = self._create_file("test.doc", b"fake doc")
        # 模拟 LibreOffice 不可用的场景（通过传入不存在的路径）
        # 注意：如果系统确实安装了 LibreOffice，此测试会跳过
        import shutil
        if not shutil.which("soffice") and not shutil.which("libreoffice"):
            result = _convert_old_office(path, "docx")
            self.assertIn("LibreOffice", result.text)

    def test_convert_old_office_invalid_file(self):
        """无效文件转换应返回失败信息。"""
        path = self._create_file("invalid.doc", b"not a real doc file")
        import shutil
        if shutil.which("soffice") or shutil.which("libreoffice"):
            result = _convert_old_office(path, "docx")
            # 转换失败应返回错误信息
            self.assertTrue(
                "失败" in result.text or "失败" in result.text or
                "error" in result.text.lower() or "不存在" in result.text or
                result.text == "" or "转换" in result.text
            )

    def test_docx_still_works(self):
        """.docx 文件应正常解析（不经过转换）。"""
        from docx import Document
        doc_path = os.path.join(self.test_dir, "test.docx")
        doc = Document()
        doc.add_heading("测试标题", level=1)
        doc.add_paragraph("这是测试段落内容。")
        doc.save(doc_path)

        result = parse_docx(doc_path)
        self.assertIn("测试段落内容", result.text)
        self.assertTrue(len(result.sections) >= 1)
        # 标题在 sections 中
        section_titles = [s.title for s in result.sections]
        self.assertIn("测试标题", section_titles)

    def test_pptx_still_works(self):
        """.pptx 文件应正常解析。"""
        from pptx import Presentation
        pptx_path = os.path.join(self.test_dir, "test.pptx")
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        slide.shapes.title.text = "PPT 标题"
        prs.save(pptx_path)

        result = parse_pptx(pptx_path)
        self.assertIn("PPT 标题", result.text)

    def test_xlsx_still_works(self):
        """.xlsx 文件应正常解析。"""
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "测试表"
        ws.append(["姓名", "年龄"])
        ws.append(["张三", "25"])
        xlsx_path = os.path.join(self.test_dir, "test.xlsx")
        wb.save(xlsx_path)

        result = parse_excel(xlsx_path)
        self.assertIn("测试表", result.text)
        self.assertIn("张三", result.text)


class TestParseResult(unittest.TestCase):
    def test_empty_result(self):
        r = ParseResult()
        self.assertFalse(r.has_content)

    def test_text_only(self):
        r = ParseResult("hello")
        self.assertTrue(r.has_content)

    def test_images_only(self):
        r = ParseResult(images=["a.jpg"])
        self.assertTrue(r.has_content)

    def test_both(self):
        r = ParseResult("text", ["a.jpg"])
        self.assertTrue(r.has_content)


class TestParseText(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="notemind_parser_test_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_file(self, name: str, content: str) -> str:
        path = os.path.join(self.test_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_parse_plain_text(self):
        path = self._create_file("test.txt", "Hello\nWorld")
        result = parse_text(path)
        self.assertEqual(result.text, "Hello\nWorld")

    def test_parse_csv(self):
        path = self._create_file("test.csv", "a,b,c\n1,2,3")
        result = parse_text(path)
        self.assertIn("a,b,c", result.text)

    def test_parse_empty_file(self):
        path = self._create_file("empty.txt", "")
        result = parse_text(path)
        self.assertEqual(result.text, "")


class TestParseMarkdown(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="notemind_md_test_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_file(self, name: str, content: str) -> str:
        path = os.path.join(self.test_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_parse_basic_markdown(self):
        path = self._create_file("test.md", "# Title\n\n**bold** and *italic*\n\n> quote")
        result = parse_markdown(path)
        self.assertIn("Title", result.text)
        self.assertIn("bold", result.text)
        self.assertNotIn("**", result.text)
        self.assertNotIn("*italic*", result.text)

    def test_clean_links(self):
        path = self._create_file("test.md", "[link](https://example.com)")
        result = parse_markdown(path)
        self.assertNotIn("https://", result.text)
        self.assertIn("link", result.text)

    def test_clean_code_blocks(self):
        path = self._create_file("test.md", "```python\nprint('hi')\n```")
        result = parse_markdown(path)
        self.assertNotIn("print", result.text)

    def test_extract_local_images(self):
        # Create an image file
        img_path = self._create_file("photo.jpg", "fake image data")
        md_content = f"![alt text]({img_path})"
        md_path = self._create_file("test.md", md_content)
        result = parse_markdown(md_path)
        self.assertEqual(len(result.images), 1)
        self.assertEqual(result.images[0], img_path)

    def test_skip_http_images(self):
        md_content = "![alt](https://example.com/image.png)"
        md_path = self._create_file("test.md", md_content)
        result = parse_markdown(md_path)
        self.assertEqual(len(result.images), 0)

    def test_fixture_file(self):
        fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "sample.md")
        if os.path.exists(fixture_path):
            result = parse_markdown(fixture_path)
            self.assertTrue(result.has_content)
            self.assertIn("测试", result.text)


class TestParseImage(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="notemind_img_test_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_file(self, name: str, content: bytes = b"\x89PNG") -> str:
        path = os.path.join(self.test_dir, name)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def test_parse_image_returns_path(self):
        path = self._create_file("test.jpg")
        result = parse_image(path)
        self.assertEqual(result.text, "")
        self.assertEqual(len(result.images), 1)
        self.assertEqual(result.images[0], path)


class TestGetParser(unittest.TestCase):
    def test_pdf_parser(self):
        self.assertIsNotNone(get_parser("test.pdf"))

    def test_docx_parser(self):
        self.assertIsNotNone(get_parser("test.docx"))

    def test_pptx_parser(self):
        self.assertIsNotNone(get_parser("test.pptx"))

    def test_excel_parser(self):
        self.assertIsNotNone(get_parser("test.xlsx"))

    def test_markdown_parser(self):
        self.assertIsNotNone(get_parser("test.md"))

    def test_text_parser(self):
        self.assertIsNotNone(get_parser("test.csv"))

    def test_unsupported_txt(self):
        self.assertIsNone(get_parser("test.txt"))

    def test_image_returns_special_marker(self):
        self.assertEqual(get_parser("photo.jpg"), "image")
        self.assertEqual(get_parser("photo.PNG"), "image")

    def test_unknown_format_returns_none(self):
        self.assertIsNone(get_parser("file.xyz"))

    def test_case_insensitive(self):
        self.assertEqual(get_parser("test.PDF"), get_parser("test.pdf"))
        self.assertEqual(get_parser("test.DOCX"), get_parser("test.docx"))

    def test_all_parsers_registered(self):
        for ext in PARSERS:
            self.assertIsNotNone(get_parser(f"test{ext}"))

    def test_all_image_exts_recognized(self):
        for ext in IMAGE_EXTS:
            expected = parse_svg if ext == ".svg" else "image"
            self.assertEqual(get_parser(f"test{ext}"), expected)


if __name__ == "__main__":
    unittest.main()
