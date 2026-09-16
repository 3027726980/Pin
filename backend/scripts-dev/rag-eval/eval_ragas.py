"""RAG 质量评估主脚本：按 Ragas 论文三大指标评估 simple_rag Agent

流程：准备资源（KB/Agent/模型配置）→ 逐组重置增强开关 → 组内逐题 RAG
（answer + citations）→ 逐题三指标 judge → 组级对比矩阵 + JSON 落盘。

增强开关分组（与 bench_rag_enhance 同语义，--groups 选择）：
    A 基线(全关) / B 仅MQE / C 仅HyDE / D 全开（MQE+HyDE+Rerank，无配置时退化）

用法示例：
    # 单组基线评估（默认 A，三大指标）
    .venv/Scripts/python backend/scripts-dev/rag-eval/eval_ragas.py

    # 增强开关分组对比（四组全跑）
    .venv/Scripts/python backend/scripts-dev/rag-eval/eval_ragas.py --groups A,B,C,D

    # 冒烟（前 3 题）/ 限题数 / 单指标
    .venv/Scripts/python backend/scripts-dev/rag-eval/eval_ragas.py --quick
    .venv/Scripts/python backend/scripts-dev/rag-eval/eval_ragas.py --limit 5
    .venv/Scripts/python backend/scripts-dev/rag-eval/eval_ragas.py --groups A,B --metrics faithfulness

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
    parser.add_argument("--groups", default="A",
                        help="增强开关组（逗号分隔，默认 A 单组基线）："
                             "A 基线 / B 仅MQE / C 仅HyDE / D 全开(MQE+HyDE+Rerank)")
    parser.add_argument("--quick", action="store_true", help="每组只跑前 3 题（冒烟验证）")
    parser.add_argument("--limit", type=int, default=None, help="每组只跑前 N 题")
    parser.add_argument("--reuse", default=None,
                        help="复用历史结果 JSON 的 RAG 产物仅重新评分（不调被测 Agent）")
    parser.add_argument("--throttle", type=float, default=None,
                        help="全局 HTTP 请求最小间隔秒数（低 RPM 厂商用）")
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


def resolve_groups(arg: str, all_groups: dict) -> dict:
    """解析 --groups 参数为组定义子集（保持 A/B/C/D 顺序，非法组报错）"""
    keys = [s.strip().upper() for s in arg.split(",") if s.strip()]
    bad = [k for k in keys if k not in all_groups]
    if bad:
        raise SystemExit(f"未知组: {bad}，可选: {list(all_groups)}")
    return {k: all_groups[k] for k in all_groups if k in keys}


def load_reuse_samples(path: str) -> tuple[list[dict], dict]:
    """加载 --reuse 的历史结果 JSON，提取每题 RAG 产物（answer/citations/组归属）"""
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"--reuse 文件不存在: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    detail = data.get("detail") or []
    if not detail:
        raise SystemExit(f"--reuse 文件缺少 detail 数组: {p}")
    samples = [{"group": d.get("group") or "A",
                "text": d["text"], "answer": d["answer"],
                "citations": d.get("citations") or [],
                "tokens": d.get("tokens"),
                "ms": d.get("ms")} for d in detail]
    return samples, data.get("meta") or {}


def fmt_score(score) -> str:
    """分数格式化：None → '-'，否则保留 3 位小数"""
    return f"{score:.3f}" if isinstance(score, (int, float)) else "-"


def _empty_tokens() -> dict:
    """token 统计空结构"""
    return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}


def _add_tokens(total: dict, snap: dict | None) -> None:
    """累加一次 token 快照（snap 为 None 时跳过，如失败题）"""
    if not snap:
        return
    for k in total:
        total[k] += snap.get(k, 0)


async def main() -> None:
    """主流程：资源准备 → 逐组逐题 RAG → 逐题评分 → 组级汇总落盘"""
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
    rag_tokens_by_group: dict[str, dict] = {}
    reuse_meta: dict = {}
    group_defs: dict[str, dict] = {}  # 组定义（name/flags），写进 meta

    # ── 阶段一：逐组逐题 RAG（或复用历史）──
    if args.reuse:
        samples, reuse_meta = load_reuse_samples(args.reuse)
        # 按历史样本聚合各组 RAG token（评分阶段 judge token 由本次实测累计）
        for s in samples:
            g = s["group"]
            rag_tokens_by_group.setdefault(g, _empty_tokens())
            _add_tokens(rag_tokens_by_group[g], s.get("tokens"))
        # 复用历史组定义（有则用，无则按字母生成展示名）
        for g in dict.fromkeys(s["group"] for s in samples):
            hist = (reuse_meta.get("groups") or {}).get(g) or {}
            group_defs[g] = {"name": hist.get("name", g), "flags": hist.get("flags", {})}
        if args.limit or args.quick:
            # 限题按组各取前 N（与正常模式每组限题语义一致）
            by_g: dict[str, list] = {}
            for s in samples:
                by_g.setdefault(s["group"], []).append(s)
            n = args.limit or 3
            samples = [s for ss in by_g.values() for s in ss[:n]]
        print(f"[REUSE] 从 {args.reuse} 载入 {len(samples)} 条 RAG 产物，仅重新评分")
    else:
        started_at = ec.datetime.now().isoformat(timespec="seconds")
        async with ec.async_session_local() as db:
            user = await ec.get_super_user(db)
            llm_cfg = await ec.ensure_chat_llm(db, user)
            all_groups = await ec.build_groups(db, user)
            groups = resolve_groups(args.groups, all_groups)
            group_defs = {k: {"name": v["name"], "flags": v["flags"]}
                          for k, v in groups.items()}
            kb = await ec.ensure_eval_kb(db, user)

            qset = ec.load_question_set(args.questions)
            questions_file = qset["_file"]
            limit = args.limit or (3 if args.quick else None)
            questions = qset["questions"][:limit] if limit else qset["questions"]
            print(f"\n[QSET] {qset.get('name', '')}（每组 {len(questions)} 题）"
                  f" | 指标: {','.join(metrics)} | 检索 top_k={ec._CFG['agents'].get('top_k', 4)}"
                  f" | 组: {','.join(groups)}")

            agent_id = None
            samples = []
            for gkey, ginfo in groups.items():
                # 每组显式重置增强开关（组间状态不残留）
                agent_id = await ec.ensure_eval_agent(db, user, llm_cfg, kb,
                                                      **ginfo["flags"])
                print(f"\n===== 组 {ginfo['name']}（{len(questions)} 题）=====")
                rag_tokens_by_group.setdefault(gkey, _empty_tokens())
                for i, q in enumerate(questions, 1):
                    print(f"\n===== RAG {gkey} {i}/{len(questions)}: {q['text']} =====")
                    try:
                        r = await ec.run_rag_question(db, user, agent_id, q["text"])
                    except Exception as e:
                        print(f"    [失败] 跳过该题: {str(e)[:200]}")
                        r = {"text": q["text"], "answer": None,
                             "citations": [], "ms": None, "tokens": None}
                    samples.append({**q, "group": gkey,
                                    "group_name": ginfo["name"], **r})
                    _add_tokens(rag_tokens_by_group[gkey], r.get("tokens"))
                    print(f"    answer: {(r['answer'] or '')[:120]}...")
                    print(f"    citations: {len(r['citations'])} 片段 | "
                          f"耗时 {r['ms']}ms | tokens {r['tokens']}")

    # ── 阶段二：逐题评分（judge token 按组实测累计）──
    async with ec.async_session_local() as db:
        user = await ec.get_super_user(db)
        judge_llm = await ec.ensure_judge_llm(db, user)
        embed_cfg = await ec.ensure_embedding(db, user)

    judge_capture = ec.LLMUsageCapture().attach()
    judge_tokens_by_group: dict[str, dict] = {}
    detail = []
    print(f"\n{'=' * 60}\n开始评分（judge: {judge_llm.provider}/{judge_llm.model_name}，"
          f"embedding: {embed_cfg.provider}/{embed_cfg.model_name}）\n{'=' * 60}")
    cur_group = None
    for i, s in enumerate(samples, 1):
        if s["group"] != cur_group:  # 组切换：结算上一组 judge token
            if cur_group is not None:
                judge_tokens_by_group[cur_group] = judge_capture.snapshot()
                judge_capture.reset()
            cur_group = s["group"]
            judge_tokens_by_group.setdefault(cur_group, _empty_tokens())
        print(f"\n----- 评分 {i}/{len(samples)} [{cur_group}]: {s['text']} -----")
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
            "group": s["group"],
            "group_name": (s.get("group_name")
                           or group_defs.get(s["group"], {}).get("name", s["group"])),
            "text": s["text"],
            "expect_doc": s.get("expect_doc"),
            "reference_answer": s.get("reference_answer"),
            "answer": s.get("answer"),
            "citations": s.get("citations") or [],
            "ms": s.get("ms"), "tokens": s.get("tokens"),
            "scores": scores,
        })
    if cur_group is not None:  # 结算最后一组
        judge_tokens_by_group[cur_group] = judge_capture.snapshot()
    judge_capture.detach()

    # ── 汇总：组级均值矩阵（核心对比）+ 逐题明细 ──
    def _mean_of(group: str, metric: str):
        vals = [d["scores"][metric]["score"] for d in detail
                if d["group"] == group
                and isinstance(d["scores"][metric]["score"], (int, float))]
        return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)

    group_rows = []
    group_means = {}
    for gkey, ginfo in group_defs.items():
        if gkey not in {d["group"] for d in detail}:
            continue
        means = {m: _mean_of(gkey, m)[0] for m in metrics}
        counts = {m: _mean_of(gkey, m)[1] for m in metrics}
        group_means[gkey] = {"name": ginfo["name"],
                             "means": means, "valid_counts": counts}
        group_rows.append([ginfo["name"]]
                          + [fmt_score(means[m]) for m in metrics])
    print(f"\n{'=' * 60}\n组级对比矩阵（均值，[0,1] 越高越好）\n{'=' * 60}")
    ec.print_table(["开关组"] + metrics, group_rows)

    per_rows = [[f"{d['group']} {d['text'][:20]}"]
                + [fmt_score(d["scores"][m]["score"]) for m in metrics]
                for d in detail]
    print(f"\n逐题分数明细：")
    ec.print_table(["组/问题"] + metrics, per_rows)
    print("\n指标说明（论文 §3）：")
    print("  faithfulness       答案陈述可被召回上下文推断的比例（幻觉反向指标）")
    print("  answer_relevance   从答案反生成问题与原问题的嵌入余弦均值（答非所问反向指标）")
    print("  context_relevance  召回上下文中关键句占比（越低越冗余；过低提示 top_k 过大）")
    print("  组间对比：D 相对 A 的 faithfulness/answer_relevance 提升 = 增强对生成质量的贡献；"
          "context_relevance 变化 = 增强对检索聚焦度的影响")

    # ── meta 与落盘 ──
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
        "groups": group_defs,
        "params": {"questions_file": questions_file,
                   "quick": bool(args.quick), "limit": args.limit,
                   "throttle": seconds, "reuse_from": args.reuse},
        "tokens": {g: {"rag": rag_tokens_by_group.get(g, _empty_tokens()),
                       "judge": judge_tokens_by_group.get(g, _empty_tokens())}
                   for g in {**(rag_tokens_by_group), **judge_tokens_by_group}},
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
    ec.save_result("ragas_eval", {"group_means": group_means,
                                  "summary": per_rows, "detail": detail},
                   meta)


if __name__ == "__main__":
    # Windows 事件循环已在 eval_common 导入时修正
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[中断] 已退出")
        sys.exit(130)
