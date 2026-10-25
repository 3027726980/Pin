"""作者：LHF；时间：2026-10-25；作用：按需加载技能说明到本轮临时上下文。"""

from fastapi import HTTPException
from langchain_core.tools import ToolException, tool
from pydantic import BaseModel, Field

from backend.core.observability.operations import Operation
from backend.skills.runtime import current_skill_turn
from backend.tools.common.base import BaseTool


class LoadSkillArgs(BaseModel):
    """技能加载工具参数。"""

    skill_name: str = Field(description="当前 Agent 绑定的技能名称")


class LoadSkillTool(BaseTool):
    """技能加载能力，内部注册且不进入业务工具表单。"""

    type = "load_skill"
    builtin = True
    description = "按需加载一个已绑定技能的操作说明。"

    @staticmethod
    async def validate_config(db, user, config, **kwargs):
        """内部能力不需要用户业务配置。"""
        return

    @staticmethod
    def build_langchain(db, user, config, **kwargs):
        """构建返回加载凭据的工具；正文只进入本轮请求投影。"""
        @tool(args_schema=LoadSkillArgs)
        async def load_skill(skill_name: str) -> dict:
            """加载可用技能，将操作说明加入本轮参考上下文。"""
            turn = current_skill_turn()
            if turn is None:
                raise ToolException("当前请求没有技能运行环境")
            try:
                with Operation("skill.load", f"加载技能 · {skill_name}", input={"skill_name": skill_name}) as operation:
                    item = turn.load(skill_name)
                    operation.output = item
                    return {"loaded": skill_name, "hash": item["hash"], "files": item["files"],
                            "message": "操作说明已加入本轮参考上下文，由你决定如何采用。"}
            except HTTPException as error:
                raise ToolException(str(error.detail)) from error
        load_skill.handle_tool_error = True
        return load_skill

    @staticmethod
    async def execute(db, user, config, **kwargs):
        """仅通过统一 Agent 工具调用加载技能。"""
        return await LoadSkillTool.build_langchain(db, user, config).ainvoke(kwargs)
