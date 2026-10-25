"""作者：LHF；时间：2026-10-25；作用：通过受控子进程执行技能包内 Python 脚本。"""

import json

from fastapi import HTTPException
from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, Field

from backend.skills.runtime import current_skill_turn
from backend.tools.common.base import BaseTool


class RunSkillScriptArgs(BaseModel):
    """脚本参数使用列表传递，不接受 shell 命令。"""

    skill_name: str
    path: str = Field(description="技能包内现存 .py 文件的相对路径")
    args: list[str] = Field(default_factory=list, max_length=100)
    stdin: str | None = Field(default=None, max_length=1024 * 1024)


class RunSkillScriptTool(BaseTool):
    """技能 Python 运行能力，复用工具预算与日志。"""

    type = "run_skill_script"
    builtin = True
    description = "运行已绑定技能中的 Python 脚本，返回输出和可下载产物。"

    @staticmethod
    async def validate_config(db, user, config, **kwargs):
        """执行参数在真正调用时校验。"""
        return

    @staticmethod
    def build_langchain(db, user, config, **kwargs):
        """构建由模型自主选择的脚本工具。"""
        @tool(args_schema=RunSkillScriptArgs)
        async def run_skill_script(skill_name: str, path: str, args: list[str] | None = None,
                                   stdin: str | None = None) -> dict:
            """执行技能 Python 脚本，失败保留真实退出码与输出。"""
            turn = current_skill_turn()
            if turn is None:
                raise ToolException("当前请求没有技能运行环境")
            try:
                result = await turn.execute(skill_name, path, args or [], stdin)
            except (HTTPException, OSError, TimeoutError, ValueError) as error:
                raise ToolException(str(getattr(error, "detail", error))) from error
            if result.get("error"):
                raise ToolException(json.dumps(result, ensure_ascii=False))
            return result
        run_skill_script.handle_tool_error = True
        return run_skill_script

    @staticmethod
    async def execute(db, user, config, **kwargs):
        """通过统一工具协议运行脚本。"""
        return await RunSkillScriptTool.build_langchain(db, user, config).ainvoke(kwargs)
