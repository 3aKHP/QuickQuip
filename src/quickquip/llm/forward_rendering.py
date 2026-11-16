"""Render a forward tree with a shared character budget and closed child blocks."""
from __future__ import annotations

from dataclasses import dataclass, field

OUTER_TRUNCATED = "…（合并转发内容过长，已截断）"
INNER_TRUNCATED = "…（该内层内容已截断）"
CHILD_START = "\n[内层转发开始]\n"
CHILD_END = "\n[内层转发结束]\n"


@dataclass
class ForwardBlock:
    parts: list[str | ForwardBlock] = field(default_factory=list)


def render_forward_block(block: ForwardBlock, budget: int, *, outer: bool = False) -> str:
    marker = OUTER_TRUNCATED if outer else INNER_TRUNCATED
    children = [part for part in block.parts if isinstance(part, ForwardBlock)]
    # Reserve the whole current layer, including minimal child placeholders.
    skeleton = "".join(part if isinstance(part, str) else CHILD_START + INNER_TRUNCATED
                       + CHILD_END for part in block.parts)
    if len(skeleton) > budget:
        # Treat child boundaries atomically when the current layer itself is too large.
        available = max(0, budget - len(marker))
        result = ""
        for part in block.parts:
            text = part if isinstance(part, str) else CHILD_START + INNER_TRUNCATED + CHILD_END
            if len(result) + len(text) > available:
                if isinstance(part, str):
                    result += text[:available - len(result)]
                break
            result += text
        return (result + marker)[:budget]
    remaining = budget - len(skeleton)
    output = []
    left = len(children)
    for part in block.parts:
        if isinstance(part, str):
            output.append(part)
            continue
        allowance = len(INNER_TRUNCATED) + remaining // left
        child = render_forward_block(part, allowance)
        remaining -= len(child) - len(INNER_TRUNCATED)
        left -= 1
        output.append(CHILD_START + child + CHILD_END)
    return "".join(output)
