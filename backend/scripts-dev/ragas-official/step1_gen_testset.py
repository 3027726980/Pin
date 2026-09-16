"""Step 1（官方方法）：TestsetGenerator 从项目语料自动构建测试集

官方流程（docs.ragas.io → Testset Generation for RAG）：
    语料 → KnowledgeGraph（Transforms 富化）→ Scenarios（SingleHop/MultiHop 分布）
    → Testset（user_input / reference / reference_contexts / synthesizer_name）

产物：testsets/testset_<时间戳>.json + .csv（官方 to_pandas 结构）
后续：step2_run_rag.py 用其 user_input 跑被测 RAG。

用法：
    .venv/Scripts/python backend/scripts-dev/ragas-official/step1_gen_testset.py [--size 10] [--model glm]
"""
import argparse
import json
from datetime import datetime

import official_common as oc
import ragas_compat

ragas_compat.apply()  # 必须先于 ragas import（vertexai 兼容 shim）

from langchain_core.documents import Document  # noqa: E402


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="Ragas 官方 TestsetGenerator 生成测试集")
    parser.add_argument("--size", type=int, default=None,
                        help="测试集问答对数量（默认取 official_config.yaml testset.size）")
    parser.add_argument("--model", default=None,
                        help="生成 LLM 按 model_name 子串切换（覆盖 llm.model_filter）")
    return parser.parse_args()


def build_documents(cfg: dict) -> list[Document]:
    """语料 → 官方 LangChain Document 列表（metadata 记录来源文件名）"""
    return [Document(page_content=text, metadata={"source": name})
            for name, text in oc.load_docs(cfg).items()]


async def prepare(args) -> tuple[object, object, int]:
    """解析生成所需资源：官方 LLM wrapper + embedding wrapper + 测试集规模"""
    cfg = oc.load_config()
    if args.model:
        cfg["llm"]["model_filter"] = args.model
    llm_cfg = await oc.resolve_llm_cfg(cfg)
    llm = oc.build_generator_llm(llm_cfg)
    api_key = await oc.resolve_embedding_api_key(cfg)
    embedding = oc.build_embedding_model(cfg, api_key)
    size = args.size or int(cfg["testset"].get("size", 10))
    return llm, embedding, size


def main() -> None:
    """生成测试集并落盘（ragas 内部自管事件循环，勿包在 async 里调用）"""
    args = parse_args()
    llm, embedding, size = asyncio_run_prepare(args)
    docs = build_documents(oc.load_config())
    print(f"[DOCS] 语料 {len(docs)} 份 | testset_size={size}")

    from ragas.testset import TestsetGenerator

    generator = TestsetGenerator(llm=llm, embedding_model=embedding)
    print("[RAGAS] 官方 TestsetGenerator 生成中（KnowledgeGraph → Scenarios → Testset）...")
    testset = generator.generate_with_langchain_docs(docs, testset_size=size)

    df = testset.to_pandas()
    oc.TESTSETS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = oc.TESTSETS_DIR / f"testset_{ts}.csv"
    json_path = oc.TESTSETS_DIR / f"testset_{ts}.json"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    records = df.to_dict(orient="records")
    json_path.write_text(json.dumps(
        {"meta": {"created_at": datetime.now().isoformat(timespec="seconds"),
                  "size": size, "docs": len(docs),
                  "llm": str(oc.load_config()["llm"]["model_filter"])},
         "samples": records}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8")

    print(f"\n[SAVE] 测试集已保存: {csv_path}\n                        {json_path}")
    print(f"[INFO] 查询类型分布: "
          f"{df['synthesizer_name'].value_counts().to_dict() if 'synthesizer_name' in df else '见 csv'}")
    for i, r in enumerate(records[:3], 1):
        print(f"\n----- 预览 {i}: {str(r.get('user_input'))[:80]}")
        print(f"  reference: {str(r.get('reference'))[:80]}...")


def asyncio_run_prepare(args):
    """在独立事件循环中完成异步资源准备（asyncpg 用完后关闭，再进入 ragas 同步流程）"""
    import asyncio
    return asyncio.run(prepare(args))


if __name__ == "__main__":
    main()
