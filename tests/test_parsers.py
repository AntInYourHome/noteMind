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
    get_parser,
    PARSERS,
    IMAGE_EXTS,
)


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
        self.assertIsNotNone(get_parser("test.txt"))

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
            self.assertEqual(get_parser(f"test{ext}"), "image")


if __name__ == "__main__":
    unittest.main()
