"""RAG 评估公共设施（scripts-dev/rag-eval 专用，独立自包含，不依赖 bench）

参考 bench_common.py 的成熟模式，仅保留评估所需能力（互不 import，避免耦合）：
- Windows SelectorEventLoop 修正（psycopg async 兼容）
- superuser 用户获取（同进程直调服务层，无需 JWT）
- 模型配置解析（LLM / judge / Embedding，支持 model_filter 子串与 auto_create）
- LLMUsageCapture：token / 调用次数捕获（logger 埋点 + LangChain callback 双通道）
- 全局 HTTP 节流（低 RPM 厂商）
- RAGEVAL 知识库 + docs 文档遍历上传 / simple_rag Agent 创建与配置重置
- 单题执行（新会话无记忆，返回 answer + citations 完整切片）
- 表格打印 + 结果 JSON 落盘 results/

环境自检（不调 LLM，验证 DB / 用户 / 模型配置 / handler）：
    .venv/Scripts/python backend/scripts-dev/rag-eval/eval_common.py
"""
import asyncio
import io
import json
import logging
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import func, select  # noqa: E402

from backend.core.database import async_session_local  # noqa: E402
from backend.models import (  # noqa: E402
    AgentIndex,
    Chunks,
    Documents,
    KnowledgeBases,
    UserModelConfig,
    Users,
)
from backend.schemas.agent import (  # noqa: E402
    ChatRequest,
    SimpleRagAgentCreate,
    AgentUpdate,
)
from backend.schemas.knowledge import KnowledgeBaseCreate  # noqa: E402
from backend.services.agent import AgentService  # noqa: E402
from backend.services.chat import ChatService  # noqa: E402
from backend.services.document_process import DocumentProcessService  # noqa: E402
from backend.services.knowledge import KnowledgeBaseService  # noqa: E402

from eval_config import load_config  # noqa: E402

RESULTS_DIR = Path(__file__).parent / "results"

_CFG = load_config()


# ── 用户与模型配置 ─────────────────────────

async def get_super_user(db) -> Users:
    """取第一个启用状态的 superuser（模型配置都在其名下，归属校验天然通过）"""
    user = (await db.execute(
        select(Users).where(Users.is_superuser.is_(True),
                            Users.is_active.is_(True))
    )).scalars().first()
    if user is None:
        raise RuntimeError("库中无启用状态的 superuser，请先用管理员账号初始化")
    return user


async def get_model_config(db, user: Users, model_type: int, required: bool,
                           name_contains: str | None = None):
    """按 model_type 取该用户第一条启用配置；required=True 且缺失时抛错提示

    参数:
        model_type: 1=Embedding / 2=LLM / 3=Rerank
        name_contains: 按 model_name 子串过滤（--model / --judge-model 切换配置）
    """
    stmt = select(UserModelConfig).where(
        UserModelConfig.user_id == user.id,
        UserModelConfig.model_type == model_type,
        UserModelConfig.is_active.is_(True))
    if name_contains:
        stmt = stmt.where(UserModelConfig.model_name.ilike(f"%{name_contains}%"))
    cfg = (await db.execute(stmt)).scalars().first()
    if cfg is None and required:
        raise RuntimeError(
            f"用户 {user.username} 名下没有 model_type={model_type} 的启用配置，"
            f"请先在前端「模型配置」页添加（1=Embedding / 2=LLM / 3=Rerank）")
    return cfg


