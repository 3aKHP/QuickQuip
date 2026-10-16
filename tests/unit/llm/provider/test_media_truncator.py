"""内联媒体载荷单副本存储的单元测试（issue #291）。

覆盖：裸 base64 与 data URI 两种检测形态、嵌套 ``\\"`` 转义边界、畸形
输入原样保留、``min_bytes`` 门槛、同内容去重、回拼双重校验、GC 引用
集合与保守带、环境开关。
"""

from __future__ import annotations

import base64
import json

import pytest

from quickquip.llm.provider.media_truncator import (
    MediaBlobStore,
    MediaTruncator,
    collect_manifest_shas,
    decode_payload,
    find_manifest_mime,
    resolve_min_bytes,
)

_MIN_BYTES = 1024


def _truncator(tmp_path, *, min_bytes: int = _MIN_BYTES) -> MediaTruncator:
    return MediaTruncator(MediaBlobStore(tmp_path / "blobs"), min_bytes=min_bytes)


def _text(payload: str, prefix: str = "") -> str:
    return '{"image": "' + prefix + payload + '"}'


def test_bare_base64_is_replaced_and_restores_byte_identically(tmp_path):
    truncator = _truncator(tmp_path)
    payload = "A" * 2000
    original = _text(payload)

    outcome = truncator.truncate(original)

    assert outcome.manifest is not None
    assert payload not in outcome.text
    assert outcome.saved_bytes > 0
    assert json.loads(outcome.text)["image"].startswith("[qq:blob sha256=")
    assert truncator.restore(outcome.text, outcome.manifest) == original


def test_data_uri_mime_is_captured(tmp_path):
    truncator = _truncator(tmp_path)
    payload = "B" * 2000
    original = _text(payload, "data:image/png;base64,")

    outcome = truncator.truncate(original)

    assert outcome.manifest is not None
    assert outcome.manifest["splices"][0]["mime"] == "image/png"
    assert truncator.restore(outcome.text, outcome.manifest) == original


def test_payload_below_threshold_is_kept_as_is(tmp_path):
    truncator = _truncator(tmp_path)
    original = _text("C" * 200)

    outcome = truncator.truncate(original)

    assert outcome.manifest is None
    assert outcome.text == original


def test_unterminated_string_is_kept_as_is(tmp_path):
    truncator = _truncator(tmp_path)
    original = '{"image": "' + "D" * 2000

    outcome = truncator.truncate(original)

    assert outcome.manifest is None
    assert outcome.text == original


def test_nested_escaped_json_payload_is_replaced(tmp_path):
    truncator = _truncator(tmp_path)
    payload = "E" * 2000
    original = '{"body": "{\\"image\\": \\"data:image/jpeg;base64,' + payload + '\\"}"}'

    outcome = truncator.truncate(original)

    assert outcome.manifest is not None
    assert payload not in outcome.text
    assert outcome.manifest["splices"][0]["mime"] == "image/jpeg"
    assert isinstance(json.loads(outcome.text), dict)
    assert truncator.restore(outcome.text, outcome.manifest) == original


def test_same_payload_is_stored_once(tmp_path):
    truncator = _truncator(tmp_path)
    payload = "F" * 2000
    original = '{"a": "' + payload + '", "b": "' + payload + '"}'

    outcome = truncator.truncate(original)

    splices = outcome.manifest["splices"]
    assert len(splices) == 2
    assert splices[0]["sha256"] == splices[1]["sha256"]
    blob_dir = truncator.blob_store.path_for(splices[0]["sha256"]).parent
    assert len(list(blob_dir.glob("*.b64"))) == 1
    assert truncator.restore(outcome.text, outcome.manifest) == original


def test_splice_offsets_point_at_placeholders(tmp_path):
    truncator = _truncator(tmp_path)
    original = '{"a": "' + "L" * 2000 + '", "b": "' + "M" * 2000 + '"}'

    outcome = truncator.truncate(original)

    assert len(outcome.manifest["splices"]) == 2
    for splice in outcome.manifest["splices"]:
        segment = outcome.text[splice["offset"]:splice["offset"] + splice["span"]]
        assert segment.startswith("[qq:blob sha256=")
        assert segment.endswith("]")


