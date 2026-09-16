"""Step 3（官方方法）：ragas 官方 evaluate 评估被测 RAG

官方流程（docs.ragas.io → Evaluate a simple RAG system）：
    EvaluationDataset.from_list([{user_input, response, retrieved_contexts, reference}])
    → evaluate(dataset, metrics=[官方指标], llm=评审 LLM, embeddings=...)

默认官方 RAG 指标全集（official_config.yaml metrics 节点可增删）：
    Faithfulness 忠实度 / AnswerRelevancy 答案相关性 /
    LLMContextPrecisionWithReference 上下文精确率 / LLMContextRecall 上下文召回率 /
    FactualCorrectness 事实正确性（与 reference 对比的"准确率"）

产物：results/official_eval_<时间戳>.csv + .json；控制台输出总分与逐题明细。

用法：
    .venv/Scripts/python backend/scripts-dev/ragas-official/step3_evaluate.py [--run <rag_run文件>] [--model kimi]
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

import official_common as oc
import ragas_compat

ragas_compat.apply()  # 必须先于 ragas import


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="Ragas 官方 evaluate 评估")
    parser.add_argument("--run", default=None,
                        help="results/ 下 rag_run_*.json 文件名子串（缺省取最新）")
    parser.add_argument("--model", default=None,
                        help="评审 LLM 按 model_name 子串切换（覆盖 llm.model_filter）")
    return parser.parse_args()


def load_run(name_or_path: str | None) -> tuple[Path, dict]:
    """加载 step2 产物（--run 指定子串，缺省取 results/ 最新一个 rag_run_*.json）"""
    files = sorted(oc.RESULTS_DIR.glob("rag_run_*.json"))
    if not files:
        raise RuntimeError("results/ 无 rag_run_*.json，请先运行 step2_run_rag.py")
    target = None
    if name_or_path:
        p = Path(name_or_path)
        target = p if p.exists() else next(
            (f for f in files if name_or_path in f.name), None)
        if target is None:
            raise RuntimeError(f"未找到 {name_or_path!r}，现有: {[f.name for f in files]}")
    else:
        target = files[-1]
    return target, json.loads(target.read_text(encoding="utf-8"))


def build_metrics(names: list[str], embeddings) -> list:
    """配置指标名 → 官方指标实例（AnswerRelevancy 依赖 embeddings）"""
    from ragas.metrics import (
        AnswerRelevancy,
        Faithfulness,
        FactualCorrectness,
        LLMContextPrecisionWithReference,
        LLMContextRecall,
    )

    factory = {
        "faithfulness": Faithfulness,
        "answer_relevancy": AnswerRelevancy,
        "context_precision": LLMContextPrecisionWithReference,
        "context_recall": LLMContextRecall,
        "factual_correctness": FactualCorrectness,
    }
    out = []
    for n in names:
        if n not in factory:
            raise RuntimeError(f"未知指标: {n}，可选: {list(factory)}")
        out.append(factory[n]())
    return out


def main() -> None:
    """官方 evaluate 主流程（ragas 自管事件循环，勿包在 async 里调用）"""
    args = parse_args()
    run_path, run_data = load_run(args.run)
    samples = run_data["samples"]
    print(f"[RUN] {run_path.name}（{len(samples)} 题）")

    cfg = oc.load_config()
    if args.model:
        cfg["llm"]["model_filter"] = args.model
    import asyncio
    llm_cfg, api_key = asyncio.run(oc.resolve_llm_and_embedding(cfg))
    evaluator_llm = oc.build_generator_llm(llm_cfg)
    embeddings = oc.build_embedding_model(cfg, api_key)
    metrics = build_metrics(cfg.get("metrics") or [], embeddings)
    print(f"[METRICS] {[type(m).__name__ for m in metrics]}")
    print(f"[JUDGE] {llm_cfg.provider}/{llm_cfg.model_name}\n")

    from ragas import EvaluationDataset, evaluate

    dataset = EvaluationDataset.from_list([
        {"user_input": s["user_input"], "response": s.get("response") or "",
         "retrieved_contexts": s.get("retrieved_contexts") or [],
         "reference": s.get("reference") or ""}
        for s in samples])
    print("[RAGAS] 官方 evaluate 执行中...")
    result = evaluate(dataset=dataset, metrics=metrics,
                      llm=evaluator_llm, embeddings=embeddings)

    df = result.to_pandas()
    oc.RESULTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = oc.RESULTS_DIR / f"official_eval_{ts}.csv"
    json_path = oc.RESULTS_DIR / f"official_eval_{ts}.json"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    # 总分 = 各指标分数列均值（ragas 0.4.x Result 不支持 dict()，
    # 从 to_pandas 数值列统计；列名用官方 metric.name（如 factual_correctness(mode=f1)），
    # 故按前缀动态匹配；超时/失败题的 NaN 自动跳过）
    import pandas as pd

    prefixes = ("faithfulness", "answer_relevancy", "context_precision",
                "llm_context_precision", "context_recall", "factual_correctness")
    score_cols = [c for c in df.columns if c.startswith(prefixes)]
    total = {c: round(float(pd.to_numeric(df[c], errors="coerce").dropna().mean()), 4)
             for c in score_cols}
    valid = {c: int(pd.to_numeric(df[c], errors="coerce").notna().sum())
             for c in score_cols}
    json_path.write_text(json.dumps(
        {"meta": {"rag_run": run_path.name,
                  "judge_llm": {"provider": llm_cfg.provider,
                                "model": llm_cfg.model_name},
                  "metrics": cfg.get("metrics"),
                  "agent": run_data["meta"]["agent"],
                  "top_k": run_data["meta"]["top_k"],
                  "finished_at": datetime.now().isoformat(timespec="seconds")},
         "totals": total,
         "detail": df.to_dict(orient="records")},
        ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # ── 控制台输出 ──
    print(f"\n{'=' * 62}\n官方指标总分（ragas evaluate，[0,1] 越高越好）\n{'=' * 62}")
    for k, v in total.items():
        print(f"  {k:22s} {v}")
    print(f"\n逐题明细:")
    for _, r in df.iterrows():
        cells = []
        for c in score_cols:
            v = pd.to_numeric(r[c], errors="coerce")
            cells.append(f"{c.split('(')[0][:12]}={v:.3f}" if pd.notna(v) else f"{c.split('(')[0][:12]}=NaN")
        print(f"  {str(r['user_input'])[:26]:28s} {' | '.join(cells)}")
    print(f"\n[SAVE] {csv_path}\n       {json_path}")


if __name__ == "__main__":
    main()
