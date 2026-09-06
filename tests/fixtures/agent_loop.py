"""Agent Loop 记录/重放/分段交付的测试 fixture（1.15 实施计划 §12.A）。

全部内容为自造测试数据：结构对齐 §1.1 生产样本（五 Turn、七工具调用、
前四 Turn 普通正文 32/31/50/31 code point、末 Turn 374 code point），
正文、身份与端点均不复制生产内容。

拆分口径约定（§11.2）：默认阈值 800 下末 Turn 374 保持一段；测试用
显式切分参数（见 AGENT_LOOP_TEST_SPLIT）使末 Turn 确定形成三段，
与前四 Turn 各一段合计七个文字 Chunk。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from quickquip.llm.provider import LLMRequest, LLMResponse
from quickquip.llm.tools import LLMToolCall

# ── 五 Turn 主例正文（长度由 test_agent_loop_baseline 自检锁定） ──────────

FIVE_TURN_TEXTS: tuple[str, ...] = (
    # 32 cp：Turn 0 普通正文，先于其工具执行交付
    "咦，K甲夏季赛？这个话题有点意思，让我先去查查一下现在的赛况——",
    # 31 cp
    "等我确认一下各支战队最近的选手名单和目前的积分情况，稍后再说。",
    # 50 cp
    "两支队伍最近的交手记录很有参考价值，我再看看有没有关键选手受伤的消息，这些细节都会影响接下来的走势。",
    # 31 cp
    "两边的最新情况基本都摸清楚了，我来整理一下这届比赛的主要看点。",
    # 374 cp：末 Turn，三段式（空行分界），测试切分参数下为 3 Chunk
    "先说结论：这届K甲夏季赛的格局比春季赛清晰不少，几个关键变量都落定了。\n\n"
    "积分榜前两名的队伍都保持了稳定的首发阵容，中游集团则因为两笔转会出现了明显的风格分化——一支偏向中期抱团速攻，另一支坚持四一分推打运营。从最近两周的交手记录看，速攻体系在前十五分钟的经济领先转化率很高，但一旦拖入后期决策就容易上头；运营队恰好相反，前期被动，三十分钟后的大龙团处理明显更冷静，资源置换的细节也更扎实。关键选手方面，目前没有新的伤病名单，之前手腕不适的那位已经回到了首发训练，教练组也在采访里确认了季后赛的轮换思路。\n\n"
    "整体来看，淘汰赛的看点会是两种节奏的正面对撞：一边要把比赛拖进自己的前期攻势里解决战斗，另一边只要稳住前中期就有很大机会把节奏抓回来。我的判断是运营队略占上风，但差距没有大到没有悬念的程度，具体还要看当天的版本理解、临场指挥调度和选手状态。",
)

# 七次工具调用按 1/2/2/2 分布在前四个 Turn；全部走本地 get_identity，
# 不依赖网络。查询词来自测试身份 fixture 的别名。
FIVE_TURN_TOOL_QUERIES: tuple[tuple[str, ...], ...] = (
    ("镜子",),
    ("4s", "哈基镜"),
    ("Туманность", "镜千翎"),
    ("哈基四", "镜子"),
    (),
)

# 测试切分参数（§11.2：显式测试值，不改产品默认）：末 Turn 217 字符的
# 中段超过 threshold，三段在空行/句末边界各自成 Chunk。
AGENT_LOOP_TEST_SPLIT = {"threshold": 120, "chunk_max": 240}


def five_turn_tool_calls() -> list[list[LLMToolCall]]:
    calls: list[list[LLMToolCall]] = []
    counter = 0
    for turn_index, queries in enumerate(FIVE_TURN_TOOL_QUERIES):
        batch = [
            LLMToolCall(
                id=f"call_{turn_index}_{offset}",
                name="get_identity",
                arguments_json=f'{{"query":"{query}"}}',
            )
            for offset, query in enumerate(queries)
        ]
        counter += len(batch)
        calls.append(batch)
    assert counter == 7, "五 Turn 主例必须恰好七次工具调用（§11.2）"
    return calls


@dataclass
class FiveTurnScenarioClient:
    """按剧本回放五 Turn 场景的 stub provider client。

    ``protocol`` 切换 thinking 块的协议原生形态（openai/claude/gemini），
    正文与工具调用不变；``requests`` 记录每次实际请求供断言。
    """

    protocol: str = "openai"
    requests: list[LLMRequest] = field(default_factory=list)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        turn_index = self._turn_index()
        text = FIVE_TURN_TEXTS[turn_index]
        tool_calls = five_turn_tool_calls()[turn_index]
        thinking_blocks = _native_thinking_blocks(self.protocol, turn_index)
        return LLMResponse(
            text=text,
            model=request.model,
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else "stop",
            input_tokens=100 + 37 * turn_index,
            output_tokens=17 * (turn_index + 1),
            thinking_blocks=thinking_blocks,
        )

    def _turn_index(self) -> int:
        # 请求里的 assistant 消息数 = 已完成 Turn 数。
        completed = sum(1 for m in self.requests[-1].messages if m.role == "assistant")
        assert completed < len(FIVE_TURN_TEXTS), "剧本耗尽：五 Turn 之外不应再有请求"
        return completed


def _native_thinking_blocks(protocol: str, turn_index: int) -> list[dict]:
    """三协议的原生 thinking 中间表示样例（结构与 provider 解析器一致）。"""
    label = f"turn{turn_index}"
    if protocol == "claude":
        return [
            {"type": "thinking", "thinking": f"先核对榜单再回答（{label}）。", "signature": f"sig-{label}"},
            {"type": "redacted_thinking", "data": f"redacted-{label}"},
        ]
    if protocol == "gemini":
        # replay_required 形态：带 thoughtSignature 的 part 包成 gemini_part
        return [
            {"type": "gemini_part", "part": {"text": f"检索线索（{label}）", "thoughtSignature": f"ts-{label}"}},
        ]
    return [{"type": "reasoning", "reasoning_content": f"解题思路（{label}）。"}]


# ── 三协议 wire 结构样例（投影/序列化测试用，§7.4 兼容矩阵输入） ──────────

OPENAI_NATIVE_TOOL_TURN = {
    "role": "assistant",
    "content": FIVE_TURN_TEXTS[1],
    "reasoning_content": "解题思路（turn1）。",
    "tool_calls": [
        {"id": "call_1_0", "type": "function", "function": {"name": "get_identity", "arguments": '{"query":"4s"}'}},
        {"id": "call_1_1", "type": "function", "function": {"name": "get_identity", "arguments": '{"query":"哈基镜"}'}},
    ],
}

CLAUDE_NATIVE_TOOL_TURN = {
    "role": "assistant",
    "content": [
        {"type": "thinking", "thinking": "先核对榜单再回答（turn1）。", "signature": "sig-turn1"},
        {"type": "text", "text": FIVE_TURN_TEXTS[1]},
        {"type": "tool_use", "id": "call_1_0", "name": "get_identity", "input": {"query": "4s"}},
        {"type": "tool_use", "id": "call_1_1", "name": "get_identity", "input": {"query": "哈基镜"}},
    ],
}

GEMINI_NATIVE_TOOL_TURN = {
    "role": "model",
    "parts": [
        {"text": "检索线索（turn1）。", "thoughtSignature": "ts-turn1", "thought": True},
        {"text": FIVE_TURN_TEXTS[1]},
        {"functionCall": {"id": "gemini_tool_1", "name": "get_identity", "args": {"query": "4s"}}},
        {"functionCall": {"id": "gemini_tool_2", "name": "get_identity", "args": {"query": "哈基镜"}}},
    ],
}


# ── 旧库 fixture（§4.3 迁移测试输入：1.15 之前的 schema 与行形态） ─────────

LEGACY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS conversation_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id TEXT NOT NULL,
    user_id TEXT,
    sender_name TEXT,
    canonical_name TEXT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    message_id TEXT,
    raw_content TEXT,
    created_at TEXT NOT NULL
);
"""


