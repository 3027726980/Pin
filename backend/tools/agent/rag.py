"""
Agent 工具：rag（知识库检索）

RAGTool：查询增强（MQE/HyDE）→ 批量向量化 → 多路粗召回 → 去重 → （可选 Rerank）精排 → 引用块

查询增强（Phase 4.6，独立开关，默认关闭，按需开启节省 token）：
  - MQE（mqe_enabled）：LLM 把用户问题改写为 n 个子问题，多路检索提升召回
  - HyDE（hyde_enabled）：LLM 生成假设回答文档作为检索线索
  - 增强 LLM：enhance_cfg（chat.py 透传，空 = 跟随对话模型）；失败降级仅用原始 query

Rerank（rerank_enabled）：粗召回 top_k*factor → RerankService 精排 → top_k
  （模型缺失/API 异常自动降级纯向量排序，不阻断对话）

默认值（config.yaml tools 节点）：
  top_k               → tools.default_top_k
  score_threshold     → tools.default_score_threshold
  mqe_enabled         → tools.default_mqe_enabled
  hyde_enabled        → tools.default_hyde_enabled
  mqe_query_count     → tools.default_mqe_query_count
  rerank_enabled      → tools.default_rerank_enabled
"""
import asyncio
import functools
import json
import logging
import time
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.utils import to_uuid
from backend.models import Users
from backend.repositories import DocumentRepo, KnowledgeBaseRepo, UserModelConfigRepo
from backend.schemas.agent import Citation
from backend.services.embedding import EmbeddingService
from backend.services.llm import LLMService
from backend.services.model_policy import current_turn_budget, model_requests_per_minute
from backend.services.rag_policy import RagPolicy, RetrievalSignals, resolve_rag_mode
from backend.services.rerank import RerankService
from backend.tools.common.base import BaseTool

logger = logging.getLogger(__name__)

# 工具描述（供 LLM 判断是否调用）
RAG_TOOL_DESCRIPTION = "检索知识库中与用户问题相关的资料片段，返回可能包含答案的引用内容。"

# ── 查询增强 Prompt（中文，低温调用保证改写稳定）──
_MQE_PROMPT_TEMPLATE = (
    "你是一个检索查询优化助手。请把下面的用户问题改写成 {n} 个不同角度的检索子问题，\n"
    "覆盖同义词替换、口语转书面、拆分子问题、补充隐含条件等，以提高知识库检索召回率。\n\n"
    "要求：\n"
    "- 只输出 JSON 字符串数组，如 [\"子问题1\", \"子问题2\", \"子问题3\"]\n"
    "- 不要输出解释、markdown 代码块标记或其他内容\n\n"
    "用户问题：{message}"
)

_HYDE_PROMPT_TEMPLATE = (
    "你是一个知识库检索助手。请根据下面的用户问题，写一段直接回答该问题的文字。\n"
    "这段文字将作为检索线索，内容应包含可能出现在知识库文档中的关键信息、术语和表述方式。\n\n"
    "要求：只输出回答正文，不要输出解释或其他内容。\n\n"
    "用户问题：{message}"
)


