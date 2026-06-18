"""验证 Web Admin 的 import 隔离：启动时不触发 message_pipeline 的单例实例化。

PR-4（perf/web-admin-lazy-import）将 10 个 route 文件的 message_pipeline
顶层 import 改为 handler 内懒导入。本测试固化这一不变量：如果未来有人
在 route 文件顶层重新引入 message_pipeline import，此测试会失败。
"""

from __future__ import annotations

import sys


def test_web_app_import_does_not_load_message_pipeline() -> None:
    """import quickquip.app.web.app 不应触发 message_pipeline 加载。

    message_pipeline 在 import 阶段实例化 17 个单例（含 jieba/wordcloud/
    游戏模块等重型依赖）。Web admin 只用其中 8 个，懒导入确保启动时
    不加载 bot 专属对象，降低 VmHWM ~60MB。
    """
    # 清除可能已加载的 message_pipeline（测试收集阶段可能有副作用）
    loaded_before = "quickquip.app.message_pipeline" in sys.modules
    if loaded_before:
        # 如果已经被加载（比如前序测试触发的），移除它再验证 web.app 的 import 不重新拉入
        del sys.modules["quickquip.app.message_pipeline"]

    import quickquip.app.web.app  # noqa: F401

    assert "quickquip.app.message_pipeline" not in sys.modules, (
        "import quickquip.app.web.app 不应触发 message_pipeline 加载——"
        "检查 route 文件是否有残留的顶层 message_pipeline import"
    )
