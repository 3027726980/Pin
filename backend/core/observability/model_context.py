"""作者：LHF；时间：2026-10-25；作用：模型调用完成后一次记录完整脱敏 context 与 response。"""

import codecs
import json
import logging
import re
from datetime import UTC, datetime
from uuid import uuid4

import httpx

from backend.core.observability.context import current_trace
from backend.core.observability.events import _is_sensitive_key, sanitize_event_detail
from backend.core.observability.operations import Operation, model_scope

_clients: dict[str, httpx.AsyncClient] = {}
_logger = logging.getLogger("backend.agent.trace")


def sanitize_trace_payload(payload):
    """普通事件维持限长；模型输入单独保留完整内容，并移除正文中的凭据。"""
    if payload.get("event") != "llm.context" and not payload.get("record_version"):
        return sanitize_event_detail(payload)

    def redact(value, schema_properties=False):
        """递归脱敏正文，保留消息数量、顺序和文本长度以外的完整结构。"""
        if isinstance(value, str):
            value = re.sub(
                r"\b(?:sk-|pin_)[a-zA-Z0-9_-]+|(?i:Bearer)\s+[^\s\"',}]+",
                "[REDACTED]",
                value,
            )
            return re.sub(
                r"(?i)(\b(?:api_key|password|token|secret|authorization)\b[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+",
                r"\1[REDACTED]",
                value,
            )
        if isinstance(value, dict):
            return {
                str(key): redact(item, key == "properties")
                for key, item in value.items()
                if not _is_sensitive_key(key)
                or schema_properties
                or key == "token"
                and "logprob" in value
            }
        if isinstance(value, list):
            return [redact(item) for item in value]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if hasattr(value, "model_dump"):
            return redact(value.model_dump(mode="json"))
        return redact(str(value))

    return redact(payload)


def write_context_event(event, summary, detail, *, status="completed"):
    """把上下文诊断写入当前 Trace，仅进入完整链路而不广播到公开聊天流。"""
    trace = current_trace()
    payload = {
        "event": event,
        "event_id": f"ctx_{uuid4().hex}",
        "timestamp": datetime.now(UTC).isoformat(),
        "request_id": trace.request_id if trace else None,
        "trace_id": trace.trace_id if trace else None,
        "turn_id": trace.turn_id if trace else None,
        "conversation_id": trace.conversation_id if trace else None,
        "agent_id": trace.agent_id if trace else None,
        "stage": "model",
        "stage_id": "context.1",
        "visibility": "debug",
        "status": status,
        "summary": summary,
        "detail": detail,
    }
    # 压缩和手动压缩汇总同样采用终态结构，不再作为缺少输入输出的旧事件。
    started_at = detail.get("started_at", payload["timestamp"])
    payload.update(
        {
            "record_version": 1,
            "kind": "request" if event == "trace.summary" else "compaction",
            "operation_id": trace.turn_id
            if trace and event == "trace.summary"
            else payload["event_id"],
            "parent_id": trace.turn_id if trace and event != "trace.summary" else None,
            "started_at": started_at,
            "ended_at": payload["timestamp"],
            "duration_ms": max(
                0,
                round(
                    (
                        datetime.now(UTC) - datetime.fromisoformat(started_at)
                    ).total_seconds()
                    * 1000
                ),
            ),
            "input": {
                "conversation_id": trace.conversation_id if trace else None,
                **{
                    key: value
                    for key, value in detail.items()
                    if key.startswith("before_")
                    or key in {"trigger", "trigger_fraction", "keep_fraction"}
                },
            },
            "output": detail,
            "metadata": {"source_event": event},
            "error": None,
        }
    )
    payload.pop("detail", None)
    _logger.info(event, extra={"structured_data": sanitize_trace_payload(payload)})


