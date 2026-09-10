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

周报：全量窗口直接 serialize_period_chat。
月报：build_monthly_chat_input 按周公平分配字符预算，周内高活跃日优先
整日保留，低活跃日抽稀或整日保留，保证各周都有覆盖且终稿输入维持在
目标量级（默认约 24 万字符，中文约 1 字 ≈ 1 token 时 ≥200k token）。

纯函数：输入 read_window 形态的消息 dict，输出 (序列化文本, 统计)。
统计供日志留档与压缩比测量，不参与序列化决策。
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

__all__ = [
    "DEFAULT_MONTHLY_INPUT_CHARS",
    "MonthlyInputStats",
    "PeriodSerializeStats",
    "bot_user_ids_from_env",
    "build_monthly_chat_input",
    "serialize_period_chat",
]

# 月报终稿输入字符预算缺省：中文密集内容约 1 字 ≈ 1 token（保守档），
# 24 万字符对应 ≥200k token，同时低于 1M 窗口模型的舒适上限。
DEFAULT_MONTHLY_INPUT_CHARS = 240_000

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


@dataclass(frozen=True)
class MonthlyInputStats:
    """月报分周预算组装统计。"""

    messages_in: int = 0
    messages_selected: int = 0
    chars: int = 0
    target_chars: int = 0
    weeks: int = 0
    days_full: int = 0
    days_sampled: int = 0
    days_skipped: int = 0
    lines: int = 0
    day_sections: int = 0
    minute_blocks: int = 0
    merged_runs: int = 0
    repeat_collapses: int = 0
    urls_replaced: int = 0
    messages_truncated: int = 0
    messages_skipped: int = 0
    bot_lines: int = 0


# 抽稀日至少要能放下日分节标题 + 若干行，再小就没有叙事价值
_MIN_SAMPLED_DAY_CHARS = 80


def _sample_text_to_budget(
    messages: list[dict],
    max_chars: int,
    *,
    local_tz: ZoneInfo,
    bot_user_ids: set[str],
    max_line_parts: int,
    max_body_chars: int,
    repeat_threshold: int,
) -> tuple[str, PeriodSerializeStats] | None:
    """对单日消息等距抽稀，使序列化结果字符数 ≤ max_chars。

    从全量开始二分 per_day；仍放不下则返回 None。
    """
    if not messages or max_chars < _MIN_SAMPLED_DAY_CHARS:
        return None

    def _render(sample: list[dict]) -> tuple[str, PeriodSerializeStats]:
        return serialize_period_chat(
            sample,
            local_tz=local_tz,
            bot_user_ids=bot_user_ids,
            max_line_parts=max_line_parts,
            max_body_chars=max_body_chars,
            repeat_threshold=repeat_threshold,
        )

    full_text, full_stats = _render(messages)
    if len(full_text) <= max_chars:
        return full_text, full_stats

    lo, hi = 1, len(messages)
    best: tuple[str, PeriodSerializeStats] | None = None
    while lo <= hi:
        per_day = (lo + hi) // 2
        # 等距抽样（与 period_report.sample_messages_by_day 同策略）
        step = len(messages) / per_day
        indices = [int(i * step) for i in range(per_day)]
        # 去重并保持时间序（step<1 时 indices 可能重复）
        seen: set[int] = set()
        picked: list[dict] = []
        for i in indices:
            if i not in seen and 0 <= i < len(messages):
                seen.add(i)
                picked.append(messages[i])
        text, stats = _render(picked)
        if len(text) <= max_chars:
            best = (text, stats)
            lo = per_day + 1
        else:
            hi = per_day - 1
    return best


