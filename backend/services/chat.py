"""
对话编排服务：按 Agent 类型获取引用 → 组装 prompt → LLM 生成

- chat():       非流式，返回 ChatResponse
- chat_stream(): 流式，产出 SSE 事件 dict
- 类型分发：
  simple_rag：知识库直接绑定（kb_id/top_k/score_threshold 为表字段），构造 rag 工具配置执行
  general：执行 Agent.tools 工具列表（RAG 作为工具注册）
"""
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Users
from backend.repositories import (
    GeneralAgentRepo,
    SimpleRagAgentRepo,
    UserModelConfigRepo,
)
from backend.schemas.agent import ChatRequest, ChatResponse, Citation
from backend.services.llm import LLMService
from backend.tools import RAGTool, ToolRegistry

logger = logging.getLogger(__name__)


class ChatService:
    """对话编排：引用获取（按类型）+ prompt 组装 + LLM 生成"""

    # ═══════════════════════════════════════════════
    # 非流式
    # ═══════════════════════════════════════════════

    @staticmethod
    async def chat(
        db: AsyncSession,
        user: Users,
        agent_id: UUID,
        request: ChatRequest,
    ) -> ChatResponse:
        """
        非流式对话

        流程：定位 Agent（类型分发）→ 获取引用（simple_rag 直接检索 / general 执行工具）
              → 无输出短路 → 组装 prompt → LLM 生成
        """
        atype, agent, llm_cfg = await ChatService._load_agent_context(db, user, agent_id)
        citations = await ChatService._collect_citations(db, user, atype, agent, request.message)

        # 无工具输出 → 短路返回，不调 LLM
        if not citations:
            return ChatResponse(answer="知识库中没有相关信息。", citations=[])

        messages = ChatService._build_messages(agent, request, citations)
        try:
            answer = await LLMService.chat(
                provider=llm_cfg.provider,
                model_name=llm_cfg.model_name,
                api_key=llm_cfg.api_key,
                base_url=llm_cfg.base_url,
                messages=messages,
                temperature=agent.temperature,
                top_p=agent.top_p,
            )
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            raise HTTPException(status_code=502, detail=f"LLM 服务调用失败: {e}")

        return ChatResponse(answer=answer, citations=citations)

    # ═══════════════════════════════════════════════
    # 流式
    # ═══════════════════════════════════════════════

    @staticmethod
    async def chat_stream(
        db: AsyncSession,
        user: Users,
        agent_id: UUID,
        request: ChatRequest,
    ) -> AsyncIterator[dict]:
        """
        流式对话，产出 SSE 事件 dict

        事件序列：{"type": "delta", "content": ...} × N
                 → {"type": "citations", "citations": [...]}
                 → {"type": "done"}
        """
        atype, agent, llm_cfg = await ChatService._load_agent_context(db, user, agent_id)
        citations = await ChatService._collect_citations(db, user, atype, agent, request.message)

        if not citations:
            yield {"type": "delta", "content": "知识库中没有相关信息。"}
            yield {"type": "citations", "citations": []}
            yield {"type": "done"}
            return

        messages = ChatService._build_messages(agent, request, citations)
        try:
            async for delta in LLMService.chat_stream(
                provider=llm_cfg.provider,
                model_name=llm_cfg.model_name,
                api_key=llm_cfg.api_key,
                base_url=llm_cfg.base_url,
                messages=messages,
                temperature=agent.temperature,
                top_p=agent.top_p,
            ):
                yield {"type": "delta", "content": delta}
        except Exception as e:
            logger.error(f"LLM 流式调用失败: {e}")
            yield {"type": "error", "code": 502, "message": f"LLM 服务调用失败: {e}"}
            yield {"type": "done"}
            return

        yield {"type": "citations", "citations": [c.model_dump() for c in citations]}
        yield {"type": "done"}

    # ═══════════════════════════════════════════════
    # 内部工具
    # ═══════════════════════════════════════════════

    @staticmethod
    async def _load_agent_context(
        db: AsyncSession,
        user: Users,
        agent_id: UUID,
    ) -> tuple[str, object, object]:
        """
        定位 Agent（按类型）并校验 LLM 配置

        返回 (type, agent_orm, llm_cfg)
        Raises: HTTPException 404/400
        """
        # 先查 general，再查 simple_rag
        agent = await GeneralAgentRepo.get_by_id(db, agent_id)
        atype = "general"
        if agent is None or agent.status == 9 or agent.user_id != user.id:
            agent = await SimpleRagAgentRepo.get_by_id(db, agent_id)
            atype = "simple_rag"

        if agent is None or agent.status == 9 or agent.user_id != user.id:
            raise HTTPException(status_code=404, detail="Agent 不存在")
        if agent.status == 0:
            raise HTTPException(status_code=400, detail="Agent 已禁用")

        # general 类型校验工具 type 合法（simple_rag 无工具列表）
        if atype == "general":
            for tool in agent.tools:
                if tool.get("type") not in ToolRegistry.TOOLS:
                    raise HTTPException(status_code=400, detail=f"不支持的工具类型: {tool.get('type')}")

        # LLM 配置校验
        llm_cfg = await UserModelConfigRepo.get_by_id(db, agent.llm_config_id)
        if llm_cfg is None or llm_cfg.user_id != user.id or llm_cfg.model_type != 2:
            raise HTTPException(status_code=400, detail="LLM 模型配置无效")
        if not llm_cfg.api_key:
            raise HTTPException(status_code=400, detail="LLM 配置缺少 API Key")

        return atype, agent, llm_cfg

    @staticmethod
    async def _collect_citations(
        db: AsyncSession,
        user: Users,
        atype: str,
        agent: object,
        message: str,
    ) -> list[Citation]:
        """
        按类型获取引用块

        simple_rag：构造 rag 工具配置（kb_id/top_k/score_threshold 为表字段）直接执行
        general：执行 agent.tools 全部工具，合并输出
        """
        if atype == "simple_rag":
            config = {
                "type": "rag",
                "kb_id": str(agent.kb_id),
                "top_k": agent.top_k,
                "score_threshold": agent.score_threshold,
            }
            return await RAGTool.execute(db, user, config, message)

        tool_results = await ToolRegistry.execute_all(db, user, agent.tools, message)
        citations: list[Citation] = []
        for output in tool_results.values():
            if isinstance(output, list):
                citations.extend(output)
        return citations

    @staticmethod
    def _build_messages(
        agent: object,
        request: ChatRequest,
        citations: list[Citation],
    ) -> list[dict]:
        """
        组装 LLM messages

        system: agent.system_prompt（{agent_name} 占位替换）
        中间: history（最多最近 10 条）
        user:  引用块 + 用户问题
        """
        system_prompt = agent.system_prompt.replace("{agent_name}", agent.name)
        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        for h in request.history[-10:]:
            messages.append({"role": h.role, "content": h.content})

        messages.append({"role": "user", "content": ChatService._build_user_prompt(citations, request.message)})
        return messages

    @staticmethod
    def _build_user_prompt(citations: list[Citation], message: str) -> str:
        """组装带引用块的 user prompt"""
        parts = ["以下是知识库中可能与问题相关的资料片段：", ""]
        for i, c in enumerate(citations, 1):
            parts.append(f"[{i}] （来源：《{c.document_name}》）")
            parts.append(c.content)
            parts.append("")
        parts.append("请基于以上资料回答用户问题。回答中引用资料时标注对应编号。")
        parts.append('如果资料不足以回答，请直接说明"知识库中没有相关信息"。')
        parts.append("")
        parts.append(f"用户问题：{message}")
        return "\n".join(parts)
