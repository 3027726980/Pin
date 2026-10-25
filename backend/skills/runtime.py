"""作者：LHF；时间：2026-10-25；作用：每轮技能上下文、快照、执行和产物授权。"""

import asyncio
import hashlib
import json
import shutil
import time
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID, uuid4

from fastapi import HTTPException
from filelock import FileLock, Timeout
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage

from backend.core.observability.operations import Operation
from backend.skills.registry import SkillRegistry, safe_relative, skill_setting
from backend.skills.runner import run_python

_TURN: ContextVar["SkillTurn | None"] = ContextVar("skill_turn", default=None)


def current_skill_turn():
    """返回当前请求的技能上下文，异步子工具共享同一轮实例。"""
    return _TURN.get()


def available_skills(registry, owner_id, agent_id):
    """只返回已绑定、有效且启用的技能，其他包仍可在管理列表诊断。"""
    bound = registry.bindings(owner_id, agent_id)
    return [item for item in registry.list(owner_id)
            if item["name"] in bound and item.get("valid") and item["enabled"]]


def catalog_text(items):
    """生成轻量能力目录，明确由模型判断是否使用。"""
    if not items:
        return ""
    lines = [f"- {item['name']}: {item['description']}" for item in items]
    return ("\n\n<available_skills>\n" + "\n".join(lines)
            + "\n</available_skills>\n以上是可用技能；相关时可调用 load_skill 读取说明，"
              "再按需使用已有工具、read_skill_file 或 run_skill_script。"
              "技能和 @ 提及是任务参考与用户偏好，由你判断如何处理，可以直接回答。"
              "历史加载回执不包含正文，不能替代本轮按需加载。"
              "只使用当前已授权能力，不因技能中的 allowed-tools 扩大权限。")


def preference_text(mentions, bodies):
    """将偏好和技能正文包装为本轮临时用户参考材料。"""
    if not mentions and not bodies:
        return ""
    selected = "、".join(f"{item.kind}:{item.name}" for item in mentions)
    sections = [f"本轮用户偏好：{selected or '按任务自行选择'}。这些偏好不要求强制使用技能或工具。"]
    for name, body in bodies.items():
        sections.append(f"<skill_reference name={json.dumps(name)}>\n{body}\n</skill_reference>")
    return "\n\n<turn_reference>\n" + "\n\n".join(sections) + "\n</turn_reference>"


class SkillTurn:
    """请求级运行环境；技能正文只投影到请求，不写入 checkpoint 用户消息。"""

    def __init__(self, owner_id, agent_id, conversation_id, mentions=(), registry=None):
        """装载目录、验证提及，并为明确提及技能准备稳定副本。"""
        self.registry = registry or SkillRegistry()
        self.owner_id = str(owner_id)
        self.agent_id = str(agent_id)
        self.conversation_id = str(conversation_id)
        self.mentions = list(mentions)
        self.items = available_skills(self.registry, owner_id, agent_id)
        self.names = {item["name"] for item in self.items}
        self.loaded = {}
        self.resources = {}
        self.artifacts = []
        self.run_id = uuid4().hex
        self.root = self.registry.user_root(owner_id) / ".runs" / self.run_id
        self.semaphore = asyncio.Semaphore(max(1, int(skill_setting("max_parallel_scripts", 2))))
        self._lock = None
        self.input_capacity = None
        self.token_counter = None

    def validate_mentions(self, tool_names):
        """只允许已绑定技能和真正注册给此 Agent 的业务工具。"""
        for item in self.mentions:
            choices = self.names if item.kind == "skill" else set(tool_names)
            if item.name not in choices:
                raise HTTPException(422, f"提及的{item.kind}不可用：{item.name}")

    def _ensure_root(self):
        """惰性创建执行目录并持有跨进程活动锁。"""
        if self._lock is not None:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = FileLock(str(self.root / ".active.lock"))
        self._lock.acquire()
        self._save_manifest()

    def _save_manifest(self):
        """产物清单和归属保存为本地 JSON，下载只允许清单中文件。"""
        value = {"owner_id": self.owner_id, "agent_id": self.agent_id,
                 "conversation_id": self.conversation_id, "artifacts": self.artifacts,
                 "updated_at": time.time()}
        temporary = self.root / "manifest.tmp"
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.root / "manifest.json")

    def load(self, name):
        """检查本轮授权并创建技能快照，重复加载复用同一副本。"""
        if name not in self.names:
            raise HTTPException(404, "技能未绑定或不可用")
        current = self.registry.get(self.owner_id, name)
        if not current["enabled"] or name not in self.registry.bindings(self.owner_id, self.agent_id):
            raise HTTPException(404, "技能已停用或解除绑定")
        if name not in self.loaded:
            self._ensure_root()
            target = self.root / "snapshots" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            self.loaded[name] = self.registry.snapshot(self.owner_id, self.agent_id, name, target)
        return self.loaded[name]

    def prepare(self, tool_names):
        """执行前验证所有提及，正文注入本轮模型参考上下文。"""
        self.validate_mentions(tool_names)
        for item in self.mentions:
            if item.kind == "skill":
                self.load(item.name)
        with Operation("skill.context", "本轮技能与能力偏好", input={"mentions": [item.model_dump() for item in self.mentions]},
                       metadata={"available_skills": sorted(self.names)}) as operation:
            operation.output = {"injected_skills": [item.name for item in self.mentions if item.kind == "skill"]}

    def reference(self, *, include_loaded=True):
        """主 Agent 注入手动选择正文；核验可同时参考本轮自动加载说明。"""
        names = self.loaded if include_loaded else {item.name for item in self.mentions if item.kind == "skill"}
        bodies = {name: self.loaded[name]["body"] for name in names}
        bodies.update(self.resources)
        return preference_text(self.mentions, bodies)

    @property
    def catalog(self):
        """返回本轮固定的技能名称与用途目录。"""
        return catalog_text(self.items)

    async def execute(self, name, path, args, stdin):
        """在技能副本里运行脚本，将真实输出与产物交还 Agent。"""
        from backend.services.model_policy import current_turn_budget
        self.load(name)
        source = safe_relative(self.root / "snapshots" / name, path)
        if not source.is_file() or source.suffix != ".py":
            raise HTTPException(422, "只能执行技能目录中存在的 Python 文件")
        async with self.semaphore:
            execution = self.root / "executions" / uuid4().hex / name
            await asyncio.to_thread(shutil.copytree, self.root / "snapshots" / name, execution)
            baseline = {p.relative_to(execution).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in execution.rglob("*") if p.is_file()}
            budget = current_turn_budget()
            timeout = float(skill_setting("script_timeout_seconds", 60))
            if budget is not None:
                timeout = min(timeout, budget.remaining_ms / 1000)
            if timeout <= 0:
                raise TimeoutError("本轮执行预算已耗尽")
            result = await run_python(safe_relative(execution, path), args, stdin, timeout=timeout,
                                      max_output=int(skill_setting("max_output_bytes", 256 * 1024)), cwd=execution)
            additions = []
            for candidate in sorted(execution.rglob("*")):
                if candidate.is_symlink() or not candidate.is_file() or "__pycache__" in candidate.parts:
                    continue
                relative = candidate.relative_to(execution).as_posix()
                if baseline.get(relative) == hashlib.sha256(candidate.read_bytes()).hexdigest():
                    continue
                artifact = {"run_id": self.run_id, "path": candidate.relative_to(self.root).as_posix(),
                            "name": candidate.name, "size": candidate.stat().st_size}
                additions.append(artifact)
            self.artifacts.extend(additions)
            self._save_manifest()
            result["artifacts"] = additions
            if result["status"] != "completed":
                result["error"] = {"type": result["status"], "message": result["stderr"] or result["status"]}
            return result

    @contextmanager
    def bind(self):
        """绑定当前异步链路并在请求结束时释放活动锁。"""
        token = _TURN.set(self)
        try:
            yield self
        finally:
            _TURN.reset(token)
            if self._lock is not None:
                self._save_manifest()
                self._lock.release()
            cleanup_runs(self.registry, self.owner_id)


