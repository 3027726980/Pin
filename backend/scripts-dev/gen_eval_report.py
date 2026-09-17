"""三套 RAG 评估体系结果聚合报告生成器（bench / rag-eval / ragas-official）

扫描三个 results 目录，聚合为自包含单文件 HTML（数据内嵌、零依赖、浏览器直接打开）：
- bench（backend/scripts-dev/bench/results/bench_*.json）：规则指标（精准度/召回率/MRR）
- rag-eval（.../rag-eval/results/ragas_eval_*.json）：论文自实现三指标（含增强分组）
- ragas-official（.../ragas-official/results/official_eval_*.json）：官方五指标

轻量裁剪：只取分数与元数据（不嵌入 citations 全文/指标中间产物，控制文件体积）。

用法：
    .venv/Scripts/python backend/scripts-dev/gen_eval_report.py [--out eval_report.html] [--keep 5]

产物默认 backend/scripts-dev/eval_report.html（Git 忽略），双击浏览器打开。
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

SCRIPTS_DEV = Path(__file__).parent
SOURCES = {
    "bench": SCRIPTS_DEV / "bench" / "results",
    "rag_eval": SCRIPTS_DEV / "rag-eval" / "results",
    "official": SCRIPTS_DEV / "ragas-official" / "results",
}
BENCH_GROUP_SHORT = {"A": "A 基线", "B": "B 仅MQE", "C": "C 仅HyDE", "D": "D 全开"}


# ── 读取与裁剪 ────────────────────────────

def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def scan_bench(keep: int) -> list[dict]:
    """bench 增强对比结果：取 bench_rag_enhance_*.json 最新 keep 个"""
    runs = []
    for p in sorted(SOURCES["bench"].glob("bench_rag_enhance_*.json")):
        try:
            d = _load(p)
        except (json.JSONDecodeError, OSError):
            continue
        meta = d.get("meta") or {}
        runs.append({
            "file": p.name,
            "time": (meta.get("started_at") or p.stem.split("_")[-2] + " " + p.stem.split("_")[-1]),
            "top_k": meta.get("top_k"),
            "model": (meta.get("llm") or {}).get("model"),
            "summary": d.get("summary") or [],
            # 失败/低分题（轻量行）
            "issues": [
                {"group": r.get("group", "")[:1], "q": r.get("question", "")[:24],
                 "recall": r.get("recall"), "mrr": r.get("mrr"),
                 "docs": [c.get("document_name", "")[:12] for c in (r.get("citations") or [])[:4]]
                 if isinstance(r.get("citations"), list) and r.get("citations")
                 and isinstance(r["citations"][0], dict) else []}
                for r in (d.get("detail") or [])
                if not r.get("recall") or (r.get("mrr") or 0) < 1],
        })
    return runs[-keep:][::-1]  # 最新在前


def scan_rag_eval(keep: int) -> list[dict]:
    """rag-eval 结果（论文三指标 + 增强分组）：取 ragas_eval_*.json 最新 keep 个"""
    runs = []
    for p in sorted(SOURCES["rag_eval"].glob("ragas_eval_*.json")):
        try:
            d = _load(p)
        except (json.JSONDecodeError, OSError):
            continue
        meta = d.get("meta") or {}
        metrics = meta.get("metrics") or []
        rows = []
        for r in (d.get("detail") or []):
            row = {"group": r.get("group", ""), "q": r.get("text", "")[:28]}
            for m in metrics:
                v = ((r.get("scores") or {}).get(m) or {}).get("score")
                row[m] = round(v, 3) if isinstance(v, (int, float)) else None
            rows.append(row)
        runs.append({
            "file": p.name,
            "time": meta.get("started_at") or "",
            "groups": meta.get("groups") or {},
            "metrics": metrics,
            "group_means": d.get("group_means") or {},
            "rows": rows,
            "tokens": meta.get("tokens") or {},
        })
    return runs[-keep:][::-1]


def scan_official(keep: int) -> list[dict]:
    """ragas-official 结果（官方五指标）：取 official_eval_*.json 最新 keep 个"""
    runs = []
    for p in sorted(SOURCES["official"].glob("official_eval_*.json")):
        try:
            d = _load(p)
        except (json.JSONDecodeError, OSError):
            continue
        meta = d.get("meta") or {}
        detail = d.get("detail") or []
        # 官方 to_pandas 指标列名（factual_correctness(mode=f1) 等）动态收集
        cols = []
        for c in (detail[0].keys() if detail else []):
            if c.startswith(("faithfulness", "answer_relevancy", "context_precision",
                             "llm_context_precision", "context_recall", "factual_correctness")):
                cols.append(c)
        rows = [{"q": (r.get("user_input") or "")[:30],
                 **{c: (round(r[c], 3) if isinstance(r.get(c), (int, float)) else None)
                    for c in cols}} for r in detail]
        # totals 兼容补算：早期版本的统计 bug 可能漏列，从 detail 动态列重算缺失项
        totals = dict(d.get("totals") or {})
        for c in cols:
            if c not in totals:
                vals = [r[c] for r in detail if isinstance(r.get(c), (int, float))]
                if vals:
                    totals[c] = round(sum(vals) / len(vals), 4)
        runs.append({
            "file": p.name,
            "time": (meta.get("finished_at") or ""),
            "rag_run": meta.get("rag_run"),
            "judge": (meta.get("judge_llm") or {}).get("model"),
            "top_k": meta.get("top_k"),
            "totals": totals,
            "cols": cols,
            "rows": rows,
        })
    return runs[-keep:][::-1]


# ── HTML 模板 ──────────────────────────────

_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>RAG 评估结果对比报告</title>
<style>
  :root { --ok:#0a7d33; --bad:#c0392b; --line:#e2e5e9; --bg:#f6f7f9; }
  * { box-sizing:border-box; }
  body { font-family:"Segoe UI","Microsoft YaHei",sans-serif; margin:0; background:var(--bg); color:#222; }
  header { background:#1f2d3d; color:#fff; padding:18px 28px; }
  header h1 { margin:0 0 4px; font-size:20px; }
  header .sub { opacity:.75; font-size:13px; }
  main { max-width:1180px; margin:0 auto; padding:20px 16px 60px; }
  section { background:#fff; border:1px solid var(--line); border-radius:10px; margin-top:22px; padding:18px 22px; }
  h2 { margin:0 0 4px; font-size:17px; }
  .desc { color:#667; font-size:13px; margin-bottom:12px; }
  .toolbar { display:flex; gap:10px; align-items:center; margin-bottom:12px; flex-wrap:wrap; }
  select, .meta { font-size:13px; padding:5px 8px; }
  .meta { color:#556; }
  table { border-collapse:collapse; width:100%; font-size:13.5px; }
  th, td { border-bottom:1px solid var(--line); padding:7px 10px; text-align:left; }
  th { background:#f0f2f5; white-space:nowrap; }
  td.num { text-align:right; font-variant-numeric:tabular-nums; }
  td.best { color:var(--ok); font-weight:700; }
  .bar { height:14px; border-radius:3px; background:#3d7bd9; display:inline-block; vertical-align:middle; margin-right:6px; }
  .barwrap { display:flex; align-items:center; gap:6px; }
  .badge { display:inline-block; padding:1px 8px; border-radius:10px; font-size:12px; background:#eef2f7; margin-right:6px; }
  .ok { color:var(--ok); font-weight:700; } .bad { color:var(--bad); font-weight:700; }
  .cards { display:flex; gap:14px; flex-wrap:wrap; margin-top:10px; }
  .card { flex:1 1 150px; border:1px solid var(--line); border-radius:8px; padding:10px 14px; }
  .card .k { font-size:12px; color:#667; } .card .v { font-size:22px; font-weight:700; }
  details { margin-top:10px; } summary { cursor:pointer; color:#3d7bd9; font-size:13px; }
  .empty { color:#900; }
  footer { text-align:center; color:#889; font-size:12px; padding:24px; }
</style>
</head>
<body>
<header>
  <h1>RAG 评估结果对比报告</h1>
  <div class="sub">三套体系：bench（规则指标） / rag-eval（Ragas 论文自实现） / ragas-official（官方库 evaluate） · 生成于 __GENERATED__</div>
</header>
<main>
  <section id="sec-bench">
    <h2>① bench · 增强开关对比（规则指标）</h2>
    <div class="desc">精准度=参考关键词组命中 / 召回率=期望文档 Hit@K / MRR=期望文档首现排名倒数。数据源：bench/results/bench_rag_enhance_*.json</div>
    <div class="toolbar"><label>运行批次 <select id="sel-bench"></select></label><span class="meta" id="meta-bench"></span></div>
    <div id="body-bench"></div>
  </section>
  <section id="sec-rag">
    <h2>② rag-eval · Ragas 论文三指标（自实现，含增强分组）</h2>
    <div class="desc">faithfulness 忠实度 / answer_relevancy 答案相关性 / context_relevance 上下文相关性，均 [0,1] 越高越好。数据源：rag-eval/results/ragas_eval_*.json</div>
    <div class="toolbar"><label>运行批次 <select id="sel-rag"></select></label><span class="meta" id="meta-rag"></span></div>
    <div id="body-rag"></div>
  </section>
  <section id="sec-official">
    <h2>③ ragas-official · 官方五指标（官方测试集 + evaluate）</h2>
    <div class="desc">官方 TestsetGenerator 自动生成测试集（含 reference），官方 evaluate 评审。数据源：ragas-official/results/official_eval_*.json</div>
    <div class="toolbar"><label>运行批次 <select id="sel-official"></select></label><span class="meta" id="meta-official"></span></div>
    <div id="body-official"></div>
  </section>
</main>
<footer>本文件由 gen_eval_report.py 生成 · 重新运行脚本即可刷新数据</footer>
<script>
const DATA = __DATA__;

function fmt(v, pct) {
  if (v === null || v === undefined) return '<span class="bad">-</span>';
  return pct ? (v * 100).toFixed(0) + '%' : (typeof v === 'number' ? v.toFixed(3) : v);
}
function bar(v, max) {
  if (v === null || v === undefined) return '';
  const w = Math.max(2, Math.min(100, v / (max || 1) * 100));
  return `<span class="barwrap"><span class="bar" style="width:${w}%"></span><span>${v.toFixed(3)}</span></span>`;
}
function bestMark(rows, key, higher) {
  const vals = rows.map(r => r[key]).filter(v => typeof v === 'number');
  if (!vals.length) return null;
  return higher ? Math.max(...vals) : Math.min(...vals);
}

/* ── bench ── */
function renderBench() {
  const run = DATA.bench.runs[document.getElementById('sel-bench').value];
  const el = document.getElementById('body-bench');
  document.getElementById('meta-bench').textContent =
    `top_k=${run.top_k} · 模型=${run.model || '-'} · ${run.time}`;
  if (!run.summary.length) { el.innerHTML = '<div class="empty">无 summary 数据</div>'; return; }
  const mrrBest = Math.max(...run.summary.map(r => r.mrr));
  let h = '<table><tr><th>开关组</th><th>题数</th><th>精准度</th><th>召回率</th><th>MRR</th><th>LLM调用</th><th>tokens(p+c)</th><th>平均耗时</th></tr>';
  for (const r of run.summary) {
    h += `<tr><td>${r.group}</td><td class="num">${r.question_count}</td>` +
      `<td class="num">${r.accuracy}</td><td class="num">${r.recall_rate}</td>` +
      `<td class="num ${r.mrr === mrrBest ? 'best' : ''}">${r.mrr}</td>` +
      `<td class="num">${r.llm_calls}</td><td class="num">${r.prompt_tokens}+${r.completion_tokens}</td>` +
      `<td class="num">${(r.avg_ms / 1000).toFixed(1)}s</td></tr>`;
  }
  h += '</table>';
  if (run.issues.length) {
    h += '<details><summary>未满分题明细（召回失败 / MRR&lt;1）</summary><table><tr><th>组</th><th>问题</th><th>召回</th><th>MRR</th><th>召回切片顺序</th></tr>';
    for (const it of run.issues) {
      h += `<tr><td>${it.group}</td><td>${it.q}</td>` +
        `<td>${it.recall ? '<span class="ok">✓</span>' : '<span class="bad">✗</span>'}</td>` +
        `<td class="num">${it.mrr}</td><td>${(it.docs || []).join(' → ') || '-'}</td></tr>`;
    }
    h += '</table></details>';
  }
  el.innerHTML = h;
}

/* ── rag-eval ── */
function renderRag() {
  const run = DATA.rag_eval.runs[document.getElementById('sel-rag').value];
  const el = document.getElementById('body-rag');
  const metrics = run.metrics || [];
  document.getElementById('meta-rag').textContent = run.time || run.file;
  if (!metrics.length) { el.innerHTML = '<div class="empty">无指标数据</div>'; return; }
  let h = '<table><tr><th>开关组</th>' + metrics.map(m => `<th>${m}</th>`).join('') + '</tr>';
  for (const [g, gm] of Object.entries(run.group_means)) {
    h += `<tr><td>${(run.groups[g] || {}).name || g}</td>`;
    for (const m of metrics) {
      const v = (gm.means || {})[m];
      h += `<td class="num">${bar(v, 1)}</td>`;
    }
    h += '</tr>';
  }
  h += '</table>';
  h += '<details><summary>逐题分数</summary><table><tr><th>组</th><th>问题</th>' +
    metrics.map(m => `<th>${m}</th>`).join('') + '</tr>';
  for (const r of run.rows) {
    h += `<tr><td>${r.group}</td><td>${r.q}</td>`;
    for (const m of metrics) h += `<td class="num">${fmt(r[m])}</td>`;
    h += '</tr>';
  }
  h += '</table></details>';
  el.innerHTML = h;
}

/* ── ragas-official ── */
const METRIC_NAME = {
  'llm_context_precision_with_reference': 'context_precision（精确率）',
  'factual_correctness(mode=f1)': 'factual_correctness（准确率）',
  'faithfulness': 'faithfulness（忠实度）',
  'answer_relevancy': 'answer_relevancy（答案相关性）',
  'context_recall': 'context_recall（召回覆盖）'
};
function renderOfficial() {
  const run = DATA.official.runs[document.getElementById('sel-official').value];
  const el = document.getElementById('body-official');
  document.getElementById('meta-official').textContent =
    `judge=${run.judge || '-'} · top_k=${run.top_k} · ${run.time}`;
  const cols = run.cols || [];
  let h = '<div class="cards">';
  for (const c of cols) {
    const v = (run.totals || {})[c];
    h += `<div class="card"><div class="k">${METRIC_NAME[c] || c}</div><div class="v">${fmt(v)}</div></div>`;
  }
  h += '</div>';
  if (run.rows.length) {
    h += '<details open><summary>逐题分数</summary><table><tr><th>问题</th>' +
      cols.map(c => `<th>${METRIC_NAME[c] || c}</th>`).join('') + '</tr>';
    for (const r of run.rows) {
      h += `<tr><td>${r.q}</td>`;
      for (const c of cols) {
        const v = r[c];
        h += `<td class="num">${bar(v, 1)}</td>`;
      }
      h += '</tr>';
    }
    h += '</table></details>';
  }
  el.innerHTML = h;
}

/* ── 初始化 ── */
function fill(sel, runs, renderer, label) {
  const s = document.getElementById(sel);
  runs.forEach((r, i) => {
    const opt = document.createElement('option');
    opt.value = i;
    opt.textContent = `${r.time || r.file}（${label}）`;
    s.appendChild(opt);
  });
  s.onchange = renderer;
}
fill('sel-bench', DATA.bench.runs, renderBench, 'bench增强');
fill('sel-rag', DATA.rag_eval.runs, renderRag, '论文三指标');
fill('sel-official', DATA.official.runs, renderOfficial, '官方五指标');
renderBench(); renderRag(); renderOfficial();
</script>
</body>
</html>
"""


