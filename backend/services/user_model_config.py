"""
用户模型配置 业务逻辑
"""
import time
from types import SimpleNamespace
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Users
from backend.repositories import (
    GeneralAgentRepo,
    KnowledgeBaseRepo,
    SimpleRagAgentRepo,
    UserModelConfigRepo,
)
from backend.schemas.user_model_config import (
    UserModelConfigCreate,
    UserModelConfigResponse,
    UserModelConfigUpdate,
    DefaultModelConfigResponse,
    ModelConfigTestResponse,
)
from backend.services.embedding import EmbeddingService
from backend.core.config import settings
from backend.services.llm import LLMService


class UserModelConfigService:


    @staticmethod
    def _ensure_protocol(protocol: str | None) -> None:
        """校验调用模式（协议）在 config.yaml protocols 节点内"""
        if not protocol:
            return
        valid = {x.get("code") for x in getattr(settings, "protocols", None) or []}
        if protocol not in valid:
            raise HTTPException(
                status_code=400, detail=f"不支持的调用模式: {protocol}（config.yaml protocols 节点可配置）")

    @staticmethod
    async def test_config(user: Users, data: UserModelConfigCreate) -> ModelConfigTestResponse:
        """
        测试模型配置连通性（不落库，支持测试未保存的表单参数）

        按 model_type 分发：
          - 2 LLM：非流式发一条 ping 消息
          - 1 Embedding：向量化一个短文本，校验返回向量
          - 3 Rerank：对 query + 2 个假候选做精排（直接调实现，不走降级包装）

        任何异常 → ok=False + 截断的错误详情（不抛 HTTPException，测试失败是正常结果）
        """
        import time

        t0 = time.perf_counter()
        try:
            if data.model_type == 2:
                # 使用模型配置填写的采样参数（未填则走默认）；max_tokens 透传
                reply = await LLMService.chat(
                    provider=data.provider,
                    model_name=data.model_name,
                    api_key=data.api_key or "",
                    base_url=data.base_url,
                    messages=[{"role": "user", "content": "ping"}],
                    protocol=data.protocol,
                    temperature=data.temperature if data.temperature is not None else 0.7,
                    top_p=data.top_p if data.top_p is not None else 0.9,
                    max_tokens=data.max_tokens,
                )
                return ModelConfigTestResponse(
                    ok=True,
                    detail=f"连接成功，回复：{(reply or '').strip()[:50] or '(空回复)'}",
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )
            if data.model_type == 1:
                vectors = EmbeddingService.embed(
                    provider=data.provider,
                    model_name=data.model_name,
                    api_key=data.api_key or "",
                    base_url=data.base_url,
                    texts=["测试"],
                    protocol=data.protocol,
                )
                dim = len(vectors[0]) if vectors else 0
                if dim <= 0:
                    raise ValueError("返回向量为空")
                return ModelConfigTestResponse(
                    ok=True,
                    detail=f"连接成功，向量维度 {dim}",
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                    extra={"dimension": dim},
                )
            if data.model_type == 3:
                from backend.services.rerank import RERANK_IMPLEMENTATIONS

                impl = RERANK_IMPLEMENTATIONS.get(data.provider)
                if impl is None:
                    raise ValueError(
                        f"厂商 {data.provider} 暂不支持 Rerank（可选 local / aliyun）")
                candidates = [
                    {"chunk_id": "00000000-0000-0000-0000-000000000001",
                     "content": "测试文档一：Pin 是一个 AI 助手平台",
                     "filename": "测试.txt", "score": 0.1},
                    {"chunk_id": "00000000-0000-0000-0000-000000000002",
                     "content": "测试文档二：报销流程与制度说明",
                     "filename": "测试.txt", "score": 0.2},
                ]
                result = await impl.rerank(
                    SimpleNamespace(
                        provider=data.provider,
                        model_name=data.model_name,
                        api_key=data.api_key or "",
                        base_url=data.base_url,
                    ),
                    "测试查询", candidates, 2)
                if not result:
                    raise ValueError("Rerank 无返回结果")
                return ModelConfigTestResponse(
                    ok=True,
                    detail="连接成功，Rerank 正常返回",
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                )
            raise ValueError(f"暂不支持测试该模型类型（model_type={data.model_type}）")
        except Exception as e:
            return ModelConfigTestResponse(
                ok=False,
                detail=str(e)[:200],
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )

    @staticmethod
    async def list_defaults(db: AsyncSession) -> list[DefaultModelConfigResponse]:
        items = await UserModelConfigRepo.list_default_configs(db)
        return [DefaultModelConfigResponse.model_validate(c) for c in items]

    @staticmethod
    async def list_by_user(db: AsyncSession, user: Users) -> list[UserModelConfigResponse]:
        items = await UserModelConfigRepo.list_by_user(db, user.id)
        return [UserModelConfigResponse.model_validate(c) for c in items]

    @staticmethod
    async def create(db: AsyncSession, user: Users, data: UserModelConfigCreate) -> UserModelConfigResponse:
        await UserModelConfigService._ensure_base_url(db, data.provider, data.base_url)
        UserModelConfigService._ensure_protocol(data.protocol)
        cfg = await UserModelConfigRepo.create(
            db,
            user_id=user.id,
            provider=data.provider,
            model_name=data.model_name,
            model_type=data.model_type,
            base_url=data.base_url,
            api_key=data.api_key,
            dimension=data.dimension,
            protocol=data.protocol,
            temperature=data.temperature,
            top_p=data.top_p,
            max_tokens=data.max_tokens,
            is_active=data.is_active,
        )
        await db.commit()
        await db.refresh(cfg)  # 刷新 server_default 填充的 created_at/updated_at
        return UserModelConfigResponse.model_validate(cfg)

    @staticmethod
    async def _find_references(db: AsyncSession, cfg_id: UUID) -> tuple[list, list]:
        """
        查找引用该模型配置的知识库与 Agent（均未删除）

        返回 (kbs, agents)
        """
        kbs = await KnowledgeBaseRepo.find_by_model_config(db, cfg_id)
        agents = await GeneralAgentRepo.find_by_model_config(db, cfg_id)
        agents += await SimpleRagAgentRepo.find_by_model_config(db, cfg_id)
        return kbs, agents

    @staticmethod
    def _ref_error(kbs: list, agents: list) -> HTTPException:
        """组装引用冲突错误（409）"""
        parts = []
        if kbs:
            names = "、".join(kb.name for kb in kbs[:3])
            parts.append(f"{len(kbs)} 个知识库（{names}）")
        if agents:
            names = "、".join(a.name for a in agents[:3])
            parts.append(f"{len(agents)} 个 Agent（{names}）")
        return HTTPException(
            status_code=409,
            detail=f"该模型配置正被{'、'.join(parts)}引用，请先解除绑定后再操作",
        )

    @staticmethod
    async def _ensure_base_url(db: AsyncSession, provider: str, base_url: str | None) -> None:
        """
        自定义厂商（不在预置列表）必须填写接口地址

        预置厂商（config.yaml seed 的 default_model_config）有默认地址可推断，base_url 可空；
        自定义厂商无默认地址，不填会导致调用失败。
        """
        if base_url:
            return
        if await UserModelConfigRepo.exists_provider(db, provider):
            return
        raise HTTPException(status_code=400, detail="自定义厂商必须填写接口地址")

    @staticmethod
    async def update(db: AsyncSession, user: Users, cfg_id: UUID, data: UserModelConfigUpdate) -> UserModelConfigResponse:
        cfg = await UserModelConfigRepo.get_by_id(db, cfg_id)
        if cfg is None or cfg.user_id != user.id:
            raise HTTPException(status_code=404, detail="配置不存在")

        UserModelConfigService._ensure_protocol(data.protocol)
        # 仅当厂商变更时校验新厂商的 base_url（未变不重复校验）
        if data.provider is not None and data.provider != cfg.provider:
            await UserModelConfigService._ensure_base_url(db, data.provider, data.base_url)

        # 禁用前检查引用（知识库 + 两类 Agent）
        if data.is_active is False and cfg.is_active:
            kbs, agents = await UserModelConfigService._find_references(db, cfg_id)
            if kbs or agents:
                raise UserModelConfigService._ref_error(kbs, agents)

        cfg = await UserModelConfigRepo.update(
            db, cfg,
            provider=data.provider,
            model_name=data.model_name,
            model_type=data.model_type,
            base_url=data.base_url,
            api_key=data.api_key,
            dimension=data.dimension,
            protocol=data.protocol,
            temperature=data.temperature,
            top_p=data.top_p,
            max_tokens=data.max_tokens,
            is_active=data.is_active,
        )
        await db.commit()
        await db.refresh(cfg)  # 重新加载 onupdate 触发的 updated_at，避免 MissingGreenlet
        return UserModelConfigResponse.model_validate(cfg)

    @staticmethod
    async def delete(db: AsyncSession, user: Users, cfg_id: UUID) -> None:
        cfg = await UserModelConfigRepo.get_by_id(db, cfg_id)
        if cfg is None or cfg.user_id != user.id:
            raise HTTPException(status_code=404, detail="配置不存在")

        # 删除前检查引用（知识库 + 两类 Agent），避免外键冲突 500
        kbs, agents = await UserModelConfigService._find_references(db, cfg_id)
        if kbs or agents:
            raise UserModelConfigService._ref_error(kbs, agents)

        await UserModelConfigRepo.delete(db, cfg)
        await db.commit()
