"""Agent 中间件轻量工厂

当前仅 SummarizationMiddleware:
- 触发/保留参数 + enabled 开关走 config.yaml(checkpoint.summarization)
- 总结模型为 Agent 级配置(summary_llm_config_id),空则跟随对话模型
- 未来新增中间件(如消息修剪):在此工厂加构建逻辑 + config.yaml 加配置块,chat.py 零改动

注意：langchain 依赖在函数内延迟 import（启动提速，仅首次对话时加载）。
"""
from backend.core.config import settings


def _build_summary_model(summary_llm_cfg, llm_cfg):
    """构建总结模型:Agent 配置的总结模型 ?? 对话模型"""
    from langchain_openai import ChatOpenAI

    cfg = summary_llm_cfg or llm_cfg
    return ChatOpenAI(
        model=cfg.model_name,
        api_key=cfg.api_key,
        base_url=cfg.base_url or "https://api.openai.com/v1",
        timeout=60.0,
    )


def build_middlewares(summary_llm_cfg, llm_cfg) -> list:
    """按 config.yaml + Agent 配置构建中间件列表"""
    from langchain.agents.middleware import SummarizationMiddleware

    sc = settings.checkpoint.summarization
    if not getattr(sc, "enabled", True):
        return []
    return [
        SummarizationMiddleware(
            model=_build_summary_model(summary_llm_cfg, llm_cfg),
            trigger=("messages", sc.trigger_message_count),
            keep=("messages", sc.keep_message_count),
        )
    ]
