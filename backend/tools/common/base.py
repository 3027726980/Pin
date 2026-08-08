"""
通用工具类

BaseTool：所有 Agent 工具的抽象基类，只定义统一调用协议：
  固定形参 (db, user, config)，多余参数通过 **kwargs 传入（由调用方与子类约定）。

设计原则：抽象层保持极简，不规定任何具体工具的概念（如 message / citations_store）；
子类实现时按需定义自己的参数（如 rag 的 message、引用收集器），
因为反正每个工具都要重写这些方法，扩展参数由开发者自行确定。

新增工具 = 新建一个工具类（实现上述方法）+ 注册到 ToolRegistry.TOOLS，
调用方（chat/agent 服务）零改动。
"""
from abc import ABC, abstractmethod


class BaseTool(ABC):
    """工具抽象基类：定义工具的注册、校验、构建、执行协议"""

    # 工具类型（注册表 key，与 schema 中 ToolConfig.type 对应）
    type: str = ""

    # 工具描述（给 LLM 判断是否调用）
    description: str = ""

    # 需要补全名称的配置字段：{config_key: response_key}
    # 例：rag 工具 {"kb_id": "kb_name"} → 注册表会查知识库名称并补全到响应
    name_ref_keys: dict[str, str] = {}

    @staticmethod
    @abstractmethod
    async def validate_config(db, user, config: dict, **kwargs) -> None:
        """
        校验工具配置（创建/编辑 Agent 时调用）

        参数:
            db: AsyncSession
            user: 当前用户
            config: 工具配置（如 {"kb_id": ...}）
            **kwargs: 子类按需扩展

        校验失败时 raise HTTPException（404/400）
        """
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def build_langchain(db, user, config: dict, **kwargs):
        """
        构建 LangChain 工具（对话时调用，闭包绑定 db/user/config）

        参数:
            db: AsyncSession
            user: 当前用户
            config: 工具配置
            **kwargs: 子类按需扩展（如 rag 需要引用收集器）

        返回: LangChain 工具对象（@tool），供 create_agent 注册
        """
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def execute(db, user, config: dict, **kwargs):
        """
        工具核心执行逻辑（simple_rag 等代码控制场景直接调用）

        参数:
            db: AsyncSession
            user: 当前用户
            config: 工具配置
            **kwargs: 子类按需扩展（如 rag 需要用户消息）

        返回: 工具输出（结构由各工具定义，如 rag 返回 list[Citation]）
        """
        raise NotImplementedError
