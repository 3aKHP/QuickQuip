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


def test_llm_runtime_all_list_not_empty():
    """Sanity guard: __all__ should never be accidentally cleared."""
    assert len(llm_runtime.__all__) > 0
