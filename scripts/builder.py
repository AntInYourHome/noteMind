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

    def add_frontmatter(self, category: str, tags: list[str], source_path: str = None) -> "MarkdownBuilder":
        """添加 YAML frontmatter。

        Args:
            category: 分类
            tags: 标签列表
            source_path: 原始文件的完整路径（用于溯源）
        """
        self._category = category
        self._tags = tags
        tags_str = ", ".join(tags)
        frontmatter_lines = [
            f"source: {self.source_name}",
            f"date: {self.date_str}",
            f"category: {category}",
            f"tags: [{tags_str}]",
        ]
        if source_path:
            frontmatter_lines.append(f"original_path: {source_path}")
        self.parts.append("---\n" + "\n".join(frontmatter_lines) + "\n---\n")
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

    def add_section_title(self, title: str) -> "MarkdownBuilder":
        """添加一个二级标题。"""
        self.parts.append(f"## {title}\n")
        return self

    def add_paragraph(self, text: str) -> "MarkdownBuilder":
        """添加一个段落。"""
        self.parts.append(f"{text}\n")
        return self

    def add_sections(self, section_results: list) -> "MarkdownBuilder":
        """添加章节内容（仅标题+摘要，不写原文正文）。"""
        if not section_results:
            return self

        self.parts.append("## 目录\n")

        for sr in section_results:
            # 章节标题
            if sr.get("title"):
                self.parts.append(f"### {sr['title']}\n")

            # 章节摘要（只写摘要，不写原文正文）
            if sr.get("summary") and sr.get("title"):
                self.parts.append(f"{sr['summary']}\n")

        return self

    def add_images(self, vault_image_paths: list[str], image_descriptions: list[str]) -> "MarkdownBuilder":
        """添加图片及 AI 描述。"""
        if vault_image_paths:
            self.parts.append("## 图片存档\n")
            for img_path, desc in zip(vault_image_paths, image_descriptions):
                self.parts.append(f"![[{img_path}]]\n")
                if desc:
                    self.parts.append(f"> {desc}\n\n")
        return self

    def add_source_ref(self, source_path: str) -> "MarkdownBuilder":
        """添加原文位置引用。"""
        if source_path:
            import os
            from pathlib import Path
            filename = Path(source_path).name
            self.parts.append("## 原文位置\n")
            self.parts.append(f"- 原文：`{filename}`\n")
            self.parts.append(f"- 路径：`{source_path}`\n\n")
        return self

    def add_archive_link(self, archive_filename: str, category: str) -> "MarkdownBuilder":
        """添加归档文件的双链（Obsidian wikilink）。

        Args:
            archive_filename: 归档文件名（如 "HarmonyOS+6.0安全技术白皮书.pdf"）
            category: 多级分类路径（如 "安全/操作系统安全/HarmonyOS"）
        """
        if not archive_filename:
            return self
        # 计算从分类目录到 _archive 的相对路径
        archive_link = archive_filename
        self.parts.append(f"## 原始文件\n")
        self.parts.append(f"- 归档：[[{archive_link}]]\n\n")
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

    def build_index(self, section_links: list[tuple[str, str]], source_path: str = None) -> str:
        """构建索引文件（主文档：仅摘要 + 章节链接）。

        Args:
            section_links: [(章节文件名（不含.md）, 章节标题), ...]
            source_path: 原始文件的完整路径
        """
        parts = []
        # frontmatter
        tags_str = ", ".join(self._tags if hasattr(self, '_tags') else [])
        fm_lines = [
            f"source: {self.source_name}",
            f"date: {self.date_str}",
            f"category: {self._category if hasattr(self, '_category') else '其他'}",
            f"tags: [{tags_str}]",
            "doc_type: index",
            f"sections: {len(section_links)}",
        ]
        if source_path:
            fm_lines.append(f"original_path: {source_path}")
        parts.append("---\n" + "\n".join(fm_lines) + "\n---\n")
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
                           image_descriptions: list[str] = None, image_index: int = 0,
                           source_path: str = None) -> str:
        """构建单个章节独立笔记文件。

        Args:
            section: {"title": "...", "summary": "...", "text": "..."}
            parent_name: 索引文件名（不含 .md）
            tags: 该章节的标签
            image_descriptions: 该章节对应的图片描述
            image_index: 图片起始索引
            source_path: 原始文件的完整路径
        """
        parts = []
        tags_str = ", ".join(tags) if tags else ""
        fm_lines = [
            f"source: {self.source_name}",
            f"date: {self.date_str}",
            f"category: {self._category if hasattr(self, '_category') else '其他'}",
            f"tags: [{tags_str}]",
            f"parent: {parent_name}",
        ]
        if source_path:
            fm_lines.append(f"original_path: {source_path}")
        parts.append("---\n" + "\n".join(fm_lines) + "\n---\n")
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
