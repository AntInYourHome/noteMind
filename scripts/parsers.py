"""
NoteMind 格式解析器 — 统一返回 {text, images, sections} 结构
长文档按章节/段落拆分，每节独立 AI 摘要
"""

import os
import re
import tempfile


class Section:
    """文档的一个章节。"""
    def __init__(self, title: str, text: str, images: list[str] = None):
        self.title = title or "未命名章节"
        self.text = text
        self.images = images or []


class ParseResult:
    """解析结果：全文 + 提取的图片 + 结构化章节。"""
    def __init__(self, text: str = "", images: list[str] = None, sections: list = None):
        self.text = text or ""
        self.images = images or []
        self.sections = sections or []

    @property
    def has_content(self):
        return bool(self.text.strip()) or len(self.images) > 0 or len(self.sections) > 0

    def should_split(self, threshold: int = 3000) -> bool:
        """判断是否需要按章节拆分。"""
        if len(self.sections) >= 3:
            return True
        return len(self.text) >= threshold


def parse_pdf(file_path: str) -> ParseResult:
    """PDF → 文字 + 图片 + 按页面/章节拆分"""
    try:
        import fitz
        doc = fitz.open(file_path)
        text_parts = []
        images = []
        sections = []
        section_texts = []

        for page_num, page in enumerate(doc, 1):
            page_text = page.get_text()
            text_parts.append(page_text)
            section_texts.append(page_text)

            # 提取图片
            page_images = []
            for img_info in page.get_images(full=True):
                xref = img_info[0]
                base_image = doc.extract_image(xref)
                if base_image:
                    ext = base_image["ext"]
                    img_bytes = base_image["image"]
                    img_path = os.path.join(
                        tempfile.gettempdir(),
                        f"pdf_p{page_num}_{xref}.{ext}"
                    )
                    with open(img_path, "wb") as f:
                        f.write(img_bytes)
                    images.append(img_path)
                    page_images.append(img_path)

            sections.append(Section(f"第 {page_num} 页", page_text.strip(), page_images))

        doc.close()
        full_text = "\n\n".join(text_parts)
        return ParseResult(full_text, images, sections)
    except ImportError:
        return ParseResult("", [])


def parse_docx(file_path: str) -> ParseResult:
    """Word (.docx) → 文字 + 内嵌图片 + 按标题拆分章节"""
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        doc = Document(file_path)
        sections = []
        images = []
        current_title = None
        current_text = []
        current_images = []

        # 先提取所有内嵌图片
        img_dir = tempfile.mkdtemp(prefix="docx_imgs_")
        rels = doc.part.rels
        for rel in rels:
            if "image" in rels[rel].reltype:
                image = rels[rel].target_part
                ext = image.content_type.split("/")[-1]
                if ext not in ("jpeg", "png", "gif", "bmp"):
                    ext = "png"
                img_path = os.path.join(img_dir, f"docx_img_{rel}.{ext}")
                with open(img_path, "wb") as f:
                    f.write(image.blob)
                images.append(img_path)

        for para in doc.paragraphs:
            # 判断是否为标题（居中、加粗、大字号）
            is_heading = False
            try:
                style_name = para.style.name.lower() if para.style else ""
                if "heading" in style_name or "title" in style_name:
                    is_heading = True
            except Exception:
                pass

            if is_heading and current_text:
                sections.append(Section(current_title or "概述", "\n".join(current_text), current_images))
                current_text = []
                current_images = []
                current_title = para.text.strip()
            elif is_heading:
                current_title = para.text.strip()
            else:
                if para.text.strip():
                    current_text.append(para.text)

        # 提取表格
        table_parts = []
        for table in doc.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    table_parts.append(" | ".join(cells))

        if table_parts:
            current_text.append("\n表格内容:\n" + "\n".join(table_parts))

        if current_text:
            sections.append(Section(current_title or "概述", "\n".join(current_text), current_images))

        # 如果没有章节，返回全文
        if not sections:
            full_text = "\n\n".join([p.text for p in doc.paragraphs if p.text.strip()])
            return ParseResult(full_text, images, [])

        full_text = "\n\n".join([s.text for s in sections])
        return ParseResult(full_text, images, sections)
    except ImportError:
        return ParseResult("", [])


def parse_pptx(file_path: str) -> ParseResult:
    """PPT (.pptx) → 逐页文字 + 每页图片 + 每页作为一节"""
    try:
        from pptx import Presentation
        prs = Presentation(file_path)
        sections = []
        images = []
        img_dir = tempfile.mkdtemp(prefix="pptx_imgs_")

        for i, slide in enumerate(prs.slides, 1):
            slide_text = []

            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        if para.text.strip():
                            slide_text.append(para.text.strip())

                # 提取图片
                try:
                    from pptx.enum.shapes import MSO_SHAPE_TYPE
                    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                        image = shape.image
                        ext = image.ext
                        img_path = os.path.join(img_dir, f"slide{i}_{shape.shape_id}.{ext}")
                        with open(img_path, "wb") as f:
                            f.write(image.blob)
                        images.append(img_path)
                        # 将该图片关联到对应章节
                except Exception:
                    pass

            text = "\n".join(slide_text)
            if text or images:
                sections.append(Section(f"幻灯片 {i}", text, [img for img in images if img_path.endswith(str(i))]))

        # 简化：所有图片归到全文，sections 按页拆分文字
        full_text = "\n\n".join([s.text for s in sections])
        return ParseResult(full_text, images, sections)
    except ImportError:
        return ParseResult("", [])


