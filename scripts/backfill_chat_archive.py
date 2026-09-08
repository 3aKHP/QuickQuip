# -*- coding: utf-8 -*-
"""把既有 JSONL 采集器历史数据回灌进聊天归档（1.15.2 一次性运维脚本）。

数据源：data/wordcloud_msgs/ 与 data/daily_msgs/（群目录/<日期>.jsonl）。
同一消息被双采集器各记一份：归档按内容哈希去重（group|ts|sender|text），
后写入的一份自动忽略。daily_msgs 行带 user_id 时会补全该字段。

用法（部署新版本后执行一次）：
    python scripts/backfill_chat_archive.py            # 执行回灌
    python scripts/backfill_chat_archive.py --dry-run  # 只统计不写入
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quickquip.chat.archive import ChatArchive  # noqa: E402
from quickquip.common.paths import DAILY_MESSAGES_DIR, WORDCLOUD_MESSAGES_DIR  # noqa: E402


def _iter_jsonl(root: Path):
    if not root.exists():
        return
    for group_dir in sorted(root.iterdir()):
        if not group_dir.is_dir() or not group_dir.name.isdigit():
            continue
        for path in sorted(group_dir.glob("*.jsonl")):
            with path.open("r", encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        entry = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    text = str(entry.get("text", "")).strip()
                    if not text:
                        continue
                    try:
                        ts = float(entry.get("ts", 0))
                    except (TypeError, ValueError):
                        continue
                    yield group_dir.name, {
                        "sender": entry.get("sender", "未知"),
                        "text": text,
                        "ts": ts,
                        "user_id": entry.get("user_id"),
                    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写入")
    args = parser.parse_args()

    archive = ChatArchive()
    if not archive.stats().get("available"):
        print("聊天归档数据库不可用，中止。", file=sys.stderr)
        return 1

    sources = (("wordcloud_msgs", WORDCLOUD_MESSAGES_DIR), ("daily_msgs", DAILY_MESSAGES_DIR))
    total_seen = total_written = 0
    for label, root in sources:
        seen = written = 0
        for group_id, entry in _iter_jsonl(root):
            seen += 1
            if args.dry_run:
                continue
            if archive.record(
                group_id,
                entry["sender"],
                entry["text"],
                ts=entry["ts"],
                user_id=entry.get("user_id"),
            ):
                written += 1
        total_seen += seen
        total_written += written if not args.dry_run else 0
        print(f"{label}: 读取 {seen} 条" + ("" if args.dry_run else f"，新写入 {written} 条（其余按内容哈希去重）"))

    final = archive.stats()
    print(f"归档现状：{final['messages']} 条 / {final['groups']} 群"
          + ("（dry-run 未写入）" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
