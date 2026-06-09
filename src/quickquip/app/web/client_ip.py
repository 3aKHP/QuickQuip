"""Shared helper to resolve the real client IP from a FastAPI request.

Sits behind a Docker bridge (request.client.host is always the gateway). When
the direct peer is a private / loopback address this helper trusts the
leftmost X-Forwarded-For value; otherwise it returns the direct TCP peer IP.
"""

from fastapi import Request

_TRUSTED_PREFIXES = ("127.", "::1", "10.", "172.", "192.168.")


def get_client_ip(request: Request) -> str:
    direct_ip = request.client.host if request.client else ""
    if direct_ip and any(direct_ip.startswith(p) for p in _TRUSTED_PREFIXES):
        forwarded_for = request.headers.get("x-forwarded-for", "")
        if forwarded_for:
            candidate = forwarded_for.split(",")[0].strip()
            if candidate and "\n" not in candidate and "\r" not in candidate:
                return candidate
    return direct_ip