async def capture_model_request(request: httpx.Request, purpose: str):
    """准备请求采集对象，仅暂存输入；响应完成后才输出日志。"""
    try:
        payload = json.loads(await request.aread())
    except (ValueError, UnicodeDecodeError):
        return
    if not isinstance(payload, dict):
        return
    if not any(key in payload for key in ("messages", "input", "instructions")):
        return
    scope = model_scope()
    if scope is not None:
        scope["attempt"] = scope.get("attempt", 0) + 1
    label, _, provider = purpose.partition(":")
    observer = ModelResponseCapture(
        payload,
        {
            "purpose": (scope or {}).get("purpose", label),
            "provider": (scope or {}).get("provider") or provider or request.url.host,
            "model": payload.get("model"),
            "endpoint": f"{request.url.scheme}://{request.url.host}{request.url.path}",
            "logical_call_id": (scope or {}).get("logical_call_id"),
            "attempt": (scope or {}).get("attempt", 1),
        },
    )
    request.extensions["pin_model_capture"] = observer
    return observer


def _merge_delta(target, delta):
    """合并流式消息的文本、工具参数和扩展字段，不保存原始帧。"""
    for key, value in delta.items():
        if value is None:
            continue
        if isinstance(value, str):
            target[key] = (
                (target.get(key, "") + value)
                if key not in {"role", "id", "type"}
                else value
            )
        elif isinstance(value, dict):
            _merge_delta(target.setdefault(key, {}), value)
        elif isinstance(value, list):
            current = target.setdefault(key, [])
            for item in value:
                if isinstance(item, dict) and "index" in item:
                    index = item["index"]
                    while len(current) <= index:
                        current.append({})
                    _merge_delta(current[index], item)
                elif (
                    key == "content"
                    and isinstance(item, dict)
                    and item.get("type") == "text"
                ):
                    # 多模态文本块按顺序聚合；非文本块保留其公开结构。
                    if (
                        current
                        and isinstance(current[-1], dict)
                        and current[-1].get("type") == "text"
                    ):
                        current[-1]["text"] += item.get("text", "")
                    else:
                        current.append(dict(item))
                else:
                    current.append(item)
        else:
            target[key] = value


