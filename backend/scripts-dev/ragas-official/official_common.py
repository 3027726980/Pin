"""Ragas 官方方法评估公共设施：配置加载 + 项目资源准备（superuser/模型配置/KB/Agent）

官方三步流程共用：
- load_config()：official_config.yaml（数据与逻辑分离）
- load_docs(cfg)：docs_dir 语料（官方 KnowledgeGraph 输入）
- resolve_generator_llm()：库中配置 → 官方 LangchainLLMWrapper(ChatOpenAI)
- resolve_embedding()：库中 api_key + 配置 backend → 官方 LangchainEmbeddingsWrapper
- ensure_eval_kb / ensure_eval_agent：被测 RAG 资源（与 rag-eval 同源命名，横向可比）

所有 ragas 入口脚本必须先 `ragas_compat.apply()` 再 import ragas。
"""
import asyncio
import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

# tiktoken 编码文件离线缓存（openaipublic.blob.core.windows.net 直连不稳，
# 首次经本地代理下载 cl100k_base 后全流程复用；文件名 = URL 的 sha1）
os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(Path(__file__).parent / "tiktoken_cache"))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import yaml  # noqa: E402

from backend.core.database import async_session_local  # noqa: E402
from backend.models import (  # noqa: E402
    AgentIndex,
    Documents,
    KnowledgeBases,
    UserModelConfig,
    Users,
)
from backend.schemas.agent import (  # noqa: E402
    SimpleRagAgentCreate,
    AgentUpdate,
)
from backend.schemas.knowledge import KnowledgeBaseCreate  # noqa: E402
from backend.services.agent import AgentService  # noqa: E402
from backend.services.document_process import DocumentProcessService  # noqa: E402
from backend.services.knowledge import KnowledgeBaseService  # noqa: E402
from sqlalchemy import select  # noqa: E402

OFFICIAL_DIR = Path(__file__).parent
CONFIG_PATH = OFFICIAL_DIR / "official_config.yaml"
TESTSETS_DIR = OFFICIAL_DIR / "testsets"
RESULTS_DIR = OFFICIAL_DIR / "results"


# ── 配置 ──────────────────────────────────

def load_config() -> dict:
    """读取 official_config.yaml 全量配置"""
    if not CONFIG_PATH.exists():
        raise RuntimeError(
            f"配置文件不存在: {CONFIG_PATH}，请复制 official_config.example.yaml")
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_docs(cfg: dict) -> dict[str, str]:
    """遍历 docs_dir 下全部 .txt 语料（官方 KnowledgeGraph 的输入）

    返回:
        dict[str, str]: {文件名: 文本内容}
    """
    docs_dir = (OFFICIAL_DIR / cfg["kb"]["docs_dir"]).resolve()
    if not docs_dir.exists():
        raise RuntimeError(f"语料目录不存在: {docs_dir}")
    docs = {p.name: p.read_text(encoding="utf-8") for p in sorted(docs_dir.glob("*.txt"))}
    if not docs:
        raise RuntimeError(f"语料目录为空: {docs_dir}")
    return docs


# ── 项目资源（同进程直调服务层，无需 JWT）──────────

async def get_super_user(db) -> Users:
    """取第一个启用状态的 superuser（模型配置归属校验天然通过）"""
    user = (await db.execute(
        select(Users).where(Users.is_superuser.is_(True),
                            Users.is_active.is_(True))
    )).scalars().first()
    if user is None:
        raise RuntimeError("库中无启用状态的 superuser，请先用管理员账号初始化")
    return user


async def get_model_config(db, user: Users, model_type: int, required: bool = True,
                           name_contains: str | None = None):
    """按 model_type 取该用户第一条启用配置（1=Embedding / 2=LLM）"""
    stmt = select(UserModelConfig).where(
        UserModelConfig.user_id == user.id,
        UserModelConfig.model_type == model_type,
        UserModelConfig.is_active.is_(True))
    if name_contains:
        stmt = stmt.where(UserModelConfig.model_name.ilike(f"%{name_contains}%"))
    cfg = (await db.execute(stmt)).scalars().first()
    if cfg is None and required:
        raise RuntimeError(
            f"用户 {user.username} 名下没有 model_type={model_type} 的启用配置")
    return cfg


