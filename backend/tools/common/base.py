"""
通用工具类

BaseTool：所有 Agent 工具的抽象基类，定义统一接口。
"""
from abc import ABC, abstractmethod


class BaseTool(ABC):
    """工具抽象基类：type 标识工具类型，execute 执行工具逻辑"""

    type: str = ""

    @abstractmethod
    async def execute(self, db, user, config: dict, message: str):
        """
        执行工具

        参数:
            db: AsyncSession
            user: 当前用户
            config: 工具配置（来自 Agent 的 tools JSONB）
            message: 用户消息

        返回: 工具输出（结构由各工具定义，如 rag 返回 list[Citation]）
        """
        raise NotImplementedError
