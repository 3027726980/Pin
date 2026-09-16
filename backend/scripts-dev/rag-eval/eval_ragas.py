"""RAG 质量评估主脚本：按 Ragas 论文三大指标评估 simple_rag Agent

流程：准备资源（KB/Agent/模型配置）→ 逐题 RAG（answer + citations）
→ 逐题三指标 judge → 控制台汇总表 + JSON 落盘 results/ragas_eval_<时间戳>.json

用法示例：
    # 全量评估（默认三大指标）
    .venv/Scripts/python backend/scripts-dev/rag-eval/eval_ragas.py

    # 冒烟（前 3 题）/ 限题数 / 单指标
    .venv/Scripts/python backend/scripts-dev/rag-eval/eval_ragas.py --quick
    .venv/Scripts/python backend/scripts-dev/rag-eval/eval_ragas.py --limit 5
    .venv/Scripts/python backend/scripts-dev/rag-eval/eval_ragas.py --metrics faithfulness

    # 换被测模型 / 换评审模型 / 低 RPM 厂商节流
    .venv/Scripts/python backend/scripts-dev/rag-eval/eval_ragas.py --model glm --judge-model kimi --throttle 21

    # 复用历史 RAG 结果仅重新评分（调 prompt / 换 judge 后不重跑 RAG 不花钱）
    .venv/Scripts/python backend/scripts-dev/rag-eval/eval_ragas.py --reuse results/ragas_eval_xxx.json
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

import eval_common as ec
from ragas_metrics import METRIC_NAMES, evaluate_sample


def parse_args() -> argparse.Namespace:
    """解析命令行参数（--help 查看全部）"""
    parser = argparse.ArgumentParser(
        description="Ragas 论文指标 RAG 质量评估（直调服务层，无需启动后端）")
    parser.add_argument("--questions", default=None,
                        help="问题集：路径或文件名子串；缺省用 rag-eval/questions/ 排序第一个")
    parser.add_argument("--model", default=None,
                        help="被测 LLM 按 model_name 子串切换（覆盖 eval_config.yaml llm.model_filter）")
    parser.add_argument("--judge-model", default=None,
                        help="评审 LLM 按 model_name 子串切换（覆盖 judge.model_filter）")
    parser.add_argument("--metrics", default=None,
                        help=f"逗号分隔指标子集（默认全部）：{','.join(METRIC_NAMES)}")
    parser.add_argument("--quick", action="store_true", help="只跑前 3 题（冒烟验证）")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 题")
    parser.add_argument("--reuse", default=None,
                        help="复用历史结果 JSON 的 RAG 产物仅重新评分（不调被测 Agent）")
    parser.add_argument("--throttle", type=float, default=None,
                        help="全局 HTTP 请求最小间隔秒数（覆盖 --throttle 默认逻辑，低 RPM 厂商用）")
    return parser.parse_args()


def resolve_metrics(arg: str | None) -> list[str]:
    """解析 --metrics 参数为合法指标列表（非法值直接报错）"""
    if not arg:
        return list(METRIC_NAMES)
    names = [s.strip() for s in arg.split(",") if s.strip()]
    bad = [n for n in names if n not in METRIC_NAMES]
    if bad:
        raise SystemExit(f"未知指标: {bad}，可选: {list(METRIC_NAMES)}")
    return [n for n in METRIC_NAMES if n in names]  # 保持论文顺序


def load_reuse_samples(path: str) -> tuple[list[dict], dict]:
    """加载 --reuse 的历史结果 JSON，提取每题 RAG 产物（answer/citations）"""
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"--reuse 文件不存在: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    detail = data.get("detail") or []
    if not detail:
        raise SystemExit(f"--reuse 文件缺少 detail 数组: {p}")
    samples = [{"text": d["text"], "answer": d["answer"],
                "citations": d.get("citations") or []} for d in detail]
    return samples, data.get("meta") or {}


def fmt_score(score) -> str:
    """分数格式化：None → '-'，否则保留 3 位小数"""
    return f"{score:.3f}" if isinstance(score, (int, float)) else "-"


async def main() -> None:
    """主流程：资源准备 → 逐题 RAG → 逐题评分 → 汇总落盘"""
    args = parse_args()
    seconds = args.throttle if args.throttle is not None else ec.throttle_seconds()
    ec.install_throttle(seconds)
    metrics = resolve_metrics(args.metrics)

    # ── 命令行覆盖配置节点（--model / --judge-model）──
    if args.model:
        ec._CFG["llm"]["model_filter"] = args.model
    if args.judge_model:
        ec._CFG.setdefault("judge", {})["model_filter"] = args.judge_model

    started_at: str | None = None
    questions_file: str | None = None
    rag_total_tokens = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
    reuse_meta: dict = {}

    # ── 阶段一：逐题 RAG（或复用历史）──
    if args.reuse:
        samples, reuse_meta = load_reuse_samples(args.reuse)
        if args.limit or args.quick:
            samples = samples[:args.limit or 3]
        print(f"[REUSE] 从 {args.reuse} 载入 {len(samples)} 题 RAG 产物，仅重新评分")
    else:
        started_at = ec.datetime.now().isoformat(timespec="seconds")
        async with ec.async_session_local() as db:
            user = await ec.get_super_user(db)
            llm_cfg = await ec.ensure_chat_llm(db, user)
            kb = await ec.ensure_eval_kb(db, user)
            agent_id = await ec.ensure_eval_agent(db, user, llm_cfg, kb)

            qset = ec.load_question_set(args.questions)
            questions_file = qset["_file"]
            limit = args.limit or (3 if args.quick else None)
            questions = qset["questions"][:limit] if limit else qset["questions"]
            print(f"\n[QSET] {qset.get('name', '')}（{len(questions)} 题）"
                  f" | 指标: {','.join(metrics)} | 检索 top_k={ec._CFG['agents'].get('top_k', 4)}")

            samples = []
            for i, q in enumerate(questions, 1):
                print(f"\n===== RAG {i}/{len(questions)}: {q['text']} =====")
                try:
                    r = await ec.run_rag_question(db, user, agent_id, q["text"])
                except Exception as e:
                    print(f"    [失败] 跳过该题: {str(e)[:200]}")
                    r = {"text": q["text"], "answer": None,
                         "citations": [], "ms": None, "tokens": None}
                samples.append({**q, **r})
                rag_total_tokens = {
                    k: rag_total_tokens[k] + (r["tokens"] or {}).get(k, 0)
                    for k in rag_total_tokens}
                print(f"    answer: {(r['answer'] or '')[:120]}...")
                print(f"    citations: {len(r['citations'])} 片段 | "
                      f"耗时 {r['ms']}ms | tokens {r['tokens']}")

    # ── 阶段二：逐题评分（judge 调用 token 单独累计）──
    async with ec.async_session_local() as db:
        user = await ec.get_super_user(db)
        judge_llm = await ec.ensure_judge_llm(db, user)
        embed_cfg = await ec.ensure_embedding(db, user)

    judge_capture = ec.LLMUsageCapture().attach()
    detail = []
    print(f"\n{'=' * 60}\n开始评分（judge: {judge_llm.provider}/{judge_llm.model_name}，"
          f"embedding: {embed_cfg.provider}/{embed_cfg.model_name}）\n{'=' * 60}")
    for i, s in enumerate(samples, 1):
        print(f"\n----- 评分 {i}/{len(samples)}: {s['text']} -----")
        if not s.get("answer"):
            scores = {m: {"score": None, "details": {"note": "RAG 生成失败/被跳过"}}
                      for m in metrics}
        else:
            scores = await evaluate_sample(
                s["text"], s["answer"],
                [c["content"] for c in s.get("citations") or []],
                judge_llm, embed_cfg, ec._CFG.get("metrics") or {}, metrics)
        line = " | ".join(f"{m}={fmt_score(scores[m]['score'])}" for m in metrics)
        print(f"    {line}")
        detail.append({
            "text": s["text"],
            "expect_doc": s.get("expect_doc"),
            "reference_answer": s.get("reference_answer"),
            "answer": s.get("answer"),
            "citations": s.get("citations") or [],
            "ms": s.get("ms"), "tokens": s.get("tokens"),
            "scores": scores,
        })
    judge_capture.detach()

    # ── 汇总 ──
    rows = []
    means = {m: [] for m in metrics}
    for d in detail:
        rows.append([d["text"][:24]] + [fmt_score(d["scores"][m]["score"])
                                        for m in metrics])
        for m in metrics:
            v = d["scores"][m]["score"]
            if isinstance(v, (int, float)):
                means[m].append(v)
    mean_row = ["均值(有效题)"] + [
        f"{sum(means[m]) / len(means[m]):.3f}" if means[m] else "-"
        for m in metrics]
    valid_row = ["有效题数"] + [f"{len(means[m])}/{len(detail)}" for m in metrics]

    print(f"\n{'=' * 60}\n评估汇总\n{'=' * 60}")
    ec.print_table(["问题"] + metrics, rows)
    ec.print_table(["统计"] + metrics, [mean_row, valid_row])
    print("\n指标说明（论文 §3，均为 [0,1] 越高越好）：")
    print("  faithfulness       答案陈述可被召回上下文推断的比例（幻觉反向指标）")
    print("  answer_relevance   从答案反生成问题与原问题的嵌入余弦均值（答非所问反向指标）")
    print("  context_relevance  召回上下文中关键句占比（越低越冗余；过低提示 top_k 过大）")

    # ── meta 与落盘 ──
    judge_tokens = judge_capture.snapshot()
    meta = {
        "test": "ragas_eval",
        "started_at": started_at,
        "finished_at": ec.datetime.now().isoformat(timespec="seconds"),
        "metrics": metrics,
        "kb": {"name": ec._CFG["kb"]["name"],
               "docs_dir": ec._CFG["kb"]["docs_dir"],
               "chunk_size": ec._CFG["kb"]["chunk_size"],
               "chunk_overlap": ec._CFG["kb"]["chunk_overlap"]},
        "retrieval": {"top_k": ec._CFG["agents"].get("top_k", 4),
                      "score_threshold": ec._CFG["agents"].get("score_threshold", 0.3)},
        "params": {"questions_file": questions_file,
                   "quick": bool(args.quick), "limit": args.limit,
                   "throttle": seconds, "reuse_from": args.reuse},
        "tokens": {"rag_chain": rag_total_tokens, "judge": judge_tokens},
    }
    if args.reuse:
        # 复用模式：被测模型信息取自历史 meta（本次未走被测 Agent）
        meta["reused_llm"] = reuse_meta.get("llm")
    else:
        meta["llm"] = {"provider": llm_cfg.provider,
                       "model": llm_cfg.model_name,
                       "base_url": llm_cfg.base_url}
    meta["judge_llm"] = {"provider": judge_llm.provider,
                         "model": judge_llm.model_name,
                         "base_url": judge_llm.base_url}
    meta["embedding"] = {"provider": embed_cfg.provider,
                         "model": embed_cfg.model_name}
    ec.save_result("ragas_eval", {"summary": rows, "mean": mean_row,
                                  "valid_count": valid_row, "detail": detail},
                   meta)


if __name__ == "__main__":
    # Windows 事件循环已在 eval_common 导入时修正
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[中断] 已退出")
        sys.exit(130)
