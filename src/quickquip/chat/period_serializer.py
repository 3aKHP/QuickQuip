"""周期报告（周报/月报）聊天记录预处理器：清洗 + 压缩序列化。

目标：在不歪曲语义的前提下压缩全量聊天记录，使其可整体塞入宽上下文
模型。三级结构：

    【09-08 周二】                 ← 日分节（日期 + 星期每天一次）
    [08:12] 张三：早 / 都起了没      ← 分钟块首行（带时间戳），块内同身份
    张四：起了                     相邻消息以 / 合并为行；续行沿用块首时间戳
    [21:33] 王五：哈哈哈哈哈 ×12    ← 相邻相同消息 ≥3 折叠为 ×N

清洗规则（消费侧；归档层始终保真，见 chat/archive.py）：
- 正文折叠连续空白/换行为单空格，空消息跳过
- URL 只留域名（[example.com]）：负责总结的模型无法访问链接，长 URL
  只消耗 token 并带来提示词注入面
- 单条正文超长截断（默认 400 字符，加 … 标记）
- 说话人名折叠空白并截断（默认 24 字符），防止打穿行协议
- bot 自产消息按 user_id 匹配，显示名后缀 (bot)

纯函数：输入 read_window 形态的消息 dict，输出 (序列化文本, 统计)。
统计供日志留档与压缩比测量，不参与序列化决策。
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

__all__ = [
    "PeriodSerializeStats",
    "bot_user_ids_from_env",
    "serialize_period_chat",
]

_URL_RE = re.compile(r"https?://\S+")
_WEEKDAY_NAMES = ("一", "二", "三", "四", "五", "六", "日")


@dataclass(frozen=True)
class PeriodSerializeStats:
    """序列化统计（日志留档 / 压缩比测量用）。"""

    messages_in: int = 0
    messages_skipped: int = 0
    messages_truncated: int = 0
    urls_replaced: int = 0
    lines: int = 0
    day_sections: int = 0
    minute_blocks: int = 0
    merged_runs: int = 0
    repeat_collapses: int = 0
    bot_lines: int = 0
    chars: int = 0


@dataclass
class _Entry:
    ts: float
    identity: str
    sender: str
    text: str


@dataclass
class _Run:
    """分钟块内同身份的相邻消息串（parts 为 (文本, 相邻重复条数) 折叠态）。"""

    identity: str
    sender: str
    message_count: int = 0
    parts: list[tuple[str, int]] = field(default_factory=list)

    def append(self, text: str) -> None:
        self.message_count += 1
        if self.parts and self.parts[-1][0] == text:
            prev_text, count = self.parts[-1]
            self.parts[-1] = (prev_text, count + 1)
        else:
            self.parts.append((text, 1))


def _fold_ws(value: object) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def _domain_of(url: str) -> str:
    try:
        host = urlparse(url).netloc.rsplit("@", 1)[-1].split(":")[0].lower()
    except ValueError:
        return url
    return host[4:] if host.startswith("www.") else host


def _replace_urls(text: str) -> tuple[str, int]:
    count = 0

    def _sub(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"[{_domain_of(match.group(0))}]"

    return _URL_RE.sub(_sub, text), count


def bot_user_ids_from_env(environ: Mapping[str, str] | None = None) -> frozenset[str]:
    """从环境变量 QQ_ACCOUNT（逗号/空白分隔）解析 bot 账号集合。

    缺省/占位值/非数字片段一律忽略；本地开发未配置时返回空集（不做标记）。
    """
    raw = (environ if environ is not None else os.environ).get("QQ_ACCOUNT", "")
    return frozenset(
        part.strip() for part in re.split(r"[,\s]+", raw) if part.strip().isdigit()
    )


def _clean_entries(
    messages: list[dict], *, max_body_chars: int, stats: dict
) -> list[_Entry]:
    entries: list[_Entry] = []
    for entry in sorted(messages, key=lambda e: float(e.get("ts") or 0)):
        text = _fold_ws(entry.get("text", ""))
        if not text:
            stats["messages_skipped"] += 1
            continue
        text, n_urls = _replace_urls(text)
        stats["urls_replaced"] += n_urls
        if len(text) > max_body_chars:
            text = text[:max_body_chars] + "…"
            stats["messages_truncated"] += 1
        sender = _fold_ws(entry.get("sender", ""))[:24] or "未知"
        user_id = entry.get("user_id")
        identity = str(user_id).strip() if user_id is not None and str(user_id).strip() else sender
        entries.append(
            _Entry(ts=float(entry.get("ts") or 0), identity=identity, sender=sender, text=text)
        )
    return entries


def _render_run(
    run: _Run, *, repeat_threshold: int, max_line_parts: int
) -> tuple[list[list[str]], int]:
    """把串内折叠态 parts 展开为至多 max_line_parts 段的行切分。

    相邻重复 ≥repeat_threshold 渲染为"文本 ×N"；恰好 2 条保持两条原文。
    返回 (行切分, 折叠发生次数)。
    """
    rendered: list[str] = []
    collapses = 0
    for text, count in run.parts:
        if count >= repeat_threshold:
            rendered.append(f"{text} ×{count}")
            collapses += 1
        else:
            rendered.extend([text] * count)
    chunks = [rendered[i : i + max_line_parts] for i in range(0, len(rendered), max_line_parts)]
    return chunks, collapses


def serialize_period_chat(
    messages: Iterable[dict],
    *,
    local_tz: ZoneInfo,
    bot_user_ids: Iterable[str] = frozenset(),
    max_line_parts: int = 8,
    max_body_chars: int = 400,
    repeat_threshold: int = 3,
) -> tuple[str, PeriodSerializeStats]:
    """把归档消息序列化为周期报告输入文本。

    输入为 read_window 形态的消息 dict（sender/text/ts/user_id），
    输出 (序列化文本, 统计)。确定性纯函数，无 I/O。
    """
    stats: dict = {name: 0 for name in PeriodSerializeStats.__dataclass_fields__}
    message_list = list(messages)
    stats["messages_in"] = len(message_list)
    entries = _clean_entries(message_list, max_body_chars=max_body_chars, stats=stats)
    bots = {str(b).strip() for b in bot_user_ids if str(b).strip()}

    out_lines: list[str] = []
    prev_day: str | None = None
    prev_minute: str | None = None
    block_prefix = ""
    run: _Run | None = None

    def flush_run() -> None:
        nonlocal run, block_prefix
        if run is None:
            return
        chunks, collapses = _render_run(
            run, repeat_threshold=repeat_threshold, max_line_parts=max_line_parts
        )
        stats["repeat_collapses"] += collapses
        if run.message_count > 1:
            stats["merged_runs"] += 1
        display = f"{run.sender}(bot)" if run.identity in bots else run.sender
        for index, chunk in enumerate(chunks):
            prefix = block_prefix if index == 0 else ""
            out_lines.append(f"{prefix}{display}：{' / '.join(chunk)}")
            stats["lines"] += 1
            if run.identity in bots:
                stats["bot_lines"] += 1
        # 时间戳只落在分钟块内第一个串的首行，后续串与跨块切分续行均为裸行
        block_prefix = ""
        run = None

    for entry in entries:
        moment = datetime.fromtimestamp(entry.ts, tz=local_tz)
        day_key = moment.strftime("%m-%d")
        minute_key = moment.strftime("%H:%M")

        if day_key != prev_day:
            flush_run()
            weekday = _WEEKDAY_NAMES[moment.weekday()]
            out_lines.append(f"【{day_key} 周{weekday}】")
            stats["day_sections"] += 1
            prev_day = day_key
            prev_minute = None

        if minute_key != prev_minute:
            flush_run()
            block_prefix = f"[{minute_key}] "
            stats["minute_blocks"] += 1
            prev_minute = minute_key

        if run is not None and run.identity != entry.identity:
            flush_run()

        if run is None:
            run = _Run(identity=entry.identity, sender=entry.sender)
        run.append(entry.text)

    flush_run()

    text = "\n".join(out_lines)
    stats["chars"] = len(text)
    return text, PeriodSerializeStats(**stats)
