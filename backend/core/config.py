import os
import sys
import yaml
from pathlib import Path
from types import SimpleNamespace


def _dict_to_namespace(data: dict) -> SimpleNamespace:
    """递归把 dict 转成 SimpleNamespace，支持 a.b.c 访问"""
    for key, value in data.items():
        if isinstance(value, dict):
            data[key] = _dict_to_namespace(value)
    return SimpleNamespace(**data)


# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent

# 加载 YAML，自动转成点号访问
_yaml_path = Path(__file__).parent.parent / "config.yaml"
with open(_yaml_path, encoding="utf-8") as f:
    _raw: dict = yaml.safe_load(f)

settings = _dict_to_namespace(_raw)

# ── 环境变量覆盖（生产环境不把敏感信息写 YAML）──
if (env_secret := os.getenv("JWT_SECRET_KEY")):
    settings.jwt.secret_key = env_secret
if (env_admin_user := os.getenv("ADMIN_USERNAME")):
    settings.admin.username = env_admin_user
if (env_admin_pass := os.getenv("ADMIN_PASSWORD")):
    settings.admin.password = env_admin_pass

# ── 安全检查：默认 secret_key 不允许用于生产 ──
_prod_unsafe = "change-me-in-production"
if settings.jwt.secret_key == _prod_unsafe:
    # 非生产环境警告，生产环境（通过 gunicorn 等）直接拒绝启动
    print(
        "[WARNING] JWT secret_key 仍为默认值 'change-me-in-production'，"
        "请通过环境变量 JWT_SECRET_KEY 设置生产密钥",
        file=sys.stderr,
    )
