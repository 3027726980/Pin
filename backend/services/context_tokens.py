"""作者：LHF；时间：2026-10-25；作用：使用本地模型 tokenizer 或 tiktoken 统一计算上下文 token。"""
import json
from functools import lru_cache
from pathlib import Path

import tiktoken
from langchain_core.messages import convert_to_openai_messages

from backend.core.config import settings


class LocalTokenizerEncoding:
    """作用：直接加载本地 tokenizer.json 与聊天模板，不依赖 AutoTokenizer 的类名推断。"""

    def __init__(self, directory):
        """作用：只读取本地 JSON，不执行目录中的 Python 文件或联网下载。"""
        from transformers import PreTrainedTokenizerFast

        path = Path(directory).expanduser().resolve()
        config = json.loads((path / "tokenizer_config.json").read_text(encoding="utf-8"))
        special = {}
        for key in ("bos_token", "eos_token", "pad_token", "unk_token"):
            value = config.get(key)
            if value is not None:
                special[key] = value.get("content") if isinstance(value, dict) else value
        self.tokenizer = PreTrainedTokenizerFast(
            tokenizer_file=str(path / "tokenizer.json"),
            chat_template=config.get("chat_template"), **special)
        self.name = f"local:{path.name}"

    def encode(self, text, *, disallowed_special=()):
        """作用：使用该模型词表分词；纯文本计数不额外插入 BOS/EOS。"""
        return self.tokenizer.encode(text, add_special_tokens=False)

    def chat_tokens(self, messages):
        """作用：按包内模板渲染后计数，包含模板要求的 BOS、角色与生成起始标记。"""
        normalized = []
        for message in messages:
            item = dict(message)
            content = item.get("content")
            if content is not None and not isinstance(content, str):
                item["content"] = json.dumps(content, ensure_ascii=False)
            # 此包模板用 content=None 表示工具调用；保留调用前文本，避免工具参数被忽略。
            if item.get("tool_calls"):
                if item.get("content"):
                    normalized.append({"role": "assistant", "content": item["content"]})
                item["content"] = None
            normalized.append(item)
        rendered = self.tokenizer.apply_chat_template(
            normalized, tokenize=False, add_generation_prompt=True)
        return len(self.encode(rendered))


@lru_cache(maxsize=16)
def _local_encoding(directory):
    """作用：缓存本地分词器，避免每次圆环刷新或工具循环重复加载词表。"""
    return LocalTokenizerEncoding(directory)


@lru_cache(maxsize=64)
def _encoding(model_name, override):
    """作用：缓存模型分词器；未知模型使用明确标记的通用编码，不冒充供应商原生 tokenizer。"""
    if override:
        return tiktoken.get_encoding(override), "configuration"
    try:
        return tiktoken.encoding_for_model(model_name.removeprefix("openai/")), "model"
    except KeyError:
        return tiktoken.get_encoding("o200k_base"), "fallback"


class ContextTokenCounter:
    """作用：优先使用配置的本地 tokenizer，未配置时使用 tiktoken，不冒充供应商计费用量。"""

    def __init__(self, model_name=""):
        """作用：按模型名选择本地词表，其次按显式编码配置选择 tiktoken。"""
        sc = settings.checkpoint.summarization
        paths = getattr(sc, "model_tokenizer_paths", None)
        local_path = (getattr(paths, model_name, None)
                      or getattr(paths, model_name.rsplit("/", 1)[-1].lower(), None)) if paths else None
        if local_path:
            self.encoding, self.source = _local_encoding(str(Path(local_path).expanduser().resolve())), "local_tokenizer"
            self.method = "local_tokenizer_estimate"
            return
        overrides = getattr(sc, "model_token_encodings", None)
        override = getattr(overrides, model_name, None) if overrides else None
        self.encoding, self.source = _encoding(model_name, override)
        self.method = "tiktoken_estimate"

    def text_tokens(self, text):
        """作用：把文本作为普通内容分词，包含特殊 token 字面量时也不抛异常。"""
        return len(self.encoding.encode(text, disallowed_special=()))

    def __call__(self, messages, *, tools=None):
        """作用：本地模板计算角色封装；无本地模板时每条预留 3 token，工具 Schema 单独计数。"""
        converted = convert_to_openai_messages(list(messages))
        if isinstance(self.encoding, LocalTokenizerEncoding) and self.encoding.tokenizer.chat_template:
            total = self.encoding.chat_tokens(converted) if converted else 0
            # 所提供模板未渲染工具定义，因此单独计入 Schema，仍保留供应商封装估算标记。
            if tools:
                total += self.text_tokens(json.dumps(tools, ensure_ascii=False))
            return total
        total = 0
        for message in converted:
            total += 3
            for value in message.values():
                if value is not None:
                    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
                    total += self.text_tokens(text)
        if tools:
            total += self.text_tokens(json.dumps(tools, ensure_ascii=False))
        return total

    def split_text(self, text, max_tokens):
        """作用：按实际分词数切分且保留所有 Unicode 字符，不按字符/token 比例裁剪。"""
        start = 0
        while start < len(text):
            low, high = 1, len(text) - start
            best = 0
            while low <= high:
                mid = (low + high) // 2
                if self.text_tokens(text[start:start + mid]) <= max_tokens:
                    best, low = mid, mid + 1
                else:
                    high = mid - 1
            if best == 0:
                raise ValueError("分块预算不足以容纳一个字符")
            yield text[start:start + best]
            start += best