@dataclass(frozen=True, slots=True)
class LegacyRow:
    group_id: str
    user_id: str | None
    sender_name: str | None
    canonical_name: str | None
    role: str
    content: str
    message_id: str | None = None
    raw_content: str | None = None
    created_at: str = "2026-08-01T00:00:00+00:00"


def legacy_rows() -> list[LegacyRow]:
    """覆盖 §4.3 迁移分组的四种形态：成对、连续 user、无 receipt、孤立段。

    按提交顺序排列（id 即插入顺序）：
    - a0 孤立 assistant（legacy_orphan）
    - u1/a1 成对（a1 无 message_id → legacy_untracked）
    - u2、u3 连续 user（各自独立 Loop；u3 后跟 a3）
    - a3 带 message_id="m3"（覆盖全文的 sent receipt）
    """
    return [
        LegacyRow("1001", None, None, None, "assistant", "开场白：新版本已就位。"),
        LegacyRow("1001", "2002", "镜子", "镜子", "user", "今天K甲决赛几点开始？"),
        LegacyRow("1001", None, None, None, "assistant", "晚上七点开始，我先帮你盯着赛程。"),
        LegacyRow("1001", "4004", "4s", "4s", "user", "顺便问下参赛队伍名单。"),
        LegacyRow("1001", "2002", "镜子", "镜子", "user", "名单出来了吗？"),
        LegacyRow("1001", None, None, None, "assistant", "名单已出，八支队伍。", message_id="m3"),
    ]


def build_legacy_db(path: Path) -> None:
    """写入 1.15 之前形态的 llm.db（旧 schema + legacy_rows）。"""
    conn = sqlite3.connect(path)
    try:
        conn.executescript(LEGACY_SCHEMA_SQL)
        for row in legacy_rows():
            conn.execute(
                """
                INSERT INTO conversation_messages
                    (group_id, user_id, sender_name, canonical_name, role, content, message_id, raw_content, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.group_id,
                    row.user_id,
                    row.sender_name,
                    row.canonical_name,
                    row.role,
                    row.content,
                    row.message_id,
                    row.raw_content,
                    row.created_at,
                ),
            )
        conn.commit()
    finally:
        conn.close()
