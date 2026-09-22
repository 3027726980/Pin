"""文档解析文本的受限、可复现清洗规则。"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata

from backend.schemas.cleaning import CleaningConfig, CleaningRule, CleaningRuleType


def _as_config(config: CleaningConfig | dict) -> CleaningConfig:
    """将 API/数据库字典统一转换为经过校验的配置对象。"""
    if isinstance(config, CleaningConfig):
        return config
    return CleaningConfig.model_validate(config)


def _remove_control_chars(text: str) -> str:
    """移除除换行、回车、制表符外的 Unicode 控制字符。"""
    return "".join(
        char
        for char in text
        if char in {"\n", "\r", "\t"} or unicodedata.category(char) != "Cc"
    )


def clean_text(raw: str, config: CleaningConfig | dict) -> str:
    """按顺序应用受限清洗规则并返回文本，不访问外部资源。"""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    for rule in _as_config(config).rules:
        if not rule.enabled:
            continue
        if rule.type == "normalize_unicode":
            text = unicodedata.normalize("NFC", text)
        elif rule.type == "remove_control_chars":
            text = _remove_control_chars(text)
        elif rule.type == "collapse_blank_lines":
            text = re.sub(r"\n{" + str(rule.max_consecutive + 1) + r",}", "\n" * rule.max_consecutive, text)
        elif rule.type == "trim_lines":
            text = "\n".join(line.strip() for line in text.split("\n"))
        elif rule.type == "collapse_punctuation":
            text = re.sub(r"([，。！？；：,.!?;:])\1+", r"\1", text)
        elif rule.type == "replace_text":
            text = text.replace(rule.value or "", rule.replacement)
        elif rule.type == "regex_remove":
            text = re.sub(rule.value or "", rule.replacement, text)
    return text


def cleaning_hash(config: CleaningConfig | dict) -> str:
    """计算规范化规则配置的 SHA-256，供处理结果失效判定使用。"""
    payload = _as_config(config).model_dump(mode="json", exclude_none=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
