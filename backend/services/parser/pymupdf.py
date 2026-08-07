"""
PDF 解析器（PyMuPDF）
"""
from backend.services.parser.base import BaseParser


class PyMuPDFParser(BaseParser):
    """PDF 解析，使用 PyMuPDF 逐页提取文本"""

    def parse(self, file_path: str) -> str:
        import fitz

        pages: list[str] = []
        with fitz.open(file_path) as doc:
            for page in doc:
                text = page.get_text()
                if text.strip():
                    pages.append(text)
        return "\n\n".join(pages)
