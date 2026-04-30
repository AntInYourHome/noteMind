"""
NoteMind 去重模块测试
"""

import json
import os
import shutil
import tempfile
import unittest

from scripts.dedup import (
    compute_md5,
    load_dedup_index,
    save_dedup_index,
    check_duplicate,
    add_to_index,
)


class TestDedup(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="notemind_dedup_test_")
        self.vault = os.path.join(self.test_dir, "vault")
        os.makedirs(self.vault)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_file(self, name: str, content: str) -> str:
        path = os.path.join(self.test_dir, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_compute_md5(self):
        path = self._create_file("test.txt", "hello world")
        md5 = compute_md5(path)
        self.assertEqual(len(md5), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in md5))

    def test_compute_md5_same_content(self):
        path1 = self._create_file("a.txt", "same content")
        path2 = self._create_file("b.txt", "same content")
        self.assertEqual(compute_md5(path1), compute_md5(path2))

    def test_compute_md5_different_content(self):
        path1 = self._create_file("a.txt", "content A")
        path2 = self._create_file("b.txt", "content B")
        self.assertNotEqual(compute_md5(path1), compute_md5(path2))

    def test_load_empty_index(self):
        index = load_dedup_index(self.vault, ".test_index.json")
        self.assertEqual(index, {})

    def test_save_load_index(self):
        test_data = {
            "abc123": {"filename": "test.pdf", "category": "项目", "note_path": "项目/test.md"},
        }
        save_dedup_index(self.vault, ".test_index.json", test_data)
        loaded = load_dedup_index(self.vault, ".test_index.json")
        self.assertEqual(test_data, loaded)

    def test_check_duplicate_not_exists(self):
        path = self._create_file("new.txt", "new content")
        result = check_duplicate(path, self.vault, ".test_index.json")
        self.assertIsNone(result)

    def test_check_duplicate_exists(self):
        path = self._create_file("test.txt", "dup content")
        md5 = compute_md5(path)
        save_dedup_index(self.vault, ".test_index.json", {
            md5: {"filename": "test.txt", "category": "笔记", "note_path": "笔记/test.md"},
        })
        result = check_duplicate(path, self.vault, ".test_index.json")
        self.assertIsNotNone(result)
        self.assertEqual(result["category"], "笔记")

    def test_add_to_index(self):
        path = self._create_file("test.txt", "index test")
        md5 = compute_md5(path)
        add_to_index(path, md5, "安全", "安全/test.md", self.vault, ".test_index.json")
        loaded = load_dedup_index(self.vault, ".test_index.json")
        self.assertIn(md5, loaded)
        self.assertEqual(loaded[md5]["category"], "安全")


if __name__ == "__main__":
    unittest.main()
