from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib import parse
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from plugins.tieba_store import TiebaStore, TiebaThread
from plugins.tz_config import BEIJING_TIMEZONE

try:
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError, async_playwright
except ModuleNotFoundError:
    PlaywrightError = RuntimeError
    PlaywrightTimeoutError = RuntimeError
    Page = Any
    async_playwright = None


TIEBA_RULE_NAME = "tieba_random_post"
DATA_DIR = Path("data/tieba")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
STORE_PATH = DATA_DIR / "pool.json"
PROFILE_DIR = DATA_DIR / "profile"
STATE_PATH = DATA_DIR / "storage_state.json"
DEFAULT_SYNC_INTERVAL_SECONDS = 900
DEFAULT_MAX_POOL_SIZE = 240
DEFAULT_RECENT_SENT_LIMIT = 30
DEFAULT_DETAIL_FETCH_LIMIT = 18
DEFAULT_RANDOM_AVOID_RECENT = 10


class TiebaServiceError(RuntimeError):
    pass


class TiebaLoginRequiredError(TiebaServiceError):
    pass


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _normalize_forum_keyword(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized.endswith("吧") and len(normalized) > 1:
        return normalized[:-1].strip()
    return normalized


def _load_project_env_files() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    load_dotenv(PROJECT_ROOT / "dev/.env", override=True)


def _clean_text(value: str, *, limit: int = 0) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "")).strip()
    if limit > 0:
        return normalized[:limit]
    return normalized


def _clean_thread_title(value: str) -> str:
    normalized = _clean_text(value, limit=120)
    if normalized.endswith("-百度贴吧"):
        normalized = normalized[: -len("-百度贴吧")].rstrip()
    return normalized


def _format_timestamp(timestamp: float) -> str:
    if timestamp <= 0:
        return "未记录"
    dt = datetime.fromtimestamp(timestamp, tz=ZoneInfo(BEIJING_TIMEZONE))
    return dt.strftime("%Y-%m-%d %H:%M")


@dataclass(slots=True)
class TiebaConfig:
    enabled: bool
    forum_keyword: str
    sync_interval_seconds: int
    max_pool_size: int
    recent_sent_limit: int
    detail_fetch_limit: int
    random_avoid_recent: int
    prefer_image_threads: bool
    browser_headless: bool
    browser_channel: str
    profile_dir: Path
    state_path: Path
    store_path: Path

    @property
    def forum_url(self) -> str:
        encoded_kw = parse.quote(self.forum_keyword)
        return f"https://tieba.baidu.com/f?kw={encoded_kw}"

    @property
    def is_configured(self) -> bool:
        return self.enabled and bool(self.forum_keyword)


