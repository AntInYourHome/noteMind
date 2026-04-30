"""
NoteMind Markdown 构建器 — 将分析结果格式化为 Obsidian Markdown
建造者模式：逐步构建最终文档
"""

from datetime import datetime
from pathlib import Path


class MarkdownBuilder:
    """构建 Obsidian 格式的 Markdown 文档。"""

    def __init__(self, source_name: str, date_str: str = None):
        self.source_name = source_name
        self.date_str = date_str or datetime.now().strftime("%Y-%m-%d")
        self.parts = []

    def add_frontmatter(self, category: str, tags: list[str]) -> "MarkdownBuilder":
        """添加 YAML frontmatter。"""
        self._category = category
        self._tags = tags
        tags_str = ", ".join(tags)
        self.parts.append(f"""---
source: {self.source_name}
date: {self.date_str}
category: {category}
tags: [{tags_str}]
---
""")
        return self

    def add_title(self) -> "MarkdownBuilder":
        """添加标题。"""
        title = Path(self.source_name).stem
        self.parts.append(f"# {title}\n")
        return self

    def add_file_summary(self, summary: str) -> "MarkdownBuilder":
        """添加文件级摘要（短文档用）。"""
        self._summary = summary
        if summary:
            self.parts.append("## AI 摘要\n")
            self.parts.append(f"{summary}\n")
        return self

    def add_sections(self, section_results: list) -> "MarkdownBuilder":
        """添加章节内容（长文档逐章输出）。"""
        if not section_results:
            return self

        self.parts.append("## 内容\n")

        for sr in section_results:
            # 章节标题
            if sr.get("title"):
                self.parts.append(f"### {sr['title']}\n")

            # 章节摘要
            if sr.get("summary") and sr.get("title"):
                self.parts.append(f"**摘要**: {sr['summary']}\n\n")

            # 章节正文
            if sr.get("text") and sr.get("title"):
                self.parts.append(f"{sr['text']}\n\n")

        return self

    def add_images(self, vault_image_paths: list[str], image_descriptions: list[str]) -> "MarkdownBuilder":
        """添加图片及 AI 描述。"""
        for img_path, desc in zip(vault_image_paths, image_descriptions):
            self.parts.append(f"![[{img_path}]]\n")
            self.parts.append(f"> **AI 图片描述**: {desc}\n\n")
        return self

    def add_tags_section(self, tags: list[str]) -> "MarkdownBuilder":
        """添加标签区域。"""
        if tags:
            tags_display = ", ".join([f"`#{t}`" for t in tags])
            self.parts.append("## 标签\n")
            self.parts.append(f"{tags_display}\n")
        return self

    def add_footer(self) -> "MarkdownBuilder":
        """添加页脚。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.parts.append(f"\n> 由 NoteMind 自动生成于 {now}\n")
        return self

    def build(self) -> str:
        """返回最终 Markdown 字符串。"""
        return "\n".join(self.parts)

    def build_index(self, section_links: list[tuple[str, str]]) -> str:
        """构建索引文件（主文档：仅摘要 + 章节链接）。

        Args:
            section_links: [(章节文件名（不含.md）, 章节标题), ...]
        """
        parts = []
        # frontmatter
        tags_str = ", ".join(self._tags if hasattr(self, '_tags') else [])
        parts.append(f"""---
source: {self.source_name}
date: {self.date_str}
category: {self._category if hasattr(self, '_category') else "其他"}
tags: [{tags_str}]
doc_type: index
sections: {len(section_links)}
---
""")
        # 标题
        title = Path(self.source_name).stem
        parts.append(f"# {title}\n")
        # 全文摘要（第一个 section 的 summary）
        if hasattr(self, '_summary') and self._summary:
            parts.append("## 文件摘要\n")
            parts.append(f"{self._summary}\n\n")
        # 章节目录（双向链接）
        parts.append("## 目录\n")
        for link_name, section_title in section_links:
            parts.append(f"- [[{link_name}]] {section_title}\n")
        # 页脚
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        parts.append(f"\n---\n> 由 NoteMind 自动生成于 {now}\n")
        return "\n".join(parts)

    def build_section_note(self, section: dict, parent_name: str, tags: list[str] = None,
                           image_descriptions: list[str] = None, image_index: int = 0) -> str:
        """构建单个章节独立笔记文件。

        Args:
            section: {"title": "...", "summary": "...", "text": "..."}
            parent_name: 索引文件名（不含 .md）
            tags: 该章节的标签
            image_descriptions: 该章节对应的图片描述
            image_index: 图片起始索引
        """
        parts = []
        tags_str = ", ".join(tags) if tags else ""
        parts.append(f"""---
source: {self.source_name}
date: {self.date_str}
category: {self._category if hasattr(self, '_category') else "其他"}
tags: [{tags_str}]
parent: {parent_name}
---
""")
        # 章节标题
        if section.get("title"):
            parts.append(f"# {section['title']}\n")
        # 摘要
        if section.get("summary"):
            parts.append("## 摘要\n")
            parts.append(f"{section['summary']}\n\n")
        # 正文
        if section.get("text"):
            parts.append(f"{section['text']}\n\n")
        # 图片
        if image_descriptions and image_descriptions[image_index:]:
            parts.append("## 图片\n")
            for desc in image_descriptions[image_index:]:
                parts.append(f"> {desc}\n\n")
        # 返回链接
        parts.append(f"\n> 返回 [[{parent_name}]]")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        parts.append(f"\n> 由 NoteMind 自动生成于 {now}\n")
        return "\n".join(parts)
