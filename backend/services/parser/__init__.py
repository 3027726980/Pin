"""
解析器模块 — 统一导出
"""
from backend.services.parser.base import BaseParser
from backend.services.parser.factory import get_parser
from backend.services.parser.pymupdf import PyMuPDFParser
from backend.services.parser.markitdown import MarkitdownParser
from backend.services.parser.text import TextParser

__all__ = [
    "BaseParser",
    "PyMuPDFParser",
    "MarkitdownParser",
    "TextParser",
    "get_parser",
]
