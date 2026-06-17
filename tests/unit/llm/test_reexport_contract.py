"""Guard against service.py re-export contract drift.

``plugins/llm_runtime.py`` re-exports a set of symbols from
``quickquip.llm.service`` for the NoneBot adapter layer. Several of these
are imported into service.py solely for re-export (marked ``# noqa: F401``).
If such a re-export is accidentally removed, ruff's F401 suppression would
silently mask the now-dead import.

This test verifies that every symbol in ``plugins/llm_runtime.__all__`` is
accessible as an attribute of ``quickquip.llm.service`` — so removing a
re-export from service.py while it's still listed in llm_runtime's __all__
will fail this test immediately.
"""
from __future__ import annotations

from quickquip.llm import service
from plugins import llm_runtime


def test_llm_runtime_all_symbols_resolvable_from_service():
    """Every public symbol re-exported by plugins/llm_runtime must resolve
    from quickquip.llm.service. Catches drift where a ``# noqa: F401``
    re-export is removed but llm_runtime still imports it.
    """
    missing = [
        name
        for name in llm_runtime.__all__
        if not hasattr(service, name)
    ]
    assert not missing, (
        f"plugins/llm_runtime re-exports symbols not found on "
        f"quickquip.llm.service: {missing}. Either restore the re-export "
        f"in service.py (with `import X as X` + noqa: F401) or remove the "
        f"stale entry from llm_runtime.__all__."
    )


def test_llm_runtime_all_list_is_not_empty():
    """Sanity guard: __all__ should never be accidentally cleared."""
    assert len(llm_runtime.__all__) >= 10
