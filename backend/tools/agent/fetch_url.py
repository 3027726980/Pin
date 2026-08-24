"""
Agent 工具：fetch_url（网页内容抓取）

功能：抓取指定 URL 的网页文本内容，供 LLM 分析页面资料。

新增工具流程（仅此一个文件，其他代码零改动）：
1. 继承 BaseTool，声明 type / description / param_schema
2. 实现 validate_config（配置校验）和 build_langchain（LangChain 工具构建）
3. 保存即生效：tool-defs 接口自动返回、前端自动渲染参数表单

健壮性：抓取失败返回错误文本（不抛异常），LLM 自行决定下一步。
"""
import logging

from backend.tools.common.base import BaseTool

logger = logging.getLogger(__name__)

FETCH_URL_DESCRIPTION = "抓取指定 URL 的网页文本内容，返回页面正文（用于分析网页资料）。"


class FetchUrlTool(BaseTool):
    """网页抓取工具：LLM 自主决定是否调用，传入 URL 获取页面内容"""

    type = "fetch_url"
    description = FETCH_URL_DESCRIPTION
    # 配置中需要补全名称的字段（如 {"kb_id": "kb_name"}），本工具无
    name_ref_keys = {}

    # ── 参数 Schema（前端动态表单渲染）──
    param_schema: list[dict] = [
        {"key": "base_url", "label": "默认网址", "type": "string",
         "required": False,
         "placeholder": "可选，如 https://example.com（不填则每次由 LLM 传入 URL）"},
        {"key": "max_chars", "label": "最大抓取字符数", "type": "number",
         "default": 2000, "min": 100, "max": 10000},
        {"key": "strip_html", "label": "去除 HTML 标签", "type": "boolean",
         "default": True},
    ]

    @staticmethod
    async def validate_config(db, user, config: dict, **kwargs) -> None:
        """配置校验（创建/编辑 Agent 时调用）：base_url 填了就必须合法"""
        base_url = config.get("base_url")
        if base_url and not str(base_url).startswith(("http://", "https://")):
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail="默认网址必须以 http:// 或 https:// 开头")
        return None

    @staticmethod
    def build_langchain(db, user, config: dict, **kwargs):
        """构建 LangChain 工具（对话时调用，闭包绑定配置，返回 @tool 对象）"""
        from langchain_core.tools import tool

        max_chars = config.get("max_chars") or 2000
        strip_html = config.get("strip_html", True)
        default_url = config.get("base_url") or ""

        @tool
        async def fetch_url(url: str = "") -> str:
            """抓取指定 URL 的网页文本内容，返回页面正文。URL 为空时使用配置的默认网址。"""
            target = (url or "").strip() or default_url
            if not target:
                return "错误：未提供 URL，且未配置默认网址"
            try:
                import httpx
                async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                    resp = await client.get(target)
                    resp.raise_for_status()
                text = resp.text
                if strip_html:
                    import re
                    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", "", text)
                    text = re.sub(r"<[^>]+>", " ", text)
                    text = re.sub(r"\s+", " ", text).strip()
                return text[:max_chars]
            except Exception as e:
                logger.warning(f"fetch_url 抓取失败: {e}")
                return f"抓取失败：{e}"

        return fetch_url

    # execute 可选：仅 simple_rag 代码控制场景需要，纯 LLM 调用型工具可不实现
