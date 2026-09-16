"""RAG 评估配置加载器：eval_config.yaml + docs 目录

数据与逻辑分离：模型/检索/指标参数全部在 eval_config.yaml 维护，脚本不硬编码业务参数。

- load_config()：读取本目录 eval_config.yaml 全量配置
- load_docs(cfg)：遍历 docs_dir（支持相对路径，相对本文件所在目录）下全部 .txt，
  返回 {文件名: 文本内容}，文件名即上传后的 document_name
  （docs_dir 默认指向 ../bench/docs，复用 bench 既有测试文档，避免数据冗余）
"""
from pathlib import Path

import yaml

EVAL_DIR = Path(__file__).parent
CONFIG_PATH = EVAL_DIR / "eval_config.yaml"


def load_config() -> dict:
    """读取 eval_config.yaml 全量配置

    返回:
        dict: 配置树（llm / judge / embedding / kb / agents / metrics 节点）
    """
    if not CONFIG_PATH.exists():
        raise RuntimeError(
            f"配置文件不存在: {CONFIG_PATH}，请复制 eval_config.example.yaml 为 eval_config.yaml")
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_docs(cfg: dict) -> dict[str, str]:
    """遍历配置指定 docs_dir 下全部 .txt 测试文档

    参数:
        cfg: load_config() 返回的配置树

    返回:
        dict[str, str]: {文件名: 文本内容}，文件名（含扩展名）即 document_name
    """
    docs_dir = (EVAL_DIR / cfg["kb"]["docs_dir"]).resolve()
    if not docs_dir.exists():
        raise RuntimeError(f"文档目录不存在: {docs_dir}，请创建并放入 .txt 测试文档")
    docs = {p.name: p.read_text(encoding="utf-8")
            for p in sorted(docs_dir.glob("*.txt"))}
    if not docs:
        raise RuntimeError(f"文档目录为空: {docs_dir}，至少放一份 .txt 测试文档")
    return docs
