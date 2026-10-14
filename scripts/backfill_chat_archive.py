# -*- coding: utf-8 -*-
"""把旧 JSONL 采集器历史回灌进聊天归档。

数据源：data/daily_msgs/ 与 data/wordcloud_msgs/（群目录/<日期>.jsonl）。
同一消息被双采集器各记一份：归档按内容哈希（group|秒|sender|text，另带
同秒同文的出现序号）跨源去重；daily_msgs 行携带 user_id 时回填归因字段
（因此 daily 源先处理，其首入行直接带全字段）。

在部署根执行，先备份 data/chat_archive.db 与旧 JSONL 目录：
    python scripts/backfill_chat_archive.py --dry-run  # 预览读取条数
    python scripts/backfill_chat_archive.py            # 执行回灌

检查输出中的新增、归因回填、已存在、跳过和写入失败数量。写入失败时退出码
为非零；修复后可重新执行。确认结果符合预期后，再清理旧 JSONL 目录。
Windows 懒人包使用 python\\python.exe 替换上述 python。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT if SOURCE_ROOT.is_dir() else PROJECT_ROOT))

from quickquip.chat.archive import ChatArchive, RecordResult  # noqa: E402
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
    # Windows 控制台默认代码页（如 cp1252）无法编码中文输出：统一重配为
    # UTF-8 并以替换符兜底，避免 UnicodeEncodeError 中断回灌。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写入")
    args = parser.parse_args()

    archive = ChatArchive()
    if not archive.stats().get("available"):
        print("聊天归档数据库不可用，中止。", file=sys.stderr)
        return 1

    # daily 先入：其行带 user_id，wordcloud 行撞键时只回填缺失的归因字段。
    sources = (("daily_msgs", DAILY_MESSAGES_DIR), ("wordcloud_msgs", WORDCLOUD_MESSAGES_DIR))
    failed_total = 0
    for label, root in sources:
        counts: Counter[RecordResult] = Counter()
        seen = 0
        occurrences: Counter[tuple[str, int, str, str]] = Counter()
        for group_id, entry in _iter_jsonl(root):
            seen += 1
            if args.dry_run:
                continue
            key = (group_id, int(entry["ts"]), entry["sender"], entry["text"])
            occurrences[key] += 1
            result = archive.record_result(
                group_id,
                entry["sender"],
                entry["text"],
                ts=entry["ts"],
                user_id=entry.get("user_id"),
                occurrence=occurrences[key] - 1,
            )
            counts[result] += 1
        if args.dry_run:
            print(f"{label}: 读取 {seen} 条")
            continue
        failed_total += counts[RecordResult.FAILED]
        print(
            f"{label}: 读取 {seen} 条，新写入 {counts[RecordResult.INSERTED]} 条，"
            f"回填 user_id {counts[RecordResult.BACKFILLED]} 条，"
            f"已存在 {counts[RecordResult.DUPLICATE]} 条，"
            f"跳过 {counts[RecordResult.SKIPPED]} 条，"
            f"写入失败 {counts[RecordResult.FAILED]} 条"
        )

    final = archive.stats()
    if not final.get("available"):
        print("聊天归档数据库不可用，无法核验回灌结果。", file=sys.stderr)
        return 1
    print(f"归档现状：{final['messages']} 条 / {final['groups']} 群"
          + ("（dry-run 未写入）" if args.dry_run else ""))
    return 1 if failed_total else 0


if __name__ == "__main__":
    raise SystemExit(main())
