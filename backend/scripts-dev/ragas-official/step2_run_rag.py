"""Step 2（官方方法）：用官方测试集驱动被测 RAG，收集评估样本

官方流程（docs.ragas.io → Evaluate a simple RAG system / Collect Evaluation Data）：
    对 testset 的每条 user_input 运行被测系统，收集
    {user_input, response, retrieved_contexts}（reference 随测试集保留）。

被测系统 = 项目 simple_rag Agent（ChatService 直调，新会话无记忆，429 指数退避）。
产物：responses/rag_run_<时间戳>.json（step3 官方 evaluate 的输入）。

用法：
    .venv/Scripts/python backend/scripts-dev/ragas-official/step2_run_rag.py [--testset <文件名子串>] [--limit N] [--throttle 秒]
"""
import argparse
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

import official_common as oc
from backend.schemas.agent import ChatRequest  # noqa: E402
from backend.services.chat import ChatService  # noqa: E402


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="官方测试集 × 被测 RAG 执行")
    parser.add_argument("--testset", default=None,
                        help="testsets/ 下测试集文件名子串（缺省取最新一个）")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 题")
    parser.add_argument("--throttle", type=float, default=0.0,
                        help="全局 HTTP 请求最小间隔秒数（低 RPM 厂商用）")
    return parser.parse_args()


def load_testset(name_or_path: str | None) -> tuple[Path, list[dict]]:
    """加载测试集 JSON（--testset 指定子串，缺省取 testsets/ 最新一个）"""
    oc.TESTSETS_DIR.mkdir(exist_ok=True)
    files = sorted(oc.TESTSETS_DIR.glob("testset_*.json"))
    if not files:
        raise RuntimeError("testsets/ 为空，请先运行 step1_gen_testset.py")
    target = None
    if name_or_path:
        p = Path(name_or_path)
        target = p if p.exists() else next(
            (f for f in files if name_or_path in f.name), None)
        if target is None:
            raise RuntimeError(f"未找到测试集 {name_or_path!r}，现有: {[f.name for f in files]}")
    else:
        target = files[-1]  # 文件名含时间戳，排序即最新
    data = json.loads(target.read_text(encoding="utf-8"))
    samples = data.get("samples") or []
    if not samples:
        raise RuntimeError(f"测试集无样本: {target}")
    return target, samples


async def run_rag_question(db, user, agent_id: str, question: str,
                           retries: int = 6) -> dict:
    """执行单题（新会话无记忆）：返回 answer 与召回切片原文，429 指数退避重试"""
    for attempt in range(retries + 1):
        try:
            resp = await ChatService.chat(
                db, user, agent_id, ChatRequest(message=question, debug=False))
            return {"response": resp.answer,
                    "retrieved_contexts": [c.content for c in resp.citations],
                    "retrieved_docs": [c.document_name for c in resp.citations]}
        except Exception as e:
            msg = str(e)
            retryable = ("429" in msg or "rate_limit" in msg.lower())
            if retryable and attempt < retries:
                wait = min(2 ** attempt, 30)
                print(f"    [429 限流] {wait}s 后重试（{attempt + 1}/{retries}）")
                await asyncio.sleep(wait)
                continue
            raise


async def main() -> None:
    """主流程：加载官方测试集 → 准备被测 Agent → 逐题收集 → 落盘"""
    args = parse_args()
    if args.throttle > 0:
        import httpx

        orig_send = httpx.AsyncClient.send
        lock = asyncio.Lock()
        last = {"t": 0.0}

        async def throttled_send(self, request, **kwargs):
            async with lock:
                wait = last["t"] + args.throttle - asyncio.get_event_loop().time()
                if wait > 0:
                    await asyncio.sleep(wait)
                last["t"] = asyncio.get_event_loop().time()
            return await orig_send(self, request, **kwargs)

        httpx.AsyncClient.send = throttled_send
        print(f"[THROTTLE] HTTP 间隔 {args.throttle}s")

    testset_path, samples = load_testset(args.testset)
    if args.limit:
        samples = samples[:args.limit]
    print(f"[TESTSET] {testset_path.name}（{len(samples)} 题）")

    cfg = oc.load_config()
    agent_id, _llm_cfg = await oc.prepare_rag_resources(cfg)

    out = []
    async with oc.async_session_local() as db:
        user = await oc.get_super_user(db)
        for i, s in enumerate(samples, 1):
            q = str(s["user_input"]).strip()
            print(f"\n===== RAG {i}/{len(samples)}: {q[:60]}")
            t0 = time.perf_counter()
            try:
                r = await run_rag_question(db, user, agent_id, q)
            except Exception as e:
                print(f"    [失败] 记为空答案继续: {str(e)[:150]}")
                r = {"response": "", "retrieved_contexts": [], "retrieved_docs": []}
            ms = int((time.perf_counter() - t0) * 1000)
            print(f"    response: {r['response'][:80]}...")
            print(f"    contexts: {len(r['retrieved_contexts'])} 片段 | {ms}ms")
            out.append({
                "user_input": q,
                "reference": str(s.get("reference") or ""),
                "reference_contexts": s.get("reference_contexts") or [],
                "synthesizer_name": str(s.get("synthesizer_name") or ""),
                **r,
                "ms": ms,
            })

    oc.RESULTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = oc.RESULTS_DIR / f"rag_run_{ts}.json"
    path.write_text(json.dumps(
        {"meta": {"testset": testset_path.name,
                  "agent": cfg["agents"]["simple_rag"],
                  "top_k": cfg["agents"].get("top_k", 4),
                  "finished_at": datetime.now().isoformat(timespec="seconds")},
         "samples": out}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[SAVE] 评估样本已保存: {path}（下一步 step3_evaluate.py）")


if __name__ == "__main__":
    asyncio.run(main())
