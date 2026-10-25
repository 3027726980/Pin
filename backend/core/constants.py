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

# 默认通用 Agent 系统提示词模板（{agent_name} 在创建时替换为实际名称）
DEFAULT_SYSTEM_PROMPT = (
    "你是「{agent_name}」，根据用户任务提供准确、清楚的帮助。"
    "你可以直接回答，也可以按需使用已配置工具和技能。用户 @ 表达偏好，由你决定如何采用。"
    "使用检索资料时只引用本轮工具返回的 [S#] 标识；资料不足或工具失败时如实说明，不编造来源。"
    "回答使用中文。"
)

# ── 意图识别默认规则模板（general Agent 创建时填充，用户可增删改）──
# 设计原则：general 规则可激进（误判代价 = 多花 token），规则目标为配置化类别码
DEFAULT_INTENT_RULES: dict = {
    "rules": [
        {"name": "检索意图", "kind": "keyword", "keywords": ["查", "搜索", "检索", "看看", "找一下", "查询"], "target": "general", "priority": 5},
        {"name": "对比分析", "kind": "keyword", "keywords": ["对比", "比较", "分析", "评估", "优缺点", "区别", "差异"], "target": "general", "priority": 5},
        {"name": "任务规划", "kind": "keyword", "keywords": ["规划", "方案", "计划", "步骤", "流程", "怎么做", "如何", "帮我"], "target": "general", "priority": 5},
        {"name": "数据类", "kind": "keyword", "keywords": ["数据", "统计", "报表", "指标", "趋势"], "target": "general", "priority": 5},
    ]
}
