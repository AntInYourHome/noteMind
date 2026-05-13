"""
NoteMind 格式解析器 — 统一返回 {text, images, sections} 结构
长文档按章节/段落拆分，每节独立 AI 摘要
"""

import os
import re
import tempfile
from threading import Lock

# 智能 OCR 阈值：每页平均字符数低于此值时才 OCR 图片
OCR_CHAR_THRESHOLD_PER_PAGE = 100


class Section:
    """文档的一个章节。"""
    def __init__(self, title: str, text: str, images: list[str] = None):
        self.title = title or "未命名章节"
        self.text = text
        self.images = images or []


class ParseResult:
    """解析结果：全文 + 提取的图片 + 结构化章节。"""
    def __init__(self, text: str = "", images: list[str] = None, sections: list = None,
                 image_ocr_texts: list[str] = None):
        self.text = text or ""
        self.images = images or []
        self.sections = sections or []
        self.image_ocr_texts = image_ocr_texts or []

    @property
    def has_content(self):
        return bool(self.text.strip()) or len(self.images) > 0 or len(self.sections) > 0

    def should_split(self, threshold: int = 3000) -> bool:
        """判断是否需要按章节拆分。"""
        if len(self.sections) >= 3:
            return True
        return len(self.text) >= threshold


def _ocr_image(file_path: str) -> str:
    """对单张图片做 OCR，返回提取的文本。"""
    ocr = _get_ocr_instance()
    if ocr is None:
        return ""
    try:
        result, _ = ocr(file_path)
        if result:
            return "\n".join(line[1] for line in result if len(line) >= 2)
    except Exception:
        pass
    return ""


def _should_ocr_images(text: str, page_count: int, image_count: int) -> bool:
    """判断是否需要对图片做 OCR。文字为主的文档跳过 OCR。"""
    if image_count == 0:
        return False
    chars_per_page = len(text.strip()) / max(page_count, 1)
    return chars_per_page < OCR_CHAR_THRESHOLD_PER_PAGE


def parse_pdf(file_path: str) -> ParseResult:
    """PDF → 文字 + 图片 + 按页面/章节拆分（智能 OCR）"""
    try:
        import fitz
        doc = fitz.open(file_path)
        text_parts = []
        all_images = []
        page_data = []  # [(page_text, [img_paths])]

        # Pass 1: 提取文字 + 保存图片（不做 OCR）
        for page_num, page in enumerate(doc, 1):
            page_text = page.get_text()
            text_parts.append(page_text)
            page_images = []

            for img_info in page.get_images(full=True):
                xref = img_info[0]
                base_image = doc.extract_image(xref)
                if base_image:
                    ext = base_image["ext"]
                    img_path = os.path.join(
                        tempfile.gettempdir(),
                        f"pdf_p{page_num}_{xref}.{ext}"
                    )
                    with open(img_path, "wb") as f:
                        f.write(img_bytes := base_image["image"])
                    all_images.append(img_path)
                    page_images.append(img_path)

            page_data.append((page_text.strip(), page_images))

        doc.close()

        # 判断是否需要 OCR
        full_text = "\n\n".join(text_parts)
        do_ocr = _should_ocr_images(full_text, len(page_data), len(all_images))

        # Pass 2: 构建章节，条件 OCR
        sections = []
        all_image_ocr = []

        for page_num, (page_text, page_images) in enumerate(page_data, 1):
            page_image_ocr_texts = []
            if do_ocr:
                for img_path in page_images:
                    ocr_text = _ocr_image(img_path)
                    page_image_ocr_texts.append(ocr_text)
                    all_image_ocr.append(ocr_text)

            page_content = page_text
            ocr_combined = "\n".join(t for t in page_image_ocr_texts if t)
            if ocr_combined:
                page_content = f"{page_text}\n\n[图片内容识别]\n{ocr_combined}" if page_text else ocr_combined

            sections.append(Section(f"第 {page_num} 页", page_content, page_images))

        # 尝试用真实标题替换 "第 X 页"
        sections = _infer_section_titles(sections)

        return ParseResult(full_text, all_images, sections, all_image_ocr)
    except ImportError:
        return ParseResult("", [])