def test_placeholder_needs_no_json_escaping(tmp_path):
    truncator = _truncator(tmp_path)

    outcome = truncator.truncate(_text("K" * 2000))

    placeholder = json.loads(outcome.text)["image"]
    assert placeholder.endswith("]")
    assert '"' not in placeholder
    assert "\\" not in placeholder


def test_restore_rejects_tampered_text(tmp_path):
    truncator = _truncator(tmp_path)
    outcome = truncator.truncate(_text("G" * 2000))

    with pytest.raises(ValueError):
        truncator.restore(outcome.text.replace("bytes=", "bytes  =", 1), outcome.manifest)


def test_restore_rejects_tampered_blob(tmp_path):
    truncator = _truncator(tmp_path)
    outcome = truncator.truncate(_text("H" * 2000))
    digest = outcome.manifest["splices"][0]["sha256"]
    truncator.blob_store.path_for(digest).write_text("tampered", encoding="utf-8")

    with pytest.raises(ValueError):
        truncator.restore(outcome.text, outcome.manifest)


def test_disabled_truncator_never_touches_text(tmp_path):
    truncator = _truncator(tmp_path, min_bytes=0)
    original = _text("I" * 5000)

    outcome = truncator.truncate(original)

    assert outcome.manifest is None
    assert outcome.text == original


def test_manifest_helpers_accept_field_and_wrapped_shapes(tmp_path):
    truncator = _truncator(tmp_path)
    outcome = truncator.truncate(_text("J" * 2000, "data:image/webp;base64,"))
    field_manifest = outcome.manifest
    digest = field_manifest["splices"][0]["sha256"]
    wrapped = {"v": 1, "request": field_manifest}

    assert collect_manifest_shas(json.dumps(field_manifest)) == {digest}
    assert collect_manifest_shas(json.dumps(wrapped)) == {digest}
    assert find_manifest_mime(json.dumps(wrapped), digest) == "image/webp"
    assert collect_manifest_shas("{not json") == set()
    assert find_manifest_mime(None, digest) is None


def test_blob_gc_keeps_referenced_and_respects_grace_band(tmp_path):
    store = MediaBlobStore(tmp_path / "blobs")
    kept, _ = store.store("keep-me")
    dropped, _ = store.store("drop-me")

    assert store.collect_orphaned({kept}, grace_seconds=0) == 1
    assert store.path_for(kept).exists()
    assert not store.path_for(dropped).exists()

    # 保守带内即使无引用也不删：规避「blob 已写入、引用行尚未提交」窗口。
    assert store.collect_orphaned(set(), grace_seconds=3600) == 0
    assert store.path_for(kept).exists()


def test_decode_payload_strips_data_uri_prefix(tmp_path):
    raw = b"\x89PNG\r\n\x1a\npayload"
    encoded = base64.b64encode(raw).decode("ascii")

    assert decode_payload(f"data:image/png;base64,{encoded}") == (raw, "image/png")
    assert decode_payload(encoded) == (raw, "")
    assert decode_payload("AAA") is None


def test_resolve_min_bytes_reads_env_switch():
    assert resolve_min_bytes({}) == 0
    assert resolve_min_bytes({"LLM_TRACE_MEDIA_MIN_BYTES": ""}) == 0
    assert resolve_min_bytes({"LLM_TRACE_MEDIA_MIN_BYTES": "0"}) == 0
    assert resolve_min_bytes({"LLM_TRACE_MEDIA_MIN_BYTES": "65536"}) == 65536
    assert resolve_min_bytes({"LLM_TRACE_MEDIA_MIN_BYTES": "abc"}) == 0
    assert resolve_min_bytes({"LLM_TRACE_MEDIA_MIN_BYTES": "-5"}) == 0
