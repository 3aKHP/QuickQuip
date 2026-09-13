"""OneBot boundary for persistent record bodies."""
from quickquip.app.identities import identities
from quickquip.common.record_content import from_segments, legacy, references
from quickquip.adapters.nonebot.member_cards import fetch_mention_names


async def prepare_body(message, scope, bot=None, command=None, extra_ids=()):
    # Only a serialized source is CQ-decoded. Text segments remain literal.
    body = legacy(message) if isinstance(message, str) else from_segments(message, command)
    snapshot = identities.snapshot(scope)
    if bot is not None and str(scope).isdigit():
        names = await fetch_mention_names(
            bot, scope, list(dict.fromkeys([*extra_ids, *sorted(references(body))])),
            is_registered=lambda qq: qq in snapshot.index.by_qq or qq in snapshot.names,
        )
        snapshot.names.update(names)
    for part in body["parts"]:
        if part["type"] == "member":
            part["name"] = part.get("name") or snapshot.names.get(part["qq"]) or snapshot.index.resolve_user(part["qq"]).canonical_name or ""
    return body, snapshot


def reply_source(reply):
    message = getattr(reply, "message", None)
    raw = getattr(reply, "raw_message", None)
    if message is None or isinstance(message, str) and raw is not None and not isinstance(raw, str):
        return raw or ""
    return message
