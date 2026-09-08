# -*- coding: utf-8 -*-
"""把既有 JSONL 采集器历史数据回灌进聊天归档（1.15.2 一次性运维脚本）。

数据源：data/daily_msgs/ 与 data/wordcloud_msgs/（群目录/<日期>.jsonl）。
同一消息被双采集器各记一份：归档按内容哈希（group|秒|sender|text，另带
同秒同文的出现序号）跨源去重；daily_msgs 行携带 user_id 时回填归因字段
（因此 daily 源先处理，其首入行直接带全字段）。

用法（部署新版本后执行一次）：
    python scripts/backfill_chat_archive.py            # 执行回灌
    python scripts/backfill_chat_archive.py --dry-run  # 只统计不写入
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
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
                    text = str(entry.get("text", ""))
                    if not text.strip():
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

    # daily 先入：其行带 user_id，wordcloud 行撞键时只回填缺失的归因字段。
    sources = (("daily_msgs", DAILY_MESSAGES_DIR), ("wordcloud_msgs", WORDCLOUD_MESSAGES_DIR))
    for label, root in sources:
        seen = written = 0
        occurrences: Counter[tuple[str, int, str, str]] = Counter()
        for group_id, entry in _iter_jsonl(root):
            seen += 1
            if args.dry_run:
                continue
            key = (group_id, int(entry["ts"]), entry["sender"], entry["text"])
            occurrences[key] += 1
            if archive.record(
                group_id,
                entry["sender"],
                entry["text"],
                ts=entry["ts"],
                user_id=entry.get("user_id"),
                occurrence=occurrences[key] - 1,
            ):
                written += 1
        print(f"{label}: 读取 {seen} 条" + ("" if args.dry_run else f"，新写入 {written} 条（其余按内容哈希去重或仅回填 user_id）"))

    final = archive.stats()
    print(f"归档现状：{final['messages']} 条 / {final['groups']} 群"
          + ("（dry-run 未写入）" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
