"""作者：LHF；时间：2026-10-25；作用：本地技能管理、绑定和产物下载接口。"""
# ruff: noqa: B008 -- FastAPI 的 Depends/File 是声明式依赖参数。

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from backend.api.deps import get_current_user
from backend.core.database import get_db
from backend.repositories import ConversationRepo
from backend.schemas.common import SuccessResponse
from backend.services.agent import AgentService
from backend.skills.registry import SkillRegistry, skill_setting
from backend.skills.runtime import artifact_file
from backend.skills.schemas import SkillBindingUpdate, SkillStateUpdate
from backend.skills.service import agent_capabilities

router = APIRouter(prefix="/api/v1", tags=["技能"])


@router.get("/skills")
async def list_skills(user=Depends(get_current_user)):
    """动态读取当前用户本地技能和逐包诊断。"""
    return SuccessResponse(result=await asyncio.to_thread(SkillRegistry().list, user.id))


async def _upload(file, user, replace_name=None):
    """限制上传读取量，格式校验和发布在线程执行。"""
    limit = int(skill_setting("max_zip_bytes", 10 * 1024 * 1024))
    data = await file.read(limit + 1)
    try:
        if len(data) > limit:
            raise HTTPException(422, "ZIP 超过上传大小限制")
        result = await asyncio.to_thread(SkillRegistry().upload, user.id, data, replace_name)
        return SuccessResponse(result=result)
    finally:
        await file.close()


@router.post("/skills")
async def upload_skill(file: UploadFile = File(...), user=Depends(get_current_user)):
    """校验并导入单个 ZIP 技能包；上传不执行脚本。"""
    return await _upload(file, user)


@router.put("/skills/{name}/package")
async def replace_skill(name: str, file: UploadFile = File(...), user=Depends(get_current_user)):
    """以同名合法技能包替换原目录，失败保留原包。"""
    return await _upload(file, user, name)


@router.get("/skills/{name}/files")
async def skill_files(name: str, path: str | None = Query(None), user=Depends(get_current_user)):
    """返回包内清单，或指定相对路径的文本预览。"""
    registry = SkillRegistry()
    result = (await asyncio.to_thread(registry.read_file, user.id, name, path) if path
              else (await asyncio.to_thread(registry.get, user.id, name))["files"])
    return SuccessResponse(result=result)


@router.get("/skills/{name}")
async def get_skill(name: str, user=Depends(get_current_user)):
    """预览当前用户技能元信息和正文。"""
    return SuccessResponse(result=await asyncio.to_thread(SkillRegistry().get, user.id, name))


@router.put("/skills/{name}")
async def set_skill_state(name: str, body: SkillStateUpdate, user=Depends(get_current_user)):
    """将启停状态原子写入本地配置。"""
    return SuccessResponse(result=await asyncio.to_thread(SkillRegistry().set_enabled, user.id, name, body.enabled))


@router.delete("/skills/{name}")
async def delete_skill(name: str, user=Depends(get_current_user)):
    """解除全部绑定后删除本地技能。"""
    await asyncio.to_thread(SkillRegistry().remove, user.id, name)
    return SuccessResponse(message="技能已删除")


@router.get("/agents/{agent_id}/skills")
async def get_bindings(agent_id: UUID, db=Depends(get_db), user=Depends(get_current_user)):
    """校验 Agent 所有权，只读文件绑定。"""
    await AgentService.get(db, user, agent_id)
    return SuccessResponse(result={"names": SkillRegistry().bindings(user.id, agent_id)})


@router.put("/agents/{agent_id}/skills")
async def update_bindings(agent_id: UUID, body: SkillBindingUpdate, db=Depends(get_db), user=Depends(get_current_user)):
    """保存 Agent 本地技能绑定，不更新 Agent 数据表。"""
    await AgentService.get(db, user, agent_id)
    names = await asyncio.to_thread(SkillRegistry().bind, user.id, agent_id, body.names)
    return SuccessResponse(result={"names": names})


@router.get("/agents/{agent_id}/capabilities")
async def capabilities(agent_id: UUID, db=Depends(get_db), user=Depends(get_current_user)):
    """获取 @ 候选，仅包含此 Agent 的有效能力。"""
    return SuccessResponse(result=await agent_capabilities(db, user, agent_id))


@router.get("/agents/{agent_id}/skill-runs/{run_id}/artifacts")
async def download_artifact(agent_id: UUID, run_id: str, path: str = Query(...),
                            db=Depends(get_db), user=Depends(get_current_user)):
    """只下载当前用户拥有的会话产物，禁止按任意路径读取。"""
    await AgentService.get(db, user, agent_id)
    target, conversation_id = artifact_file(SkillRegistry(), user.id, agent_id, run_id, path)
    conv = await ConversationRepo.get_by_id(db, UUID(conversation_id))
    if conv is None or conv.status == 9 or conv.agent_id != agent_id or conv.user_id != user.id:
        raise HTTPException(404, "产物不存在")
    return FileResponse(target, filename=target.name, media_type="application/octet-stream")
