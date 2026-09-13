"""Versioned record bodies. Explicit references are distinct from literal text."""
from __future__ import annotations

import json
import re

QQ = re.compile(r"[1-9][0-9]{0,19}\Z")
CQ = re.compile(r"\[CQ:([a-zA-Z_]+)((?:,[^,\[\]]+=[^,\[\]]*)*)\]")
LEGACY_AT = re.compile(r"(?<![\w@])@QQ([1-9][0-9]{0,19})(?![\w])")
MEDIA = {"image": "图片", "record": "语音", "video": "视频", "face": "表情", "forward": "转发", "node": "转发"}


def unescape(value):
    return value.replace("&#44;", ",").replace("&#91;", "[").replace("&#93;", "]").replace("&amp;", "&")


def plain(text):
    return {"version": 1, "parts": [{"type": "text", "text": str(text)}]}


def validate(body, max_length=4096):
    if not isinstance(body, dict) or type(body.get("version")) is not int or body.get("version") != 1 or not isinstance(body.get("parts"), list):
        raise ValueError("content_parts requires version 1 and a parts list")
    result = []
    if len(body["parts"]) > 4096:
        raise ValueError("too many content parts")
    for part in body["parts"]:
        if not isinstance(part, dict):
            raise ValueError("invalid content part")
        kind = part.get("type")
        if kind == "text" and isinstance(part.get("text"), str):
            result.append({"type": kind, "text": part["text"]})
        elif kind == "member" and isinstance(part.get("qq"), str) and QQ.fullmatch(part["qq"]):
            if not isinstance(part.get("usage", "mention"), str) or part.get("usage", "mention") not in {"mention", "identity"} or not isinstance(part.get("name", ""), str):
                raise ValueError("invalid member reference")
            result.append({"type": kind, "qq": part["qq"], "name": part.get("name", ""), "usage": part.get("usage", "mention")})
        elif kind == "all":
            result.append({"type": "all"})
        elif kind == "media" and isinstance(part.get("media"), str) and part["media"] in MEDIA:
            result.append({"type": "media", "media": part["media"]})
        else:
            raise ValueError("invalid content part")
    body = {"version": 1, "parts": result}
    if len(render(body)) > max_length or any(len(p.get("name", "")) > max_length for p in result):
        raise ValueError(f"content exceeds {max_length} characters")
    return body


def from_segments(message, command=None):
    parts = []
    command_pending = bool(command)
    for segment in message:
        kind = segment.get("type") if isinstance(segment, dict) else getattr(segment, "type", "")
        data = segment.get("data", {}) if isinstance(segment, dict) else getattr(segment, "data", {})
        if kind == "text":
            text = str(data.get("text", ""))
            if command_pending:
                text, count = re.subn(r"^\s*[/!]?" + re.escape(command) + r"(?=\s|$)\s*", "", text, count=1)
                if count or text.strip():
                    command_pending = False
            parts.append({"type": "text", "text": text})
        elif kind == "at":
            qq = str(data.get("qq", ""))
            if qq == "all":
                parts.append({"type": "all"})
            elif QQ.fullmatch(qq):
                parts.append({"type": "member", "qq": qq, "name": str(data.get("name", "") or ""), "usage": "mention"})
        elif kind in MEDIA:
            parts.append({"type": "media", "media": kind})
    return {"version": 1, "parts": parts}


def legacy(text):
    parts = []
    def add_text(value):
        pos = 0
        for match in LEGACY_AT.finditer(value):
            parts.append({"type": "text", "text": value[pos:match.start()]})
            parts.append({"type": "member", "qq": match[1], "name": "", "usage": "mention"})
            pos = match.end()
        parts.append({"type": "text", "text": value[pos:]})
    pos = 0
    for match in CQ.finditer(text):
        data = dict(item.split("=", 1) for item in match[2].lstrip(",").split(",") if "=" in item)
        body = from_segments([{"type": match[1], "data": {k: unescape(v) for k, v in data.items()}}])
        if not body["parts"]:
            continue
        add_text(text[pos:match.start()])
        parts.extend(body["parts"])
        pos = match.end()
    add_text(text[pos:])
    return {"version": 1, "parts": parts}


def decode(content, encoded=None):
    if encoded:
        try:
            return validate(json.loads(encoded) if isinstance(encoded, str) else encoded, max_length=1_000_000)
        except (ValueError, TypeError):
            pass
    return legacy(str(content))


def render(body, snapshot=None):
    result = []
    for part in body["parts"]:
        kind = part["type"]
        if kind == "text":
            result.append(part["text"])
        elif kind == "member":
            name = snapshot.name(part["qq"], part.get("name", "")) if snapshot else part.get("name") or "QQ" + part["qq"]
            result.append(("@" if part.get("usage", "mention") == "mention" else "") + name)
        elif kind == "all":
            result.append("@全体成员")
        elif kind == "media":
            result.append("[" + MEDIA[part["media"]] + "]")
    return "".join(result)


def references(body):
    return {p["qq"] for p in body["parts"] if p["type"] == "member"}


def project(row, snapshot):
    row = dict(row)
    body = decode(row["content"], row.get("content_parts_json"))
    for part in body["parts"]:
        if part["type"] == "member":
            part["display"] = snapshot.name(part["qq"], part.get("name", ""))
    row["content_parts"] = body
    row["content_display"] = render(body, snapshot)
    if row.get("user_id"):
        row["user_display"] = snapshot.name(row["user_id"])
    return row



def display(row):
    """Readable memory fact with its optional owner label."""
    prefix = f"[{row['user_display']}] " if row.get("user_display") else ""
    return prefix + str(row.get("content_display", row["content"]))
