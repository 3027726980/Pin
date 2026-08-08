"""
通用工具类

BaseTool：所有 Agent 工具的抽象基类，工具自带全部能力：
  - type / description：元信息（注册、LLM 决策用）
  - name_ref_keys：需要补全名称的配置字段（如 rag 的 kb_id → kb_name）
  - validate_config：配置校验（创建/编辑 Agent 时调用）
  - build_langchain：LangChain 工具构建（对话时调用，闭包绑定上下文）
新增工具 = 新建一个工具类（实现上述方法）+ 注册到 ToolRegistry.TOOLS，
调用方（chat/agent 服务）零改动。
"""
from abc import ABC, abstractmethod


class BaseTool(ABC):
    """工具抽象基类：定义工具的注册、校验、构建、补全能力"""

    # 工具类型（注册表 key，与 schema 中 ToolConfig.type 对应）
    type: str = ""

    # 工具描述（给 LLM 判断是否调用）
    description: str = ""

    # 需要补全名称的配置字段：{config_key: response_key}
    # 例：rag 工具 {"kb_id": "kb_name"} → 注册表会查知识库名称并补全到响应
    name_ref_keys: dict[str, str] = {}

    @staticmethod
    @abstractmethod
    async def validate_config(db, user, config: dict) -> None:
        """
        校验工具配置（创建/编辑 Agent 时调用）

        参数:
            db: AsyncSession
            user: 当前用户
            config: 工具配置（如 {"kb_id": ...}）

        校验失败时 raise HTTPException（404/400）
        """
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def build_langchain(db, user, config: dict, citations_store: list):
        """
        构建 LangChain 工具（对话时调用，闭包绑定 db/user/config）

        参数:
            db: AsyncSession
            user: 当前用户
            config: 工具配置
            citations_store: 外部列表，工具执行结果追加至此（响应回传引用）

        返回: LangChain 工具对象（@tool），供 create_agent 注册
        """
        raise NotImplementedError

    @staticmethod
    def execute(db, user, config: dict, message: str):
        """工具核心执行逻辑（simple_rag 等代码控制场景直接调用）"""
        raise NotImplementedError
