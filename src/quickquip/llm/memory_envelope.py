"""当前轮次的记忆目录与相关正文。截取只影响请求材料。"""

from quickquip.common.record_content import display
from quickquip.llm.memory_content import tokens
from quickquip.llm.token_estimate import estimate_tokens

MEMORY_TOKEN_BUDGET = 2048
DIRECTORY_TOKEN_BUDGET = 512
_TRUNCATED = "\n〔内容节选，可使用 read_memory 读取全文〕"


def _fit(text: str, budget: int) -> str:
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if estimate_tokens(text[:mid]) <= budget:
            low = mid
        else:
            high = mid - 1
    return text[:low]


def excerpt(text: str, query: str, budget: int) -> str:
    if estimate_tokens(text) <= budget:
        return text
    if budget <= estimate_tokens(_TRUNCATED):
        return ""
    # 按空行划分 Markdown 段落，优先保留命中段，再按原文顺序展示。
    paragraphs = text.split("\n\n")
    terms = set(tokens(query))
    literal = query.strip().casefold()
    ordered = sorted(
        range(len(paragraphs)), key=lambda i: (
            -len(terms & set(tokens(paragraphs[i])))
            - int(bool(literal and literal in paragraphs[i].casefold())), i)
    )
    available = budget - estimate_tokens(_TRUNCATED)
    selected = {}
    for i in ordered:
        candidate = paragraphs[i]
        cost = estimate_tokens(candidate + "\n\n")
        if cost <= available:
            selected[i] = candidate
            available -= cost
        elif not selected:
            # 单一长段落围绕第一个命中位置截取，避免永远只读到开头。
            needles = terms | ({literal} if literal else set())
            positions = [candidate.casefold().find(t) for t in needles if t in candidate.casefold()]
            start = max(0, min(positions) - 100) if positions else 0
            selected[i] = _fit(candidate[start:], max(0, available - 2))
            break
    return "\n\n".join(selected[i] for i in sorted(selected)) + _TRUNCATED


def render_memory_envelope(memories: list[dict], *, budget: int = MEMORY_TOKEN_BUDGET) -> str:
    if not memories or budget <= 0:
        return ""
    heading = f"当前会话共 {len(memories)} 条记忆，仅在相关时参考："
    more = "未展示的目录可用 list_memories 搜索或分页读取。"
    lines = [heading]
    directory_budget = min(DIRECTORY_TOKEN_BUDGET, budget)
    shown = 0
    for item in memories:
        line = f"#{item.get('id', '未知')} {item.get('title', '')}：{item.get('description', '')}"
        if estimate_tokens("\n".join(lines + [line, more])) > directory_budget:
            break
        lines.append(line)
        shown += 1
    if shown < len(memories):
        lines.append(more)
    for item in [m for m in memories if m.get("recalled", True)][:5]:
        header = (
            f"\n#{item.get('id', '未知')}〔依据："
            f"QQ {item.get('source_user_id') or '未知'}，"
            f"角色 {item.get('source_role', 'unknown')}〕\n"
        )
        if item.get("user_id"):
            header += f"历史关联成员：QQ {item['user_id']}\n"
        available = budget - estimate_tokens("\n".join(lines) + "\n" + header)
        body = excerpt(display(item), str(item.get("recall_query", "")), available)
        if body:
            lines.append(header + body)
    return _fit("\n".join(lines), budget)
