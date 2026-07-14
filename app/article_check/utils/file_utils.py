"""
文件工具 — 论文文件检测、解析、文本提取
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 支持的文件类型
SUPPORTED_FORMATS = {
    ".tex": "latex",
    ".ltx": "latex",
    ".cls": "latex",
    ".sty": "latex",
    ".docx": "docx",
    ".pdf": "pdf",
    ".txt": "text",
    ".md": "markdown",
}


def detect_file_type(path: Path) -> str:
    """检测文件类型"""
    suffix = path.suffix.lower()
    return SUPPORTED_FORMATS.get(suffix, "unknown")


def read_paper_content(path: Path) -> str:
    """读取论文内容（尝试多种编码）"""
    encodings = ["utf-8", "gbk", "gb2312", "latin-1"]
    for enc in encodings:
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def extract_text_from_pdf(path: Path) -> str:
    """
    从 PDF 提取文本

    需要安装 PyMuPDF 或 pdfplumber。
    如果未安装，返回空字符串。
    """
    try:
        import fitz  # PyMuPDF
        text_parts = []
        with fitz.open(str(path)) as doc:
            for page in doc:
                text_parts.append(page.get_text())
        return "\n".join(text_parts)
    except ImportError:
        pass

    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
        return "\n".join(text_parts)
    except ImportError:
        pass

    logger.warning("PDF 解析库未安装。安装: pip install PyMuPDF 或 pdfplumber")
    return ""


def extract_text_from_docx(path: Path) -> str:
    """
    从 DOCX 提取纯文本。

    优先保留段落边界，避免将 Word 文档按 zip 二进制直接读取。
    """
    try:
        from docx import Document
    except ImportError:
        logger.warning("DOCX 解析库未安装。安装: pip install python-docx")
        return ""

    doc = Document(str(path))
    paragraphs = [para.text.strip() for para in doc.paragraphs if para.text and para.text.strip()]
    return "\n".join(paragraphs)


def find_papers(
    directory: str,
    recursive: bool = True,
    file_types: Optional[List[str]] = None,
) -> List[Dict[str, any]]:
    """
    扫描目录中的论文文件

    Args:
        directory: 扫描目录
        recursive: 是否递归
        file_types: 文件类型过滤，如 ["latex", "docx"]

    Returns:
        论文文件信息列表
    """
    types = file_types or ["latex", "docx", "pdf"]
    ext_map = {}
    for ext, file_type in SUPPORTED_FORMATS.items():
        if file_type in types:
            ext_map.setdefault(ext, file_type)

    papers = []
    base = Path(directory)

    pattern = "**/*" if recursive else "*"

    for ext, ftype in ext_map.items():
        for f in base.glob(f"{pattern}{ext}"):
            if f.is_file():
                papers.append({
                    "path": str(f.resolve()),
                    "name": f.stem,
                    "type": ftype,
                    "size": f.stat().st_size,
                })

    # 按类型分组排序
    papers.sort(key=lambda p: (p["type"], p["name"]))
    return papers
