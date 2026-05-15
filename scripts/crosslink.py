"""
NoteMind 文档双链 — 基于标签/分类/内容相似度建立 Obsidian [[wikilink]] 关联
"""

import os
import re


class DocumentIndex:
    """文档索引，用于计算文档间关联度。"""

    def __init__(self, vault_path: str = None):
        # {note_name: {"path": str, "tags": set, "category": str, "summary": str}}
        self.documents = {}
        self.vault_path = vault_path

    def add(self, note_name: str, path: str, tags: list, category: str, summary: str):
        self.documents[note_name] = {
            "path": path,
            "tags": set(tags) if tags else set(),
            "category": category or "其他",
            "summary": summary or "",
            # 计算 obsidian wikilink：取 vault 内的相对路径（不含 .md 后缀）
            "wikilink": self._compute_wikilink(path, self.vault_path),
        }

    @staticmethod
    def _compute_wikilink(abs_path: str, vault_path: str = None) -> str:
        """从绝对路径计算 Obsidian wikilink。

        优先使用 vault 内相对路径。
        例如: /vault/安全/操作系统安全/2026-05-07-白皮书.md
        → 安全/操作系统安全/2026-05-07-白皮书

        图片文件保留后缀：/vault/安全/photo.jpg → 安全/photo.jpg

        如果 vault_path 未提供，回退到基于已知分类目录的匹配。
        """
        from pathlib import Path
        p = Path(abs_path)
        stem = p.with_suffix("")
        parts = stem.parts

        # 图片文件保留后缀
        image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg"}
        is_image = p.suffix.lower() in image_exts

        # 如果提供了 vault_path，优先使用相对路径
        if vault_path:
            try:
                vault_p = Path(vault_path)
                if is_image:
                    rel = os.path.relpath(str(p), str(vault_p))
                else:
                    rel = os.path.relpath(str(stem), str(vault_p))
                if not rel.startswith(".."):
                    return rel.replace(os.sep, "/")
            except (ValueError, OSError):
                pass

        # 回退：找到第一个已知顶级目录
        known_tops = {"安全", "操作系统", "技术", "个人", "其他"}
        for i, part in enumerate(parts):
            if part in known_tops:
                base = "/".join(parts[i:])
                if is_image:
                    # 补回后缀
                    return base + p.suffix
                return base
        # 兜底：用最后三级
        if is_image:
            return p.name  # 图片直接用文件名
        return "/".join(parts[-3:]) if len(parts) >= 3 else stem.name

    def compute_links(self, max_links: int = 5, min_score: float = 2.0) -> dict[str, list[str]]:
        """为每篇文档计算 Top-K 相关文档。

        评分规则：
        - 共享标签：每个 +3.0
        - 同分类：+1.0
        - 摘要关键词 Jaccard 相似度：+0.5 * jaccard
        """
        results = {}
        doc_names = list(self.documents.keys())

        for i, name_a in enumerate(doc_names):
            doc_a = self.documents[name_a]
            scores = []

            for j, name_b in enumerate(doc_names):
                if i == j:
                    continue
                doc_b = self.documents[name_b]
                score = 0.0

                # 标签重叠（权重 3.0）
                shared_tags = doc_a["tags"] & doc_b["tags"]
                score += len(shared_tags) * 3.0

                # 同分类（权重 1.0）
                if doc_a["category"] == doc_b["category"]:
                    score += 1.0

                # 摘要关键词 Jaccard 相似度（权重 0.5）
                keywords_a = _extract_keywords(doc_a["summary"])
                keywords_b = _extract_keywords(doc_b["summary"])
                if keywords_a and keywords_b:
                    intersection = keywords_a & keywords_b
                    union = keywords_a | keywords_b
                    jaccard = len(intersection) / len(union) if union else 0
                    score += jaccard * 0.5

                if score >= min_score:
                    scores.append((score, name_b))

            scores.sort(key=lambda x: (-x[0], x[1]))
            results[name_a] = [name for _, name in scores[:max_links]]

        return results


def _extract_keywords(text: str) -> set[str]:
    """从摘要中提取 2-4 字中文关键词。"""
    if not text:
        return set()
    return set(re.findall(r'[\u4e00-\u9fff]{2,4}', text))


def apply_crosslinks(vault_path: str, index: DocumentIndex,
                     max_links: int = 5, min_score: float = 2.0) -> int:
    """在 Markdown 文件中写入双链段落。

    Returns:
        更新的文件数
    """
    links = index.compute_links(max_links=max_links, min_score=min_score)
    updated_count = 0

    for note_name, linked_names in links.items():
        doc = index.documents[note_name]
        file_path = doc["path"]
        if not linked_names or not os.path.exists(file_path):
            continue

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 构建相关文档段落（使用完整 wikilink 路径）
        lines = ["\n## 相关文档\n"]
        for linked_name in linked_names:
            linked_doc = index.documents[linked_name]
            wl = linked_doc.get("wikilink", linked_name)
            lines.append(f"- [[{wl}]]\n")
        new_section = "".join(lines)

        # 替换已有相关文档段落，或追加到末尾
        section_pattern = r"\n## 相关文档\n[\s\S]*?(?=\n##|\Z)"
        if re.search(section_pattern, content):
            content = re.sub(section_pattern, new_section, content)
        else:
            # 追加到 footer 之前或文件末尾
            footer_pattern = r"\n> 由 NoteMind 自动生成于"
            if re.search(footer_pattern, content):
                content = re.sub(footer_pattern, new_section + "\n> 由 NoteMind 自动生成于", content)
            else:
                content = content.rstrip() + new_section + "\n"

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        updated_count += 1

    return updated_count
