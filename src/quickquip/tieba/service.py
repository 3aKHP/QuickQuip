from __future__ import annotations

import asyncio
import random
from collections.abc import Callable, Iterable

from quickquip.tieba.store import TiebaForumState, TiebaStore, TiebaThread
from quickquip.tieba.config import (
    TiebaConfig,
    load_tieba_config,
    normalize_forum_keyword,
)
from quickquip.tieba.crawler import PLAYWRIGHT_ERROR_TYPES, TiebaCrawler
from quickquip.tieba.errors import TiebaLoginRequiredError, TiebaServiceError


class TiebaService:
    """贴吧同步编排与后台循环生命周期。

    构造不做磁盘 IO：帖子池由 load()/startup() 显式加载。共享实例由组合根
    quickquip.app.message_pipeline 持有；独立入口（web admin、login CLI）
    自行构造或从组合根获取后显式 load()。
    """

    def __init__(self, config: TiebaConfig | None = None):
        self._use_env_config = config is None
        self.config = config or load_tieba_config()
        self.store = TiebaStore(
            self.config.store_path,
            max_threads=self.config.max_pool_size,
            recent_sent_limit=self.config.recent_sent_limit,
        )
        self.crawler = TiebaCrawler(self.config)
        self._sync_lock = asyncio.Lock()
        self._background_task: asyncio.Task[None] | None = None

    def load(self) -> None:
        """从磁盘加载帖子池。启动流程显式调用，import/构造时不触发。"""
        self.store.load()

    def reload_config(self) -> TiebaConfig:
        if self._use_env_config:
            self.config = load_tieba_config()
        self.store.max_threads = self.config.max_pool_size
        self.store.set_recent_sent_limit(self.config.recent_sent_limit)
        self.crawler.config = self.config
        return self.config

    def playwright_ready(self) -> bool:
        return self.crawler.playwright_ready()

    # --- 窄读接口：供 adapter / web 层读取池状态，调用方不穿透 store ---

    def list_forum_keywords(self) -> list[str]:
        return self.store.list_forum_keywords()

    def get_forum_state(self, forum_keyword: str) -> TiebaForumState | None:
        return self.store.get_forum_state(forum_keyword)

    def list_threads(self, forum_keywords: Iterable[str]) -> list[TiebaThread]:
        return self.store.list_threads(forum_keywords)

    def count_threads(self, forum_keywords: Iterable[str]) -> int:
        return self.store.count(forum_keywords)

    def resolve_forum_keywords(
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

    @staticmethod
    def _classify_sync_error(exc: Exception) -> tuple[str, str, bool, bool]:
        """分类同步异常，返回 (message, status, login_required, wrap)。

        wrap=True 表示单来源时需包装成 TiebaServiceError 抛出；wrap=False
        时原异常直接重抛（调用方依赖 TiebaLoginRequiredError 等具体类型）。
        分支顺序与原 except 链一致：Playwright 缺失时 PLAYWRIGHT_ERROR_TYPES
        退化为 RuntimeError，仍先于 TiebaServiceError 命中，语义不变。
        """
        if isinstance(exc, TiebaLoginRequiredError):
            return str(exc), "login_required", True, False
        if isinstance(exc, PLAYWRIGHT_ERROR_TYPES):
            return f"Playwright 访问失败：{exc}", "error", False, True
        if isinstance(exc, TiebaServiceError):
            return str(exc), "error", False, False
        return f"贴吧同步异常：{exc}", "error", False, True

    async def sync_now(
        self,
        *,
        force: bool = False,
        forum_keyword: str | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> dict[str, object]:
        async with self._sync_lock:
            selected_forums = self.resolve_forum_keywords(forum_keyword)
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
                except Exception as exc:
                    message, status, login_required, wrap = self._classify_sync_error(exc)
                    self.store.record_sync_failure(selected_forum, message, login_required=login_required)
                    if on_progress:
                        detail = f"需要重新登录：{exc}" if login_required else message
                        on_progress(f"✗ {selected_forum}吧 {detail}")
                    if len(selected_forums) == 1:
                        if wrap:
                            raise TiebaServiceError(message) from exc
                        raise
                    results.append(
                        {
                            "forum_keyword": selected_forum,
                            "updated": 0,
                            "count": self.store.count((selected_forum,)),
                            "status": status,
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
        self.load()
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
        selected_forums = self.resolve_forum_keywords(forum_keyword)
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
        threads = await self.crawler.collect_threads(forum_keyword, limit=5)
        valid = [t for t in threads if t.cover_image_url or t.image_urls]
        if valid:
            return random.choice(valid)
        if threads:
            return random.choice(threads)
        return None

    def is_login_required(self, forum_keyword: str | None = None) -> bool:
        selected_forums = self.resolve_forum_keywords(forum_keyword, require_enabled=False)
        return self.store.any_login_required(selected_forums)

    def mark_sent(self, thread: TiebaThread) -> None:
        self.store.mark_sent(thread.tid, thread.forum_keyword)

    async def interactive_login(self, forum_keyword: str | None = None) -> None:
        selected_forums = self.resolve_forum_keywords(forum_keyword, require_enabled=False)
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
