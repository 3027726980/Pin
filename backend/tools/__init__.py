"""
工具包 — Agent 能力单元

结构：
  tools/__init__.py    ← ToolRegistry 注册表（统一调度：校验/构建/补全/定义收集）
  tools/common/        ← 通用工具类（BaseTool 抽象基类等）
  tools/agent/         ← Agent 可注册的工具（rag / plan / reflect 等，目录扫描自动注册）

新增工具流程（Phase 4.10 起，调用方零改动）：
  1. tools/agent/ 下新建工具类文件（继承 BaseTool：type/description/param_schema
     + validate_config/build_langchain/execute；select 参数需要动态选项时覆写 fetch_options）
  2. 完成 —— 自动注册（__init_subclass__ + 目录扫描）、tool-defs 接口、前端动态表单
     全部自动生效，无需修改任何其他文件
"""
from backend.tools.common.base import BaseTool
# 显式 import（触发 tools/agent 目录扫描自动注册；本模块引用这些类供 ChatService 等使用）
from backend.tools.agent.rag import RAGTool
from backend.tools.agent.plan import PlanTool
from backend.tools.agent.reflect import ReflectTool
from backend.core.utils import to_uuid
from backend.schemas.agent import ToolConfig
from fastapi import HTTPException


class ToolRegistry:
    """工具注册表：按 type 统一调度工具的校验、构建、补全、定义收集"""

    # 自动注册表（BaseTool.__init_subclass__ 维护，import 即注册）
    TOOLS: dict[str, type] = BaseTool._registry

    # ═══════════════════════════════════════════════
    # 目录同步（tool-defs 每次请求前调用：磁盘为真实状态，不依赖 reload）
    # ═══════════════════════════════════════════════

    @staticmethod
    def sync_from_disk() -> None:
        """重新扫描 tools/agent/ 目录，同步注册表：

        - 磁盘上有新模块（新增工具文件）→ import 注册
        - 磁盘上已删除的模块（工具文件被删）→ 注销其工具并从 sys.modules 移除
          （允许同名重建后重新加载）

        解决：运行时增删工具文件后，前端刷新 tool-defs 能即时反映，无需重启后端。
        """
        import importlib
        import logging
        import pkgutil
        import sys

        from backend.tools import agent as agent_pkg

        logger = logging.getLogger(__name__)

        # 1. 磁盘上当前的模块名
        disk_modules = {m.name for m in pkgutil.iter_modules(agent_pkg.__path__)}
        # 2. 新增模块 → import（触发 __init_subclass__ 自动注册）
        for name in sorted(disk_modules):
            full = f"{agent_pkg.__name__}.{name}"
            if full not in sys.modules:
                try:
                    importlib.import_module(full)
                except Exception:
                    logger.exception("工具模块 %s 导入失败，已跳过", name)
        # 3. 已删除模块 → 注销其注册的工具 + 清理 sys.modules
        removed_modules: set[str] = set()
        for tool_type, cls in list(ToolRegistry.TOOLS.items()):
            mod_name = getattr(cls, "__module__", "")
            if not mod_name.startswith(f"{agent_pkg.__name__}."):
                continue  # 非 tools/agent 包内的工具（理论不存在）
            short = mod_name.rsplit(".", 1)[-1]
            if short not in disk_modules:
                logger.warning(
                    "工具 %s（来源 %s 已被删除）已注销", tool_type, short)
                del ToolRegistry.TOOLS[tool_type]
                removed_modules.add(mod_name)
        for mod in removed_modules:
            sys.modules.pop(mod, None)

    # ═══════════════════════════════════════════════
    # 内部
    # ═══════════════════════════════════════════════

    @staticmethod
    def _get(tool_type: str) -> type:
        """按 type 取工具类，未知类型抛 400"""
        cls = ToolRegistry.TOOLS.get(tool_type)
        if cls is None:
            raise HTTPException(status_code=400, detail=f"不支持的工具类型: {tool_type}")
        return cls

    # ═══════════════════════════════════════════════
    # 工具定义收集（GET /agents/tool-defs 时调用）
    # ═══════════════════════════════════════════════

    @staticmethod
    async def collect_defs(db, user) -> list[dict]:
        """
        收集全部可配置工具定义（过滤 builtin），供前端动态表单渲染

        每次请求前先 sync_from_disk：磁盘目录为真实状态，
        新增/删除工具文件即时反映（前端刷新即可），无需重启后端。

        每个工具：{type, description, params}；
        select 参数调用工具类自身 fetch_options 填充选项（未知 source 返回空列表）。
        """
        ToolRegistry.sync_from_disk()
        result = []
        for tool_type, cls in sorted(ToolRegistry.TOOLS.items()):
            if getattr(cls, "builtin", False):
                continue
            params = []
            for p in cls.param_schema or []:
                p = dict(p)
                if p.get("type") == "select" and p.get("source"):
                    try:
                        options = await cls.fetch_options(db, user, p["source"])
                    except Exception:
                        options = []
                    p["options"] = options
                params.append(p)
            result.append({
                "type": tool_type,
                "description": cls.description,
                "params": params,
            })
        return result

    # ═══════════════════════════════════════════════
    # 配置校验（创建/编辑 Agent 时调用）
    # ═══════════════════════════════════════════════

    @staticmethod
    async def validate_all(db, user, tools: list[dict]) -> None:
        """
        校验工具列表中的全部工具配置

        每个工具调用自己的 validate_config（如 rag 校验知识库归属/状态）
        """
        for tool in tools:
            cls = ToolRegistry._get(tool.get("type"))
            await cls.validate_config(db, user, tool)

    # ═══════════════════════════════════════════════
    # LangChain 工具构建（general Agent 对话时调用）
    # ═══════════════════════════════════════════════

    @staticmethod
    def build_langchain_tools(
        db,
        user,
        tools: list[dict],
        **kwargs,
    ) -> list:
        """
        将工具配置列表构建为 LangChain 工具列表（供 create_agent 注册）

        每个工具调用自己的 build_langchain（闭包绑定 db/user/config）
        **kwargs 透传给各工具（如 citations_store），由工具自行决定是否使用
        """
        result = []
        for tool in tools:
            cls = ToolRegistry._get(tool.get("type"))
            result.append(cls.build_langchain(db, user, tool, **kwargs))
        return result

    # ═══════════════════════════════════════════════
    # 响应补全（列表/详情时调用）
    # ═══════════════════════════════════════════════

    @staticmethod
    def collect_refs(tools: list[dict]) -> dict[str, list]:
        """
        收集工具声明需要补全名称的引用 id

        按配置字段聚合：{"kb_id": [uuid, ...]}（rag 工具声明 name_ref_keys = {"kb_id": "kb_name"}）
        """
        refs: dict[str, list] = {}
        for tool in tools:
            cls = ToolRegistry._get(tool.get("type"))
            for cfg_key in cls.name_ref_keys:
                val = tool.get(cfg_key)
                if val:
                    refs.setdefault(cfg_key, []).append(to_uuid(val))
        return refs

    @staticmethod
    def enrich_tools(tools: list[dict], ref_names: dict[str, dict]) -> list[ToolConfig]:
        """
        工具配置 → ToolConfig 响应，按各工具声明的 name_ref_keys 补全名称

        参数:
            tools: 工具配置列表（来自 general_agents.tools）
            ref_names: 名称映射，如 {"kb_id": {uuid: name}}（由 collect_refs + 批量查询得到）
        """
        result = []
        for tool in tools:
            cfg = ToolConfig.model_validate(tool)
            cls = ToolRegistry._get(tool.get("type"))
            for cfg_key, resp_key in cls.name_ref_keys.items():
                val = tool.get(cfg_key)
                name_map = ref_names.get(cfg_key, {})
                setattr(cfg, resp_key, name_map.get(to_uuid(val)) if val else None)
            result.append(cfg)
        return result


__all__ = ["BaseTool", "RAGTool", "PlanTool", "ReflectTool", "ToolRegistry"]
