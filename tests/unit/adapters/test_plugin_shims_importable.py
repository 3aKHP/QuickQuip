"""src/plugins/ 下所有 NoneBot 插件 shim 必须可导入。

bot.py 经 nonebot.load_plugins 加载全部 shim；任何 shim 引用了已删除的
重导出名字都会在每次启动时打 ERROR 级 traceback（PR #230 Deep-CR B1
的逃逸路径：单测从不导入 shim 层）。本测试堵住这一类失败。
"""
from __future__ import annotations

import importlib
import pkgutil

import plugins


def test_all_plugin_shims_import_cleanly():
    names = [name for _, name, _ in pkgutil.iter_modules(plugins.__path__)]
    assert names, "src/plugins/ 不应为空——发现机制本身失效"
    failures: list[tuple[str, str]] = []
    for name in names:
        try:
            importlib.import_module(f"plugins.{name}")
        except Exception as exc:  # noqa: BLE001 —— 收集全部失败一次性报告
            failures.append((name, f"{type(exc).__name__}: {exc}"))
    assert not failures, f"插件 shim 导入失败：{failures}"
