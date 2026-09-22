"""文档清洗规则的 Pydantic 契约。"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator


CleaningRuleType = Literal[
    "normalize_unicode",
    "remove_control_chars",
    "collapse_blank_lines",
    "trim_lines",
    "collapse_punctuation",
    "replace_text",
    "regex_remove",
]


class CleaningRule(BaseModel):
    """一条可配置、无脚本执行能力的文本清洗规则。"""

    type: CleaningRuleType
    enabled: bool = True
    value: str | None = Field(default=None, max_length=500)
    replacement: str = Field(default="", max_length=500)
    max_consecutive: int = Field(default=1, ge=1, le=5)

    @model_validator(mode="after")
    def validate_value(self) -> "CleaningRule":
        """校验需要匹配文本的规则，拒绝会匹配空串或嵌套量词的正则。"""
        if self.type not in {"replace_text", "regex_remove"}:
            return self
        if not self.value:
            raise ValueError(f"{self.type} 规则必须提供 value")
        if self.type == "replace_text":
            return self

        try:
            pattern = re.compile(self.value)
        except re.error as exc:
            raise ValueError(f"regex_remove 规则不是有效正则: {exc}") from exc
        if pattern.search("") is not None:
            raise ValueError("regex_remove 规则不能匹配空文本")
        if re.search(r"\([^()]*[+*{][^()]*\)[+*{]", self.value):
            raise ValueError("regex_remove 规则不能包含嵌套量词")
        return self


class CleaningConfig(BaseModel):
    """知识库级清洗规则集合。"""

    rules: list[CleaningRule] = Field(default_factory=list, max_length=30)
