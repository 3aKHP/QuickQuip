"""Search media uses public pinned destinations and bounded validated images."""

import asyncio
import base64
from io import BytesIO
import socket
from unittest.mock import AsyncMock

import httpx
from PIL import Image
import pytest

from quickquip.search.media import fetch_image


def png():
    buffer = BytesIO()
    Image.new("RGB", (1, 1)).save(buffer, format="PNG")
    return buffer.getvalue()


async def test_data_image_is_decoded_and_verified():
    data = png()
    result, mime = await fetch_image("data:image/png;base64," + base64.b64encode(data).decode())
    assert result == data and mime == "image/png"
    with pytest.raises(ValueError):
        await fetch_image("data:image/svg+xml;base64,PHN2Zy8+")


async def test_remote_image_pins_public_ip_and_preserves_tls_hostname(monkeypatch):
    original = httpx.AsyncClient
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "image/png"}, content=png())

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(
            transport=httpx.MockTransport(handler),
            **kw,
        ),
    )
    monkeypatch.setattr(
        asyncio.get_running_loop(),
        "getaddrinfo",
        AsyncMock(
            return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            ]
        ),
    )
    await fetch_image("https://images.example/image.png")
    assert seen[0].url.host == "93.184.216.34"
    assert seen[0].headers["host"] == "images.example"
    assert seen[0].extensions["sni_hostname"] == "images.example"
    assert "authorization" not in seen[0].headers


async def test_private_redirect_is_rejected_before_second_http_attempt(monkeypatch):
    original = httpx.AsyncClient
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"location": "http://private.example/secret"})

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(
            transport=httpx.MockTransport(handler),
            **kw,
        ),
    )
    monkeypatch.setattr(
        asyncio.get_running_loop(),
        "getaddrinfo",
        AsyncMock(
            side_effect=[
                [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
                [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))],
            ]
        ),
    )
    with pytest.raises(ValueError, match="公网"):
        await fetch_image("https://images.example/image.png")
    assert len(seen) == 1


async def test_decompression_bomb_is_a_normal_media_error(monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 0)
    with pytest.raises(ValueError):
        await fetch_image("data:image/png;base64," + base64.b64encode(png()).decode())
