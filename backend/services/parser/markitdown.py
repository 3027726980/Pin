"""
通用文档解析器（markitdown）
支持 DOCX / XLSX / PPTX / 等各种 Office 格式
"""
from backend.services.parser.base import BaseParser


class MarkitdownParser(BaseParser):
    """markitdown 通用解析，输出 Markdown"""

    def parse(self, file_path: str) -> str:
        from markitdown import MarkItDown

        md = MarkItDown()
        result = md.convert(file_path)
        return result.text_content
