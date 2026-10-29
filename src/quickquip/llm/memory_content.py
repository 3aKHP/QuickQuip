"""Markdown 记忆元数据与本地相关度计算。"""

from collections import Counter
import math
import re


BODY_LIMIT = 4096
TITLE_LIMIT = 64
DESCRIPTION_LIMIT = 160
DEFAULT_CAPACITY = 1000


def derive_metadata(content: str) -> tuple[str, str]:
    lines = [line.strip().lstrip("#").strip() for line in content.splitlines() if line.strip()]
    return (
        (next((line for line in lines if any(c.isalnum() for c in line)), "记忆"))[:TITLE_LIMIT],
        " ".join(lines)[:DESCRIPTION_LIMIT],
    )


def metadata(
    content: str,
    title: str | None = None,
    description: str | None = None,
    *,
    validate_body: bool = True,
) -> tuple[str, str]:
    if validate_body and (not content.strip() or len(content) > BODY_LIMIT):
        raise ValueError("记忆正文须为 1–4096 字符")
    derived_title, derived_description = derive_metadata(content)
    title = derived_title if title is None else title.strip()
    description = derived_description if description is None else description.strip()
    if not title or len(title) > TITLE_LIMIT or len(description) > DESCRIPTION_LIMIT:
        raise ValueError("标题须为 1–64 字符，描述最多 160 字符")
    return title, description


def tokens(text: str) -> list[str]:
    result = re.findall(r"[a-z0-9_]+", text.casefold())
    for part in re.findall(r"[\u3400-\u9fff]+", text):
        result.extend(part[i : i + 2] for i in range(len(part) - 1))
    return result


def rank(items: list[dict], query: str) -> list[dict]:
    terms = set(tokens(query[:4096]))
    if not terms or not items:
        return []
    docs = [
        Counter(
            tokens(
                " ".join(str(item.get(k, "")) for k in ("title", "description", "content_display"))
            )
        )
        for item in items
    ]
    lengths = [sum(doc.values()) for doc in docs]
    average = max(1, sum(lengths) / len(docs))
    frequencies = Counter(term for doc in docs for term in terms if term in doc)
    scored = []
    for item, doc, length in zip(items, docs, lengths):
        score = sum(
            math.log(1 + (len(docs) - frequencies[t] + 0.5) / (frequencies[t] + 0.5))
            * doc[t]
            * 2.2
            / (doc[t] + 1.2 * (0.25 + 0.75 * length / average))
            for t in terms
            if doc[t]
        )
        if score > 0:
            scored.append((score, item))
    return [item for _, item in sorted(scored, key=lambda pair: (-pair[0], pair[1]["id"]))]
