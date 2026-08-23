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
import json
import logging
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
        debug_store = kwargs.get("debug_store")  # 调试信息收集器（request.debug=true 时传入）

        @tool
        async def rag(query: str) -> str:
            """检索知识库中与用户问题相关的资料片段，返回可能包含答案的引用内容。"""
            try:
                cits = await RAGTool.execute(
                    db, user, config, message=query,
                    enhance_cfg=enhance_cfg, rerank_cfg=rerank_cfg,
                    debug_store=debug_store)
            except HTTPException as e:
                return json.dumps({"error": e.detail}, ensure_ascii=False)
            if citations_store is not None:
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
        top_k = config.get("top_k") or settings.tools.default_top_k
        score_threshold = config.get("score_threshold") or settings.tools.default_score_threshold

        # 检索增强开关（独立控制，空 → config.yaml 默认）
        mqe_enabled = config.get("mqe_enabled")
        if mqe_enabled is None:
            mqe_enabled = settings.tools.default_mqe_enabled
        hyde_enabled = config.get("hyde_enabled")
        if hyde_enabled is None:
            hyde_enabled = settings.tools.default_hyde_enabled
        mqe_query_count = config.get("mqe_query_count") or settings.tools.default_mqe_query_count
        rerank_enabled = config.get("rerank_enabled")
        if rerank_enabled is None:
            rerank_enabled = settings.tools.default_rerank_enabled
        enhance_cfg = kwargs.get("enhance_cfg")
        rerank_cfg = kwargs.get("rerank_cfg")
        debug_store = kwargs.get("debug_store")  # 调试信息收集器（request.debug=true 时传入）

        # 1. 知识库校验：归属 + 未删除 + 启用
        await RAGTool.validate_config(db, user, config)

        # 2. Embedding 配置校验
        kb = await KnowledgeBaseRepo.get_by_id(db, kb_id)
        if not kb.user_model_config_id:
            raise HTTPException(status_code=400, detail="知识库未配置 Embedding 模型")
        emb_cfg = await UserModelConfigRepo.get_by_id(db, kb.user_model_config_id)
        if emb_cfg is None or emb_cfg.user_id != user.id:
            raise HTTPException(status_code=400, detail="知识库未配置 Embedding 模型")

        # 3. 构建检索 query 列表（原始 query 永远保留，增强只扩不替）
        queries = [message]
        if mqe_enabled and enhance_cfg is not None:
            sub = await RAGTool._expand_queries(enhance_cfg, message, mqe_query_count)
            if sub:
                queries.extend(sub)
            else:
                logger.warning("MQE 改写失败或结果为空，仅用原始 query 检索")
        if hyde_enabled and enhance_cfg is not None:
            hypo = await RAGTool._generate_hyde(enhance_cfg, message)
            if hypo:
                queries.append(hypo)
            else:
                logger.warning("HyDE 生成失败，跳过")

        # 调试信息：实际执行的检索 query 列表（原始 + MQE 子问题 + HyDE 假设文档）
        if debug_store is not None:
            debug_store["queries"] = list(queries)

        # 4. 批量向量化（多 query 一次调用）
        query_vecs = EmbeddingService.embed(
            provider=emb_cfg.provider,
            model_name=emb_cfg.model_name,
            api_key=emb_cfg.api_key,
            base_url=emb_cfg.base_url,
            texts=queries,
            protocol=emb_cfg.protocol,
        )
        max_dim = settings.embedding.max_dimension

        # 5. 多路粗召回：每路独立检索，按 chunk_id 去重（保留最高分）
        #    rerank 开启时放大候选集（top_k * factor），供精排挑选
        limit = top_k * settings.tools.rerank.factor if rerank_enabled else top_k
        seen: dict[UUID, tuple[str, str, float]] = {}
        for qv in query_vecs:
            if len(qv) < max_dim:
                qv = list(qv) + [0.0] * (max_dim - len(qv))
            rows = await DocumentRepo.search_chunks(db, kb.id, qv, limit)
            for r in rows:
                if r["score"] < score_threshold:
                    continue
                cid = r["chunk_id"]
                if cid not in seen or r["score"] > seen[cid][2]:
                    seen[cid] = (r["content"], r["filename"], r["score"])

        if not seen:
            return []

        # 6. 精排 / 纯向量排序
        if rerank_enabled:
            candidates = [
                {"chunk_id": str(cid), "content": content,
                 "filename": filename, "score": score}
                for cid, (content, filename, score) in seen.items()
            ]
            # RerankService 内部降级：模型缺失/异常 → 纯向量排序返回前 top_k
            ranked = await RerankService.rerank(rerank_cfg, message, candidates, top_k)
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

    # ═══════════════════════════════════════════════
    # 查询增强（MQE / HyDE）
    # ═══════════════════════════════════════════════

    @staticmethod
    async def _call_enhance_llm(enhance_cfg: object, prompt: str) -> str | None:
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
            text = await RAGTool._call_enhance_llm(enhance_cfg, prompt)
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
            text = await RAGTool._call_enhance_llm(enhance_cfg, prompt)
            text = (text or "").strip()
            return text or None
        except Exception as e:
            logger.warning(f"HyDE 生成调用失败: {e}")
            return None
