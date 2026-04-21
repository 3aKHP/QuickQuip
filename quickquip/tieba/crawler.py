from __future__ import annotations

import asyncio
from datetime import datetime
import json
from collections.abc import Callable
from typing import Any
from zoneinfo import ZoneInfo

from quickquip.chat.config import BEIJING_TIMEZONE
from quickquip.tieba.store import TiebaThread
from quickquip.tieba.config import TiebaConfig, clean_text, clean_thread_title
from quickquip.tieba.errors import TiebaLoginRequiredError, TiebaServiceError

try:
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError, async_playwright
except ModuleNotFoundError:
    PlaywrightError = RuntimeError
    PlaywrightTimeoutError = RuntimeError
    Page = Any
    async_playwright = None


PLAYWRIGHT_ERROR_TYPES = (PlaywrightError, PlaywrightTimeoutError)


class TiebaCrawler:
    def __init__(self, config: TiebaConfig):
        self.config = config

    def playwright_ready(self) -> bool:
        return async_playwright is not None

    def get_storage_state_arg(self) -> str | None:
        if self.config.state_path.exists():
            return str(self.config.state_path)
        return None

    def is_challenge_page(self, title: str, content: str, url: str) -> bool:
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

    async def goto(self, page: Page, url: str) -> None:
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(1500)

    async def ensure_accessible_page(self, page: Page, *, url: str, label: str) -> None:
        await self.goto(page, url)
        title = clean_text(await page.title())
        content = clean_text(await page.content(), limit=10_000)
        current_url = clean_text(page.url)
        if self.is_challenge_page(title, content, current_url):
            raise TiebaLoginRequiredError(f"{label} 命中百度安全验证，需要人工续签登录态")

    async def load_forum_feed_data(self, page: Page, forum_keyword: str) -> dict[str, object]:
        try:
            async with page.expect_response(
                lambda response: "tieba.baidu.com/c/f/frs/page_pc" in response.url,
                timeout=20_000,
            ) as response_info:
                await self.goto(page, self.config.get_forum_url(forum_keyword))
            response = await response_info.value
            raw = await response.text()
            data = json.loads(raw)
        except Exception as exc:
            raise TiebaServiceError(f"贴吧首页接口解析失败：{exc}") from exc

        title = clean_text(await page.title())
        content = clean_text(await page.content(), limit=10_000)
        current_url = clean_text(page.url)
        if self.is_challenge_page(title, content, current_url):
            raise TiebaLoginRequiredError(f"{forum_keyword} 吧主页命中百度安全验证，需要人工续签登录态")

        if int(data.get("error_code", 0) or 0) != 0:
            raise TiebaServiceError(
                f"贴吧首页接口返回异常：error_code={data.get('error_code')} {data.get('error_msg', '')}"
            )
        return data

    def extract_forum_links(self, data: dict[str, object]) -> list[dict[str, str]]:
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
            title = clean_thread_title(str(info.get("title", "")))
            if not tid or not title or tid in seen:
                continue

            seen.add(tid)
            normalized.append(
                {
                    "tid": tid,
                    "title": title,
                    "url": f"https://tieba.baidu.com/p/{tid}",
                    "cover_image_url": str(
                        info.get("media_pic_url", "") or info.get("media_thumbnail_url", "")
                    ).strip(),
                }
            )
        return normalized

    async def load_thread_data(self, page: Page, url: str) -> dict[str, object]:
        try:
            async with page.expect_response(
                lambda r: "tieba.baidu.com/c/f/pb/page_pc" in r.url,
                timeout=20_000,
            ) as response_info:
                await self.goto(page, url)
            response = await response_info.value
            data = await response.json()
        except Exception as exc:
            raise TiebaServiceError(f"帖子页面加载失败或未触发详情接口：{exc}") from exc

        if not isinstance(data, dict):
            raise TiebaServiceError(f"帖子详情接口响应格式异常：{url}")

        error_code = int(data.get("error_code", 0) or 0)
        error_msg = str(data.get("error_msg", "") or "")
        if error_code != 0:
            if error_code in {2, 4} or "登录" in error_msg or "登陆" in error_msg:
                raise TiebaLoginRequiredError(
                    f"帖子详情接口需要登录态（error_code={error_code}）：{error_msg}"
                )
            raise TiebaServiceError(
                f"帖子详情接口返回异常：error_code={error_code} {error_msg}"
            )
        return data

    def extract_urls_from_content(self, content_items: list[dict[str, object]]) -> tuple[str, list[str]]:
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

        return clean_text(" ".join(text_parts), limit=1200), image_urls

    def extract_thread_detail_from_data(
        self,
        data: dict[str, object],
        fallback_title: str,
        forum_keyword: str,
    ) -> TiebaThread | None:
        thread = data.get("thread", {})
        first_floor = data.get("first_floor", {})
        if not isinstance(thread, dict) or not isinstance(first_floor, dict):
            return None

        tid = str(thread.get("id", "")).strip() or str(
            thread.get("origin_thread_info", {}).get("tid", "")
        ).strip()
        if not tid:
            return None

        title = clean_thread_title(str(thread.get("title", "")) or fallback_title) or fallback_title
        thread_url = str(thread.get("thread_share_link", "")).strip() or f"https://tieba.baidu.com/p/{tid}"

        author_name = clean_text(
            str(thread.get("author", {}).get("name_show", ""))
            or str(thread.get("author", {}).get("name", ""))
            or str(thread.get("origin_thread_info", {}).get("author", {}).get("name_show", ""))
            or str(thread.get("origin_thread_info", {}).get("author", {}).get("name", "")),
            limit=80,
        )

        content_items = first_floor.get("content", [])
        if not isinstance(content_items, list):
            content_items = []
        main_post_text, image_urls = self.extract_urls_from_content(content_items)

        if not main_post_text:
            origin_content = thread.get("origin_thread_info", {}).get("content", [])
            if isinstance(origin_content, list):
                main_post_text, fallback_images = self.extract_urls_from_content(origin_content)
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
            forum_keyword=forum_keyword,
            author_name=author_name,
            main_post_text=main_post_text,
            cover_image_url=cover_image_url,
            image_urls=deduped_images[:10],
        )

    async def collect_threads(
        self,
        forum_keyword: str,
        on_progress: Callable[[str], None] | None = None,
        limit: int | None = None,
    ) -> list[TiebaThread]:
        if not self.playwright_ready():
            raise TiebaServiceError("未安装 Playwright，无法启动贴吧采集")

        async with async_playwright() as playwright:
            launch_kwargs: dict[str, object] = {
                "headless": self.config.browser_headless,
            }
            if self.config.browser_channel:
                launch_kwargs["channel"] = self.config.browser_channel
            browser = await playwright.chromium.launch(**launch_kwargs)
            try:
                context = await browser.new_context(storage_state=self.get_storage_state_arg())
                page = await context.new_page()
                forum_feed_data = await self.load_forum_feed_data(page, forum_keyword)
                links = self.extract_forum_links(forum_feed_data)
                if not links:
                    raise TiebaServiceError("未在贴吧首页提取到帖子链接，请先完成登录并确认页面可正常打开")

                selected_links = links[: limit if limit is not None else self.config.detail_fetch_limit]
                threads: list[TiebaThread] = []
                for item in selected_links:
                    try:
                        detail_data = await self.load_thread_data(page, item["url"])
                        detail = self.extract_thread_detail_from_data(
                            detail_data,
                            fallback_title=item["title"],
                            forum_keyword=forum_keyword,
                        )
                        if detail is None:
                            continue
                        if not detail.cover_image_url:
                            detail.cover_image_url = item.get("cover_image_url", "")
                        if detail.cover_image_url and detail.cover_image_url not in detail.image_urls:
                            detail.image_urls.insert(0, detail.cover_image_url)
                        detail.fetched_at = datetime.now(tz=ZoneInfo(BEIJING_TIMEZONE)).timestamp()
                        threads.append(detail)
                        if on_progress:
                            img_hint = f" [{len(detail.image_urls)}图]" if detail.image_urls else ""
                            on_progress(f"✓ {detail.title[:30]}{img_hint}")
                    except TiebaLoginRequiredError:
                        raise  # login expiry aborts the entire forum
                    except TiebaServiceError as exc:
                        if on_progress:
                            on_progress(f"✗ 跳过 {item.get('title', item['url'])[:30]}: {exc}")
                        continue  # single-thread failure: skip and try next
                return threads
            finally:
                await browser.close()

    async def interactive_login(self, forum_keyword: str) -> None:
        if not forum_keyword:
            raise TiebaServiceError("请先在 .env 中设置 TIEBA_FORUM_KEYWORD 或 TIEBA_FORUM_KEYWORDS")
        if not self.playwright_ready():
            raise TiebaServiceError("未安装 Playwright，请先执行 pip install -r requirements.txt")

        forum_url = self.config.get_forum_url(forum_keyword)

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
                await self.goto(page, forum_url)
                print("浏览器已打开。请手动完成贴吧登录和任何安全验证，然后回到终端按回车继续。")
                await asyncio.to_thread(input, "完成后按回车继续...")
                await self.ensure_accessible_page(
                    page,
                    url=forum_url,
                    label=f"{forum_keyword} 吧主页",
                )
                await context.storage_state(path=str(self.config.state_path))
            finally:
                await context.close()
