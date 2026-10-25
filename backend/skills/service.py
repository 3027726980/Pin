"""作者：LHF；时间：2026-10-25；作用：协调现有 Agent 权限与文件系统技能目录。"""

from backend.services.agent import AgentService
from backend.skills.registry import SkillRegistry
from backend.skills.runtime import available_skills
from backend.tools import ToolRegistry


async def agent_capabilities(db, owner, agent_id):
    """返回真正配置给当前 Agent 的业务工具和有效技能，不扩展授权范围。"""
    agent = await AgentService.get(db, owner, agent_id)
    configs = [item.model_dump(mode="json") for item in agent.tools]
    tools = ToolRegistry.build_langchain_tools(db, owner, configs, citations_store=[])
    return {"skills": [{"kind": "skill", "name": item["name"], "description": item["description"]}
                       for item in available_skills(SkillRegistry(), owner.id, agent_id)],
            "tools": [{"kind": "tool", "name": item.name, "description": item.description} for item in tools]}