async def resolve_llm_cfg(cfg: dict):
    """解析官方流程 LLM 配置（testset 生成与 evaluate 评审共用），返回 UserModelConfig"""
    node = cfg["llm"]
    async with async_session_local() as db:
        user = await get_super_user(db)
        llm = await get_model_config(db, user, 2, required=True,
                                     name_contains=node.get("model_filter"))
        if llm is None and (node.get("auto_create") or {}).get("api_key"):
            from backend.schemas.user_model_config import UserModelConfigCreate
            from backend.services.user_model_config import UserModelConfigService

            ac = node["auto_create"]
            resp = await UserModelConfigService.create(db, user, UserModelConfigCreate(
                provider=ac["provider"], model_name=ac["model_name"], model_type=2,
                base_url=ac.get("base_url"), api_key=ac["api_key"]))
            await db.commit()
            print(f"[CONFIG] 已自动创建 LLM 配置: {resp.provider}/{resp.model_name}")
            llm = resp
    if llm is None:
        raise RuntimeError("库中无匹配 LLM 配置，且 official_config.yaml auto_create 为空")
    return llm


async def resolve_embedding_api_key(cfg: dict) -> str:
    """从库中 embedding 配置读取 api_key（official_config.yaml 不存密钥）"""
    async with async_session_local() as db:
        user = await get_super_user(db)
        emb = await get_model_config(db, user, 1, required=False,
                                     name_contains=cfg["embedding"].get("model_filter"))
    if emb is None or not emb.api_key:
        raise RuntimeError("库中无 embedding 配置或 api_key 为空（本地模型可留空另议）")
    return emb.api_key


# ── 官方 wrapper 构建 ──────────────────────

def build_generator_llm(llm_cfg):
    """库中 LLM 配置 → 官方 LangchainLLMWrapper(ChatOpenAI)（OpenAI 兼容端点）"""
    from langchain_openai import ChatOpenAI
    from ragas.llms import LangchainLLMWrapper

    return LangchainLLMWrapper(ChatOpenAI(
        model=llm_cfg.model_name, api_key=llm_cfg.api_key,
        base_url=llm_cfg.base_url or None, temperature=0.4))


def build_embedding_model(cfg: dict, api_key: str):
    """配置 backend → 官方 LangchainEmbeddingsWrapper（KG transforms / AnswerRelevancy 用）

    参数:
        cfg: 配置树（embedding 节点）
        api_key: 库中 embedding 配置的 api_key（由调用方在 async 上下文预解析）
    """
    from ragas.embeddings import LangchainEmbeddingsWrapper

    node = cfg["embedding"]
    backend = node.get("backend", "dashscope")
    if backend == "dashscope":
        from langchain_community.embeddings import DashScopeEmbeddings

        return LangchainEmbeddingsWrapper(DashScopeEmbeddings(
            model=node["model_name"], dashscope_api_key=api_key))
    if backend == "local":
        from langchain_community.embeddings import HuggingFaceEmbeddings
        from backend.core.config import settings

        local_dir = Path(settings.local_models.cache_dir) / node["model_name"]
        return LangchainEmbeddingsWrapper(HuggingFaceEmbeddings(model_name=str(local_dir)))
    if backend == "openai":
        from langchain_openai import OpenAIEmbeddings

        return LangchainEmbeddingsWrapper(OpenAIEmbeddings(
            model=node["model_name"], api_key=api_key,
            base_url=node.get("base_url") or None))
    raise RuntimeError(f"未知 embedding backend: {backend}")


# ── 被测 RAG 资源（与 rag-eval 同源命名，保证横向可比）──────────

