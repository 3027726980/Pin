"""
解析器工厂：根据文件后缀选择对应的解析器

映射：
  PDF  → PyMuPDFParser
  TXT/MD → TextParser
  其他  → MarkitdownParser（DOCX/XLSX/PPTX/...）
"""
from backend.services.parser.base import BaseParser
from backend.services.parser.pymupdf import PyMuPDFParser
from backend.services.parser.markitdown import MarkitdownParser
from backend.services.parser.text import TextParser


def get_parser(file_type: str) -> BaseParser:
    ext = file_type.lower().lstrip(".") if file_type else ""

    if ext == "pdf":
        return PyMuPDFParser()
    elif ext in ("txt", "md", "markdown"):
        return TextParser()
    else:
        return MarkitdownParser()
