"""
纯文本解析器（TXT / MD 等直接读取）
"""
from pathlib import Path

from backend.services.parser.base import BaseParser


class TextParser(BaseParser):
    """纯文本文件直接读取"""

    def parse(self, file_path: str) -> str:
        return Path(file_path).read_text(encoding="utf-8")