def parse_excel(file_path: str) -> ParseResult:
    """Excel (.xlsx) → 文字（按工作表分章节）"""
    try:
        from openpyxl import load_workbook
        wb = load_workbook(file_path, read_only=True, data_only=True)
        sections = []
        all_text = []

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            sheet_lines = []
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) if c is not None else "" for c in row]
                if any(cells):
                    sheet_lines.append(" | ".join(cells))

            if sheet_lines:
                text = "\n".join(sheet_lines)
                sections.append(Section(f"工作表: {sheet_name}", text))
                all_text.append(f"## {sheet_name}\n{text}")

        wb.close()
        full_text = "\n\n".join(all_text)
        return ParseResult(full_text, [], sections)
    except ImportError:
        return ParseResult("", [])


def parse_markdown(file_path: str) -> ParseResult:
    """Markdown → 纯文本 + 本地图片 + 按 ## 标题拆分章节"""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 提取本地图片
    images = []
    img_pattern = r'!\[.*?\]\((.*?)\)'
    for match in re.finditer(img_pattern, content):
        img_path = match.group(1)
        if not img_path.startswith(("http://", "https://", "data:")):
            base_dir = os.path.dirname(os.path.abspath(file_path))
            full_path = os.path.join(base_dir, img_path)
            if os.path.exists(full_path):
                images.append(full_path)

    # 按 ## 标题拆分章节
    sections = []
    # 匹配 ## 或 ### 标题
    heading_pattern = r'^(#{1,6})\s+(.+)$'
    parts = re.split(heading_pattern, content, flags=re.MULTILINE)

    if len(parts) > 3:
        # 有标题结构
        current_title = None
        current_text = []
        current_images = []

        i = 0
        while i < len(parts):
            if parts[i].startswith("#"):
                # 新章节
                if current_text:
                    clean = _clean_markdown("".join(current_text))
                    if clean.strip():
                        sections.append(Section(current_title or "概述", clean, current_images))
                current_title = parts[i + 1].strip()
                current_text = []
                current_images = []
                i += 2
            else:
                # 找图片
                for m in re.finditer(img_pattern, parts[i]):
                    img_p = m.group(1)
                    if not img_p.startswith(("http://", "https://", "data:")):
                        base_dir = os.path.dirname(os.path.abspath(file_path))
                        fp = os.path.join(base_dir, img_p)
                        if os.path.exists(fp) and fp in images:
                            current_images.append(fp)
                current_text.append(parts[i])
                i += 1

        if current_text:
            clean = _clean_markdown("".join(current_text))
            if clean.strip():
                sections.append(Section(current_title or "概述", clean, current_images))

    # 清洗全文
    text = _clean_markdown(content)
    return ParseResult(text.strip(), images, sections)


def _clean_markdown(content: str) -> str:
    """清洗 Markdown 为纯文本。"""
    text = re.sub(r'```[\s\S]*?```', '', content)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'\[([^\]]*)\]\(.*?\)', r'\1', text)
    text = re.sub(r'#+\s*', '', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'>\s*', '', text)
    text = re.sub(r'^[-*]\s*', '', text, flags=re.MULTILINE)
    return text.strip()


def parse_image(file_path: str) -> ParseResult:
    """图片文件 → 无文字，图片路径本身"""
    return ParseResult("", [file_path])


def parse_text(file_path: str) -> ParseResult:
    """纯文本文件 → 文字"""
    with open(file_path, "r", encoding="utf-8") as f:
        return ParseResult(f.read().strip(), [])


def parse_onenote(file_path: str) -> ParseResult:
    """OneNote (.one) → 文字"""
    try:
        from onenote2xml import OneNote
        one = OneNote(file_path)
        text = one.text()
        if isinstance(text, str):
            return ParseResult(text.strip(), [])
        return ParseResult(str(text).strip(), [])
    except Exception:
        return ParseResult(_fallback_binary_text(file_path), [])


def _fallback_binary_text(file_path: str) -> str:
    """通用二进制文件回退。"""
    with open(file_path, "rb") as f:
        raw = f.read()
    try:
        return raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        try:
            return raw.decode("gbk").strip()
        except UnicodeDecodeError:
            return ""


# 文件扩展名 → 解析函数映射
PARSERS = {
    ".pdf": parse_pdf,
    ".docx": parse_docx,
    ".doc": parse_docx,
    ".pptx": parse_pptx,
    ".ppt": parse_pptx,
    ".xlsx": parse_excel,
    ".xls": parse_excel,
    ".md": parse_markdown,
    ".markdown": parse_markdown,
    ".txt": parse_text,
    ".log": parse_text,
    ".csv": parse_text,
    ".one": parse_onenote,
}

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"}


def get_parser(file_path: str):
    """根据文件扩展名返回解析函数。"""
    ext = os.path.splitext(file_path)[1].lower()
    if ext in IMAGE_EXTS:
        return "image"
    return PARSERS.get(ext)
