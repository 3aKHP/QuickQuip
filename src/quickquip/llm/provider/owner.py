"""Provider 请求归属（owner）解析与不可逆指纹（§7.1）。

owner 捕获一次成功请求的实际端点、wire model 与协议 profile。API key、
Authorization 与原始 headers 不入库、不入日志、不参与指纹；含敏感路由
参数的 URL 先剔除敏感参数再散列，持久值不可反推原参数。
"""
from __future__ import annotations

import hashlib
import json
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from quickquip.llm.agent_records import ResponseOwner
from quickquip.llm.config import ProviderConfig
from quickquip.llm.tools import LLMToolSpec

# URL query 中的敏感参数名（小写）：绝不进入指纹或持久化 owner。
SENSITIVE_QUERY_KEYS = frozenset(
    {"key", "api_key", "apikey", "token", "access_token", "signature", "sig", "auth"}
)

# 影响协议序列化形状的配置面（profile 指纹输入）。stream 开关不参与：
# 流式/非流式必须产生等价 block（§4.4），不构成 profile 差异。
_PROFILE_FIELDS = ("protocol", "prompt_caching", "cache_ttl", "auth_method", "builtin_search")


def normalize_endpoint(url: str) -> str:
    """规范化端点：scheme/host/path + 排序后的非敏感 query 参数。"""
    try:
        split = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    query = sorted(
        (key, value)
        for key, value in parse_qsl(split.query, keep_blank_values=True)
        if key.lower() not in SENSITIVE_QUERY_KEYS
    )
    return urlunsplit(
        (split.scheme.lower(), split.netloc.lower(), split.path, urlencode(query), "")
    )


def _short_digest(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def endpoint_fingerprint(url: str) -> str:
    return _short_digest(f"endpoint:{normalize_endpoint(url)}")


def profile_fingerprint(config: ProviderConfig) -> str:
    parts = [f"{field}={getattr(config, field, None)!r}" for field in _PROFILE_FIELDS]
    return _short_digest(f"profile:{'|'.join(parts)}")


def resolve_wire_model(config: ProviderConfig, request_model: str) -> str:
    """实际 wire model：extra_body 的 model 覆盖优先（§7.3）。

    禁止 owner 记录 model A 而最终请求被 extra_body 改为 model B——
    序列化端把 extra_body update 到 payload 之后，此函数与最终 payload
    的 model 字段同源。
    """
    override = config.extra_body.get("model") if config.extra_body else None
    return str(override) if isinstance(override, str) and override.strip() else request_model


def build_response_owner(
    config: ProviderConfig, url: str, request_model: str
) -> ResponseOwner:
    """从实际成功的端点构造 owner（只含不可逆指纹与非敏感元数据）。"""
    return ResponseOwner(
        provider_id=config.id,
        protocol=config.protocol,
        wire_model=resolve_wire_model(config, request_model),
        display_model=request_model,
        endpoint_fingerprint=endpoint_fingerprint(url),
        profile_fingerprint=profile_fingerprint(config),
    )


def primary_endpoint_url(config: ProviderConfig, model: str) -> str:
    """主端点 URL（与各 client 的 _build_request_parts 同构）。

    供历史投影在请求前构造目标 owner；敏感 query（gemini 的 key）不参与
    指纹，可省略。
    """
    base = config.base_url.rstrip("/")
    if config.protocol == "openai":
        return f"{base}/chat/completions"
    if config.protocol == "claude":
        return f"{base}/messages?beta=true"
    return f"{base}/models/{model}:generateContent"


def tools_schema_fingerprint(specs: list[LLMToolSpec]) -> str:
    """工具 schema 指纹（§7.1：单独记录，参与 epoch projection profile）。"""
    payload = [
        {"name": spec.name, "description": spec.description, "schema": spec.input_schema}
        for spec in specs
    ]
    return _short_digest(f"tools:{json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


def owner_matches(stored: dict | None, target: ResponseOwner | None) -> bool:
    """owner 精确匹配（§7.2）：五元组全等才允许原生路径。"""
    if stored is None or target is None:
        return False
    if not isinstance(stored, dict):
        return False
    return (
        stored.get("provider_id") == target.provider_id
        and stored.get("protocol") == target.protocol
        and stored.get("wire_model") == target.wire_model
        and stored.get("endpoint_fingerprint") == target.endpoint_fingerprint
        and stored.get("profile_fingerprint") == target.profile_fingerprint
    )