class ModelResponseCapture:
    """增量解析 OpenAI/DashScope SSE，并在请求结束后写完整合并结果。"""

    def __init__(self, payload, metadata):
        """保存实际序列化输入和请求级终态对象，不进行网络访问。"""
        self.operation = Operation(
            "model",
            f"模型调用 · {metadata['purpose']}",
            input=payload,
            metadata=metadata,
        )
        self.streaming = bool(payload.get("stream"))
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.buffer = ""
        self.result = {}
        self.done = False
        self.http_status = None

    def feed(self, data):
        """只处理当前到达字节；原始字节由响应包装器立即转发。"""
        self.buffer += self.decoder.decode(data)
        if self.streaming:
            self.buffer = self.buffer.replace("\r\n", "\n")
            while "\n\n" in self.buffer:
                frame, self.buffer = self.buffer.split("\n\n", 1)
                self._consume_frame(frame)

    def _consume_frame(self, frame):
        """供应商扩展格式解析失败只影响诊断，不能中断实际响应转发。"""
        try:
            self._frame(frame)
        except Exception as error:  # noqa: BLE001 - 诊断旁路必须隔离供应商扩展格式异常。
            self.operation.metadata.setdefault("capture_errors", []).append(
                {"type": type(error).__name__, "message": str(error)}
            )
            data = "\n".join(
                line[5:].lstrip()
                for line in frame.splitlines()
                if line.startswith("data:")
            )
            try:
                packet = json.loads(data)
            except ValueError:
                packet = {"unparsed_data": data}
            self.result.setdefault("unmerged_response", []).append(packet)

    def _frame(self, frame):
        """解析单个 SSE 帧，处理结束标志、错误和结构化模型返回字段。"""
        data = "\n".join(
            line[5:].lstrip() for line in frame.splitlines() if line.startswith("data:")
        )
        if data == "[DONE]":
            self.done = True
            return
        if not data:
            return
        try:
            packet = json.loads(data)
        except ValueError:
            self.result.setdefault("parse_errors", []).append({"data": data})
            return
        if not isinstance(packet, dict):
            self.result.setdefault("data", []).append(packet)
            return
        event_type = packet.get("type", "")
        if event_type in {
            "response.completed",
            "response.failed",
            "response.incomplete",
        }:
            self.result = packet.get("response", packet)
            self.done = True
            if event_type != "response.completed":
                self.operation.status = "failed"
            return
        if event_type == "response.output_text.delta":
            self.result["output_text"] = self.result.get(
                "output_text", ""
            ) + packet.get("delta", "")
            return
        if event_type and event_type.startswith("response."):
            # Responses API 的最终 response 覆盖中间状态；未正常结束时保留已收到的增量。
            if "delta" in packet:
                self.result.setdefault("partial_output", []).append(
                    {"type": event_type, "delta": packet["delta"]}
                )
            return
        native_output = packet.get("output") or {}
        if not isinstance(native_output, dict):
            native_output = {"value": native_output}
        choices = packet.get("choices", native_output.get("choices"))
        for key, value in packet.items():
            if key not in {"choices", "output"} and value is not None:
                self.result[key] = value
        if choices is not None:
            output = self.result.setdefault("choices", [])
            for choice in choices:
                index = choice.get("index", 0)
                while len(output) <= index:
                    output.append({"index": len(output), "message": {}})
                item = output[index]
                _merge_delta(
                    item["message"], choice.get("delta") or choice.get("message") or {}
                )
                for key, value in choice.items():
                    if key not in {"delta", "message"} and value is not None:
                        if key == "logprobs" and isinstance(value, dict):
                            _merge_delta(item.setdefault(key, {}), value)
                        else:
                            item[key] = value
        if native_output:
            for key, value in native_output.items():
                if key == "text":
                    self.result.setdefault("output", {})[key] = (
                        self.result.get("output", {}).get(key, "") + value
                    )
                elif key != "choices":
                    self.result.setdefault("output", {})[key] = value
        if packet.get("error") or packet.get("code") not in (None, "", "200", 200):
            self.operation.status = "failed"
            self.operation.error = {
                "type": "ProviderError",
                "message": packet.get("error") or packet.get("message"),
                "code": packet.get("code"),
            }

    def finish(self, *, exhausted=False, error=None):
        """结束时只写一条记录，保留失败/取消的部分响应和缺失 usage 的真实状态。"""
        if self.operation.finished:
            return
        if self.streaming:
            if self.buffer.strip():
                self._consume_frame(self.buffer)
        else:
            try:
                self.result = json.loads(self.buffer)
            except ValueError:
                self.result = {"body": self.buffer}
        self.operation.output = self.result if self.result or self.buffer else None
        if isinstance(self.result, dict) and self.result.get("error"):
            self.operation.status = "failed"
            self.operation.error = {
                "type": "ProviderError",
                "message": self.result["error"],
            }
        self.operation.metadata.update(
            {
                "http_status": self.http_status,
                "stream": self.streaming,
                "response_format": "merged_sse" if self.streaming else "json",
                "response_complete": exhausted or self.done,
                "usage_reported": bool(self.result.get("usage"))
                if isinstance(self.result, dict)
                else False,
            }
        )
        if self.http_status is not None and self.http_status >= 400:
            self.operation.status = "failed"
            self.operation.error = {
                "type": "HTTPError",
                "status_code": self.http_status,
            }
        elif error is None and not exhausted and not self.done:
            self.operation.status = "cancelled"
        self.operation.finish(error=error)


def _log_capture_failure(phase, error):
    """作用：采集故障只记录阶段和异常类型，日志处理器故障也不能影响原始请求。"""
    try:
        _logger.warning("模型诊断采集失败 phase=%s error_type=%s", phase, type(error).__name__)
    except Exception:
        pass


class SafeResponseCapture:
    """作用：隔离诊断采集故障，保留真实网络异常和取消语义。"""

    def __init__(self, observer):
        """作用：绑定采集器，每次请求独立跟踪采集失败及终态写入。"""
        self.observer = observer
        self.failed = False
        self.finished = False

    def run(self, phase, callback, *args, **kwargs):
        """作用：执行诊断操作；首次失败后停用采集，但仍允许写入已有部分数据的终态。"""
        if self.failed and phase != "finish":
            return None
        try:
            return callback(*args, **kwargs)
        except Exception as error:
            self.failed = True
            try:
                self.observer.operation.metadata.update({
                    "capture_complete": False,
                    "capture_error": {"phase": phase, "type": type(error).__name__},
                })
            except Exception:
                pass
            _log_capture_failure(phase, error)
            return None

    def finish(self, **kwargs):
        """作用：只尝试一次终态记录，日志写入异常不覆盖正常响应或原始网络错误。"""
        if not self.finished:
            self.finished = True
            self.run("finish", self.observer.finish, **kwargs)


