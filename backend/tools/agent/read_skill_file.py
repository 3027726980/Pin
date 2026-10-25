"""作者：LHF；时间：2026-10-25；作用：按需读取技能包内参考文本，不写入会话正文。"""

from fastapi import HTTPException
from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, Field

from backend.core.observability.operations import Operation
from backend.skills.registry import safe_relative
from backend.skills.runtime import current_skill_turn
from backend.tools.common.base import BaseTool


class ReadSkillFileArgs(BaseModel):
    """技能资源读取参数。"""

    skill_name: str
    path: str = Field(description="技能目录内相对文件路径")


class ReadSkillFileTool(BaseTool):
    """技能文本资源读取，内部能力。"""

    type = "read_skill_file"
    builtin = True
    description = "读取已绑定技能目录中的参考文本。"

    @staticmethod
    async def validate_config(db, user, config, **kwargs):
        """内部能力不需要业务配置。"""
        return

    @staticmethod
    def build_langchain(db, user, config, **kwargs):
        """构建只读取包内文件的工具。"""
        @tool(args_schema=ReadSkillFileArgs)
        async def read_skill_file(skill_name: str, path: str) -> dict:
            """读取技能参考文件并加入本轮临时上下文。"""
            turn = current_skill_turn()
            if turn is None:
                raise ToolException("当前请求没有技能运行环境")
            try:
                turn.load(skill_name)
                target = safe_relative(turn.root / "snapshots" / skill_name, path)
                if not target.is_file() or target.stat().st_size > 1024 * 1024:
                    raise ToolException("文本文件不存在或超过 1 MiB")
                text = target.read_text(encoding="utf-8-sig")
                with Operation("skill.file", "读取技能参考文件", input={"skill_name": skill_name, "path": path}) as operation:
                    operation.output = {"content": text}
                turn.resources[f"{skill_name}/{path}"] = text
                return {"loaded": path, "message": "文件内容已加入本轮参考上下文。"}
            except (HTTPException, UnicodeError, OSError) as error:
                raise ToolException(str(getattr(error, "detail", error))) from error
        read_skill_file.handle_tool_error = True
        return read_skill_file

    @staticmethod
    async def execute(db, user, config, **kwargs):
        """通过统一工具协议读取参考文件。"""
        return await ReadSkillFileTool.build_langchain(db, user, config).ainvoke(kwargs)
