"""Apply declared wire casing/order after HTTPX has added transport headers."""
from __future__ import annotations

import httpx


def request_layout_hook(order: tuple[str, ...]):
    async def apply(request: httpx.Request) -> None:
        remaining = list(request.headers.multi_items())
        arranged = []
        for name in order:
            arranged.extend((name, value) for key, value in remaining
                            if key.lower() == name.lower())
            remaining = [(key, value) for key, value in remaining if key.lower() != name.lower()]
        request.headers = httpx.Headers([*arranged, *remaining])

    return apply
