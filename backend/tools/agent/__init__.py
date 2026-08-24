"""
Agent 工具包（自动发现）

目录扫描：import 本包时自动加载 tools/agent/ 下所有工具模块，
配合 BaseTool.__init_subclass__ 钩子完成自动注册（import 即注册）。

新增工具 = 在 tools/agent/ 下新建一个实现 BaseTool 的文件即可，
无需在本文件或其他任何地方登记（工具类声明 type/description/param_schema）。
"""
import importlib
import pkgutil

__all__ = []

for _m in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{_m.name}")
