"""LLM 身份域：共享身份模型 re-export + 当轮信封的身份编排。

信封编排（参与者归并、被艾特成员档案采集）是纯投影：输入身份索引与
当轮消息材料，输出 ``build_turn_envelope`` 消费的 ``participants`` /
``mention_profiles`` 字段；确定性输出，同输入同字节。
"""
from __future__ import annotations

import re

from quickquip.common.identity import IdentityEntry, IdentityIndex, IdentityMatch

__all__ = [
    "IdentityEntry",
    "IdentityIndex",
    "IdentityMatch",
    "collect_known_participants",
    "collect_mention_profiles",
]


# 正文/存量历史中以数字形态出现的 @ 提及（@QQ123456），以及信封档案条目数
# 上限（名字在前、QQ 作配对键，见 docs/dev/llm-module.md §5.5）
_AT_QQ_PATTERN = re.compile(r"@QQ(\d{5,12})")
_MENTION_PROFILE_LIMIT = 5


def collect_known_participants(
    identities: IdentityIndex,
    *,
    user_id: int | str,
    sender_name: str,
    history: list[dict[str, str]],
    recent_messages: list[dict[str, str]] | None = None,
    quoted_sender_name: str = "",
    quoted_user_id: str = "",
) -> list[dict[str, str]]:
    """归并当轮信封的参与者（触发者、引用对象、现场补丁与 history 的 user 行）。"""
    participants: list[dict[str, str]] = []
    seen_user_ids: set[str] = set()

    def _push(raw_user_id: int | str | None, raw_sender_name: str = "", raw_canonical_name: str = "") -> None:
        user_key = str(raw_user_id or "").strip()
        if user_key and not user_key.isdigit():
            # 合成触发源（boredom_timer/scheduled_timer 等）不是群成员，
            # 不进信封参与者（触发者本人与 history 合成行两路都过滤）
            return
        sender_value = raw_sender_name.strip()
        canonical_value = raw_canonical_name.strip()
        if not user_key and not sender_value:
            return
        dedupe_key = user_key or f"name:{sender_value}"
        if dedupe_key in seen_user_ids:
            return
        seen_user_ids.add(dedupe_key)
        if user_key:
            identity = identities.resolve_user(user_key, sender_value)
            if identity.is_registered:
                canonical_value = identity.canonical_name or canonical_value
                sender_value = sender_value or identity.sender_name or user_key
        participants.append(
            {
                "user_id": user_key,
                "sender_name": sender_value or user_key,
                "canonical_name": canonical_value,
            }
        )

    _push(user_id, sender_name)
    if quoted_sender_name or quoted_user_id:
        _push(quoted_user_id, quoted_sender_name)
    for item in recent_messages or []:
        _push(item.get("user_id", ""), item.get("sender_name", ""), item.get("canonical_name", ""))
    for item in history:
        if item.get("role") != "user":
            continue
        _push(item.get("user_id", ""), item.get("sender_name", ""), item.get("canonical_name", ""))
    return participants


def collect_mention_profiles(
    identities: IdentityIndex,
    *,
    mentioned_qq_ids: list[str],
    prompt: str,
    quoted_text: str,
    forward_text: str,
    history: list[dict[str, object]],
    scene_patch: list[dict[str, str]] | None,
    current_user_id: str,
    quoted_user_id: str,
) -> list[dict[str, str]]:
    """收集被艾特但未在窗口内发言的登记成员档案（信封注入用）。

    候选双路：入口结构化采集的 ``mentioned_qq_ids``（当前消息，精确）
    ＋对 prompt/引用/转发/history/现场文本扫 ``@QQ 数字``（覆盖冻结
    落库的存量形态）。已在窗口带发言人标签的成员跳过（场景行可见，
    无需档案）；未登记成员跳过（无可注入）。
    """
    visible: set[str] = set()
    for uid in (current_user_id, quoted_user_id):
        uid = str(uid or "").strip()
        if uid:
            visible.add(uid)
    for item in history or []:
        uid = str(item.get("user_id") or "").strip()
        if uid:
            visible.add(uid)
    for item in scene_patch or []:
        uid = str(item.get("user_id") or "").strip()
        if uid:
            visible.add(uid)

    candidates: list[str] = []

    def _push(qq: str) -> None:
        normalized = str(qq or "").strip()
        if normalized and normalized.isdigit() and normalized not in candidates:
            candidates.append(normalized)

    for qq in mentioned_qq_ids:
        _push(str(qq))
    scan_texts = [prompt, quoted_text, forward_text]
    for item in history or []:
        scan_texts.append(str(item.get("raw_content") or item.get("content") or ""))
    for item in scene_patch or []:
        scan_texts.append(str(item.get("text") or ""))
    for text in scan_texts:
        for match in _AT_QQ_PATTERN.finditer(text):
            _push(match.group(1))

    profiles: list[dict[str, str]] = []
    for qq in candidates:
        if qq in visible:
            continue
        match = identities.resolve_user(qq)
        if not match.is_registered or not match.canonical_name:
            continue
        profiles.append(
            {
                "canonical_name": match.canonical_name,
                "user_id": qq,
                "aliases": "、".join(match.aliases[:6]),
                "note": match.note,
            }
        )
        if len(profiles) >= _MENTION_PROFILE_LIMIT:
            break
    return profiles
