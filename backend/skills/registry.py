"""作者：LHF；时间：2026-10-25；作用：技能包校验、热读取、原子配置及用户隔离。"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

import yaml
from fastapi import HTTPException
from filelock import FileLock

from backend.core.config import PROJECT_ROOT, settings

NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def skill_setting(name, default):
    """读取可选技能配置，兼容没有新增配置的既有安装。"""
    return getattr(getattr(settings, "skills", None), name, default)


def safe_relative(root: Path, value: str) -> Path:
    """解析包内路径，拒绝绝对路径、Windows 路径和任何符号链接。"""
    if not value or "\\" in value or ":" in value or "\x00" in value:
        raise HTTPException(422, "文件路径不合法")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part in {".", ".."} for part in relative.parts):
        raise HTTPException(422, "文件路径必须位于技能目录内")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if any(part.endswith((".", " ")) or part.split(".")[0].upper() in reserved for part in relative.parts):
        raise HTTPException(422, "文件名包含不兼容的设备名或末尾字符")
    target = root.joinpath(*relative.parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise HTTPException(422, "文件路径越出技能目录")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise HTTPException(422, "技能目录不允许符号链接")
    return target


class SkillRegistry:
    """以磁盘为唯一事实来源，配置和文件均按用户隔离。"""

    def __init__(self, root: Path | str | None = None):
        """选择存储根目录；测试可传入隔离临时目录。"""
        configured = Path(root or skill_setting("root", "storage/skills"))
        self.root = configured if configured.is_absolute() else PROJECT_ROOT / configured
        self._locks = {}

    @staticmethod
    def validate_name(name: str) -> str:
        """校验标准技能名称，保留内部点目录。"""
        if len(name) > 64 or not NAME_PATTERN.fullmatch(name):
            raise HTTPException(422, "name: 必须是 1~64 位小写字母、数字和单个连字符")
        return name

    def user_root(self, user_id) -> Path:
        """使用 UUID 建立用户边界，拒绝可注入的目录标识。"""
        try:
            owner = str(UUID(str(user_id)))
        except ValueError as error:
            raise HTTPException(422, "用户标识不合法") from error
        return self.root / owner

    @contextmanager
    def locked(self, user_id):
        """跨进程锁住同一用户的配置和包发布操作。"""
        directory = self.user_root(user_id) / ".pin"
        directory.mkdir(parents=True, exist_ok=True)
        key = str(directory / "registry.lock")
        lock = self._locks.setdefault(key, FileLock(key, timeout=15))
        with lock:
            yield

    def config(self, user_id) -> dict:
        """读取配置，不将损坏配置伪装为空配置。"""
        path = self.user_root(user_id) / ".pin/config.json"
        if not path.exists():
            return {"enabled": {}, "bindings": {}}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or not all(isinstance(value.get(k), dict) for k in ("enabled", "bindings")):
                raise ValueError("enabled/bindings 必须是对象")
            return value
        except (ValueError, OSError) as error:
            raise HTTPException(409, f"本地技能配置损坏：{error}") from error

    def _save_config(self, user_id, value: dict) -> None:
        """调用方持锁后，以同目录临时文件原子替换配置。"""
        target = self.user_root(user_id) / ".pin/config.json"
        temporary = target.with_name(f"config.{uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def inspect(self, directory: Path) -> dict:
        """校验并读取一个技能目录，返回正文、元信息和文件清单。"""
        name = self.validate_name(directory.name)
        if directory.is_symlink():
            raise HTTPException(422, "技能目录不允许符号链接")
        source = safe_relative(directory, "SKILL.md")
        if not source.is_file():
            raise HTTPException(422, "缺少 SKILL.md")
        files = []
        total = 0
        digest = hashlib.sha256()
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise HTTPException(422, f"{path.name}: 不允许符号链接")
            if not path.is_file():
                continue
            relative = path.relative_to(directory).as_posix()
            safe_relative(directory, relative)
            total += path.stat().st_size
            if total > int(skill_setting("max_unpacked_bytes", 50 * 1024 * 1024)):
                raise HTTPException(422, "技能解压体积超过限制")
            if len(files) >= int(skill_setting("max_files", 200)):
                raise HTTPException(422, "技能文件数量超过限制")
            content = path.read_bytes()
            if path.suffix == ".py":
                try:
                    ast.parse(content, filename=relative)
                except (SyntaxError, ValueError) as error:
                    raise HTTPException(422, f"{relative}: Python 语法错误：{error}") from error
            digest.update(relative.encode())
            digest.update(b"\0")
            digest.update(content)
            files.append({"path": relative, "size": len(content)})
        try:
            text = source.read_text(encoding="utf-8-sig")
            lines = text.splitlines()
            if not lines or lines[0].strip() != "---":
                raise ValueError("必须以 YAML frontmatter 开始")
            end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
            metadata = yaml.safe_load("\n".join(lines[1:end]))
            if not isinstance(metadata, dict):
                raise TypeError("YAML 必须是对象")
            if metadata.get("name") != name:
                raise ValueError("name 必须与技能目录名一致")
            description = metadata.get("description")
            if not isinstance(description, str) or not 1 <= len(description.strip()) <= 1024:
                raise ValueError("description 必须为 1~1024 字符的非空文本")
            for field in ("license", "compatibility", "allowed-tools"):
                if field in metadata and not isinstance(metadata[field], str):
                    raise ValueError(f"{field} 必须是文本")
            if len(metadata.get("compatibility", "")) > 500:
                raise ValueError("compatibility 不得超过 500 字符")
            if "metadata" in metadata and (not isinstance(metadata["metadata"], dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in metadata["metadata"].items())):
                raise ValueError("metadata 必须是字符串映射")
            body = "\n".join(lines[end + 1:]).strip()
            if not body:
                raise ValueError("技能正文不能为空")
        except (ValueError, TypeError, StopIteration, UnicodeError, yaml.YAMLError) as error:
            raise HTTPException(422, f"SKILL.md: {error}") from error
        return {"name": name, "description": description.strip(), "metadata": metadata,
                "body": body, "files": files, "hash": digest.hexdigest()}

    def list(self, user_id) -> list[dict]:
        """动态扫描所有技能，非法包返回独立诊断。"""
        root = self.user_root(user_id)
        if not root.is_dir():
            return []
        with self.locked(user_id):
            config = self.config(user_id)
            result = []
            for path in sorted(root.iterdir()):
                if path.name.startswith(".") or not path.is_dir():
                    continue
                try:
                    item = self.inspect(path)
                    item.pop("body")
                    item["valid"] = True
                except (HTTPException, OSError) as error:
                    item = {"name": path.name, "valid": False, "error": str(getattr(error, "detail", error))}
                item["enabled"] = config["enabled"].get(path.name, True)
                item["bound_agents"] = [agent for agent, names in config["bindings"].items() if path.name in names]
                result.append(item)
            return result

    def get(self, user_id, name: str) -> dict:
        """动态读取一个技能，缺失时返回 404。"""
        self.validate_name(name)
        with self.locked(user_id):
            path = self.user_root(user_id) / name
            if not path.is_dir():
                raise HTTPException(404, "技能不存在")
            result = self.inspect(path)
            result["enabled"] = self.config(user_id)["enabled"].get(name, True)
            return result

    def bindings(self, user_id, agent_id) -> list[str]:
        """读取一个 Agent 的本地绑定，包括暂时失效的技能名称。"""
        return list(self.config(user_id)["bindings"].get(str(agent_id), []))

    def bind(self, user_id, agent_id, names: list[str]) -> list[str]:
        """整体替换绑定；名称去重并校验技能可读取。"""
        names = list(dict.fromkeys(names))
        with self.locked(user_id):
            for name in names:
                self.get(user_id, name)
            config = self.config(user_id)
            config["bindings"][str(agent_id)] = names
            self._save_config(user_id, config)
        return names

    def unbind_agent(self, user_id, agent_id) -> None:
        """Agent 删除后清理绑定，不创建数据库记录。"""
        with self.locked(user_id):
            config = self.config(user_id)
            config["bindings"].pop(str(agent_id), None)
            self._save_config(user_id, config)

    def set_enabled(self, user_id, name: str, enabled: bool) -> dict:
        """原子更新启用状态，当前执行副本不受影响。"""
        with self.locked(user_id):
            self.get(user_id, name)
            config = self.config(user_id)
            config["enabled"][name] = enabled
            self._save_config(user_id, config)
        return self.get(user_id, name)

    def remove(self, user_id, name: str) -> None:
        """未被绑定时删除单个技能目录。"""
        self.validate_name(name)
        with self.locked(user_id):
            directory = self.user_root(user_id) / name
            if not directory.is_dir():
                raise HTTPException(404, "技能不存在")
            if directory.is_symlink():
                raise HTTPException(422, "技能目录不允许符号链接")
            config = self.config(user_id)
            if any(name in names for names in config["bindings"].values()):
                raise HTTPException(409, "技能仍被 Agent 绑定，请先解除绑定")
            target = (self.user_root(user_id) / name).resolve()
            if target.parent != self.user_root(user_id).resolve():
                raise HTTPException(422, "技能目录越界")
            shutil.rmtree(target)
            config["enabled"].pop(name, None)
            self._save_config(user_id, config)

    def upload(self, user_id, data: bytes, replace_name: str | None = None) -> dict:
        """先验证 ZIP，再原子发布技能目录；失败回滚已安装版本。"""
        if len(data) > int(skill_setting("max_zip_bytes", 10 * 1024 * 1024)):
            raise HTTPException(422, "ZIP 超过上传大小限制")
        if replace_name:
            self.validate_name(replace_name)
        root = self.user_root(user_id)
        staging_root = root / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=staging_root) as temporary:
            staged = Path(temporary)
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as package:
                    entries = package.infolist()
                    if len(entries) > int(skill_setting("max_files", 200)) * 2:
                        raise HTTPException(422, "ZIP 条目数量超过限制")
                    seen = set()
                    size = 0
                    for entry in entries:
                        path = safe_relative(staged, entry.filename.rstrip("/"))
                        key = path.relative_to(staged).as_posix().casefold()
                        if key in seen or stat.S_ISLNK(entry.external_attr >> 16):
                            raise HTTPException(422, f"{entry.filename}: 重复路径或符号链接")
                        seen.add(key)
                        size += entry.file_size
                        if size > int(skill_setting("max_unpacked_bytes", 50 * 1024 * 1024)):
                            raise HTTPException(422, "ZIP 解压体积超过限制")
                        if entry.is_dir():
                            path.mkdir(parents=True, exist_ok=True)
                        else:
                            path.parent.mkdir(parents=True, exist_ok=True)
                            with package.open(entry) as source, path.open("wb") as output:
                                shutil.copyfileobj(source, output)
                skill_dir = staged
                children = list(staged.iterdir())
                if not (staged / "SKILL.md").is_file():
                    if len(children) != 1 or not children[0].is_dir():
                        raise HTTPException(422, "ZIP 必须包含单个技能目录或根目录 SKILL.md")
                    skill_dir = children[0]
                if skill_dir == staged:
                    raw = (staged / "SKILL.md").read_text(encoding="utf-8-sig").split("---", 2)
                    metadata = yaml.safe_load(raw[1]) if len(raw) == 3 else {}
                    if not isinstance(metadata, dict):
                        raise HTTPException(422, "SKILL.md: YAML 必须是对象")
                    name = self.validate_name(str((metadata or {}).get("name", "")))
                    renamed = staged / ".package" / name
                    renamed.mkdir(parents=True)
                    for child in children:
                        shutil.move(str(child), str(renamed / child.name))
                    skill_dir = renamed
                item = self.inspect(skill_dir)
                name = item["name"]
                if replace_name and name != replace_name:
                    raise HTTPException(422, "替换包的 name 必须保持一致")
                with self.locked(user_id):
                    target = root / name
                    if target.is_symlink():
                        raise HTTPException(422, "待发布目录不允许符号链接")
                    if target.exists() and not replace_name:
                        raise HTTPException(409, "同名技能已存在，请使用替换操作")
                    if replace_name and not target.is_dir():
                        raise HTTPException(404, "待替换技能不存在")
                    backup = staging_root / uuid4().hex
                    if target.exists():
                        os.replace(target, backup)
                    try:
                        os.replace(skill_dir, target)
                    except BaseException:
                        if backup.exists():
                            os.replace(backup, target)
                        raise
                    if backup.exists():
                        shutil.rmtree(backup)
                return self.get(user_id, name)
            except (zipfile.BadZipFile, UnicodeError, yaml.YAMLError, KeyError, OSError) as error:
                raise HTTPException(422, f"技能包格式错误：{error}") from error

    def read_file(self, user_id, name: str, path: str) -> dict:
        """预览技能文件；二进制仅返回清单信息。"""
        self.get(user_id, name)
        with self.locked(user_id):
            target = safe_relative(self.user_root(user_id) / name, path)
            if not target.is_file():
                raise HTTPException(404, "文件不存在")
            if target.stat().st_size > 1024 * 1024:
                raise HTTPException(422, "文本预览文件不得超过 1 MiB")
            try:
                text = target.read_text(encoding="utf-8-sig")
            except UnicodeError:
                return {"path": path, "binary": True, "size": target.stat().st_size}
            return {"path": path, "binary": False, "content": text}

    def snapshot(self, user_id, agent_id, name: str, destination: Path) -> dict:
        """在持锁状态下校验当前授权并复制本轮使用的技能。"""
        with self.locked(user_id):
            item = self.get(user_id, name)
            if name not in self.bindings(user_id, agent_id) or not item["enabled"]:
                raise HTTPException(404, "技能未绑定或已停用")
            shutil.copytree(self.user_root(user_id) / name, destination)
            return self.inspect(destination)
