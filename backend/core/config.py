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
def _apply_env_overrides(cfg) -> None:
    """应用环境变量覆盖(可测试:传入独立配置对象验证覆盖逻辑)"""
    if (env_secret := os.getenv("JWT_SECRET_KEY")):
        cfg.jwt.secret_key = env_secret
    if (env_admin_user := os.getenv("ADMIN_USERNAME")):
        cfg.admin.username = env_admin_user
    if (env_admin_pass := os.getenv("ADMIN_PASSWORD")):
        cfg.admin.password = env_admin_pass
    if (env_checkpoint_url := os.getenv("CHECKPOINT_URL")):
        cfg.checkpoint.url = env_checkpoint_url
    if (env_keep_rounds := os.getenv("CHECKPOINT_KEEP_ROUNDS")):
        try:
            cfg.checkpoint.keep_rounds = int(env_keep_rounds)
        except ValueError:
            print(f"[WARNING] CHECKPOINT_KEEP_ROUNDS 非法值: {env_keep_rounds}，忽略")
    if (env_log_dir := os.getenv("LOG_DIR")):
        cfg.logging.dir = env_log_dir


_apply_env_overrides(settings)

# ── 安全检查：默认 secret_key 不允许用于生产 ──
_prod_unsafe = "change-me-in-production"
if settings.jwt.secret_key == _prod_unsafe:
    # 非生产环境警告，生产环境（通过 gunicorn 等）直接拒绝启动
    print(
        "[WARNING] JWT secret_key 仍为默认值 'change-me-in-production'，"
        "请通过环境变量 JWT_SECRET_KEY 设置生产密钥",
        file=sys.stderr,
    )
