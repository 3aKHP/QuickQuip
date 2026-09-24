"""epoch_snapshot action 的快照装配（只读导出，不触发任何纪元判定）。

Web Admin 经 action queue 请 bot 进程执行 ``epoch_snapshot``，本模块把
EpochManager 进程内真值组装成可 JSON 化的 dict：锚点全量、每键窗口
行数/token（与 usage 计量同口径）、生效 EpochParams（provider 覆盖合并
后的值）、history_limit 覆盖态与最近一封信封的六段分解。

单键/单 scope 的读取失败只降级该键字段，不让整个快照失败。
"""

from __future__ import annotations

import logging
import time

from quickquip.llm.epoch import DEFAULT_EPOCH_MAX_ROWS, estimate_rows_budget

logger = logging.getLogger(__name__)


def _scope_parts(scope_key: str) -> tuple[str, str]:
    if scope_key.startswith("private:"):
        return scope_key.removeprefix("private:"), "private"
    return scope_key, "group"


def _epoch_params_dict(svc, provider_id: str) -> dict[str, int] | None:
    try:
        provider = svc.config.providers.get(provider_id)
        params = svc.config.resolve_epoch_params(provider)
    except Exception:
        logger.warning(
            "epoch snapshot params resolve failed provider=%s", provider_id, exc_info=True
        )
        return None
    return {
        "context_tokens": params.context_tokens,
        "cold_idle_seconds": params.cold_idle_seconds,
        "cold_target_tokens": params.cold_target_tokens,
        "cold_trigger_tokens": params.cold_trigger_tokens,
        "hot_target_tokens": params.hot_target_tokens,
        "cap_tokens": params.cap_tokens,
    }


def build_epoch_snapshot(svc) -> dict[str, object]:
    generated_at = time.time()
    store = getattr(svc, "store", None)
    keys_out: list[dict[str, object]] = []
    history_limits: dict[str, int | None] = {}

    for entry in svc._epochs.snapshot():
        item: dict[str, object] = dict(entry)
        item["idle_seconds"] = max(0.0, generated_at - float(entry["last_activity_at"]))
        item["params"] = _epoch_params_dict(svc, str(entry["provider_id"]))

        scope_key = str(entry["scope_key"])
        if scope_key not in history_limits:
            try:
                chat_id, chat_type = _scope_parts(scope_key)
                history_limits[scope_key] = svc.get_chat_settings(
                    chat_id, chat_type
                ).history_limit
            except Exception:
                history_limits[scope_key] = None
        item["history_limit"] = history_limits[scope_key]

        window_rows: int | None = None
        window_tokens: int | None = None
        if store is not None:
            try:
                rows = store.list_conversation_messages_since(
                    scope_key, int(entry["anchor_id"]), limit=DEFAULT_EPOCH_MAX_ROWS
                )
                window_rows = len(rows)
                window_tokens = estimate_rows_budget(rows)
            except Exception:
                logger.warning(
                    "epoch snapshot window read failed scope=%s", scope_key, exc_info=True
                )
        item["window_rows"] = window_rows
        item["window_tokens"] = window_tokens
        keys_out.append(item)

    try:
        envelopes = svc._envelope_cache.export()
    except Exception:
        envelopes = []

    return {"generated_at": generated_at, "keys": keys_out, "envelopes": envelopes}
