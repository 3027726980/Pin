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

# ── 意图识别默认规则模板（general Agent 创建时填充，用户可增删改）──
# 设计原则：general 规则可激进（误判代价 = 多花 token），simple 规则必须保守（误判代价 = 瞎编）
DEFAULT_INTENT_RULES: dict = {
    "rules": [
        {"name": "检索意图", "kind": "keyword", "keywords": ["查", "搜索", "检索", "看看", "找一下", "查询"], "target": "general", "priority": 5},
        {"name": "对比分析", "kind": "keyword", "keywords": ["对比", "比较", "分析", "评估", "优缺点", "区别", "差异"], "target": "general", "priority": 5},
        {"name": "任务规划", "kind": "keyword", "keywords": ["规划", "方案", "计划", "步骤", "流程", "怎么做", "如何", "帮我"], "target": "general", "priority": 5},
        {"name": "数据类", "kind": "keyword", "keywords": ["数据", "统计", "报表", "指标", "趋势"], "target": "general", "priority": 5},
        {"name": "问候语", "kind": "keyword", "keywords": ["你好", "您好", "hi", "hello", "嗨", "哈喽", "早上好", "中午好", "下午好", "晚上好"], "target": "simple", "priority": 10},
        {"name": "感谢语", "kind": "keyword", "keywords": ["谢谢", "感谢", "辛苦了", "多谢"], "target": "simple", "priority": 20},
        {"name": "告别语", "kind": "keyword", "keywords": ["再见", "拜拜", "晚安"], "target": "simple", "priority": 30},
        {"name": "简短肯定", "kind": "keyword", "keywords": ["好的", "可以", "明白了", "知道了", "ok", "嗯"], "target": "simple", "priority": 40},
    ]
}
