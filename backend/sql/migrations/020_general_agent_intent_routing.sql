-- 020_general_agent_intent_routing.sql
-- general Agent 意图路由 + 内置推理工具开关（设计文档 dev-docs/20）

-- 意图识别规则集（Agent 级 JSONB，默认模板与 core/constants.py DEFAULT_INTENT_RULES 保持一致）
ALTER TABLE general_agents
    ADD COLUMN intent_rules JSONB NOT NULL DEFAULT '{"rules": [
        {"name": "检索意图", "kind": "keyword", "keywords": ["查", "搜索", "检索", "看看", "找一下", "查询"], "target": "general", "priority": 5},
        {"name": "对比分析", "kind": "keyword", "keywords": ["对比", "比较", "分析", "评估", "优缺点", "区别", "差异"], "target": "general", "priority": 5},
        {"name": "任务规划", "kind": "keyword", "keywords": ["规划", "方案", "计划", "步骤", "流程", "怎么做", "如何", "帮我"], "target": "general", "priority": 5},
        {"name": "数据类", "kind": "keyword", "keywords": ["数据", "统计", "报表", "指标", "趋势"], "target": "general", "priority": 5},
        {"name": "问候语", "kind": "keyword", "keywords": ["你好", "您好", "hi", "hello", "嗨", "哈喽", "早上好", "中午好", "下午好", "晚上好"], "target": "simple", "priority": 10},
        {"name": "感谢语", "kind": "keyword", "keywords": ["谢谢", "感谢", "辛苦了", "多谢"], "target": "simple", "priority": 20},
        {"name": "告别语", "kind": "keyword", "keywords": ["再见", "拜拜", "晚安"], "target": "simple", "priority": 30},
        {"name": "简短肯定", "kind": "keyword", "keywords": ["好的", "可以", "明白了", "知道了", "ok", "嗯"], "target": "simple", "priority": 40}
    ]}'::jsonb;

ALTER TABLE general_agents
    ADD COLUMN intent_routing BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE general_agents
    ADD COLUMN plan_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE general_agents
    ADD COLUMN reflect_enabled BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN general_agents.intent_rules IS '意图识别规则集（Agent 级，可编辑；默认复制全局模板 DEFAULT_INTENT_RULES）';
COMMENT ON COLUMN general_agents.intent_routing IS '意图路由开关：false=纯 ReAct（简单问题由 LLM 自我路由）；true=规则+LLM 兜底分类，simple 走零工具直接回答';
COMMENT ON COLUMN general_agents.plan_enabled IS '注册 plan 工具（复杂任务规划）';
COMMENT ON COLUMN general_agents.reflect_enabled IS '注册 reflect 工具（答案反思）';