async def _ensure_config(db, user: Users, node: dict, model_type: int,
                         fallback_filter: str | None = None):
    """按 yaml 配置节点解析某类模型配置：filter 子串匹配 > 自动创建 > 报错

    节点结构（llm / judge / embedding 通用）：
        model_filter: 库中 model_name 子串过滤
        auto_create: {provider, model_name, base_url, api_key}（api_key 非空时生效）
    fallback_filter：节点未配 model_filter 时回落（judge 缺省复用被测 LLM）
    """
    filt = node.get("model_filter") or fallback_filter
    cfg = await get_model_config(db, user, model_type, required=False,
                                 name_contains=filt)
    if cfg is not None:
        return cfg
    ac = node.get("auto_create") or {}
    if ac.get("api_key"):
        from backend.schemas.user_model_config import UserModelConfigCreate
        from backend.services.user_model_config import UserModelConfigService

        resp = await UserModelConfigService.create(db, user, UserModelConfigCreate(
            provider=ac["provider"], model_name=ac["model_name"],
            model_type=model_type, base_url=ac.get("base_url"),
            api_key=ac["api_key"]))
        await db.commit()
        print(f"[CONFIG] 已按 eval_config.yaml 自动创建模型配置: "
              f"{resp.provider}/{resp.model_name} (type={model_type})")
        return resp
    raise RuntimeError(
        f"库中无 model_type={model_type} 匹配配置（filter={filt!r}），"
        f"且 eval_config.yaml auto_create.api_key 为空")


async def ensure_chat_llm(db, user: Users):
    """解析被测 Agent 的生成 LLM 配置（eval_config.yaml llm 节点）"""
    return await _ensure_config(db, user, _CFG["llm"], 2)


async def ensure_judge_llm(db, user: Users):
    """解析评审 LLM 配置（judge 节点；未配 model_filter 时回落复用被测 LLM 配置）"""
    return await _ensure_config(db, user, _CFG.get("judge") or {}, 2,
                                fallback_filter=_CFG["llm"].get("model_filter"))


async def ensure_embedding(db, user: Users):
    """解析 Embedding 配置（embedding 节点；Answer Relevance 余弦计算用）"""
    return await _ensure_config(db, user, _CFG.get("embedding") or {}, 1)


# ── LLM token 捕获 ─────────────────────────

_TOKEN_RE = re.compile(r"prompt_tokens=(\d+) completion_tokens=(\d+)")


