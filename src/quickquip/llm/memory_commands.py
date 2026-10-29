"""记忆指令的纯文本参数解析，保留正文中的结构化成员引用。"""

import re
from copy import deepcopy

from quickquip.common.record_content import render


def write_arguments(body: dict) -> tuple[int | None, dict]:
    text = render(body)
    match = re.match(r"^\s*--(?:\s+|$)", text)
    memory_id = None
    if match is None:
        match = re.match(r"^\s*--id\s+(\d+)\s+", text)
        if match:
            memory_id = int(match[1])
        elif text.lstrip().startswith("--id"):
            raise ValueError("用法：/remember --id <编号> <新正文>")
    result = deepcopy(body)
    remaining = match.end() if match else 0
    for part in result["parts"]:
        if not remaining:
            break
        if part["type"] != "text":
            raise ValueError("记忆参数须放在正文和艾特之前")
        removed = min(remaining, len(part["text"]))
        part["text"] = part["text"][removed:]
        remaining -= removed
    return memory_id, result


def list_arguments(text: str) -> tuple[int | None, int, str]:
    text = text.strip()
    if text.startswith("-- "):
        return None, 1, text[3:]
    if text.startswith("--id"):
        match = re.fullmatch(r"--id\s+(\d+)", text)
        if not match:
            raise ValueError("用法：/memories --id <编号>")
        return int(match[1]), 1, ""
    if text.startswith("--page"):
        match = re.fullmatch(r"--page\s+([1-9]\d*)(?:\s+([\s\S]*))?", text)
        if not match:
            raise ValueError("用法：/memories --page <页码> [关键词]")
        return None, int(match[1]), (match[2] or "").removeprefix("-- ")
    return None, 1, text
