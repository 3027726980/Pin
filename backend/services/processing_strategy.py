"""文档处理策略的继承解析、规范化 hash 与算法版本。"""

import hashlib
import json

from backend.models import Documents, KnowledgeBases
from backend.schemas.knowledge import ProcessingConfig


PROCESSING_ALGORITHM_VERSION = 1


def knowledge_base_processing_config(kb: KnowledgeBases) -> ProcessingConfig:
    """从知识库字段构造一份经过校验的完整默认处理策略。"""
    return ProcessingConfig(
        cleaning_config=kb.cleaning_config,
        chunk_size=kb.chunk_size,
        chunk_overlap=kb.chunk_overlap,
        chunk_separators=kb.chunk_separators,
    )


def effective_processing_config(
    kb: KnowledgeBases,
    doc: Documents,
) -> ProcessingConfig:
    """返回文档实际使用的策略：独立策略优先，否则继承知识库。"""
    if doc.processing_config is not None:
        return ProcessingConfig.model_validate(doc.processing_config)
    return knowledge_base_processing_config(kb)


def processing_config_hash(config: ProcessingConfig) -> str:
    """对规范化策略 JSON 计算稳定 SHA-256。"""
    payload = json.dumps(
        config.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