def _infer_section_titles(sections: list) -> list:
    """从 PDF 页面文本中提取真实标题，替换 "第 X 页"。

    策略：
      1. 每页首行中文文本作为候选标题
      2. 如果标题是页码/页眉/页脚（如 "第 X 页"、"HarmonyOS 6.0..."），跳过
      3. 合并相邻相同标题的页面
    """
    import re

    # 页眉/页脚模式
    skip_patterns = [
        re.compile(r'^第\s*\d+\s*页'),        # 页码
        re.compile(r'^HarmonyOS\s*\d'),       # 页眉
        re.compile(r'^\d+$'),                  # 纯数字页码
        re.compile(r'^\s*$'),                  # 空行
        re.compile(r'^[\u4e00-\u9fff]{1,2}$'), # 单字/双字（可能是页眉标记）
    ]

    for sec in sections:
        # 从页面文本中提取首行有意义的中文标题
        lines = sec.text.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # 跳过页眉页脚
            if any(p.match(line) for p in skip_patterns):
                continue
            # 取第一个有意义的行作为标题
            # 提取该行中的中文部分（最多 30 字）
            chinese = re.findall(r'[\u4e00-\u9fff][\u4e00-\u9fff\w\s·.]{2,29}', line)
            if chinese:
                title = chinese[0].strip()
                if len(title) >= 3 and len(title) <= 30:
                    sec.title = title
                    break

    # 合并连续相同标题的页面
    merged = []
    for sec in sections:
        if merged and merged[-1].title == sec.title and merged[-1].title != f"第 {len(merged)} 页":
            # 合并文本和图片
            prev = merged[-1]
            prev.text = prev.text + "\n\n" + sec.text
            prev.images.extend(sec.images)
        else:
            merged.append(sec)

    return merged if merged else sections


def parse_docx(file_path: str) -> ParseResult:
    """Word (.docx/.doc) → 文字 + 内嵌图片 + 按标题拆分章节（智能 OCR）

    对于老版本 .doc 文件，尝试通过 LibreOffice 转换为 .docx。
    """
    ext = os.path.splitext(file_path)[1].lower()

    # 老版本 .doc 文件需要转换
    if ext == ".doc":
        return _convert_old_office(file_path, "docx")

    return _parse_docx_impl(file_path)


def _parse_docx_impl(file_path: str) -> ParseResult:
    """解析 .docx 文件的内部实现。"""
    try:
        from docx import Document
        doc = Document(file_path)
        images = []
        all_image_ocr = []
        img_dir = tempfile.mkdtemp(prefix="docx_imgs_")

        # Pass 1: 提取文字 + 保存图片（不做 OCR）
        paragraphs_text = []
        for para in doc.paragraphs:
            if para.text.strip():
                paragraphs_text.append(para.text)

        full_text = "\n".join(paragraphs_text)

        # 提取图片
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

        # 判断是否需要 OCR
        # DOCX 没有明确页数，用段落数估算
        page_estimate = max(len([p for p in doc.paragraphs if p.style and "heading" in p.style.name.lower()]), 1)
        do_ocr = _should_ocr_images(full_text, page_estimate, len(images))

        # 条件 OCR
        if do_ocr:
            for img_path in images:
                ocr_text = _ocr_image(img_path)
                all_image_ocr.append(ocr_text)

        # Pass 2: 按标题拆分章节
        sections = []
        current_title = None
        current_text = []
        current_images = []

        for para in doc.paragraphs:
            is_heading = False
            try:
                style_name = para.style.name.lower() if para.style else ""
                if "heading" in style_name or "title" in style_name:
                    is_heading = True
            except Exception:
                pass

            if is_heading and current_text:
                sec = Section(current_title or "概述", "\n".join(current_text), current_images)
                sections.append(sec)
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

        if not sections:
            return ParseResult(full_text, images, [], all_image_ocr)

        full_text_sections = "\n\n".join([s.text for s in sections])
        return ParseResult(full_text_sections, images, sections, all_image_ocr)
    except ImportError:
        return ParseResult("", [])


