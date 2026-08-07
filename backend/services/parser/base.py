"""
文档解析器抽象基类
"""
from abc import ABC, abstractmethod


class BaseParser(ABC):
    """解析器基类 — 所有解析器需实现 parse 方法"""

    @abstractmethod
    def parse(self, file_path: str) -> str:
        """解析文件，返回纯文本"""
        ...
