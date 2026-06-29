"""_prepare_image_inputs: per-image fault tolerance and per-request cap."""
from __future__ import annotations

from plugins.llm_config import ProviderConfig
from plugins.llm_provider import BaseProviderClient, LLMImageInput, LLMProviderError
from quickquip.llm.provider.base import MAX_IMAGES_PER_REQUEST


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
