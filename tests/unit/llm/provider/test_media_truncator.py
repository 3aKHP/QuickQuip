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
    original = '{"image": "' + payload + '", "b64_json": "' + payload + '"}'

    outcome = truncator.truncate(original)

    splices = outcome.manifest["splices"]
    assert len(splices) == 2
    assert splices[0]["sha256"] == splices[1]["sha256"]
    blob_dir = truncator.blob_store.path_for(splices[0]["sha256"]).parent
    assert len(list(blob_dir.glob("*.b64"))) == 1
    assert truncator.restore(outcome.text, outcome.manifest) == original


def test_splice_offsets_point_at_placeholders(tmp_path):
    truncator = _truncator(tmp_path)
    original = '{"image": "' + "L" * 2000 + '", "b64_json": "' + "M" * 2000 + '"}'

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
    with pytest.raises(ValueError):
        collect_manifest_shas("{not json")
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


@pytest.mark.parametrize("key", ["content", "text", "result", "data"])
@pytest.mark.parametrize("value", ["These are ordinary English words " * 80, "abcd" * 600])
def test_plain_text_stays_readable_even_if_valid_base64(tmp_path, key, value):
    original = json.dumps({key: value})
    outcome = _truncator(tmp_path).truncate(original)
    assert outcome.text == original
    assert outcome.manifest is None
    assert not list(tmp_path.rglob("*.b64"))


@pytest.mark.parametrize("shape", [
    {"inlineData": {"mimeType": "image/png", "data": "A" * 2000}},
    {"source": {"type": "base64", "media_type": "image/png", "data": "A" * 2000}},
    {"type": "image_generation_call", "result": "A" * 2000},
    {"type": "response.image_generation_call.partial_image", "partial_image_b64": "A" * 2000},
])
def test_protocol_media_fields_and_sse_restore(tmp_path, shape):
    original = 'event: result\ndata: ' + json.dumps(shape) + '\n\ndata: [DONE]\n\n'
    truncator = _truncator(tmp_path)
    outcome = truncator.truncate(original)
    assert outcome.manifest is not None
    assert truncator.restore(outcome.text, outcome.manifest) == original


@pytest.mark.parametrize("payload", ["A" * 2001, "A" * 1999 + "=A", "A " * 1000])
def test_invalid_base64_in_media_field_is_preserved(tmp_path, payload):
    original = _text(payload)
    outcome = _truncator(tmp_path).truncate(original)
    assert outcome.text == original
    assert outcome.manifest is None


@pytest.mark.parametrize("suffix", [",", ' trailing', ', "image": "duplicate"}'])
def test_malformed_or_duplicate_key_json_is_preserved(tmp_path, suffix):
    original = _text("A" * 2000)[:-1] + suffix
    outcome = _truncator(tmp_path).truncate(original)
    assert outcome.text == original
    assert outcome.manifest is None


def test_nested_json_unicode_offsets_and_same_text_in_non_media_field(tmp_path):
    payload = "A" * 2000
    nested = json.dumps({"note": "中文😀\n", "image": payload, "content": payload})
    original = json.dumps({"body": nested, "text": payload})
    truncator = _truncator(tmp_path)
    outcome = truncator.truncate(original)
    assert len(outcome.manifest["splices"]) == 1
    assert json.loads(json.loads(outcome.text)["body"])["content"] == payload
    assert json.loads(outcome.text)["text"] == payload
    assert truncator.restore(outcome.text, outcome.manifest) == original


def test_multimegabyte_payload_scanning_has_bounded_memory():
    import tracemalloc
    from quickquip.llm.provider.media_truncator import _json_payloads

    # 1 MiB 编码载荷曾引起约 150 MiB 正则回溯分配；容许线性副本开销。
    original = json.dumps({"image": "A" * (1024 * 1024)})
    tracemalloc.start()
    try:
        cuts = _json_payloads(original)
        current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(cuts) == 1
    assert peak < 32 * len(original)
    assert current < len(original)
