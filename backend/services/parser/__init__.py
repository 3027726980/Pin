"""
文档解析器抽象层 + 工厂

解析器映射：
  PDF  → PyMuPDFParser
  其他 → MarkitdownParser
  TXT/MD → TextParser（直接读取）
"""
from abc import ABC, abstractmethod
from pathlib import Path


class BaseParser(ABC):
    """解析器基类"""

    @abstractmethod
    def parse(self, file_path: str) -> str:
        """解析文件，返回纯文本"""
        ...


# ── 具体实现 ────────────────────────────

class PyMuPDFParser(BaseParser):
    """PDF 解析（PyMuPDF）"""

    def parse(self, file_path: str) -> str:
        import fitz  # PyMuPDF

        pages: list[str] = []
        with fitz.open(file_path) as doc:
            for page in doc:
                text = page.get_text()
                if text.strip():
                    pages.append(text)
        return "\n\n".join(pages)


class MarkitdownParser(BaseParser):
    """通用文档解析（markitdown，输出 Markdown）"""

    def parse(self, file_path: str) -> str:
        from markitdown import MarkItDown

        md = MarkItDown()
        result = md.convert(file_path)
        return result.text_content


class TextParser(BaseParser):
    """纯文本直接读取（TXT / MD）"""

    def parse(self, file_path: str) -> str:
        return Path(file_path).read_text(encoding="utf-8")


# ── 工厂 ────────────────────────────────

def get_parser(file_type: str) -> BaseParser:
    """根据文件后缀返回对应的解析器"""
    ext = file_type.lower().lstrip(".") if file_type else ""

    if ext == "pdf":
        return PyMuPDFParser()
    elif ext in ("txt", "md", "markdown"):
        return TextParser()
    else:
        # docx / xlsx / pptx / 其他 → markitdown
        return MarkitdownParser()