def build_data(keep: int) -> dict:
    """聚合三套体系（裁剪后）"""
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "bench": {"runs": scan_bench(keep)},
        "rag_eval": {"runs": scan_rag_eval(keep)},
        "official": {"runs": scan_official(keep)},
    }


def main() -> None:
    """扫描结果 → 注入 HTML 模板 → 落盘"""
    parser = argparse.ArgumentParser(description="三套评估体系结果 HTML 报告生成")
    parser.add_argument("--out", default=str(SCRIPTS_DEV / "eval_report.html"),
                        help="报告输出路径（默认 backend/scripts-dev/eval_report.html）")
    parser.add_argument("--keep", type=int, default=5, help="每套体系保留最近 N 次运行")
    args = parser.parse_args()

    data = build_data(args.keep)
    counts = {k: len(data[k]["runs"]) for k in ("bench", "rag_eval", "official")}
    html = (_HTML
            .replace("__GENERATED__", data["generated_at"])
            .replace("__DATA__", json.dumps(data, ensure_ascii=False)))
    out = Path(args.out)
    out.write_text(html, encoding="utf-8")
    print(f"[OK] 报告已生成: {out}（{out.stat().st_size / 1024:.0f} KB）")
    print(f"     运行批次数: bench={counts['bench']} rag-eval={counts['rag_eval']} official={counts['official']}")
    print("     浏览器打开即可查看对比")


if __name__ == "__main__":
    main()
