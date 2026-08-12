"""
文档解析器

映射：
  PDF  → PyMuPDFParser（fitz 逐页提取）
  TXT/MD → TextParser（直接读取）
  其他  → MarkitdownParser（DOCX/XLSX/PPTX/...）
"""
from abc import ABC, abstractmethod
from pathlib import Path

import pymupdf


class BaseParser(ABC):
    @abstractmethod
    def parse(self, file_path: str) -> str:
        ...


class PyMuPDFParser(BaseParser):
    def parse(self, file_path: str) -> str:
        pages = []
        with pymupdf.open(file_path) as doc:
            for page in doc:
                text = page.get_text()
                if text.strip():
                    pages.append(text)
        return "\n\n".join(pages)


class MarkitdownParser(BaseParser):
    def parse(self, file_path: str) -> str:
        # 延迟 import：markitdown[all] 会拉起 torch/transformers（启动耗时 ~5s），
        # 仅首次解析文档时才加载（启动提速优化）
        from markitdown import MarkItDown

        return MarkItDown().convert(file_path).text_content


class TextParser(BaseParser):
    def parse(self, file_path: str) -> str:
        return Path(file_path).read_text(encoding="utf-8")


def get_parser(file_type: str) -> BaseParser:
    ext = file_type.lower().lstrip(".") if file_type else ""
    if ext == "pdf":
        return PyMuPDFParser()
    elif ext in ("txt", "md", "markdown"):
        return TextParser()
    else:
        return MarkitdownParser()
