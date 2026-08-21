"""贴吧展示投影：只读 config 与论坛状态拼字符串，不承担同步或生命周期职责。

消费者集中在 adapters/nonebot 命令层；函数保持纯投影，状态解析与加载由
TiebaService 的窄读接口完成。
"""

from __future__ import annotations

from collections.abc import Iterable

from quickquip.tieba.config import TiebaConfig, format_timestamp
from quickquip.tieba.store import TiebaForumState, TiebaThread


def format_status(
    config: TiebaConfig,
    forum_states: Iterable[tuple[str, TiebaForumState | None]],
    *,
    total_cached: int,
    playwright_ready: bool,
) -> str:
    lines = ["贴吧状态"]
    lines.append(f"功能开关：{'ON' if config.enabled else 'OFF'}")
    lines.append(f"已配置来源：{len(config.forum_keywords)} 个")
    lines.append(f"Playwright：{'已就绪' if playwright_ready else '未安装'}")
    lines.append(f"缓存帖子：{total_cached}")
    lines.append(f"偏好带图：{'ON' if config.prefer_image_threads else 'OFF'}")
    lines.append(f"最近避重：{config.random_avoid_recent}")
    lines.append(f"状态文件：{'已存在' if config.state_path.exists() else '缺失'}")

    for forum_keyword, state in forum_states:
        lines.append(f"来源：{forum_keyword}吧")
        lines.append(f"  缓存帖子：{len(state.threads) if state else 0}")
        lines.append(f"  上次开始：{format_timestamp(state.last_sync_started_at) if state else '未记录'}")
        lines.append(f"  上次完成：{format_timestamp(state.last_sync_completed_at) if state else '未记录'}")
        lines.append(f"  上次状态：{state.last_sync_status if state else 'idle'}")
        lines.append(f"  登录态：{'需要人工续签' if state and state.login_required else '正常或未判定'}")
        if state and state.last_error:
            lines.append(f"  最近错误：{state.last_error}")

    lines.append("登录工具：python -m quickquip.tieba.login")
    return "\n".join(lines)


def format_sources(
    config: TiebaConfig,
    forum_states: Iterable[tuple[str, TiebaForumState | None]],
    *,
    show_usage_hint: bool,
) -> str:
    states = list(forum_states)
    lines = ["贴吧来源"]
    lines.append(f"功能开关：{'ON' if config.enabled else 'OFF'}")
    if not config.forum_keywords:
        lines.append("当前未配置任何贴吧来源")
        lines.append("请在 .env 中设置 TIEBA_FORUM_KEYWORDS 或 TIEBA_FORUM_KEYWORD")
        return "\n".join(lines)

    lines.append(f"已配置来源：{len(config.forum_keywords)} 个")
    if not states:
        lines.append("当前未选中任何来源")
        return "\n".join(lines)

    for forum_keyword, state in states:
        count = len(state.threads) if state else 0
        status = state.last_sync_status if state else "idle"
        login_status = "需要续签" if state and state.login_required else "正常或未判定"
        lines.append(f"- {forum_keyword}吧 | 缓存 {count} 条 | 状态 {status} | 登录态 {login_status}")

    if show_usage_hint:
        lines.append("可用：/tieba <贴吧名>、/tieba text <贴吧名>、/tieba status <贴吧名>")
    return "\n".join(lines)


def build_thread_preview(thread: TiebaThread) -> str:
    summary = thread.main_post_text or "主楼内容为空或当前未能提取正文。"
    if len(summary) > 180:
        summary = f"{summary[:180]}..."
    lines = [f"【{thread.title}】"]
    if thread.forum_keyword:
        lines.append(f"来源：{thread.forum_keyword}吧")
    if thread.author_name:
        lines.append(f"作者：{thread.author_name}")
    lines.append(summary)
    lines.append(thread.thread_url)
    return "\n".join(lines)