class SkillContextMiddleware(AgentMiddleware):
    """只替换当次模型消息投影，避免参考正文成为持久化用户消息。"""

    async def awrap_model_call(self, request, handler):
        """给最后一条真实用户消息追加本轮技能参考，工具协议保持不变。"""
        turn = current_skill_turn()
        reference = turn.reference() if turn else ""
        if not reference:
            projected = request
        else:
            messages = list(request.messages)
            for index in range(len(messages) - 1, -1, -1):
                if isinstance(messages[index], HumanMessage):
                    original = messages[index]
                    messages[index] = original.model_copy(update={"content": original.text + reference})
                    break
            projected = request.override(messages=messages)
        if turn and turn.token_counter and turn.input_capacity:
            from langchain_core.utils.function_calling import convert_to_openai_tool
            schemas = [convert_to_openai_tool(tool) for tool in projected.tools]
            messages = ([projected.system_message] if projected.system_message else []) + list(projected.messages)
            if turn.token_counter(messages, tools=schemas) > turn.input_capacity:
                raise HTTPException(422, "当前问题、技能和工具结果超过模型输入容量，请减少提及或开启新会话")
        return await handler(projected)


def cleanup_runs(registry, owner_id):
    """按保留时间清理已结束执行，活动文件锁支持多个后端进程。"""
    root = registry.user_root(owner_id) / ".runs"
    if not root.exists():
        return
    cutoff = time.time() - float(skill_setting("retention_hours", 24)) * 3600
    for directory in root.iterdir():
        manifest = directory / "manifest.json"
        if not directory.is_dir() or directory.is_symlink() or not manifest.exists() or manifest.stat().st_mtime >= cutoff:
            continue
        lock = FileLock(str(directory / ".active.lock"))
        try:
            with lock.acquire(timeout=0):
                pass
        except Timeout:
            continue
        if directory.resolve().parent == root.resolve():
            shutil.rmtree(directory, ignore_errors=True)


def artifact_file(registry, owner_id, agent_id, run_id, path):
    """解析被清单授权的产物，返回路径及其会话归属供路由再次鉴权。"""
    try:
        UUID(run_id)
    except ValueError as error:
        raise HTTPException(404, "产物不存在") from error
    directory = registry.user_root(owner_id) / ".runs" / run_id
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise HTTPException(404, "产物不存在或已过期") from error
    if manifest.get("owner_id") != str(owner_id) or manifest.get("agent_id") != str(agent_id):
        raise HTTPException(404, "产物不存在")
    if not any(item.get("path") == path for item in manifest.get("artifacts", [])):
        raise HTTPException(404, "产物不存在")
    target = safe_relative(directory, path)
    if not target.is_file():
        raise HTTPException(404, "产物不存在或已过期")
    return target, manifest["conversation_id"]
