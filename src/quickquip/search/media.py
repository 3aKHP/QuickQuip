"""Bounded retrieval of untrusted search-result images using pinned public IPs."""

from __future__ import annotations

import asyncio
import base64
import ipaddress
from io import BytesIO
import warnings

from PIL import Image
import re
import socket
from urllib.parse import urlsplit

import httpx

MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def validate_image(data: bytes, mime: str) -> tuple[bytes, str]:
    if mime not in ALLOWED_MIME or not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("不支持的图片格式或大小")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.width * image.height > 20_000_000:
                    raise ValueError("图片像素数过大")
                actual = Image.MIME.get(image.format or "", "")
                if actual not in ALLOWED_MIME:
                    raise ValueError("不支持的图片格式")
                image.verify()
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise ValueError("图片像素数过大") from exc
    return data, actual


def image_urls(text: str, results: list[dict]) -> list[str]:
    urls = []
    for row in results:
        for key in ("image_url", "thumbnail_url"):
            value = row.get(key)
            if isinstance(value, str) and value:
                urls.append(value)
    urls.extend(re.findall(r"Image URL:\s*(https?://[^\s#]+)", text))
    return list(dict.fromkeys(urls))[:3]


async def fetch_image(url: str) -> tuple[bytes, str]:
    """Never send provider credentials, follow unchecked redirects or resolve twice."""
    async with asyncio.timeout(20):
        if url.startswith("data:image/"):
            header, encoded = url.split(",", 1)
            if ";base64" not in header or len(encoded) > MAX_IMAGE_BYTES * 2:
                raise ValueError("图片数据格式或大小无效")
            data = base64.b64decode(encoded, validate=True)
            if len(data) > MAX_IMAGE_BYTES:
                raise ValueError("图片过大")
            return await asyncio.to_thread(validate_image, data, header[5:].split(";")[0])
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            for _ in range(4):
                parts = urlsplit(url)
                if (
                    parts.scheme not in {"https", "http"}
                    or not parts.hostname
                    or parts.username
                    or parts.password
                    or parts.port not in (None, 80, 443)
                ):
                    raise ValueError("不支持的图片地址")
                port = parts.port or (443 if parts.scheme == "https" else 80)
                addresses = await asyncio.get_running_loop().getaddrinfo(
                    parts.hostname,
                    port,
                    type=socket.SOCK_STREAM,
                )
                ips = [row[4][0] for row in addresses]
                if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
                    raise ValueError("图片地址必须使用公网 IP")
                ips.sort(key=lambda ip: ipaddress.ip_address(ip).version)
                pinned = httpx.URL(url).copy_with(host=ips[0])
                async with client.stream(
                    "GET",
                    pinned,
                    headers={"host": parts.netloc},
                    extensions={"sni_hostname": parts.hostname},
                ) as response:
                    if response.is_redirect:
                        url = str(httpx.URL(url).join(response.headers["location"]))
                        continue
                    response.raise_for_status()
                    mime = response.headers.get("content-type", "").split(";")[0]
                    if mime not in ALLOWED_MIME:
                        raise ValueError("搜索媒体不是支持的图片格式")
                    chunks = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_IMAGE_BYTES:
                            raise ValueError("图片过大")
                        chunks.append(chunk)
                    return await asyncio.to_thread(validate_image, b"".join(chunks), mime)
            raise ValueError("图片重定向次数过多")