def _make_upload(filename: str, text: str):
    """构造 UploadFile（走真实上传链路）"""
    from fastapi import UploadFile
    return UploadFile(file=io.BytesIO(text.encode("utf-8")), filename=filename)


async def ensure_eval_kb(db, cfg: dict, user: Users):
    """确保评估知识库存在且语料已向量化（复跑复用，首跑自动全链路处理）"""
    kb_name = cfg["kb"]["name"]
    kb = (await db.execute(
        select(KnowledgeBases).where(KnowledgeBases.name == kb_name,
                                     KnowledgeBases.user_id == user.id,
                                     KnowledgeBases.status == 1)
    )).scalars().first()
    if kb is None:
        kb = await KnowledgeBaseService.create(
            db, user, KnowledgeBaseCreate(
                name=kb_name, description="Ragas 官方方法评估自动创建",
                chunk_size=cfg["kb"]["chunk_size"],
                chunk_overlap=cfg["kb"]["chunk_overlap"],
                chunk_separators=cfg["kb"]["chunk_separators"]))
        print(f"[KB] 已创建知识库: {kb_name} ({kb.id})")
    docs = (await db.execute(
        select(Documents).where(Documents.knowledge_base_id == kb.id,
                                Documents.status == 1)
    )).scalars().all()
    done = {d.filename for d in docs if d.is_vectorized == 1}
    for fname, text in load_docs(cfg).items():
        if fname in done:
            continue
        print(f"[DOC] 上传并处理: {fname} ...")
        item = await KnowledgeBaseService.upload_file(
            db, user, kb.id, _make_upload(fname, text))
        await DocumentProcessService.auto_process_document(str(kb.id), str(item.id))
    return kb


async def ensure_eval_agent(db, cfg: dict, user: Users, llm_cfg, kb) -> str:
    """创建/重置被测 simple_rag Agent（按名复用并全量重置配置），返回 agent_id"""
    name = cfg["agents"]["simple_rag"]
    top_k = int(cfg["agents"].get("top_k", 4))
    threshold = float(cfg["agents"].get("score_threshold", 0.3))
    row = (await db.execute(
        select(AgentIndex).where(AgentIndex.name == name,
                                 AgentIndex.user_id == user.id,
                                 AgentIndex.status == 1)
    )).scalars().first()
    if row is None:
        resp = await AgentService.create(db, user, SimpleRagAgentCreate(
            name=name, description="Ragas 官方方法评估 simple_rag Agent",
            kb_id=kb.id, llm_config_id=llm_cfg.id,
            top_k=top_k, score_threshold=threshold))
        agent_id = str(resp.id)
        print(f"[AGENT] 已创建 {name} ({agent_id})")
    else:
        agent_id = str(row.id)
        print(f"[AGENT] 复用 {name} ({agent_id})")
    await AgentService.update(db, user, agent_id, AgentUpdate(
        llm_config_id=str(llm_cfg.id), top_k=top_k, score_threshold=threshold))
    await db.commit()
    return agent_id


async def prepare_rag_resources(cfg: dict) -> tuple[str, object]:
    """一步到位准备被测 RAG 资源，返回 (agent_id, llm_cfg)"""
    llm_cfg = await resolve_llm_cfg(cfg)
    async with async_session_local() as db:
        user = await get_super_user(db)
        kb = await ensure_eval_kb(db, cfg, user)
        agent_id = await ensure_eval_agent(db, cfg, user, llm_cfg, kb)
    return agent_id, llm_cfg


async def resolve_llm_and_embedding(cfg: dict):
    """同一事件循环内解析 LLM 配置与 embedding api_key（全局 engine 连接池绑定 loop，
    多次 asyncio.run 会跨 loop 报错，必须合并为单次运行），返回 (llm_cfg, api_key)"""
    llm_cfg = await resolve_llm_cfg(cfg)
    api_key = await resolve_embedding_api_key(cfg)
    return llm_cfg, api_key
