"""
NoteMind 去重模块 — 基于 MD5 的文件去重防呆
"""

import hashlib
import json
import os
from pathlib import Path


def compute_md5(file_path: str, chunk_size: int = 8192) -> str:
    """计算文件的 MD5 值。"""
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            md5.update(chunk)
    return md5.hexdigest()


def load_dedup_index(vault_path: str, index_name: str) -> dict:
    """加载去重索引 {md5: {filename, date, category, note_path}}。"""
    index_file = os.path.join(vault_path, index_name)
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_dedup_index(vault_path: str, index_name: str, index: dict) -> None:
    """保存去重索引。"""
    index_file = os.path.join(vault_path, index_name)
    os.makedirs(os.path.dirname(index_file), exist_ok=True)
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def check_duplicate(file_path: str, vault_path: str, index_name: str) -> dict | None:
    """
    检查文件是否已处理过。
    返回 None 表示不重复；返回 dict 表示已处理的记录。
    """
    md5 = compute_md5(file_path)
    index = load_dedup_index(vault_path, index_name)
    return index.get(md5, None)


def add_to_index(file_path: str, md5: str, category: str, note_path: str, vault_path: str, index_name: str) -> None:
    """将新处理的文件加入索引。"""
    index = load_dedup_index(vault_path, index_name)
    index[md5] = {
        "filename": os.path.basename(file_path),
        "category": category,
        "note_path": note_path,
    }
    save_dedup_index(vault_path, index_name, index)
