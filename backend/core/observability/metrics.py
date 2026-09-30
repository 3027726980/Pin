"""单次 Agent Turn 的统一延迟和调用次数指标。"""

from dataclasses import dataclass
from time import perf_counter


@dataclass(slots=True)
class TurnMetrics:
    """收集反馈、首 Token、总耗时及调用次数。"""

    started_at: float
    feedback_latency_ms: int | None = None
    answer_first_token_ms: int | None = None
    total_duration_ms: int | None = None
    queue_wait_ms: int = 0
    llm_calls: int = 0
    tool_calls: int = 0

    def _elapsed_ms(self) -> int:
        """返回从 Turn 开始到当前的单调时钟耗时。"""
        return max(0, round((perf_counter() - self.started_at) * 1000))

    def mark_feedback(self) -> None:
        """记录首个反馈事件，只接受第一次调用。"""
        if self.feedback_latency_ms is None:
            self.feedback_latency_ms = self._elapsed_ms()

    def mark_answer_delta(self) -> None:
        """记录首个答案 delta，只接受第一次调用。"""
        if self.answer_first_token_ms is None:
            self.answer_first_token_ms = self._elapsed_ms()

    def add_queue_wait(self, duration_ms: int) -> None:
        """累加模型限流或连接池排队耗时。"""
        self.queue_wait_ms += max(0, duration_ms)

    def increment_llm_calls(self) -> None:
        """增加一次 LLM 调用计数。"""
        self.llm_calls += 1

    def increment_tool_calls(self) -> None:
        """增加一次工具调用计数。"""
        self.tool_calls += 1

    def finish(self) -> None:
        """记录 Turn 总耗时，只接受第一次调用。"""
        if self.total_duration_ms is None:
            self.total_duration_ms = self._elapsed_ms()


__all__ = ["TurnMetrics"]
