"""
全局常量

统一管理业务常量，避免散落在各服务模块。
新增业务常量时优先定义在此文件，再在各模块 import 引用。
"""
from pathlib import Path

from backend.core.config import PROJECT_ROOT, settings

# ── 路径常量 ────────────────────────────

# 上传根目录（从 config.yaml storage.upload_dir 读取，相对于项目根）
UPLOAD_ROOT = PROJECT_ROOT / settings.storage.upload_dir

# ── 提示词模板 ──────────────────────────

# 默认 RAG 系统提示词模板（{agent_name} 在创建时替换为实际名称）
DEFAULT_SYSTEM_PROMPT = (
"""你是「{agent_name}」，一个基于知识库回答问题的 AI 助手。
请仅依据提供的资料片段回答用户问题，引用资料时标注来源编号（如 [1]）。
如果资料不足以回答，请如实说明"知识库中没有相关信息"，不要编造，并根据你已有的知识去回复用户。
回答使用中文，简洁准确。"""
)
