"""人工故障注入工具：仅显式配置到测试 Agent 时执行，无外部副作用。"""
import logging

from fastapi import HTTPException
from langchain_core.tools import ToolException, tool

from backend.tools.common.base import BaseTool

logger = logging.getLogger(__name__)


class FaultProbeTool(BaseTool):
    """始终失败，用于验证工具错误恢复与日志定位。"""

    type = "fault_probe"
    description = "故障测试工具（必定失败，仅用于测试 Agent）"
    param_schema = [{
        "key": "mode", "label": "故障模式", "type": "string",
        "default": "recoverable", "placeholder": "recoverable 或 runtime",
    }]

    @staticmethod
    async def validate_config(db, user, config: dict, **kwargs) -> None:
        """校验故障模式；不访问数据库。"""
        if config.get("mode", "recoverable") not in {"recoverable", "runtime"}:
            raise HTTPException(status_code=422, detail="故障模式必须为 recoverable 或 runtime")

    @staticmethod
    def build_langchain(db, user, config: dict, **kwargs):
        """构建必定抛错的工具；recoverable 转为错误 ToolMessage。"""
        mode = config.get("mode", "recoverable")

        @tool
        async def fault_probe() -> str:
            """执行人工故障测试，必定失败。只调用一次，失败后说明原因，不要重试。"""
            error_type = ToolException if mode == "recoverable" else RuntimeError
            try:
                raise error_type(f"PIN_FAULT_PROBE: intentional failure mode={mode}")
            except Exception:
                logger.exception("fault_probe failed mode=%s error_code=PIN_FAULT_PROBE", mode)
                raise

        fault_probe.handle_tool_error = True
        return fault_probe
