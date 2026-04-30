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
