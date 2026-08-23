"""
本地模型下载脚本（正式版）

用途：一键下载本地模型（Embedding / Rerank）到 config.yaml 指定的 local_models.cache_dir，
      供 local 厂商配置使用（离线部署友好）。

用法：
  python backend/script/download_models.py BAAI/bge-reranker-v2-m3    # Rerank 模型
  python backend/script/download_models.py bge-small-zh-v1.5         # Embedding 模型
  python backend/script/download_models.py --all                     # 下载全部预置本地模型
  python backend/script/download_models.py <任意模型ID>              # 任意模型
  python backend/script/download_models.py BAAI/bge-reranker-v2-m3 --name my-reranker  # 自定义目录名
  python backend/script/download_models.py --list                    # 查看预置模型

下载源：默认 auto（优先 ModelScope 魔搭，失败自动回退 HuggingFace），可用 --source 指定。
下载位置：自动读取 config.yaml 的 local_models.cache_dir（默认 backend/local_models）。
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = PROJECT_ROOT / "backend" / "local_models"   # 兜底默认（读不到 config 时）
CONFIG_PATH = PROJECT_ROOT / "backend" / "config.yaml"

# 预置本地模型：别名 → {source: 上游模型 ID, target: 本地目录名（相对 cache_dir）}
PRESET_MODELS: dict[str, dict[str, str]] = {
    "bge-small-zh-v1.5": {
        "source": "BAAI/bge-small-zh-v1.5",
        "target": "bge-small-zh-v1.5",
        "desc": "本地 Embedding 模型（512 维）",
    },
    "BAAI/bge-reranker-v2-m3": {
        "source": "BAAI/bge-reranker-v2-m3",
        "target": "BAAI/bge-reranker-v2-m3",
        "desc": "本地 Rerank 模型（多语言精排）",
    },
}


def load_cache_dir() -> Path:
    """从 config.yaml 读取 local_models.cache_dir（相对项目根）作为下载根目录"""
    try:
        import yaml

        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        raw = (cfg.get("local_models") or {}).get("cache_dir")
        if raw:
            p = Path(raw)
            return p if p.is_absolute() else PROJECT_ROOT / p
    except Exception as e:
        print(f"[!] 读取 config.yaml 失败（{e}），使用默认目录 {CACHE_DIR}")
    return CACHE_DIR


def download_modelscope(model_id: str, target_dir: Path) -> bool:
    """ModelScope（魔搭）下载：国内速度快"""
    try:
        from modelscope import snapshot_download
    except ImportError:
        print("[!] 未安装 modelscope，执行: pip install modelscope")
        return False
    try:
        snapshot_download(model_id, local_dir=str(target_dir))
        return True
    except Exception as e:
        print(f"[!] 魔搭下载失败: {e}")
        return False


def download_huggingface(model_id: str, target_dir: Path) -> bool:
    """HuggingFace 下载：官方源"""
    try:
        from huggingface_hub import snapshot_download as hf_download
    except ImportError:
        print("[!] 未安装 huggingface_hub，执行: pip install huggingface-hub")
        return False
    try:
        hf_download(model_id, local_dir=str(target_dir))
        return True
    except Exception as e:
        print(f"[!] HuggingFace 下载失败: {e}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="下载本地模型到 config.yaml 指定的 local_models.cache_dir")
    parser.add_argument("models", nargs="*", help="模型名（预置别名或完整模型 ID）")
    parser.add_argument("--all", action="store_true", help="下载全部预置本地模型")
    parser.add_argument("--source", choices=["modelscope", "huggingface", "auto"],
                        default="auto", help="下载源（默认 auto：优先魔搭，失败回退 HF）")
    parser.add_argument("--name", default=None,
                        help="本地目录名/模型名（默认 = 模型 ID，如 BAAI/bge-reranker-v2-m3 → 目录 BAAI/bge-reranker-v2-m3）")
    parser.add_argument("--list", action="store_true", help="列出预置本地模型")
    args = parser.parse_args()

    if args.list or (not args.models and not args.all):
        print("预置本地模型：")
        for alias, info in PRESET_MODELS.items():
            print(f"  {alias:28s} ← {info['source']}  [{info['desc']}]")
        print("\n用法示例：")
        print("  python backend/script/download_models.py BAAI/bge-reranker-v2-m3")
        print("  python backend/script/download_models.py bge-small-zh-v1.5")
        print("  python backend/script/download_models.py --all")
        print("  python backend/script/download_models.py BAAI/bge-reranker-v2-m3 --name my-reranker")
        print("  python backend/script/download_models.py --list")
        return 0

    # 下载根目录：自动读取 config.yaml local_models.cache_dir
    base_dir = load_cache_dir()
    print(f"[i] 下载根目录（config.yaml local_models.cache_dir）: {base_dir}")

    # 确定下载目标
    targets: list[tuple[str, str, Path]] = []
    if args.all:
        for alias, info in PRESET_MODELS.items():
            targets.append((info["source"], info["target"], base_dir / info["target"]))
    else:
        for m in args.models:
            info = PRESET_MODELS.get(m)
            if info:
                targets.append((info["source"], info["target"], base_dir / info["target"]))
            else:
                # 任意模型：目标目录名可用 --name 覆盖，默认 = 模型 ID（BAAI/xxx 保持两级）
                name = args.name or m
                targets.append((m, name, base_dir / name))

    base_dir.mkdir(parents=True, exist_ok=True)

    ok_all = True
    for source_id, target_name, target_dir in targets:
        print(f"\n=== 下载 {source_id}\n    目标: {target_dir} ===")
        if target_dir.exists() and any(target_dir.iterdir()):
            print(f"[=] 目录已存在且非空，跳过（如需重新下载请先删除 {target_dir}）")
            continue
        ok = False
        if args.source in ("auto", "modelscope"):
            print("[>] 尝试 ModelScope（魔搭）...")
            ok = download_modelscope(source_id, target_dir)
        if not ok and args.source in ("auto", "huggingface"):
            print("[>] 尝试 HuggingFace ...")
            ok = download_huggingface(source_id, target_dir)
        if ok:
            print(f"[√] 完成: {target_dir}")
        else:
            print(f"[×] 失败: {source_id}（请检查网络或更换 --source）")
            ok_all = False

    print("\n提示：下载后可在模型配置页选择 local 厂商对应类型创建配置，并点「测试连接」验证。")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
