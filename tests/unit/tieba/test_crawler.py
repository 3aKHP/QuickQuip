"""Tieba crawler tests.

Pure-Python helpers (is_challenge_page, extract_urls_from_content) run in the
default suite. Browser-driving tests are marked @pytest.mark.playwright and
skipped unless invoked explicitly (pytest -m playwright).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from filelock import FileLock

from plugins.tieba_service import TiebaConfig
from quickquip.tieba.crawler import TiebaCrawler
from quickquip.tieba.errors import TiebaServiceError


@pytest.fixture
def crawler(tmp_path: Path) -> TiebaCrawler:
    config = TiebaConfig(
        enabled=True,
        sync_interval_seconds=900,
        max_pool_size=240,
        recent_sent_limit=30,
        detail_fetch_limit=18,
        random_avoid_recent=10,
        prefer_image_threads=True,
        browser_headless=True,
        browser_channel="",
        profile_dir=tmp_path / "profile",
        crawler_profile_dir=tmp_path / "crawler_profile",
        state_path=tmp_path / "storage_state.json",
        store_path=tmp_path / "pool.json",
        forum_keyword="测试",
        forum_keywords=("测试",),
    )
    return TiebaCrawler(config)


class TestIsChallengePage:
    def test_recognizes_captcha_markers(self, crawler: TiebaCrawler):
        assert crawler.is_challenge_page("百度安全验证", "", "") is True
        assert crawler.is_challenge_page("", "请完成 seccaptcha 验证", "") is True
        assert crawler.is_challenge_page("", "", "https://.../bioc_options") is True
        assert crawler.is_challenge_page("账号安全", "", "") is True
        assert crawler.is_challenge_page("", "", "访问受限") is True

    def test_normal_page_not_flagged(self, crawler: TiebaCrawler):
        assert crawler.is_challenge_page("测试吧", "正常内容", "https://tieba.baidu.com/f?kw=测试") is False


class TestExtractUrlsFromContent:
    def test_collects_text_and_images(self, crawler: TiebaCrawler):
        items = [
            {"type": 1, "text": "楼主说了几句话"},
            {"type": 3, "origin_src": "https://example.com/a.jpg"},
            {"type": 5, "src": "https://example.com/b.png"},
        ]
        text, images = crawler.extract_urls_from_content(items)
        assert "楼主说了几句话" in text
        assert images == ["https://example.com/a.jpg", "https://example.com/b.png"]

    def test_filters_portrait_and_emoticons(self, crawler: TiebaCrawler):
        items = [
            {"type": 3, "origin_src": "https://tb.himg.baidu.com/sys/portrait/item/abc"},
            {"type": 3, "origin_src": "https://example.com/emoticon/1.png"},
            {"type": 3, "origin_src": "https://example.com/real.jpg"},
        ]
        _, images = crawler.extract_urls_from_content(items)
        assert images == ["https://example.com/real.jpg"]

    def test_deduplicates_identical_urls(self, crawler: TiebaCrawler):
        items = [
            {"type": 3, "origin_src": "https://example.com/dup.jpg"},
            {"type": 3, "src": "https://example.com/dup.jpg"},
        ]
        _, images = crawler.extract_urls_from_content(items)
        assert images == ["https://example.com/dup.jpg"]

    def test_ignores_non_http_urls(self, crawler: TiebaCrawler):
        items = [{"type": 3, "origin_src": "data:image/png;base64,AAA"}]
        _, images = crawler.extract_urls_from_content(items)
        assert images == []


@pytest.mark.playwright
async def test_collect_threads_against_live_tieba(crawler: TiebaCrawler):
    """Requires Playwright browsers installed and network access. Placeholder.

    Invoke explicitly with: pytest -m playwright tests/unit/tieba/test_crawler.py
    """
    pytest.skip("live browser smoke test — implement against a staged fixture when needed")


async def test_collect_threads_fails_when_profile_locked(
    crawler: TiebaCrawler, monkeypatch
) -> None:
    """While the browser lock is held by another instance, collect_threads fails
    fast instead of opening a second Chromium against the same persistent profile.

    Guards the shared-user_data_dir regression: bot and web-admin (or a concurrent
    in-process caller) must not launch Chromium simultaneously against the same
    profile dir (issue #80, PR #92 review).
    """
    monkeypatch.setattr(crawler, "playwright_ready", lambda: True)
    held = FileLock(crawler._browser_lock_path)
    held.acquire(timeout=0)
    try:
        with pytest.raises(TiebaServiceError, match="采集进行中"):
            await crawler.collect_threads("测试")
    finally:
        held.release()


async def test_collect_threads_launch_kwargs_omit_storage_state_and_inject_cookies(
    crawler: TiebaCrawler, monkeypatch
) -> None:
    """launch_persistent_context must NOT receive storage_state (it raises
    TypeError — the v1.10.1 bug); cookies from storage_state.json must be
    injected via add_cookies instead."""
    cookies = [{"name": "BDUSS", "value": "x", "domain": "tieba.baidu.com", "path": "/"}]
    crawler.config.state_path.parent.mkdir(parents=True, exist_ok=True)
    crawler.config.state_path.write_text(
        json.dumps({"cookies": cookies, "origins": []}), encoding="utf-8"
    )

    captured: dict = {}
    mock_context = AsyncMock()
    mock_context.pages = []
    mock_context.new_page = AsyncMock(return_value=AsyncMock())

    def _capture(**kwargs):
        captured.update(kwargs)
        return mock_context

    mock_playwright = MagicMock()
    mock_playwright.chromium.launch_persistent_context = AsyncMock(side_effect=_capture)

    class _FakeAsyncPlaywright:
        async def __aenter__(self):
            return mock_playwright

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr("quickquip.tieba.crawler.async_playwright", _FakeAsyncPlaywright)
    # empty feed -> extract_forum_links returns [] -> raises before any crawling,
    # but only after cookies are injected
    monkeypatch.setattr(
        crawler, "load_forum_feed_data", AsyncMock(return_value={"page_data": {"feed_list": []}})
    )

    with pytest.raises(TiebaServiceError, match="未在贴吧首页提取到帖子链接"):
        await crawler.collect_threads("测试")

    assert "storage_state" not in captured
    assert captured["user_data_dir"] == str(crawler.config.crawler_profile_dir)
    assert any("disk-cache-size" in a for a in captured["args"])
    mock_context.add_cookies.assert_awaited_once_with(cookies)


async def test_collect_threads_skips_add_cookies_when_no_state_file(
    crawler: TiebaCrawler, monkeypatch
) -> None:
    """When storage_state.json is absent, add_cookies is not called."""
    assert not crawler.config.state_path.exists()

    mock_context = AsyncMock()
    mock_context.pages = []
    mock_context.new_page = AsyncMock(return_value=AsyncMock())
    mock_playwright = MagicMock()
    mock_playwright.chromium.launch_persistent_context = AsyncMock(return_value=mock_context)

    class _FakeAsyncPlaywright:
        async def __aenter__(self):
            return mock_playwright

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr("quickquip.tieba.crawler.async_playwright", _FakeAsyncPlaywright)
    monkeypatch.setattr(
        crawler, "load_forum_feed_data", AsyncMock(return_value={"page_data": {"feed_list": []}})
    )

    with pytest.raises(TiebaServiceError, match="未在贴吧首页提取到帖子链接"):
        await crawler.collect_threads("测试")

    mock_context.add_cookies.assert_not_awaited()
