"""Factory helper for ChainGameDef construction in tests."""
from __future__ import annotations

import re

from plugins.chain_game import ChainGameDef


def make_chain_def(
    name: str,
    pattern: str,
    chain: list[str],
    *,
    timeout: int = 60,
    rate_limit_key: str = "test_chain",
) -> ChainGameDef:
    return ChainGameDef(
        name=name,
        trigger_pattern=re.compile(pattern),
        chain_template=chain,
        timeout_seconds=timeout,
        rate_limit_key=rate_limit_key,
    )
