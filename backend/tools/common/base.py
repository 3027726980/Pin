"""
通用工具类

BaseTool：所有 Agent 工具的抽象基类，只定义统一调用协议：
  固定形参 (db, user, config)，多余参数通过 **kwargs 传入（由调用方与子类约定）。

设计原则：抽象层保持极简，不规定任何具体工具的概念（如 message / citations_store）；
子类实现时按需定义自己的参数（如 rag 的 message、引用收集器），
因为反正每个工具都要重写这些方法，扩展参数由开发者自行确定。

自动注册（Phase 4.10）：
  - __init_subclass__ 钩子：任何 BaseTool 子类定义后自动登记到 _registry（按 type）
  - tools/agent/__init__.py 目录扫描保证工具模块被 import（import 即注册）
  - 新增工具 = 在 tools/agent/ 下新建一个实现 BaseTool 的文件（含 param_schema），
    其他代码零改动

工具自描述（Schema 驱动前端动态表单）：
  - builtin：内置能力标记（True = tool-defs 接口不返回，如 plan/reflect 走独立开关）
  - param_schema：参数描述列表（type/label/required/default/min/max/step/placeholder/source），
    前端按此渲染表单，提交时参数作为工具配置字段
  - fetch_options：select 参数动态选项提供器（按 source 返回 [{label, value}]），
    需要动态选项的工具覆写
"""
from abc import ABC, abstractmethod


class BaseTool(ABC):
    """工具抽象基类：定义工具的注册、校验、构建、执行协议"""

    # 自动注册表（子类创建时自动登记，key = type）
    _registry: dict[str, type] = {}

    def __init_subclass__(cls, **kwargs):
        """子类定义时自动注册到 _registry（按 type 去重，后者覆盖并警告）

        注册前校验：
        - type 为空（辅助类/中间抽象类）→ 跳过，不视为工具
        - 未实现抽象方法（validate_config/build_langchain/execute）→ WARNING + 拒绝注册
        - type 重复 → WARNING + 后者覆盖

        注意：__init_subclass__ 在类创建过程中调用，此时 cls.__abstractmethods__
        尚未设置（ABCMeta 在类创建后才计算），须通过基类 BaseTool.__abstractmethods__
        逐个检查子类是否覆写。
        """
        super().__init_subclass__(**kwargs)
        import logging
        logger = logging.getLogger(__name__)

        tool_type = getattr(cls, "type", "")
        if not tool_type:
            return  # 辅助类/中间抽象类，不视为工具
        # 未实现抽象方法 → 拒绝注册（避免工具出现在列表但调用时崩溃）
        missing = [
            n for n in BaseTool.__abstractmethods__
            if getattr(getattr(cls, n, None), "__isabstractmethod__", False)
        ]
        if missing:
            logger.warning(
                "工具类 %s 未实现抽象方法 %s，已跳过注册",
                cls.__name__, sorted(missing))
            return
        prev = BaseTool._registry.get(tool_type)
        if prev is not None and prev is not cls:
            logger.warning(
                "工具类型 %r 重复注册：%s 覆盖 %s", tool_type, cls, prev)
        BaseTool._registry[tool_type] = cls
        logger.info("工具已注册: type=%s class=%s", tool_type, cls.__name__)

    # 工具类型（注册表 key，与 schema 中 ToolConfig.type 对应）
    type: str = ""

    # 工具描述（给 LLM 判断是否调用）
    description: str = ""

    # 需要补全名称的配置字段：{config_key: response_key}
    # 例：rag 工具 {"kb_id": "kb_name"} → 注册表会查知识库名称并补全到响应
    name_ref_keys: dict[str, str] = {}

    # 内置能力标记：True = 不进入 tool-defs 接口（如 plan/reflect 走独立开关）
    builtin: bool = False

    # 参数描述列表（Schema 驱动前端动态表单，新增工具只需声明此处）：
    # [
    #   {"key": "kb_id", "label": "知识库", "type": "select",
    #    "required": True, "source": "knowledge_bases"},
    #   {"key": "top_k", "label": "检索块数", "type": "number",
    #    "default": 5, "min": 1, "max": 50},
    #   {"key": "mqe_enabled", "label": "多查询扩展", "type": "boolean", "default": False},
    # ]
    # type 取值：string | textarea | number | boolean | select
    param_schema: list[dict] = []

    @staticmethod
    async def fetch_options(db, user, source: str) -> list[dict]:
        """select 参数动态选项提供器：按 source 返回 [{label, value}, ...]

        参数:
            db: AsyncSession
            user: 当前用户
            source: param_schema 中 select 参数的 source 标识

        返回: 选项列表；未知 source 返回 []（默认实现，需要动态选项的工具覆写）
        """
        return []

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
    def execute(db, user, config: dict, **kwargs):
        """
        工具核心执行逻辑（simple_rag 等代码控制场景直接调用）

        非抽象方法：仅代码控制场景需要（如 rag 的预检索）；
        纯 LLM 自主调用型工具（如 plan/reflect）无需实现。

        参数:
            db: AsyncSession
            user: 当前用户
            config: 工具配置
            **kwargs: 子类按需扩展（如 rag 需要用户消息）

        返回: 工具输出（结构由各工具定义，如 rag 返回 list[Citation]）
        """
        raise NotImplementedError("execute 未实现（仅代码控制场景需要，如 rag 预检索）")