class LLMUsageCapture(logging.Handler):
    """挂 backend.llm logger 捕获非流式调用埋点（prompt_tokens/completion_tokens）

    覆盖 LLMService 直调（judge 评估调用 / MQE/HyDE 增强 / simple 档）；
    create_agent 主链路走 LangChain callback（见 install_langchain_hook）。
    用法：cap = LLMUsageCapture().attach() → ...调用... → cap.snapshot() → cap.detach()
    """

    def __init__(self):
        super().__init__()
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if "model=" not in msg or "error=None" not in msg:
            return
        m = _TOKEN_RE.search(msg)
        if m is None:  # 埋点行但无 usage（旧格式）：计次不计量
            self.calls += 1
            return
        self.calls += 1
        self.prompt_tokens += int(m.group(1))
        self.completion_tokens += int(m.group(2))

    def attach(self) -> "LLMUsageCapture":
        lg = logging.getLogger("backend.llm")
        # 脚本进程未跑 main.py 日志初始化，默认 WARNING 会丢弃 INFO 埋点
        lg.setLevel(logging.INFO)
        if self not in lg.handlers:  # 防重（重复挂载会双计）
            lg.addHandler(self)
        return self

    def detach(self) -> None:
        logging.getLogger("backend.llm").removeHandler(self)

    def snapshot(self) -> dict:
        return {"calls": self.calls, "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens}

    def reset(self) -> None:
        self.calls = self.prompt_tokens = self.completion_tokens = 0


_CAPTURE = LLMUsageCapture()
_HOOK_INSTALLED = False


def install_langchain_hook() -> None:
    """patch ChatService._thread_config，向 ainvoke config 注入 token 捕获 callback

    create_agent 主链路走 langchain-openai ChatOpenAI，不经过 LLMService 日志
    埋点；LangGraph config 支持 callbacks，on_llm_end 从 llm_output.token_usage
    拿到 usage。脚本侧 patch，产品代码零改动，仅首次调用时安装。
    """
    global _HOOK_INSTALLED
    if _HOOK_INSTALLED:
        return
    from langchain_core.callbacks import BaseCallbackHandler

    class _LCUsageHandler(BaseCallbackHandler):
        """on_llm_end 累计 create_agent 主链路的 prompt/completion tokens"""

        def on_llm_end(self, response, *args, **kwargs) -> None:
            out = getattr(response, "llm_output", None) or {}
            usage = out.get("token_usage") or {}
            _CAPTURE.calls += 1
            _CAPTURE.prompt_tokens += int(usage.get("prompt_tokens") or 0)
            _CAPTURE.completion_tokens += int(usage.get("completion_tokens") or 0)

    from backend.services.chat import ChatService

    orig = ChatService.__dict__["_thread_config"].__func__

    def _patched_thread_config(conv):
        cfg = orig(conv)
        cfg["callbacks"] = [_LCUsageHandler()]
        return cfg

    ChatService._thread_config = staticmethod(_patched_thread_config)
    _CAPTURE.attach()  # logger 通道：LLMService 直调（judge/增强/simple 档）
    _HOOK_INSTALLED = True


def capture_snapshot_and_reset() -> dict:
    """取当前累计 token 快照并清零（调用方负责 RAG / judge 阶段分段统计）"""
    snap = _CAPTURE.snapshot()
    _CAPTURE.reset()
    return snap


# ── 全局 HTTP 节流 ────────────────────────

_throttle_state = {"last": 0.0, "seconds": 0.0, "lock": None, "installed": False}


def install_throttle(seconds: float) -> None:
    """patch httpx.AsyncClient.send：所有 LLM API HTTP 请求全局最小间隔

    覆盖 create_agent 主链路（ChatOpenAI）、LLMService 直调（judge/增强）与
    OpenAI 兼容 Embedding（同为 httpx）。seconds=0 不安装。
    """
    if seconds <= 0 or _throttle_state["installed"]:
        return
    import httpx

    _throttle_state["seconds"] = seconds
    _throttle_state["lock"] = asyncio.Lock()
    _orig_send = httpx.AsyncClient.send

    async def _throttled_send(self, request, **kwargs):
        async with _throttle_state["lock"]:
            wait = (_throttle_state["last"] + _throttle_state["seconds"]
                    - asyncio.get_event_loop().time())
            if wait > 0:
                await asyncio.sleep(wait)
            _throttle_state["last"] = asyncio.get_event_loop().time()
        return await _orig_send(self, request, **kwargs)

    httpx.AsyncClient.send = _throttled_send
    _throttle_state["installed"] = True
    print(f"[THROTTLE] 全局 HTTP 请求间隔已设为 {seconds}s")


def throttle_seconds() -> float:
    """--throttle <秒> 命令行参数：全局 HTTP 请求最小间隔（低 RPM 厂商用）"""
    if "--throttle" in sys.argv:
        i = sys.argv.index("--throttle")
        if i + 1 < len(sys.argv):
            return float(sys.argv[i + 1])
    return 0.0


# ── RAGEVAL 资源准备 ──────────────────────

# 增强开关组（与 bench_rag_enhance 同语义；D 组的 Rerank 按库中配置动态决定）
# 改组 = 改本字典（如需“仅Rerank”组自行增加 E）
GROUP_FLAGS: dict[str, dict] = {
    "A": {"mqe_enabled": False, "hyde_enabled": False, "rerank_enabled": False},
    "B": {"mqe_enabled": True, "hyde_enabled": False, "rerank_enabled": False},
    "C": {"mqe_enabled": False, "hyde_enabled": True, "rerank_enabled": False},
}


def _make_upload(filename: str, text: str):
    """构造 UploadFile（走真实上传链路：写磁盘 + 建文档记录）"""
    from fastapi import UploadFile
    return UploadFile(file=io.BytesIO(text.encode("utf-8")), filename=filename)


async def ensure_eval_kb(db, user: Users):
    """确保 RAGEVAL 知识库存在且 docs_dir 下文档已全部向量化；返回 kb ORM

    复跑时文档齐全且已向量化 → 直接复用（不重复花 embedding）；
    缺失或未向量化 → 补传 + auto_process（解析/分块/向量化全链路）。
    """
    from eval_config import load_docs

    kb_name = _CFG["kb"]["name"]
    kb = (await db.execute(
        select(KnowledgeBases).where(KnowledgeBases.name == kb_name,
                                     KnowledgeBases.user_id == user.id,
                                     KnowledgeBases.status == 1)
    )).scalars().first()
    if kb is None:
        kb = await KnowledgeBaseService.create(
            db, user, KnowledgeBaseCreate(
                name=kb_name, description="Ragas 指标评估自动创建，可随时删除",
                chunk_size=_CFG["kb"]["chunk_size"],
                chunk_overlap=_CFG["kb"]["chunk_overlap"],
                chunk_separators=_CFG["kb"]["chunk_separators"]))
        print(f"[KB] 已创建知识库: {kb_name} ({kb.id}) "
              f"(chunk_size={kb.chunk_size}, overlap={kb.chunk_overlap})")
    else:
        if (kb.chunk_size != _CFG["kb"]["chunk_size"]
                or kb.chunk_overlap != _CFG["kb"]["chunk_overlap"]):
            print(f"[KB][警告] eval_config.yaml 切片参数与现有库不一致 "
                  f"(库: chunk_size={kb.chunk_size}/overlap={kb.chunk_overlap}，"
                  f"配置: {_CFG['kb']['chunk_size']}/{_CFG['kb']['chunk_overlap']})；"
                  f"如需生效请删除知识库 {kb_name} 后重跑（将重新向量化）")
        print(f"[KB] 复用已有知识库: {kb_name} ({kb.id})")

    docs = (await db.execute(
        select(Documents).where(Documents.knowledge_base_id == kb.id,
                                Documents.status == 1)
    )).scalars().all()
    done = {d.filename for d in docs if d.is_vectorized == 1}
    for fname, text in load_docs(_CFG).items():
        if fname in done:
            continue
        print(f"[DOC] 上传并处理: {fname} ...")
        item = await KnowledgeBaseService.upload_file(
            db, user, kb.id, _make_upload(fname, text))
        await DocumentProcessService.auto_process_document(str(kb.id), str(item.id))
    return kb


async def ensure_eval_agent(db, user: Users, llm_cfg, kb,
                            **enhance_flags) -> str:
    """创建/重置 simple_rag 类型 RAGEVAL Agent（按名复用并重置配置），返回 agent_id

    复跑时用 AgentUpdate 全量覆盖 llm_config_id/top_k/score_threshold 与
    enhance_flags（mqe_enabled/hyde_enabled/rerank_enabled/rerank_config_id），
    保证每次评估的检索参数与增强开关与传入值完全一致（组间状态不残留）。
    """
    name = _CFG["agents"]["simple_rag"]
    top_k = int(_CFG["agents"].get("top_k", 4))
    threshold = float(_CFG["agents"].get("score_threshold", 0.3))
    row = (await db.execute(
        select(AgentIndex).where(AgentIndex.name == name,
                                 AgentIndex.user_id == user.id,
                                 AgentIndex.status == 1)
    )).scalars().first()
    if row is None:
        resp = await AgentService.create(db, user, SimpleRagAgentCreate(
            name=name, description="Ragas 指标评估 simple_rag Agent",
            kb_id=kb.id, llm_config_id=llm_cfg.id,
            top_k=top_k, score_threshold=threshold, **enhance_flags))
        agent_id = str(resp.id)
        print(f"[AGENT] 已创建 {name} ({agent_id})")
    else:
        agent_id = str(row.id)
        print(f"[AGENT] 复用 {name} ({agent_id})")
    await AgentService.update(db, user, agent_id, AgentUpdate(
        llm_config_id=str(llm_cfg.id), top_k=top_k, score_threshold=threshold,
        **enhance_flags))
    await db.commit()
    return agent_id


async def build_groups(db, user: Users) -> dict[str, dict]:
    """构建增强开关组定义：{组字母: {"name": 组名, "flags": AgentUpdate 开关字典}}

    A 基线(全关) / B 仅MQE / C 仅HyDE / D 全开（MQE+HyDE+Rerank）。
    D 组依赖库中 Rerank 配置（model_type=3）：有 → rerank_enabled=True +
    rerank_config_id；无 → 退化为 MQE+HyDE 并在组名注明。
    """
    groups: dict[str, dict] = {
        "A": {"name": "A 基线(全关)", "flags": dict(GROUP_FLAGS["A"])},
        "B": {"name": "B 仅MQE", "flags": dict(GROUP_FLAGS["B"])},
        "C": {"name": "C 仅HyDE", "flags": dict(GROUP_FLAGS["C"])},
    }
    rerank_cfg = await get_model_config(db, user, 3, required=False)
    if rerank_cfg is not None:
        groups["D"] = {"name": "D 全开(MQE+HyDE+Rerank)",
                       "flags": {"mqe_enabled": True, "hyde_enabled": True,
                                 "rerank_enabled": True,
                                 "rerank_config_id": str(rerank_cfg.id)}}
    else:
        groups["D"] = {"name": "D 全开(MQE+HyDE，无Rerank配置)",
                       "flags": {"mqe_enabled": True, "hyde_enabled": True,
                                 "rerank_enabled": False}}
    return groups


# ── 单题执行 ──────────────────────────────

async def run_rag_question(db, user: Users, agent_id: str, text: str,
                           retries: int = 6) -> dict:
    """执行单题（新会话无记忆）：计时 + token 快照，返回 RAG 链路原始产物

    返回:
        dict: {text, answer, citations(含 chunk 原文/精排分/原始向量分), ms, tokens}
        citations.content 即 Ragas 指标的 contexts。

    429 限流（低 RPM 厂商）指数退避重试；失败调用无 usage 写入，重试不重复计数。
    """
    install_langchain_hook()
    t0 = time.perf_counter()
    for attempt in range(retries + 1):
        _CAPTURE.reset()
        try:
            resp = await ChatService.chat(
                db, user, agent_id, ChatRequest(message=text, debug=False))
            ms = int((time.perf_counter() - t0) * 1000)
            return {
                "text": text, "answer": resp.answer,
                "citations": [
                    {"chunk_id": str(c.chunk_id), "document_name": c.document_name,
                     "content": c.content, "score": c.score,
                     "original_score": c.original_score}
                    for c in resp.citations],
                "ms": ms, "tokens": capture_snapshot_and_reset(),
            }
        except Exception as e:
            msg = str(e)
            retryable = ("429" in msg or "rate_limit" in msg.lower()
                         or "max RPM" in msg)
            if retryable and attempt < retries:
                wait = min(2 ** attempt, 30)
                print(f"    [429 限流] {wait}s 后重试（{attempt + 1}/{retries}）")
                await asyncio.sleep(wait)
                continue
            raise
        finally:
            _CAPTURE.reset()


# ── 输出 ───────────────────────────────────

def _disp_width(s: str) -> int:
    """显示宽度（全角字符按 2 计）"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s: str, width: int, align: str = "left") -> str:
    """定宽填充（中文对齐）"""
    fill = " " * max(0, width - _disp_width(str(s)))
    return f"{s}{fill}" if align == "left" else f"{fill}{s}"


def print_table(headers: list[str], rows: list[list]) -> None:
    """对齐打印表格（中文宽度自适应）"""
    widths = [_disp_width(str(h)) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], _disp_width(str(cell)))
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    print(sep)
    print("| " + " | ".join(_pad(h, widths[i]) for i, h in enumerate(headers)) + " |")
    print(sep)
    for row in rows:
        cells = [_pad(str(c), widths[i],
                      "right" if isinstance(row[i], (int, float)) else "left")
                 for i, c in enumerate(row)]
        print("| " + " | ".join(cells) + " |")
    print(sep)


def save_result(name: str, payload: dict, meta: dict | None = None) -> Path:
    """结果 JSON 落盘 results/；meta 元数据置于文件开头，返回文件路径"""
    RESULTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = RESULTS_DIR / f"{name}_{ts}.json"
    data = ({"meta": meta} if meta else {}) | payload
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print(f"\n[SAVE] 结果已保存: {path}")
    return path


# ── 问题集加载（兼容 bench 格式） ────────────

QUESTIONS_DIR = Path(__file__).parent / "questions"


def load_question_set(name_or_path: str | None = None) -> dict:
    """加载问题集 JSON：--questions 指定（路径或文件名子串），缺省取 questions/ 第一个

    搜索顺序：绝对/相对路径 → rag-eval/questions/ 文件名子串 → ../bench/questions/
    文件名子串（便利回退，与 docs_dir 默认复用 bench 文档的思路一致）。

    兼容 bench 问题集格式：text 必需；expect_doc / keyword_groups /
    reference_answer 等字段可选（ragas 指标 reference-free，仅 text 参与评分，
    其余字段原样保留在结果 detail 中供人工对照）。
    """
    QUESTIONS_DIR.mkdir(exist_ok=True)
    files = sorted(QUESTIONS_DIR.glob("*.json"))
    target: Path | None = None
    if name_or_path:
        p = Path(name_or_path)
        if p.exists():
            target = p
        else:
            bench_questions = Path(__file__).parent.parent / "bench" / "questions"
            target = next((f for f in files if name_or_path in f.name), None) \
                or next((f for f in sorted(bench_questions.glob("*.json"))
                         if name_or_path in f.name), None)
        if target is None:
            raise RuntimeError(
                f"未找到问题集 {name_or_path!r}；questions/ 现有: "
                f"{[f.name for f in files] or '（空）'}，"
                f"也可传 bench/questions 下文件的路径")
    else:
        if not files:
            raise RuntimeError(
                f"questions/ 目录为空: {QUESTIONS_DIR}；请放入问题集 JSON，"
                f"或用 --questions 指向 bench/questions 下的文件")
        target = files[0]

    data = json.loads(target.read_text(encoding="utf-8"))
    questions = []
    for i, q in enumerate(data.get("questions", []), 1):
        text = (q.get("text") or "").strip()
        if not text:
            raise RuntimeError(f"问题集 {target.name} 第 {i} 条缺少 text 字段")
        questions.append({**q, "text": text})
    if not questions:
        raise RuntimeError(f"问题集 {target.name} 的 questions 为空")
    data["questions"] = questions
    data["_file"] = str(target)
    return data


# ── 自检 ───────────────────────────────────

async def _selfcheck() -> None:
    """环境自检：DB 连接 / superuser / 三类模型配置 / handler 挂载（不调 LLM 不花钱）"""
    async with async_session_local() as db:
        user = await get_super_user(db)
        print(f"[OK] 数据库连接正常，superuser: {user.username}")

        llm = await ensure_chat_llm(db, user)
        print(f"[OK] 被测 LLM 配置: {llm.provider} / {llm.model_name}")
        judge = await ensure_judge_llm(db, user)
        print(f"[OK] 评审 LLM 配置: {judge.provider} / {judge.model_name}")
        emb = await ensure_embedding(db, user)
        print(f"[OK] Embedding 配置: {emb.provider} / {emb.model_name}")

        kb = (await db.execute(
            select(KnowledgeBases).where(
                KnowledgeBases.name == _CFG["kb"]["name"],
                KnowledgeBases.user_id == user.id))).scalars().first()
        if kb is not None:
            chunk_count = (await db.execute(
                select(func.count()).select_from(Chunks).where(
                    Chunks.kb_id == kb.id, Chunks.status == 1))).scalar() or 0
            print(f"[OK] 评估知识库: {kb.name}（chunks={chunk_count}）")
        else:
            print(f"[--] 评估知识库 {_CFG['kb']['name']} 不存在（首跑自动创建）")

        cap = LLMUsageCapture().attach()
        cap.detach()
        cap.reset()
        print("[OK] usage 捕获 handler 挂载/卸载正常")
    print("\n环境自检通过。运行评估：")
    print("  .venv/Scripts/python backend/scripts-dev/rag-eval/eval_ragas.py [--quick]")


if __name__ == "__main__":
    asyncio.run(_selfcheck())
