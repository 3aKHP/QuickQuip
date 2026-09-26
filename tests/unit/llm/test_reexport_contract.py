"""Guard against service.py re-export contract drift.

``plugins/llm_runtime.py`` re-exports a set of symbols from
``quickquip.llm.service`` for the NoneBot adapter layer. Several of these
are imported into service.py solely for re-export (marked ``# noqa: F401``).

Two failure modes this test catches:

1. **Removed re-export (caught at import time):** if a ``# noqa: F401``
   re-export is deleted from service.py while llm_runtime still imports it,
   ``from plugins import llm_runtime`` raises ``ImportError`` before this
   test runs. That's acceptable — the ImportError itself is the signal.

2. **Stale __all__ entry (caught by hasattr loop):** if a symbol is listed
   in llm_runtime's ``__all__`` but was never imported (typo) or was sourced
   from a module other than service, the ``hasattr`` loop below catches it
   with an actionable message naming the offender and how to fix it.
"""
from __future__ import annotations

from quickquip.llm import service
from plugins import llm_runtime


def test_llm_runtime_all_symbols_resolvable_from_service():
    """Every symbol in llm_runtime.__all__ must resolve as an attribute of
    quickquip.llm.service. Catches stale __all__ entries that don't correspond
    to anything service.py actually exposes.
    """
    assert llm_runtime.__all__
    missing = [
        name
        for name in llm_runtime.__all__
        if not hasattr(service, name)
    ]
    assert not missing, (
        f"plugins/llm_runtime.__all__ lists symbols not found on "
        f"quickquip.llm.service: {missing}. Either add the re-export "
        f"in service.py (with `import X as X` + noqa: F401) or remove the "
        f"stale entry from llm_runtime.__all__."
    )


# ---------------------------------------------------------------------------
# quickquip.llm.skills 包的 re-export 契约
# ---------------------------------------------------------------------------


def test_skills_package_all_symbols_resolvable():
    """skills.__all__ 里的每个符号都必须真实存在（防陈旧条目/笔误）。"""
    from quickquip.llm import skills

    missing = [name for name in skills.__all__ if not hasattr(skills, name)]
    assert not missing, (
        f"quickquip.llm.skills.__all__ 列出了不存在的符号：{missing}。"
        "补齐 re-export 或从 __all__ 移除。"
    )


def test_skills_package_no_unlisted_public_leakage():
    """dir(skills) 的公开非模块名必须 ⊆ __all__（防内部实现泄漏成公共面）。"""
    import types

    from quickquip.llm import skills

    leaked = [
        name
        for name in dir(skills)
        if not name.startswith("_")
        and name not in skills.__all__
        and not isinstance(getattr(skills, name), types.ModuleType)
    ]
    assert not leaked, (
        f"quickquip.llm.skills 泄漏了 __all__ 之外的公开符号：{leaked}。"
        "收入 __all__ 或改为下划线私有名。"
    )
