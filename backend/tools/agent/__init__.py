"""
Agent 工具包（自动发现）

目录扫描：import 本包时自动加载 tools/agent/ 下所有工具模块，
配合 BaseTool.__init_subclass__ 钩子完成自动注册（import 即注册）。

健壮性（Phase 4.10）：
- 单个模块 import 失败 → ERROR 日志 + 跳过该模块，不影响其他工具与应用启动
- 非 .py 文件自动忽略（pkgutil.iter_modules 只列出模块）
- 注册结果（成功/跳过/重复）记录日志，便于排查不规范文件

新增工具 = 在 tools/agent/ 下新建一个实现 BaseTool 的文件即可，
无需在本文件或其他任何地方登记（工具类声明 type/description/param_schema）。
"""
import importlib
import logging
import pkgutil

logger = logging.getLogger(__name__)

for _m in pkgutil.iter_modules(__path__):
    try:
        importlib.import_module(f"{__name__}.{_m.name}")
    except Exception:
        logger.exception(
            "工具模块 %s 导入失败，已跳过（请检查该文件：语法/依赖/继承是否正确）",
            _m.name,
        )