def parse_pptx(file_path: str) -> ParseResult:
    """PPT (.pptx/.ppt) → 逐页文字 + 每页图片（智能 OCR）+ 每页作为一节

    对于老版本 .ppt 文件，尝试通过 LibreOffice 转换为 .pptx。
    """
    ext = os.path.splitext(file_path)[1].lower()

    # 老版本 .ppt 文件需要转换
    if ext == ".ppt":
        return _parse_old_ppt(file_path)

    try:
        from pptx import Presentation
        prs = Presentation(file_path)
        all_images = []
        slide_data = []  # [(slide_text, [img_paths])]
        img_dir = tempfile.mkdtemp(prefix="pptx_imgs_")

        # Pass 1: 提取文字 + 保存图片（不做 OCR）
        for i, slide in enumerate(prs.slides, 1):
            slide_text_parts = []
            slide_images = []

            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        if para.text.strip():
                            slide_text_parts.append(para.text.strip())

                try:
                    from pptx.enum.shapes import MSO_SHAPE_TYPE
                    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                        image = shape.image
                        ext = image.ext
                        img_path = os.path.join(img_dir, f"slide{i}_{shape.shape_id}.{ext}")
                        with open(img_path, "wb") as f:
                            f.write(image.blob)
                        all_images.append(img_path)
                        slide_images.append(img_path)
                except Exception:
                    pass

            slide_data.append(("\n".join(slide_text_parts), slide_images))

        full_text = "\n\n".join(sd[0] for sd in slide_data if sd[0])

        # 判断是否需要 OCR
        do_ocr = _should_ocr_images(full_text, len(slide_data), len(all_images))

        # Pass 2: 构建章节，条件 OCR
        sections = []
        all_image_ocr = []

        for i, (text, slide_images) in enumerate(slide_data, 1):
            slide_image_ocr = []
            if do_ocr:
                for img_path in slide_images:
                    ocr_text = _ocr_image(img_path)
                    slide_image_ocr.append(ocr_text)
                    all_image_ocr.append(ocr_text)

            ocr_combined = "\n".join(t for t in slide_image_ocr if t)
            if ocr_combined:
                text = f"{text}\n\n[图片内容识别]\n{ocr_combined}" if text else ocr_combined

            if text or slide_images:
                sections.append(Section(f"幻灯片 {i}", text, slide_images))

        return ParseResult(full_text, all_images, sections, all_image_ocr)
    except ImportError:
        return ParseResult("", [])
    except PermissionError:
        raise  # 文件被锁定，向上传播以便跳过重试
    except OSError as e:
        # 文件被占用/锁定/无法打开
        if e.errno in (13, 16, 32):  # Permission denied / Device busy / Sharing violation
            raise
        raise


def parse_excel(file_path: str) -> ParseResult:
    """Excel (.xlsx/.xls) → 文字（按工作表分章节）

    对于老版本 .xls 文件，尝试通过 LibreOffice 转换为 .xlsx。
    """
    ext = os.path.splitext(file_path)[1].lower()

    # 老版本 .xls 文件需要转换
    if ext == ".xls":
        return _convert_old_office(file_path, "xlsx")

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
    """Markdown → 纯文本 + 本地图片（智能 OCR）+ 按 ## 标题拆分章节"""
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

    # 清洗全文
    text = _clean_markdown(content)

    # 判断是否需要 OCR
    do_ocr = _should_ocr_images(text, 1, len(images))
    all_image_ocr = []
    if do_ocr:
        for img_path in images:
            ocr_text = _ocr_image(img_path)
            all_image_ocr.append(ocr_text)

    # 按 ## 及以上标题拆分章节
    sections = []
    heading_pattern = r'^(#{1,6})\s+(.+)$'
    parts = re.split(heading_pattern, content, flags=re.MULTILINE)

    if len(parts) > 3:
        current_title = None
        current_text = []
        current_images = []

        i = 0
        while i < len(parts):
            if parts[i].startswith("#"):
                if current_text:
                    clean = _clean_markdown("".join(current_text))
                    if clean.strip():
                        sections.append(Section(current_title or "概述", clean, current_images))
                current_title = parts[i + 1].strip()
                current_text = []
                current_images = []
                i += 2
            else:
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

    # 无章节时（纯文本或无标题 MD），将全文作为"概述"章节
    if not sections and text.strip():
        sections.append(Section("概述", text.strip(), []))

    return ParseResult(text.strip(), images, sections, all_image_ocr)


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


# --- OCR 引擎（全局单例，懒加载） ---

_ocr_instance = None
_ocr_lock = Lock()


def _get_ocr_instance():
    """获取全局 OCR 实例（线程安全，懒加载）。"""
    global _ocr_instance
    if _ocr_instance is not None:
        return _ocr_instance
    with _ocr_lock:
        if _ocr_instance is not None:
            return _ocr_instance
        try:
            from rapidocr_onnxruntime import RapidOCR
            _ocr_instance = RapidOCR()
        except ImportError:
            _ocr_instance = None  # 库未安装，返回 None
    return _ocr_instance


def parse_image(file_path: str) -> ParseResult:
    """图片文件 → OCR 提取文字（失败时 fallback 到空文本）"""
    ocr = _get_ocr_instance()
    text = ""
    if ocr is not None:
        try:
            result, _ = ocr(file_path)
            if result:
                texts = [line[1] for line in result if len(line) >= 2]
                text = "\n".join(texts)
        except Exception:
            text = ""  # OCR 失败，fallback 到空文本
    return ParseResult("", [file_path], [], [text] if text else [])


def parse_text(file_path: str) -> ParseResult:
    """纯文本文件 → 文字"""
    with open(file_path, "r", encoding="utf-8") as f:
        return ParseResult(f.read().strip(), [])


