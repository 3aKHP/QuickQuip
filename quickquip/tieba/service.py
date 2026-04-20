from __future__ import annotations

import asyncio
from collections.abc import Callable

from quickquip.tieba.store import TiebaStore, TiebaThread
from quickquip.tieba.config import (
    TiebaConfig,
    format_timestamp,
    load_tieba_config,
    normalize_forum_keyword,
)
from quickquip.tieba.crawler import PLAYWRIGHT_ERROR_TYPES, TiebaCrawler
from quickquip.tieba.errors import TiebaLoginRequiredError, TiebaServiceError


class TiebaService:
    def __init__(self, config: TiebaConfig | None = None):
        self._use_env_config = config is None
        self.config = config or load_tieba_config()
        self.store = TiebaStore(
            self.config.store_path,
            max_threads=self.config.max_pool_size,
            recent_sent_limit=self.config.recent_sent_limit,
        )
        self.store.load()
        self.crawler = TiebaCrawler(self.config)
        self._sync_lock = asyncio.Lock()
        self._background_task: asyncio.Task[None] | None = None

    def reload_config(self) -> TiebaConfig:
        if self._use_env_config:
            self.config = load_tieba_config()
        self.store.max_threads = self.config.max_pool_size
        self.store.set_recent_sent_limit(self.config.recent_sent_limit)
        self.crawler.config = self.config
        return self.config

    def _playwright_ready(self) -> bool:
        return self.crawler.playwright_ready()

    def _resolve_forum_keywords(
        self,
        forum_keyword: str | None = None,
        *,
        require_enabled: bool = True,
    ) -> tuple[str, ...]:
        self.reload_config()
        if require_enabled and not self.config.enabled:
            raise TiebaServiceError("贴吧功能未启用，请先设置 TIEBA_ENABLED=true")
        if not self.config.forum_keywords:
            if not require_enabled:
                return ()
            raise TiebaServiceError("未配置 TIEBA_FORUM_KEYWORD 或 TIEBA_FORUM_KEYWORDS，无法同步贴吧")

        if forum_keyword is None:
            return self.config.forum_keywords

        normalized = normalize_forum_keyword(forum_keyword)
        if not normalized:
            return self.config.forum_keywords
        if not self.config.has_forum(normalized):
            raise TiebaServiceError(f"未配置贴吧来源：{normalized}吧")
        return (normalized,)

    def _build_sync_message(self, results: list[dict[str, object]], selected_forums: tuple[str, ...]) -> str:
        if not results:
            return "未执行任何贴吧同步"

        if len(selected_forums) == 1 and len(results) == 1:
            result = results[0]
            forum_keyword = str(result["forum_keyword"])
            status = str(result["status"])
            if status == "ok":
                return (
                    f"{forum_keyword}吧缓存已同步，当前池内 {result['count']} 条，"
                    f"最近更新 {result['updated']} 条"
                )
            return f"{forum_keyword}吧同步状态：{result['message']}"

        success_count = sum(1 for item in results if item["status"] == "ok")
        lines = [
            f"贴吧缓存同步完成：{success_count}/{len(results)} 个来源成功，总缓存 {self.store.count(selected_forums)} 条"
        ]
        for item in results:
            forum_keyword = str(item["forum_keyword"])
            status = str(item["status"])
            if status == "ok":
                lines.append(f"- {forum_keyword}吧：{item['count']} 条，更新 {item['updated']} 条")
            else:
                lines.append(f"- {forum_keyword}吧：{item['message']}")
        return "\n".join(lines)

    async def sync_now(
        self,
        *,
        force: bool = False,
        forum_keyword: str | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> dict[str, object]:
        async with self._sync_lock:
            selected_forums = self._resolve_forum_keywords(forum_keyword)
            results: list[dict[str, object]] = []

            for selected_forum in selected_forums:
                state = self.store.get_forum_state(selected_forum)
                if state is not None and state.last_sync_status == "running" and not force:
                    results.append(
                        {
                            "forum_keyword": selected_forum,
                            "updated": 0,
                            "count": len(state.threads),
                            "status": "running",
                            "message": "上一轮贴吧同步仍在进行中",
                        }
                    )
                    continue

                self.store.record_sync_started(selected_forum)
                if on_progress:
                    on_progress(f"▶ 开始同步 {selected_forum}吧")
                try:
                    threads = await self.crawler.collect_threads(selected_forum, on_progress=on_progress)
                except TiebaLoginRequiredError as exc:
                    self.store.record_sync_failure(selected_forum, str(exc), login_required=True)
                    if on_progress:
                        on_progress(f"✗ {selected_forum}吧 需要重新登录：{exc}")
                    if len(selected_forums) == 1:
                        raise
                    results.append(
                        {
                            "forum_keyword": selected_forum,
                            "updated": 0,
                            "count": self.store.count((selected_forum,)),
                            "status": "login_required",
                            "message": str(exc),
                        }
                    )
                    continue
                except PLAYWRIGHT_ERROR_TYPES as exc:
                    message = f"Playwright 访问失败：{exc}"
                    self.store.record_sync_failure(selected_forum, message)
                    if on_progress:
                        on_progress(f"✗ {selected_forum}吧 {message}")
                    if len(selected_forums) == 1:
                        raise TiebaServiceError(message) from exc
                    results.append(
                        {
                            "forum_keyword": selected_forum,
                            "updated": 0,
                            "count": self.store.count((selected_forum,)),
                            "status": "error",
                            "message": message,
                        }
                    )
                    continue
                except TiebaServiceError as exc:
                    self.store.record_sync_failure(selected_forum, str(exc))
                    if on_progress:
                        on_progress(f"✗ {selected_forum}吧 {exc}")
                    if len(selected_forums) == 1:
                        raise
                    results.append(
                        {
                            "forum_keyword": selected_forum,
                            "updated": 0,
                            "count": self.store.count((selected_forum,)),
                            "status": "error",
                            "message": str(exc),
                        }
                    )
                    continue
                except Exception as exc:
                    message = f"贴吧同步异常：{exc}"
                    self.store.record_sync_failure(selected_forum, message)
                    if on_progress:
                        on_progress(f"✗ {selected_forum}吧 {message}")
                    if len(selected_forums) == 1:
                        raise TiebaServiceError(message) from exc
                    results.append(
                        {
                            "forum_keyword": selected_forum,
                            "updated": 0,
                            "count": self.store.count((selected_forum,)),
                            "status": "error",
                            "message": message,
                        }
                    )
                    continue

                updated = self.store.record_sync_success(selected_forum, threads)
                if on_progress:
                    on_progress(f"✓ {selected_forum}吧 同步完成，新增/更新 {updated} 条，共 {self.store.count((selected_forum,))} 条")
                results.append(
                    {
                        "forum_keyword": selected_forum,
                        "updated": updated,
                        "count": self.store.count((selected_forum,)),
                        "status": "ok",
                        "message": "同步成功",
                    }
                )

            return {
                "results": results,
                "count": self.store.count(selected_forums),
                "status": "ok" if all(item["status"] == "ok" for item in results) else "partial",
                "message": self._build_sync_message(results, selected_forums),
            }

    async def startup(self) -> None:
        self.reload_config()
        if not self.config.is_configured:
            return
        if self._background_task is not None and not self._background_task.done():
            return
        self._background_task = asyncio.create_task(self._run_background_loop(), name="quickquip-tieba-sync")

    async def shutdown(self) -> None:
        if self._background_task is None:
            return
        self._background_task.cancel()
        await asyncio.gather(self._background_task, return_exceptions=True)
        self._background_task = None

    async def _run_background_loop(self) -> None:
        try:
            while True:
                try:
                    await self.sync_now(force=True)
                except TiebaServiceError:
                    pass
                await asyncio.sleep(self.config.sync_interval_seconds)
        except asyncio.CancelledError:
            raise

    async def get_random_thread(self, forum_keyword: str | None = None) -> TiebaThread | None:
        selected_forums = self._resolve_forum_keywords(forum_keyword)
        if self.store.count(selected_forums) == 0:
            try:
                await self.sync_now(force=True, forum_keyword=forum_keyword)
            except TiebaServiceError:
                pass
        return self.store.choose_random_thread(
            forum_keywords=selected_forums,
            prefer_images=self.config.prefer_image_threads,
            avoid_recent=self.config.random_avoid_recent,
        )

    async def peek_random_thread(self, forum_keyword: str) -> TiebaThread | None:
        """现爬指定吧首页，随机返回一个帖子，不写入 pool。"""
        import random
        threads = await self.crawler.collect_threads(forum_keyword, limit=5)
        valid = [t for t in threads if t.cover_image_url or t.image_urls]
        return random.choice(valid) if valid else (random.choice(threads) if threads else None)

    def is_login_required(self, forum_keyword: str | None = None) -> bool:
        selected_forums = self._resolve_forum_keywords(forum_keyword, require_enabled=False)
        return self.store.any_login_required(selected_forums)

    def mark_sent(self, thread: TiebaThread) -> None:
        self.store.mark_sent(thread.tid, thread.forum_keyword)

    def format_status(self, forum_keyword: str | None = None) -> str:
        selected_forums = self._resolve_forum_keywords(forum_keyword, require_enabled=False)
        lines = ["贴吧状态"]
        lines.append(f"功能开关：{'ON' if self.config.enabled else 'OFF'}")
        lines.append(f"已配置来源：{len(self.config.forum_keywords)} 个")
        lines.append(f"Playwright：{'已就绪' if self._playwright_ready() else '未安装'}")
        lines.append(f"缓存帖子：{self.store.count(selected_forums)}")
        lines.append(f"偏好带图：{'ON' if self.config.prefer_image_threads else 'OFF'}")
        lines.append(f"最近避重：{self.config.random_avoid_recent}")
        lines.append(f"状态文件：{'已存在' if self.config.state_path.exists() else '缺失'}")

        for selected_forum in selected_forums:
            state = self.store.get_forum_state(selected_forum)
            lines.append(f"来源：{selected_forum}吧")
            lines.append(f"  缓存帖子：{len(state.threads) if state else 0}")
            lines.append(f"  上次开始：{format_timestamp(state.last_sync_started_at) if state else '未记录'}")
            lines.append(f"  上次完成：{format_timestamp(state.last_sync_completed_at) if state else '未记录'}")
            lines.append(f"  上次状态：{state.last_sync_status if state else 'idle'}")
            lines.append(f"  登录态：{'需要人工续签' if state and state.login_required else '正常或未判定'}")
            if state and state.last_error:
                lines.append(f"  最近错误：{state.last_error}")

        lines.append("登录工具：python dev/tools/tieba_login.py")
        return "\n".join(lines)

    def format_sources(self, forum_keyword: str | None = None) -> str:
        selected_forums = self._resolve_forum_keywords(forum_keyword, require_enabled=False)
        lines = ["贴吧来源"]
        lines.append(f"功能开关：{'ON' if self.config.enabled else 'OFF'}")
        if not self.config.forum_keywords:
            lines.append("当前未配置任何贴吧来源")
            lines.append("请在 .env 中设置 TIEBA_FORUM_KEYWORDS 或 TIEBA_FORUM_KEYWORD")
            return "\n".join(lines)

        lines.append(f"已配置来源：{len(self.config.forum_keywords)} 个")
        if not selected_forums:
            lines.append("当前未选中任何来源")
            return "\n".join(lines)

        for selected_forum in selected_forums:
            state = self.store.get_forum_state(selected_forum)
            count = len(state.threads) if state else 0
            status = state.last_sync_status if state else "idle"
            login_status = "需要续签" if state and state.login_required else "正常或未判定"
            lines.append(f"- {selected_forum}吧 | 缓存 {count} 条 | 状态 {status} | 登录态 {login_status}")

        if forum_keyword is None:
            lines.append("可用：/tieba <贴吧名>、/tieba text <贴吧名>、/tieba status <贴吧名>")
        return "\n".join(lines)

    def build_thread_preview(self, thread: TiebaThread) -> str:
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

    async def interactive_login(self, forum_keyword: str | None = None) -> None:
        selected_forums = self._resolve_forum_keywords(forum_keyword, require_enabled=False)
        if not selected_forums:
            raise TiebaServiceError("请先在 .env 中设置 TIEBA_FORUM_KEYWORD 或 TIEBA_FORUM_KEYWORDS")
        login_forum = selected_forums[0]
        await self.crawler.interactive_login(login_forum)
        for selected_forum in selected_forums:
            state = self.store.get_forum_state(selected_forum)
            if state is None:
                continue
            state.login_required = False
            if state.last_sync_status == "login_required":
                state.last_error = ""
        self.store.save()
        print("登录态验证通过，浏览器资料目录已保存。")
        print(f"已导出跨平台登录态：{self.config.state_path}")


tieba_service = TiebaService()
