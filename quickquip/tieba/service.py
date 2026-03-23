from __future__ import annotations

import asyncio

from quickquip.tieba.store import TiebaStore, TiebaThread
from quickquip.tieba.config import TIEBA_RULE_NAME, TiebaConfig, format_timestamp, load_tieba_config
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
        self.store.recent_sent_limit = self.config.recent_sent_limit
        self.store.recent_sent_ids = self.store.recent_sent_ids.__class__(
            list(self.store.recent_sent_ids)[-self.config.recent_sent_limit :],
            maxlen=self.config.recent_sent_limit,
        )
        self.crawler.config = self.config
        return self.config

    def _playwright_ready(self) -> bool:
        return self.crawler.playwright_ready()

    async def sync_now(self, *, force: bool = False) -> dict[str, object]:
        async with self._sync_lock:
            self.reload_config()
            if not self.config.enabled:
                raise TiebaServiceError("贴吧功能未启用，请先设置 TIEBA_ENABLED=true")
            if not self.config.forum_keyword:
                raise TiebaServiceError("未配置 TIEBA_FORUM_KEYWORD，无法同步固定贴吧")
            if self.store.last_sync_status == "running" and not force:
                return {
                    "updated": 0,
                    "count": self.store.count(),
                    "status": "running",
                    "message": "上一轮贴吧同步仍在进行中",
                }

            self.store.record_sync_started(self.config.forum_keyword)
            try:
                threads = await self.crawler.collect_threads()
            except TiebaLoginRequiredError as exc:
                self.store.record_sync_failure(str(exc), login_required=True)
                raise
            except PLAYWRIGHT_ERROR_TYPES as exc:
                self.store.record_sync_failure(f"Playwright 访问失败：{exc}")
                raise TiebaServiceError(f"Playwright 访问失败：{exc}") from exc
            except TiebaServiceError as exc:
                self.store.record_sync_failure(str(exc))
                raise
            except Exception as exc:
                self.store.record_sync_failure(f"贴吧同步异常：{exc}")
                raise TiebaServiceError(f"贴吧同步异常：{exc}") from exc

            updated = self.store.record_sync_success(threads)
            return {
                "updated": updated,
                "count": self.store.count(),
                "status": "ok",
                "message": f"贴吧缓存已同步，当前池内 {self.store.count()} 条，最近更新 {updated} 条",
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

    async def get_random_thread(self) -> TiebaThread | None:
        if self.store.count() == 0 and self.config.is_configured:
            try:
                await self.sync_now(force=True)
            except TiebaServiceError:
                pass
        return self.store.choose_random_thread(
            prefer_images=self.config.prefer_image_threads,
            avoid_recent=self.config.random_avoid_recent,
        )

    def mark_sent(self, tid: str) -> None:
        self.store.mark_sent(tid)

    def format_status(self) -> str:
        self.reload_config()
        lines = ["贴吧状态"]
        lines.append(f"功能开关：{'ON' if self.config.enabled else 'OFF'}")
        lines.append(f"目标贴吧：{self.config.forum_keyword or '未配置'}")
        lines.append(f"Playwright：{'已就绪' if self._playwright_ready() else '未安装'}")
        lines.append(f"缓存帖子：{self.store.count()}")
        lines.append(f"偏好带图：{'ON' if self.config.prefer_image_threads else 'OFF'}")
        lines.append(f"最近避重：{self.config.random_avoid_recent}")
        lines.append(f"上次开始：{format_timestamp(self.store.last_sync_started_at)}")
        lines.append(f"上次完成：{format_timestamp(self.store.last_sync_completed_at)}")
        lines.append(f"上次状态：{self.store.last_sync_status}")
        lines.append(f"登录态：{'需要人工续签' if self.store.login_required else '正常或未判定'}")
        lines.append(f"状态文件：{'已存在' if self.config.state_path.exists() else '缺失'}")
        if self.store.last_error:
            lines.append(f"最近错误：{self.store.last_error}")
        lines.append("登录工具：python dev/tools/tieba_login.py")
        return "\n".join(lines)

    def build_thread_preview(self, thread: TiebaThread) -> str:
        summary = thread.main_post_text or "主楼内容为空或当前未能提取正文。"
        if len(summary) > 180:
            summary = f"{summary[:180]}..."
        lines = [f"【{thread.title}】"]
        if thread.author_name:
            lines.append(f"作者：{thread.author_name}")
        lines.append(summary)
        lines.append(thread.thread_url)
        return "\n".join(lines)

    async def interactive_login(self) -> None:
        self.reload_config()
        await self.crawler.interactive_login()
        self.store.login_required = False
        self.store.last_error = ""
        self.store.save()
        print("登录态验证通过，浏览器资料目录已保存。")
        print(f"已导出跨平台登录态：{self.config.state_path}")


tieba_service = TiebaService()
