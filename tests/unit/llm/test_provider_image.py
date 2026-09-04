"""_prepare_image_inputs: per-image fault tolerance and per-request cap."""
from __future__ import annotations

from plugins.llm_config import ProviderConfig
from plugins.llm_provider import BaseProviderClient, LLMImageInput, LLMProviderError
from quickquip.llm.provider.base import _IMAGE_CACHE_MAX_ENTRIES, MAX_IMAGES_PER_REQUEST


def _make_config(**overrides) -> ProviderConfig:
    defaults = dict(
        id="test",
        protocol="openai",
        base_url="http://test",
        api_key_env="TEST_KEY",
        default_model="m",
        models=["m"],
    )
    defaults.update(overrides)
    return ProviderConfig(**defaults)


def _img(url: str) -> LLMImageInput:
    return LLMImageInput(source_url=url, media_type="image/png", data_base64="AA==")


async def test_prepare_image_inputs_skips_failed_downloads(monkeypatch):
    # A single stale/404 URL (common for QQ CDN links in the recent buffer)
    # must not sink the whole request.
    client = BaseProviderClient(_make_config())

    async def fake_download(url):
        if url == "bad.png":
            raise LLMProviderError("图片下载失败：HTTP 404")
        return _img(url)

    monkeypatch.setattr(client, "_download_image", fake_download)
    result = await client._prepare_image_inputs(["good1.png", "bad.png", "good2.png"])
    assert [r.source_url for r in result] == ["good1.png", "good2.png"]


async def test_prepare_image_inputs_caps_at_max(monkeypatch):
    # More URLs than MAX_IMAGES_PER_REQUEST are truncated before download.
    client = BaseProviderClient(_make_config())

    downloaded: list[str] = []

    async def fake_download(url):
        downloaded.append(url)
        return _img(url)

    monkeypatch.setattr(client, "_download_image", fake_download)
    urls = [f"img{i}.png" for i in range(MAX_IMAGES_PER_REQUEST + 3)]
    result = await client._prepare_image_inputs(urls)
    assert len(result) == MAX_IMAGES_PER_REQUEST
    assert len(downloaded) == MAX_IMAGES_PER_REQUEST


async def test_download_image_cached_across_prepare_calls(monkeypatch):
    # 工具循环逐轮重建请求会反复序列化同一批 URL：第二次 prepare 不再下载。
    client = BaseProviderClient(_make_config())

    downloaded: list[str] = []

    async def fake_uncached(url):
        downloaded.append(url)
        return _img(url)

    monkeypatch.setattr(client, "_download_image_uncached", fake_uncached)
    first = await client._prepare_image_inputs(["a.png"])
    second = await client._prepare_image_inputs(["a.png"])
    assert downloaded == ["a.png"]
    assert first[0] is second[0]


async def test_download_image_failure_not_cached(monkeypatch):
    # 失败不进门：先 404 后成功 = 两次真实下载，错误不被缓存掩盖。
    client = BaseProviderClient(_make_config())

    calls: list[str] = []

    async def fake_uncached(url):
        calls.append(url)
        if len(calls) == 1:
            raise LLMProviderError("图片下载失败：HTTP 404", status_code=404)
        return _img(url)

    monkeypatch.setattr(client, "_download_image_uncached", fake_uncached)
    assert await client._prepare_image_inputs(["a.png"]) == []  # 失败被 prepare 跳过
    result = await client._prepare_image_inputs(["a.png"])
    assert calls == ["a.png", "a.png"]
    assert [r.source_url for r in result] == ["a.png"]


async def test_download_image_ttl_expiry_refetches(monkeypatch):
    # 过期条目惰性失效：白盒把时间戳回溯到 TTL 之前 → 重新下载。
    # 注意必须相对当前 monotonic 回溯（CI 是全新 VM，开机不足 600s 时
    # 绝对值 0.0 仍在 TTL 窗口内）
    import time

    client = BaseProviderClient(_make_config())

    downloaded: list[str] = []

    async def fake_uncached(url):
        downloaded.append(url)
        return _img(url)

    monkeypatch.setattr(client, "_download_image_uncached", fake_uncached)
    first = await client._prepare_image_inputs(["a.png"])
    client._image_cache["a.png"] = (time.monotonic() - 601.0, first[0])
    second = await client._prepare_image_inputs(["a.png"])
    assert downloaded == ["a.png", "a.png"]
    assert second[0] is not first[0]


async def test_download_image_lru_eviction(monkeypatch):
    # 容量兜底：超出 32 条逐出最旧，再取被逐 URL 触发第二次下载。
    client = BaseProviderClient(_make_config())

    downloaded: list[str] = []

    async def fake_uncached(url):
        downloaded.append(url)
        return _img(url)

    monkeypatch.setattr(client, "_download_image_uncached", fake_uncached)
    for i in range(_IMAGE_CACHE_MAX_ENTRIES + 1):
        await client._prepare_image_inputs([f"img{i}.png"])
    assert len(client._image_cache) == _IMAGE_CACHE_MAX_ENTRIES
    assert "img0.png" not in client._image_cache
    await client._prepare_image_inputs(["img0.png"])
    assert downloaded.count("img0.png") == 2