def load_tieba_config() -> TiebaConfig:
    _load_project_env_files()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return TiebaConfig(
        enabled=_env_bool("TIEBA_ENABLED", False),
        forum_keyword=_normalize_forum_keyword(os.getenv("TIEBA_FORUM_KEYWORD", "")),
        sync_interval_seconds=max(60, int(os.getenv("TIEBA_SYNC_INTERVAL_SECONDS", DEFAULT_SYNC_INTERVAL_SECONDS) or DEFAULT_SYNC_INTERVAL_SECONDS)),
        max_pool_size=max(20, int(os.getenv("TIEBA_MAX_POOL_SIZE", DEFAULT_MAX_POOL_SIZE) or DEFAULT_MAX_POOL_SIZE)),
        recent_sent_limit=max(1, int(os.getenv("TIEBA_RECENT_SENT_LIMIT", DEFAULT_RECENT_SENT_LIMIT) or DEFAULT_RECENT_SENT_LIMIT)),
        detail_fetch_limit=max(1, int(os.getenv("TIEBA_DETAIL_FETCH_LIMIT", DEFAULT_DETAIL_FETCH_LIMIT) or DEFAULT_DETAIL_FETCH_LIMIT)),
        random_avoid_recent=max(0, int(os.getenv("TIEBA_RANDOM_AVOID_RECENT", DEFAULT_RANDOM_AVOID_RECENT) or DEFAULT_RANDOM_AVOID_RECENT)),
        prefer_image_threads=_env_bool("TIEBA_PREFER_IMAGE_THREADS", True),
        browser_headless=_env_bool("TIEBA_BROWSER_HEADLESS", True),
        browser_channel=os.getenv("TIEBA_BROWSER_CHANNEL", "").strip(),
        profile_dir=PROFILE_DIR,
        state_path=STATE_PATH,
        store_path=STORE_PATH,
    )


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
        return self.config

    def _playwright_ready(self) -> bool:
        return async_playwright is not None

    def _get_storage_state_arg(self) -> str | None:
        if self.config.state_path.exists():
            return str(self.config.state_path)
        return None

    def _is_challenge_page(self, title: str, content: str, url: str) -> bool:
        haystack = "\n".join([title, content, url]).lower()
        return any(
            marker in haystack
            for marker in [
                "百度安全验证",
                "seccaptcha",
                "bioc_options",
                "账号安全",
                "访问受限",
            ]
        )

    async def _goto(self, page: Page, url: str) -> None:
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(1500)

    async def _ensure_accessible_page(self, page: Page, *, url: str, label: str) -> None:
        await self._goto(page, url)
        title = _clean_text(await page.title())
        content = _clean_text(await page.content(), limit=10_000)
        current_url = _clean_text(page.url)
        if self._is_challenge_page(title, content, current_url):
            raise TiebaLoginRequiredError(f"{label} 命中百度安全验证，需要人工续签登录态")

    async def _load_forum_feed_data(self, page: Page) -> dict[str, object]:
        try:
            async with page.expect_response(
                lambda response: "tieba.baidu.com/c/f/frs/page_pc" in response.url,
                timeout=20_000,
            ) as response_info:
                await self._goto(page, self.config.forum_url)
            response = await response_info.value
            raw = await response.text()
            data = json.loads(raw)
        except Exception as exc:
            raise TiebaServiceError(f"贴吧首页接口解析失败：{exc}") from exc

        title = _clean_text(await page.title())
        content = _clean_text(await page.content(), limit=10_000)
        current_url = _clean_text(page.url)
        if self._is_challenge_page(title, content, current_url):
            raise TiebaLoginRequiredError(f"{self.config.forum_keyword} 吧主页命中百度安全验证，需要人工续签登录态")

        if int(data.get("error_code", 0) or 0) != 0:
            raise TiebaServiceError(
                f"贴吧首页接口返回异常：error_code={data.get('error_code')} {data.get('error_msg', '')}"
            )
        return data

    def _extract_forum_links(self, data: dict[str, object]) -> list[dict[str, str]]:
        page_data = data.get("page_data", {})
        feed_list = page_data.get("feed_list", []) if isinstance(page_data, dict) else []
        if not isinstance(feed_list, list):
            return []

        normalized: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in feed_list:
            if not isinstance(item, dict):
                continue
            feed = item.get("feed", {})
            if not isinstance(feed, dict):
                continue
            info = feed.get("business_info_map", {})
            if not isinstance(info, dict):
                continue

            tid = str(info.get("thread_id", "")).strip()
            title = _clean_thread_title(str(info.get("title", "")))
            if not tid or not title or tid in seen:
                continue

            seen.add(tid)
            normalized.append(
                {
                    "tid": tid,
                    "title": title,
                    "url": f"https://tieba.baidu.com/p/{tid}",
                    "cover_image_url": str(info.get("media_pic_url", "") or info.get("media_thumbnail_url", "")).strip(),
                }
            )
        return normalized

    async def _load_thread_data(self, page: Page, url: str) -> dict[str, object]:
        try:
            async with page.expect_response(
                lambda response: "tieba.baidu.com/c/f/pb/page_pc" in response.url,
                timeout=20_000,
            ) as response_info:
                await self._goto(page, url)
            response = await response_info.value
            raw = await response.text()
            data = json.loads(raw)
        except Exception as exc:
            raise TiebaServiceError(f"帖子详情接口解析失败：{exc}") from exc

        title = _clean_text(await page.title())
        content = _clean_text(await page.content(), limit=10_000)
        current_url = _clean_text(page.url)
        if self._is_challenge_page(title, content, current_url):
            raise TiebaLoginRequiredError("帖子详情页命中百度安全验证，需要人工续签登录态")
        if int(data.get("error_code", 0) or 0) != 0:
            raise TiebaServiceError(
                f"帖子详情接口返回异常：error_code={data.get('error_code')} {data.get('error_msg', '')}"
            )
        return data

    def _extract_urls_from_content(self, content_items: list[dict[str, object]]) -> tuple[str, list[str]]:
        text_parts: list[str] = []
        image_urls: list[str] = []
        seen_images: set[str] = set()

        for item in content_items:
            if not isinstance(item, dict):
                continue
            item_type = int(item.get("type", -1) or -1)
            text_value = str(item.get("text", "")).strip()
            if item_type in {0, 1, 4} and text_value:
                text_parts.append(text_value)

            candidates = [
                str(item.get("origin_src", "")).strip(),
                str(item.get("src", "")).strip(),
                str(item.get("link", "")).strip(),
            ]
            for candidate in candidates:
                if not candidate or not candidate.startswith(("http://", "https://")):
                    continue
                lowered = candidate.lower()
                if any(marker in lowered for marker in ["portrait", "icon", "avatar", "emoticon", "ares.cdn.bcebos.com"]):
                    continue
                if candidate in seen_images:
                    continue
                if item_type in {3, 5} or any(ext in lowered for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]):
                    seen_images.add(candidate)
                    image_urls.append(candidate)

        return _clean_text(" ".join(text_parts), limit=1200), image_urls

    def _extract_thread_detail_from_data(self, data: dict[str, object], fallback_title: str) -> TiebaThread | None:
        thread = data.get("thread", {})
        first_floor = data.get("first_floor", {})
        if not isinstance(thread, dict) or not isinstance(first_floor, dict):
            return None

        tid = str(thread.get("id", "")).strip() or str(
            thread.get("origin_thread_info", {}).get("tid", "")
        ).strip()
        if not tid:
            return None

        title = _clean_thread_title(str(thread.get("title", "")) or fallback_title) or fallback_title
        thread_url = str(thread.get("thread_share_link", "")).strip() or f"https://tieba.baidu.com/p/{tid}"

        author_name = _clean_text(
            str(thread.get("author", {}).get("name_show", ""))
            or str(thread.get("author", {}).get("name", ""))
            or str(thread.get("origin_thread_info", {}).get("author", {}).get("name_show", ""))
            or str(thread.get("origin_thread_info", {}).get("author", {}).get("name", "")),
            limit=80,
        )

        content_items = first_floor.get("content", [])
        if not isinstance(content_items, list):
            content_items = []
        main_post_text, image_urls = self._extract_urls_from_content(content_items)

        if not main_post_text:
            origin_content = thread.get("origin_thread_info", {}).get("content", [])
            if isinstance(origin_content, list):
                main_post_text, fallback_images = self._extract_urls_from_content(origin_content)
                if fallback_images:
                    image_urls = fallback_images + image_urls

        video_info = thread.get("video_info", {})
        if isinstance(video_info, dict):
            for key in ["thumbnail_url", "small_thumbnail_url", "first_frame_thumbnail"]:
                candidate = str(video_info.get(key, "")).strip()
                if candidate and candidate not in image_urls:
                    image_urls.insert(0, candidate)
                    break

        share_image = str(thread.get("t_share_img", "")).strip()
        if share_image and share_image not in image_urls:
            image_urls.append(share_image)

        deduped_images: list[str] = []
        seen_images: set[str] = set()
        for url in image_urls:
            normalized = url.strip()
            if not normalized or normalized in seen_images:
                continue
            seen_images.add(normalized)
            deduped_images.append(normalized)

        cover_image_url = deduped_images[0] if deduped_images else ""
        return TiebaThread(
            tid=tid,
            title=title,
            thread_url=thread_url,
            author_name=author_name,
            main_post_text=main_post_text,
            cover_image_url=cover_image_url,
            image_urls=deduped_images[:10],
        )

    async def _collect_threads(self) -> list[TiebaThread]:
        if not self._playwright_ready():
            raise TiebaServiceError("未安装 Playwright，无法启动贴吧采集")

        async with async_playwright() as playwright:
            launch_kwargs: dict[str, object] = {
                "headless": self.config.browser_headless,
            }
            if self.config.browser_channel:
                launch_kwargs["channel"] = self.config.browser_channel
            browser = await playwright.chromium.launch(**launch_kwargs)
            try:
                context = await browser.new_context(storage_state=self._get_storage_state_arg())
                page = await context.new_page()
                forum_feed_data = await self._load_forum_feed_data(page)
                links = self._extract_forum_links(forum_feed_data)
                if not links:
                    raise TiebaServiceError("未在贴吧首页提取到帖子链接，请先完成登录并确认页面可正常打开")

                selected_links = links[: self.config.detail_fetch_limit]
                threads: list[TiebaThread] = []
                for item in selected_links:
                    detail_page = await context.new_page()
                    try:
                        await self._ensure_accessible_page(
                            detail_page,
                            url=item["url"],
                            label=f"帖子 {item['tid']}",
                        )
                        detail_data = await self._load_thread_data(detail_page, item["url"])
                        detail = self._extract_thread_detail_from_data(detail_data, fallback_title=item["title"])
                        if detail is None:
                            continue
                        if not detail.cover_image_url:
                            detail.cover_image_url = item.get("cover_image_url", "")
                        if detail.cover_image_url and detail.cover_image_url not in detail.image_urls:
                            detail.image_urls.insert(0, detail.cover_image_url)
                        detail.fetched_at = datetime.now(tz=ZoneInfo(BEIJING_TIMEZONE)).timestamp()
                        threads.append(detail)
                    finally:
                        await detail_page.close()
                return threads
            finally:
                await browser.close()

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
                threads = await self._collect_threads()
            except TiebaLoginRequiredError as exc:
                self.store.record_sync_failure(str(exc), login_required=True)
                raise
            except (PlaywrightError, PlaywrightTimeoutError) as exc:
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
        lines.append(f"上次开始：{_format_timestamp(self.store.last_sync_started_at)}")
        lines.append(f"上次完成：{_format_timestamp(self.store.last_sync_completed_at)}")
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
        if not self.config.forum_keyword:
            raise TiebaServiceError("请先在 .env 中设置 TIEBA_FORUM_KEYWORD")
        if not self._playwright_ready():
            raise TiebaServiceError("未安装 Playwright，请先执行 pip install -r requirements.txt")

        async with async_playwright() as playwright:
            launch_kwargs: dict[str, object] = {
                "user_data_dir": str(self.config.profile_dir),
                "headless": False,
            }
            if self.config.browser_channel:
                launch_kwargs["channel"] = self.config.browser_channel
            context = await playwright.chromium.launch_persistent_context(**launch_kwargs)
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                await self._goto(page, self.config.forum_url)
                print("浏览器已打开。请手动完成贴吧登录和任何安全验证，然后回到终端按回车继续。")
                await asyncio.to_thread(input, "完成后按回车继续...")
                await self._ensure_accessible_page(
                    page,
                    url=self.config.forum_url,
                    label=f"{self.config.forum_keyword} 吧主页",
                )
                await context.storage_state(path=str(self.config.state_path))
                self.store.login_required = False
                self.store.last_error = ""
                self.store.save()
                print("登录态验证通过，浏览器资料目录已保存。")
                print(f"已导出跨平台登录态：{self.config.state_path}")
            finally:
                await context.close()


tieba_service = TiebaService()