def _response_decoder(headers):
    """作用：与 HTTPX 原生选择规则一致，只有多种内容编码时才组合解码器。"""
    from httpx._decoders import SUPPORTED_DECODERS, IdentityDecoder, MultiDecoder

    children = [SUPPORTED_DECODERS[value.strip().lower()]()
                for value in headers.get_list("content-encoding", split_commas=True)
                if value.strip().lower() in SUPPORTED_DECODERS]
    if len(children) == 1:
        return children[0]
    return MultiDecoder(children=children) if children else IdentityDecoder()


class CapturedResponseStream(httpx.AsyncByteStream):
    """透传流式字节，不预读取响应，不增加首 Token 等待。"""

    def __init__(self, stream, capture, headers):
        """绑定原始响应流和独立请求采集器。"""
        self.stream, self.capture = stream, capture
        self.observer = capture.observer
        # 独立解码器只供日志使用，不能与 httpx 正在转发的解码器共享状态。
        # 适配当前 httpx 解码注册表，覆盖 gzip/deflate 及已安装的 br/zstd。
        self.content_decoder = capture.run("decoder_init", _response_decoder, headers)

    def _feed(self, data):
        """作用：独立解码日志副本，原始压缩字节仍完整透传给 HTTPX。"""
        self.observer.feed(self.content_decoder.decode(data))

    def _flush(self):
        """作用：流结束后仅刷新日志副本的解码器。"""
        self.observer.feed(self.content_decoder.flush())

    async def __aiter__(self):
        """原样转发每个数据块，在耗尽或异常时保存完整/部分响应。"""
        try:
            async for data in self.stream:
                self.capture.run("decode", self._feed, data)
                yield data
            self.capture.run("flush", self._flush)
            self.capture.finish(exhausted=True)
        except BaseException as error:
            if isinstance(error, GeneratorExit) and self.observer.done:
                self.capture.finish(exhausted=True)
            else:
                self.capture.finish(error=error)
            raise

    async def aclose(self):
        """提前关闭也产生唯一终态，随后释放原始网络连接。"""
        try:
            await self.stream.aclose()
        finally:
            self.capture.finish()


class ContextHttpClient(httpx.AsyncClient):
    """在 SDK 实际发送边界采集，兼容代理、流式、非流式和 SDK 重试。"""

    def __init__(self, *, purpose="agent", **kwargs):
        """保存用途并复用 httpx 原生连接、认证和代理配置。"""
        self.purpose = purpose
        super().__init__(**kwargs)

    async def send(self, request, *, stream=False, **kwargs):
        """每次 HTTP 尝试均独立采集，网络错误同样只落一条记录。"""
        try:
            observer = await capture_model_request(request, self.purpose)
        except Exception as error:
            _log_capture_failure("request", error)
            observer = None
        capture = SafeResponseCapture(observer) if observer is not None else None
        try:
            response = await super().send(request, stream=True, **kwargs)
            if observer is not None:
                observer.http_status = response.status_code
                observer.streaming = "text/event-stream" in response.headers.get(
                    "content-type", ""
                ) or (observer.streaming and response.status_code < 400)
                if response.is_stream_consumed:
                    capture.run("feed", observer.feed, response.content)
                    capture.finish(exhausted=True)
                else:
                    response.stream = CapturedResponseStream(
                        response.stream, capture, response.headers
                    )
            if not stream:
                await response.aread()
            return response
        except BaseException as error:
            if capture is not None:
                capture.finish(error=error)
            raise


def get_context_http_client(purpose: str = "agent") -> httpx.AsyncClient:
    """复用带输入记录钩子的客户端；钩子覆盖流式、非流式及 SDK 重试。"""
    if purpose not in _clients or _clients[purpose].is_closed:
        _clients[purpose] = ContextHttpClient(purpose=purpose)
    return _clients[purpose]


async def close_context_http_clients():
    """应用关闭时释放上下文记录客户端连接池。"""
    clients = list(_clients.values())
    _clients.clear()
    for client in clients:
        await client.aclose()
