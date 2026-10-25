"""作者：LHF；时间：2026-10-25；作用：本地技能管理、提及和产物的共享契约。"""

from typing import Literal

from pydantic import BaseModel, Field


class CapabilityMention(BaseModel):
    """用户本轮能力偏好；不代表强制执行。"""

    kind: Literal["skill", "tool"]
    name: str = Field(min_length=1, max_length=128)


class SkillBindingUpdate(BaseModel):
    """整体替换一个 Agent 的本地技能绑定。"""

    names: list[str] = Field(default_factory=list, max_length=100)


class SkillStateUpdate(BaseModel):
    """更新本地技能启用状态。"""

    enabled: bool


class SkillArtifact(BaseModel):
    """脚本产物定位信息；下载仍需身份与会话鉴权。"""

    run_id: str
    path: str
    name: str
    size: int


class ContextPreviewRequest(BaseModel):
    """只读估算待发送正文及技能偏好的输入占用。"""

    message: str = Field(default="", max_length=4000)
    mentions: list[CapabilityMention] = Field(default_factory=list, max_length=100)
