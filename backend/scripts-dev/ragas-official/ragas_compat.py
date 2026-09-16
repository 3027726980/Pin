"""ragas 0.4.3 × langchain-community 0.4.x 兼容 shim（必须先于 ragas import 执行）

背景：ragas 0.4.3 在 ragas/llms/base.py 顶层 import `langchain_community.chat_models
.vertexai.ChatVertexAI` 与 `langchain_community.llms.VertexAI`，而项目锁定的
langchain-community 0.4.2 已将 vertexai 集成拆分到独立 partner 包，导致 ModuleNotFoundError。

方案：向 sys.modules 注入占位 stub（ragas 仅在 provider=vertex 的工厂分支引用这两个
类，本项目走 openai 兼容 provider，永远不会实例化它们）；待 ragas 官方适配
community 0.4.x 后可整体移除本文件。

用法：
    import ragas_compat
    ragas_compat.apply()
    import ragas  # 之后正常 import
"""
import sys
import types


def apply() -> None:
    """注入 vertexai 占位 stub（幂等；若 community 已恢复提供则不干预）"""
    try:
        import langchain_community.chat_models.vertexai  # noqa: F401
    except ModuleNotFoundError:
        mod = types.ModuleType("langchain_community.chat_models.vertexai")

        class ChatVertexAI:  # pragma: no cover - 占位类，本项目不触达
            """占位 stub：替代已从 langchain-community 0.4.x 移除的 ChatVertexAI"""

        mod.ChatVertexAI = ChatVertexAI
        sys.modules["langchain_community.chat_models.vertexai"] = mod

    import langchain_community.llms as _llms_mod

    if not hasattr(_llms_mod, "VertexAI"):

        class VertexAI:  # pragma: no cover - 占位类，本项目不触达
            """占位 stub：替代已从 langchain-community 0.4.x 移除的 VertexAI"""

        _llms_mod.VertexAI = VertexAI