class RAGTool(BaseTool):
    """RAG 检索工具：查询增强 + 多路向量检索 + 可选 Rerank 精排，返回命中的引用块列表"""

    type = "rag"
    description = RAG_TOOL_DESCRIPTION
    # 配置中的 kb_id 需要补全知识库名称（响应 kb_name）
    name_ref_keys = {"kb_id": "kb_name"}

    # ── Phase 4.10 参数 Schema（前端动态表单渲染，与 ToolConfig 字段对齐）──
    param_schema: list[dict] = [
        {"key": "kb_id", "label": "知识库", "type": "select", "required": True,
         "source": "knowledge_bases"},
        {"key": "top_k", "label": "检索块数", "type": "number",
         "default": 5, "min": 1, "max": 50},
        {"key": "score_threshold", "label": "相似度阈值", "type": "number",
         "default": 0.3, "min": 0.0, "max": 1.0, "step": 0.05},
        {"key": "mqe_mode", "label": "多查询扩展 MQE", "type": "select",
         "default": "auto", "options": [
             {"label": "关闭", "value": "off"}, {"label": "自动（推荐）", "value": "auto"},
             {"label": "始终开启", "value": "always"}]},
        {"key": "hyde_mode", "label": "假设文档嵌入 HyDE", "type": "select",
         "default": "auto", "options": [
             {"label": "关闭", "value": "off"}, {"label": "自动（推荐）", "value": "auto"},
             {"label": "始终开启", "value": "always"}]},
        {"key": "mqe_query_count", "label": "MQE 子问题数", "type": "number",
         "default": 3, "min": 2, "max": 5},
        {"key": "rerank_mode", "label": "Rerank 精排", "type": "select",
         "default": "auto", "options": [
             {"label": "关闭", "value": "off"}, {"label": "自动（推荐）", "value": "auto"},
             {"label": "始终开启", "value": "always"}]},
    ]

    @staticmethod
    def _ensure_embedding_consistency(kb: object, emb_cfg: object) -> None:
        """检索前校验知识库保存的向量空间快照与当前配置一致。"""
        current_model = getattr(emb_cfg, "model_name", None)
        current_dimension = getattr(emb_cfg, "dimension", None)
        model_mismatch = bool(current_model) and current_model != kb.embedding_model
        dimension_mismatch = (
            current_dimension is not None
            and current_dimension != kb.embedding_dimension
        )
        if model_mismatch or dimension_mismatch:
            raise HTTPException(
                status_code=409,
                detail=(
                    "知识库 Embedding 配置与已生成向量不一致，请恢复原配置，"
                    "或使用新配置重新向量化全部文档"
                ),
            )

    @staticmethod
    async def fetch_options(db: AsyncSession, user: Users, source: str) -> list[dict]:
        """select 参数动态选项：knowledge_bases → 当前用户启用状态的知识库列表

        未知 source 返回 []（默认实现由 BaseTool 提供，本工具覆写）
        """
        if source != "knowledge_bases":
            return []
        rows, _ = await KnowledgeBaseRepo.list_by_user(db, user.id, 1, 200)
        return [
            {"label": kb.name, "value": str(kb.id)}
            for kb in rows if kb.status == 1
        ]

    @staticmethod
    async def validate_config(db: AsyncSession, user: Users, config: dict, **kwargs) -> None:
        """
        校验工具配置：kb_id 存在 + 归属当前用户 + 未删除 + 启用

        Raises: HTTPException 404（不存在/已删除/无归属） / 400（已禁用）
        """
        kb_id = to_uuid(config.get("kb_id")) if config.get("kb_id") else None
        if kb_id is None:
            raise HTTPException(status_code=400, detail="rag 工具缺少 kb_id")
        kb = await KnowledgeBaseRepo.get_by_id(db, kb_id)
        if kb is None or kb.status == 9 or kb.user_id != user.id:
            raise HTTPException(status_code=404, detail="知识库不存在")
        if kb.status == 0:
            raise HTTPException(status_code=400, detail="知识库已禁用")

    @staticmethod
    def build_langchain(db: AsyncSession, user: Users, config: dict, **kwargs):
        """
        构建 LangChain 工具（闭包绑定 db/user/config，供 create_agent 注册）

        额外参数（kwargs）:
            citations_store: 外部列表，工具执行结果追加至此（响应回传引用）
            enhance_cfg: 增强 LLM 配置（MQE/HyDE 用，空 = 跟随对话模型）
            rerank_cfg: Rerank 模型配置（空 = tools.rerank 全局默认）

        LLM 仅需提供 query 参数；工具异常时返回 JSON 错误信息（让 LLM 自行决定下一步）
        """
        from langchain_core.tools import tool

        citations_store = kwargs.get("citations_store")
        enhance_cfg = kwargs.get("enhance_cfg")
        rerank_cfg = kwargs.get("rerank_cfg")
        debug_store = kwargs.get("debug_store")  # 服务端始终采集，前端开关仅控制展示
        event_sink = kwargs.get("event_sink")

        @tool
        async def rag(query: str) -> str:
            """检索知识库资料；回答引用时必须使用结果中的 source_id 标记，如 [S1]。"""
            try:
                cits = await RAGTool.execute(
                    db, user, config, message=query,
                    enhance_cfg=enhance_cfg, rerank_cfg=rerank_cfg,
                    debug_store=debug_store, event_sink=event_sink)
            except HTTPException as e:
                return json.dumps({"error": e.detail}, ensure_ascii=False)
            if citations_store is not None:
                offset = len(citations_store)
                for index, citation in enumerate(cits, offset + 1):
                    citation.source_id = f"S{index}"
                citations_store.extend(cits)
            return json.dumps([c.model_dump(mode="json") for c in cits], ensure_ascii=False)

        return rag

    @staticmethod
    async def execute(
        db: AsyncSession,
        user: Users,
        config: dict,
        message: str,
        **kwargs,
    ) -> list[Citation]:
        """
        执行知识库检索（查询增强 → 多路召回 → 可选 Rerank 精排）

        参数:
            config: 工具配置 {kb_id, top_k, score_threshold,
                              mqe_enabled, hyde_enabled, mqe_query_count, rerank_enabled}
            message: 用户消息（作为检索 query）
            **kwargs:
                enhance_cfg: 增强 LLM 配置（None = 跳过增强）
                rerank_cfg: Rerank 模型配置（None = tools.rerank 全局默认）

        返回: 命中的引用块列表（已按 score 阈值过滤；rerank 开启时为精排结果）
        """
        kb_id = to_uuid(config.get("kb_id")) if config.get("kb_id") else None
        if kb_id is None:
            raise HTTPException(status_code=400, detail="rag 工具缺少 kb_id")
        budget = current_turn_budget()
        if budget is not None:
            budget.acquire_tool()
        top_k = config.get("top_k") or settings.tools.default_top_k
        score_threshold = (config.get("score_threshold")
                           if config.get("score_threshold") is not None
                           else settings.tools.default_score_threshold)

        # 三态模式优先；旧 enabled 仅作兼容映射。
        mqe_mode = resolve_rag_mode(config.get("mqe_mode"), config.get("mqe_enabled"))
        hyde_mode = resolve_rag_mode(config.get("hyde_mode"), config.get("hyde_enabled"))
        mqe_query_count = config.get("mqe_query_count") or settings.tools.default_mqe_query_count
        rerank_mode = resolve_rag_mode(config.get("rerank_mode"), config.get("rerank_enabled"))
        enhance_cfg = kwargs.get("enhance_cfg")
        rerank_cfg = kwargs.get("rerank_cfg")
        debug_store = kwargs.get("debug_store")  # 服务端始终采集，前端开关仅控制展示
        event_sink = kwargs.get("event_sink")
        stage_occurrences: dict[str, int] = {}

        async def emit_stage(stage: str, status: str, summary: str,
                             *, duration_ms: int | None = None,
                             visibility: str = "public", detail: dict | None = None) -> None:
            if event_sink is not None:
                if status == "running":
                    stage_occurrences[stage] = stage_occurrences.get(stage, 0) + 1
                occurrence = stage_occurrences.get(stage, 1)
                await event_sink({
                    "type": "stage", "stage": stage, "status": status,
                    "stage_id": f"{stage}.{occurrence}",
                    "summary": summary, "duration_ms": duration_ms,
                    "visibility": visibility, "detail": detail or {},
                })

        # 1. 知识库校验：归属 + 未删除 + 启用
        await RAGTool.validate_config(db, user, config)

        # 2. Embedding 配置校验
        kb = await KnowledgeBaseRepo.get_by_id(db, kb_id)
        if not kb.user_model_config_id:
            raise HTTPException(status_code=400, detail="知识库未配置 Embedding 模型")
        emb_cfg = await UserModelConfigRepo.get_by_id(db, kb.user_model_config_id)
        if emb_cfg is None or emb_cfg.user_id != user.id:
            raise HTTPException(status_code=400, detail="知识库未配置 Embedding 模型")
        RAGTool._ensure_embedding_consistency(kb, emb_cfg)

        # 3. 原始 query 先召回，策略只依据真实召回质量决策。
        started = time.perf_counter()
        await emit_stage("embedding", "running", "正在生成检索向量")
        original_vec = (await RAGTool._embed_queries(emb_cfg, [message]))[0]
        await emit_stage("embedding", "completed", "检索向量已生成",
                         duration_ms=round((time.perf_counter() - started) * 1000))
        max_dim = settings.embedding.max_dimension
        original_vec = RAGTool._pad_vector(original_vec, max_dim)
        candidate_limit = (
            top_k * settings.tools.rerank.factor
            if rerank_mode != "off" else top_k
        )
        started = time.perf_counter()
        await emit_stage("retrieval", "running", "正在检索原始问题")
        original_rows = await DocumentRepo.search_chunks(
            db, kb.id, original_vec, candidate_limit
        )
        await emit_stage("retrieval", "completed", "原始检索完成",
                         duration_ms=round((time.perf_counter() - started) * 1000),
                         detail={"candidate_count": len(original_rows)})
        accepted_original = [row for row in original_rows if row["score"] >= score_threshold]
        scores = [row["score"] for row in accepted_original]
        lower_message = message.lower()
        signals = RetrievalSignals(
            query_length=len(message.strip()),
            is_follow_up=any(token in message for token in ("那", "这个", "上述", "继续", "它", "前面")),
            is_multi_part=(len([part for part in message.replace("？", "?").split("?") if part.strip()]) > 1
                           or any(token in message for token in ("以及", "并且", "分别", "同时", "、"))),
            is_conceptual=any(token in lower_message for token in ("什么是", "定义", "概念", "原理", "why", "what is")),
            top1_score=max(scores) if scores else None,
            top3_avg=(sum(sorted(scores, reverse=True)[:3]) / min(3, len(scores))) if scores else None,
            above_threshold_count=len(scores),
            document_diversity=len({row["filename"] for row in accepted_original}),
            threshold=float(score_threshold),
        )
        rpm = (model_requests_per_minute(
            str(getattr(enhance_cfg, "provider", "")),
            str(getattr(enhance_cfg, "model_name", "")),
        ) if enhance_cfg is not None else None)
        auto_budget_available = (
            enhance_cfg is not None and rpm is None
            and (budget is None or budget.llm_calls_used + 2 <= budget.max_llm_calls)
        )
        decision = RagPolicy.decide(
            signals,
            mqe_mode=mqe_mode,
            hyde_mode=hyde_mode,
            rerank_mode=rerank_mode,
            auto_budget_available=auto_budget_available,
        )
        await emit_stage(
            "rag_strategy", "completed", f"检索策略：{decision.strategy}",
            visibility="debug",
            detail={"strategy": decision.strategy,
                    "reason_codes": list(decision.reason_codes)},
        )
        if not auto_budget_available:
            if mqe_mode == "auto":
                await emit_stage("mqe", "skipped", "MQE 因预算或模型配额跳过")
            if hyde_mode == "auto":
                await emit_stage("hyde", "skipped", "HyDE 因预算或模型配额跳过")

        # 4. 仅按策略执行增强；hybrid 在模型无低 RPM 限制时并行。
        enhanced_queries: list[str] = []

        async def run_mqe() -> list[str]:
            stage_started = time.perf_counter()
            await emit_stage("mqe", "running", "正在扩展检索问题")
            result = await RAGTool._expand_queries(enhance_cfg, message, mqe_query_count)
            await emit_stage(
                "mqe", "completed" if result else "degraded",
                f"MQE 生成 {len(result)} 个扩展问题" if result else "MQE 已降级",
                duration_ms=round((time.perf_counter() - stage_started) * 1000),
            )
            return result

        async def run_hyde() -> str | None:
            stage_started = time.perf_counter()
            await emit_stage("hyde", "running", "正在生成假设检索文档")
            result = await RAGTool._generate_hyde(enhance_cfg, message)
            await emit_stage(
                "hyde", "completed" if result else "degraded",
                "HyDE 假设文档已生成" if result else "HyDE 已降级",
                duration_ms=round((time.perf_counter() - stage_started) * 1000),
            )
            return result

        if enhance_cfg is not None and decision.strategy == "hybrid" and rpm is None:
            sub, hypo = await asyncio.gather(
                run_mqe(), run_hyde(),
            )
            enhanced_queries.extend(sub)
            if hypo:
                enhanced_queries.append(hypo)
        elif enhance_cfg is not None:
            if decision.strategy in {"mqe", "hybrid"}:
                enhanced_queries.extend(await run_mqe())
            if decision.strategy in {"hyde", "hybrid"}:
                hypo = await run_hyde()
                if hypo:
                    enhanced_queries.append(hypo)

        if debug_store is not None:
            debug_store["queries"] = [message, *enhanced_queries]
            debug_store["rag.strategy.selected"] = {
                "strategy": decision.strategy,
                "reason_codes": list(decision.reason_codes),
                "signals": {
                    "top1_score": signals.top1_score,
                    "top3_avg": signals.top3_avg,
                    "above_threshold_count": signals.above_threshold_count,
                    "document_diversity": signals.document_diversity,
                    "threshold": signals.threshold,
                },
                "modes": {"mqe": mqe_mode, "hyde": hyde_mode, "rerank": rerank_mode},
                "auto_budget_available": auto_budget_available,
            }

        # 5. 增强 query 批量向量化，并用一次 SQL 往返补充召回。
        seen: dict[UUID, tuple[str, str, float]] = {}
        RAGTool._merge_rows(seen, original_rows, score_threshold)
        if enhanced_queries:
            started = time.perf_counter()
            await emit_stage("embedding", "running", "正在生成增强检索向量")
            enhanced_vecs = [
                RAGTool._pad_vector(vec, max_dim)
                for vec in await RAGTool._embed_queries(emb_cfg, enhanced_queries)
            ]
            await emit_stage("embedding", "completed", "增强向量已生成",
                             duration_ms=round((time.perf_counter() - started) * 1000))
            started = time.perf_counter()
            await emit_stage("retrieval", "running", "正在补充检索")
            enhanced_rows = await DocumentRepo.search_chunks_multi(
                db, kb.id, enhanced_vecs, candidate_limit
            )
            await emit_stage("retrieval", "completed", "补充检索完成",
                             duration_ms=round((time.perf_counter() - started) * 1000),
                             detail={"candidate_count": len(enhanced_rows)})
            RAGTool._merge_rows(seen, enhanced_rows, score_threshold)

        if not seen:
            return []

        # 6. 精排 / 纯向量排序
        if decision.rerank:
            started = time.perf_counter()
            await emit_stage("rerank", "running", "正在精排候选资料")
            candidates = [
                {"chunk_id": str(cid), "content": content,
                 "filename": filename, "score": score}
                for cid, (content, filename, score) in seen.items()
            ]
            # RerankService 内部降级：模型缺失/异常 → 纯向量排序返回前 top_k
            ranked = await RerankService.rerank(rerank_cfg, message, candidates, top_k)
            await emit_stage("rerank", "completed", "候选资料精排完成",
                             duration_ms=round((time.perf_counter() - started) * 1000),
                             detail={"candidate_count": len(candidates), "result_count": len(ranked)})
            result = [
                Citation(
                    chunk_id=UUID(c["chunk_id"]),
                    document_name=c["filename"],
                    content=c["content"],
                    score=round(c["score"], 4),
                    original_score=round(c.get("original_score", c["score"]), 4),
                )
                for c in ranked
            ]
            if debug_store is not None:
                debug_store["rerank"] = {
                    "enabled": True,
                    "provider": getattr(rerank_cfg, "provider", None) or "local",
                    "model": getattr(rerank_cfg, "model_name", None)
                    or settings.local_models.rerank.model_name,
                }
            return result

        ranked = sorted(seen.items(), key=lambda kv: kv[1][2], reverse=True)[:top_k]
        return [
            Citation(
                chunk_id=cid,
                document_name=filename,
                content=content,
                score=round(score, 4),
                original_score=round(score, 4),
            )
            for cid, (content, filename, score) in ranked
        ]

    @staticmethod
    async def _embed_queries(emb_cfg: object, queries: list[str]) -> list[list[float]]:
        """在线程池批量向量化，避免同步 SDK 阻塞事件循环。"""
        return await asyncio.get_running_loop().run_in_executor(
            None,
            functools.partial(
                EmbeddingService.embed,
                provider=emb_cfg.provider,
                model_name=emb_cfg.model_name,
                api_key=emb_cfg.api_key,
                base_url=emb_cfg.base_url,
                texts=queries,
                protocol=emb_cfg.protocol,
            ),
        )

    @staticmethod
    def _pad_vector(vector: list[float], max_dim: int) -> list[float]:
        """将小维向量补零到数据库固定维度。"""
        return list(vector) + [0.0] * max(0, max_dim - len(vector))

    @staticmethod
    def _merge_rows(
        seen: dict[UUID, tuple[str, str, float]],
        rows: list[dict],
        threshold: float,
    ) -> None:
        """按 chunk_id 去重，保留所有检索路径中的最高原始分数。"""
        for row in rows:
            if row["score"] < threshold:
                continue
            chunk_id = row["chunk_id"]
            if chunk_id not in seen or row["score"] > seen[chunk_id][2]:
                seen[chunk_id] = (row["content"], row["filename"], row["score"])

    # ═══════════════════════════════════════════════
    # 查询增强（MQE / HyDE）
    # ═══════════════════════════════════════════════

    @staticmethod
    async def _call_enhance_llm(
        enhance_cfg: object, prompt: str, *, purpose: str
    ) -> str | None:
        """增强 LLM 统一调用：低温改写；推理模型 temperature 限制时自动用 1 重试一次

        返回回答文本；失败返回 None（调用方降级）
        """
        try:
            return await LLMService.chat(
                provider=enhance_cfg.provider,
                model_name=enhance_cfg.model_name,
                api_key=enhance_cfg.api_key,
                base_url=enhance_cfg.base_url,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                top_p=0.9,
                protocol=getattr(enhance_cfg, "protocol", None),
                max_tokens=getattr(enhance_cfg, "max_tokens", None),
                purpose=purpose,
            )
        except Exception as e:
            # 推理模型（kimi 等）只允许 temperature=1：降级重试一次
            from backend.services.chat import ChatService

            if ChatService._is_temperature_error(e):
                logger.warning("增强模型仅支持 temperature=1，自动用 1 重试: %s", e)
                try:
                    return await LLMService.chat(
                        provider=enhance_cfg.provider,
                        model_name=enhance_cfg.model_name,
                        api_key=enhance_cfg.api_key,
                        base_url=enhance_cfg.base_url,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=1.0,
                        top_p=0.9,
                        protocol=getattr(enhance_cfg, "protocol", None),
                        max_tokens=getattr(enhance_cfg, "max_tokens", None),
                        purpose=purpose,
                    )
                except Exception as e2:
                    logger.warning(f"增强 LLM 重试仍失败: {e2}")
                    return None
            logger.warning(f"增强 LLM 调用失败: {e}")
            return None

    @staticmethod
    async def _expand_queries(enhance_cfg: object, message: str, n: int) -> list[str]:
        """
        MQE：用增强 LLM 把用户问题改写为 n 个多角度检索子问题

        调用失败 / 输出解析失败 → 返回 []（调用方降级为仅原始 query，不阻断检索）
        """
        try:
            prompt = _MQE_PROMPT_TEMPLATE.format(n=n, message=message)
            text = await RAGTool._call_enhance_llm(
                enhance_cfg, prompt, purpose="mqe"
            )
            return RAGTool._parse_query_list(text or "")
        except Exception as e:
            logger.warning(f"MQE 改写调用失败: {e}")
            return []

    @staticmethod
    def _parse_query_list(text: str) -> list[str]:
        """
        解析 LLM 输出的 JSON 字符串数组（容错解析）

        兼容：纯 JSON / ```json 代码块包裹 / 前后有解释性文本（提取首个 [...]）
        解析失败 → []（降级）
        """
        if not text:
            return []
        cleaned = text.strip()
        # strip markdown 代码块围栏
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        # 提取首个 [...]（容忍前后多余文本）
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start != -1 and end > start:
            cleaned = cleaned[start:end + 1]
        try:
            data = json.loads(cleaned)
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        return [str(x).strip() for x in data if str(x).strip()]

    @staticmethod
    async def _generate_hyde(enhance_cfg: object, message: str) -> str | None:
        """
        HyDE：用增强 LLM 生成一段假设性回答文档（作为检索线索）

        调用失败 / 输出为空 → None（调用方跳过，不阻断检索）
        """
        try:
            prompt = _HYDE_PROMPT_TEMPLATE.format(message=message)
            text = await RAGTool._call_enhance_llm(
                enhance_cfg, prompt, purpose="hyde"
            )
            text = (text or "").strip()
            return text or None
        except Exception as e:
            logger.warning(f"HyDE 生成调用失败: {e}")
            return None