def build_monthly_chat_input(
    messages: Iterable[dict],
    *,
    local_tz: ZoneInfo,
    bot_user_ids: Iterable[str] = frozenset(),
    target_chars: int = DEFAULT_MONTHLY_INPUT_CHARS,
    max_line_parts: int = 8,
    max_body_chars: int = 400,
    repeat_threshold: int = 3,
) -> tuple[str, MonthlyInputStats]:
    """组装月报输入：按周公平预算 + 周内活跃日优先。

    1. 消息按本地日历日分桶，再按 ISO 周分组。
    2. 预算 target_chars 在各周间均分，避免单周刷屏饿死其他周。
    3. 周内：体量不超日基线的「平静日」整日保留；剩余预算按消息量
       从高到低喂给「活跃日」，放不下则等距抽稀，仍放不下则跳过。
    4. 输出在周内按日历序回写，并冠以【第N周 MM-DD–MM-DD】周节标题。

    确定性纯函数，无 I/O。
    """
    stats: dict = {name: 0 for name in MonthlyInputStats.__dataclass_fields__}
    stats["target_chars"] = max(1, int(target_chars))
    message_list = sorted(messages, key=lambda e: float(e.get("ts") or 0))
    stats["messages_in"] = len(message_list)
    if not message_list:
        return "", MonthlyInputStats(**stats)

    bots = {str(b).strip() for b in bot_user_ids if str(b).strip()}
    by_day: dict[date, list[dict]] = defaultdict(list)
    for entry in message_list:
        moment = datetime.fromtimestamp(float(entry.get("ts") or 0), tz=local_tz)
        by_day[moment.date()].append(entry)

    by_week: dict[tuple[int, int], list[date]] = defaultdict(list)
    for day in sorted(by_day):
        iso_year, iso_week, _ = day.isocalendar()
        by_week[(iso_year, iso_week)].append(day)

    week_keys = sorted(by_week)
    week_budget = stats["target_chars"] // len(week_keys)
    out_parts: list[str] = []

    def _render_day(day_msgs: list[dict]) -> tuple[str, PeriodSerializeStats]:
        return serialize_period_chat(
            day_msgs,
            local_tz=local_tz,
            bot_user_ids=bots,
            max_line_parts=max_line_parts,
            max_body_chars=max_body_chars,
            repeat_threshold=repeat_threshold,
        )

    for week_index, week_key in enumerate(week_keys, start=1):
        days = by_week[week_key]
        measured: list[tuple[date, list[dict], str, PeriodSerializeStats]] = []
        for day in days:
            day_msgs = by_day[day]
            text, day_stats = _render_day(day_msgs)
            measured.append((day, day_msgs, text, day_stats))

        # 周节标题与日间换行也计入本周预算，避免组装后突破 target_chars
        week_header = (
            f"【第{week_index}周 {days[0].strftime('%m-%d')}–{days[-1].strftime('%m-%d')}】"
        )
        header_cost = len(week_header) + 1
        n_days = len(measured)
        week_pool = max(0, week_budget - header_cost)
        day_baseline = max(_MIN_SAMPLED_DAY_CHARS, week_pool // n_days)

        selected: dict[date, str] = {}
        selected_stats: list[PeriodSerializeStats] = []
        used = 0
        heavy: list[tuple[date, list[dict], str, PeriodSerializeStats]] = []

        for day, day_msgs, text, day_stats in measured:
            if len(text) + 1 <= day_baseline:
                selected[day] = text
                selected_stats.append(day_stats)
                used += len(text) + 1
                stats["days_full"] += 1
            else:
                heavy.append((day, day_msgs, text, day_stats))

        leftover = max(0, week_pool - used)
        heavy.sort(key=lambda item: (-len(item[1]), item[0]))
        for day, day_msgs, full_text, full_stats in heavy:
            if leftover <= 0:
                stats["days_skipped"] += 1
                continue
            if len(full_text) + 1 <= leftover:
                selected[day] = full_text
                selected_stats.append(full_stats)
                leftover -= len(full_text) + 1
                stats["days_full"] += 1
                continue
            fitted = _sample_text_to_budget(
                day_msgs,
                leftover - 1 if leftover > 1 else leftover,
                local_tz=local_tz,
                bot_user_ids=bots,
                max_line_parts=max_line_parts,
                max_body_chars=max_body_chars,
                repeat_threshold=repeat_threshold,
            )
            if fitted is not None:
                fitted_text, fitted_stats = fitted
                selected[day] = fitted_text
                selected_stats.append(fitted_stats)
                leftover -= len(fitted_text) + 1
                stats["days_sampled"] += 1
            else:
                stats["days_skipped"] += 1

        if not selected:
            continue

        start_d, end_d = days[0], days[-1]
        week_header = f"【第{week_index}周 {start_d.strftime('%m-%d')}–{end_d.strftime('%m-%d')}】"
        out_parts.append(week_header)
        stats["weeks"] += 1
        for day in days:
            if day not in selected:
                continue
            out_parts.append(selected[day])
            stats["lines"] += selected[day].count("\n") + 1

        for day_stats in selected_stats:
            stats["messages_selected"] += day_stats.messages_in - day_stats.messages_skipped
            stats["day_sections"] += day_stats.day_sections
            stats["minute_blocks"] += day_stats.minute_blocks
            stats["merged_runs"] += day_stats.merged_runs
            stats["repeat_collapses"] += day_stats.repeat_collapses
            stats["urls_replaced"] += day_stats.urls_replaced
            stats["messages_truncated"] += day_stats.messages_truncated
            stats["messages_skipped"] += day_stats.messages_skipped
            stats["bot_lines"] += day_stats.bot_lines

    text = "\n".join(out_parts)
    stats["chars"] = len(text)
    return text, MonthlyInputStats(**stats)
