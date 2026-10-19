"""Shared helper to resolve the real client IP from a FastAPI request.

Sits behind a Docker bridge or nginx reverse proxy (request.client.host is
then always the gateway / loopback). When the direct peer is a private or
loopback address this helper walks the X-Forwarded-For chain right-to-left
and takes the rightmost untrusted hop: proxies append the peer they saw, so
the first non-private entry from the right is the real client even when the
client itself prepended a spoofed XFF value. A public direct peer means no
trusted proxy is in the path, and XFF is ignored entirely.
"""

import ipaddress

from fastapi import Request


def _is_trusted_proxy(ip_text: str) -> bool:
    try:
        address = ipaddress.ip_address(ip_text)
    except ValueError:
        return False
    return address.is_private or address.is_loopback


def get_client_ip(request: Request) -> str:
    direct_ip = request.client.host if request.client else ""
    if not direct_ip or not _is_trusted_proxy(direct_ip):
        return direct_ip
    forwarded_for = request.headers.get("x-forwarded-for", "")
    for hop in reversed(forwarded_for.split(",")):
        candidate = hop.strip()
        if not candidate or "\n" in candidate or "\r" in candidate:
            continue
        if not _is_trusted_proxy(candidate):
            return candidate
    return direct_ip