def parse_onenote(file_path: str) -> ParseResult:
    """OneNote (.one) → 文字

    策略：
    1. 尝试使用 onenote2xml 库
    2. 失败时，尝试解压 .one 文件（本质是 ZIP 包含 XML）
    3. 最后 fallback 到二进制文本提取
    """
    try:
        from onenote2xml import OneNote
        one = OneNote(file_path)
        text = one.text()
        if isinstance(text, str):
            return ParseResult(text.strip(), [])
        return ParseResult(str(text).strip(), [])
    except ImportError:
        # onenote2xml 未安装，尝试 ZIP 解析
        pass
    except Exception:
        pass

    # 尝试 ZIP 解析（.one 文件本质是 ZIP）
    try:
        import zipfile
        with zipfile.ZipFile(file_path, 'r') as zf:
            texts = []
            for name in zf.namelist():
                if name.endswith('.xml'):
                    content = zf.read(name).decode('utf-8', errors='ignore')
                    # 提取 XML 中的文本
                    import re
                    text_matches = re.findall(r'<text[^>]*>([^<]+)</text>', content)
                    texts.extend(text_matches)
            if texts:
                return ParseResult("\n".join(texts).strip(), [])
    except Exception:
        pass

    # 最终 fallback
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
    ".csv": parse_text,
}

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".svg"}


def parse_svg(file_path: str) -> ParseResult:
    """SVG 矢量图 → 提取文本内容（XML 解析）。"""
    import xml.etree.ElementTree as ET

    try:
        tree = ET.parse(file_path)
        root = tree.getroot()

        # 提取所有文本元素
        texts = []
        for elem in root.iter():
            if elem.text and elem.text.strip():
                texts.append(elem.text.strip())
            # 提取 <text> 元素的文本
            if elem.tag.endswith('text') or 'text' in elem.tag:
                for child in elem.iter():
                    if child.text and child.text.strip():
                        texts.append(child.text.strip())

        text = "\n".join(texts) if texts else ""
        return ParseResult(text, [file_path], [], [])
    except Exception:
        # XML 解析失败，当作普通图片处理
        return ParseResult("", [file_path], [], [])


def _convert_old_office(file_path: str, target_format: str) -> ParseResult:
    """转换老版本 Office 文件（.doc/.ppt/.xls）通过 LibreOffice。

    Args:
        file_path: 原始文件路径
        target_format: 目标格式（"docx", "pptx", "xlsx"）

    Returns:
        解析结果（成功时调用对应的解析函数）
    """
    import subprocess
    import shutil

    # 检查 LibreOffice 是否可用
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        ext = os.path.splitext(file_path)[1].lower()
        return ParseResult(
            f"[老版本 {ext} 文件需要 LibreOffice 转换]\n"
            "请安装 LibreOffice:\n"
            "  Linux: apt install libreoffice\n"
            "  Mac: brew install libreoffice\n"
            "  Windows: https://www.libreoffice.org/download\n",
            [],
            []
        )

    try:
        # 创建临时目录存放转换结果
        tmp_dir = tempfile.mkdtemp(prefix="office_convert_")

        # 转换文件
        result = subprocess.run(
            [soffice, "--headless", "--convert-to", target_format, "--outdir", tmp_dir, file_path],
            capture_output=True,
            timeout=60,
        )

        if result.returncode != 0:
            return ParseResult(f"[转换失败: {result.stderr.decode()}]", [], [])

        # 找到转换后的文件
        converted_name = os.path.splitext(os.path.basename(file_path))[0] + "." + target_format
        converted_path = os.path.join(tmp_dir, converted_name)

        if not os.path.exists(converted_path):
            return ParseResult("[转换后文件不存在]", [], [])

        # 根据目标格式调用对应的解析函数
        if target_format == "docx":
            parse_result = _parse_docx_impl(converted_path)
        elif target_format == "pptx":
            parse_result = _parse_pptx_impl(converted_path)
        elif target_format == "xlsx":
            parse_result = _parse_xlsx_impl(converted_path)
        else:
            parse_result = ParseResult("", [], [])

        # 清理临时文件
        shutil.rmtree(tmp_dir, ignore_errors=True)

        return parse_result

    except subprocess.TimeoutExpired:
        return ParseResult("[转换超时]", [], [])
    except Exception as e:
        return ParseResult(f"[转换异常: {e}]", [], [])


def get_parser(file_path: str):
    """根据文件扩展名返回解析函数。"""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".svg":
        return parse_svg  # SVG 使用专门的解析函数
    if ext in IMAGE_EXTS:
        return "image"
    return PARSERS.get(ext)
