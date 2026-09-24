"""从回答中的来源标记生成已验证的结构化 RAG 引用绑定。"""

from __future__ import annotations

import re

from backend.schemas.agent import Citation, CitationBinding

_SOURCE_PATTERN = re.compile(r"\[(S[1-9][0-9]*)\]")
_SENTENCE_BOUNDARY = re.compile(r"[。！？!?\n]")
_QUOTE_LIMIT = 300


def strip_unbound_source_markers(
    answer: str,
    valid_source_ids: set[str] | None = None,
) -> str:
    """移除没有本轮来源支撑的 ``[S#]`` 标记。

    ``valid_source_ids`` 为空时移除全部稳定来源标记；非空时只保留本轮
    候选来源中存在的标记，避免模型从历史消息复制不可验证的来源编号。
    """
    valid = valid_source_ids or set()
    sanitized = _SOURCE_PATTERN.sub(
        lambda marker: marker.group(0) if marker.group(1) in valid else "",
        answer,
    )
    if sanitized == answer:
        return answer
    return re.sub(r"[ \t]+([，。！？；：,.!?;:])", r"\1", sanitized)


def _claim_for_marker(answer: str, marker: re.Match[str]) -> str:
    """取包含来源标记的句子作为 claim，保留可见的 source_id 供前端定位。"""
    before = answer[:marker.start()]
    boundaries = list(_SENTENCE_BOUNDARY.finditer(before))
    start = boundaries[-1].end() if boundaries else 0
    after = answer[marker.end():]
    ending = _SENTENCE_BOUNDARY.search(after)
    end = marker.end() + ending.end() if ending else len(answer)
    return answer[start:end].strip()


def build_citation_bindings(
    answer: str,
    candidate_sources: dict[str, Citation],
) -> list[CitationBinding]:
    """只为回答中出现且属于本轮候选集的来源生成绑定。"""
    bindings: list[CitationBinding] = []
    seen: set[str] = set()
    for marker in _SOURCE_PATTERN.finditer(answer):
        source_id = marker.group(1)
        if source_id in seen:
            continue
        seen.add(source_id)
        citation = candidate_sources.get(source_id)
        if citation is None or not citation.content.strip():
            continue
        quote = citation.content.strip()[:_QUOTE_LIMIT]
        if quote not in citation.content:
            continue
        bindings.append(CitationBinding(
            source_id=source_id,
            chunk_id=citation.chunk_id,
            document_name=citation.document_name,
            claim=_claim_for_marker(answer, marker),
            quote=quote,
            score=citation.score,
            original_score=citation.original_score,
        ))
    return bindings
