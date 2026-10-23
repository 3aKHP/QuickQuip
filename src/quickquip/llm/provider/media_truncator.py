"""Trace 媒体载荷的内容寻址存储、结构化识别与原文恢复。

完整 JSON 或 SSE JSON 记录中的媒体载荷保留原始表达，正文替换为带摘要的
占位符。恢复时验证正文与载荷哈希。引用提交与文件清理的跨进程事务由
LLMTraceStore 管理；本模块不参与请求发送。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

MEDIA_MIN_BYTES_ENV = "LLM_TRACE_MEDIA_MIN_BYTES"
MANIFEST_VERSION = 1
BLOB_SUFFIX = ".b64"

_TMP_PREFIX = ".tmp-"
# 裸 base64 的廉价初筛门槛：普通短字符串（UUID、token、路径）走原样路径，
# 只有足够长的连续 base64 游程才值得进一步做完整闭合判定。
_MIN_BARE_BASE64_CHARS = 64
_BASE64_BODY = r"[A-Za-z0-9+/]+={0,2}"
_DATA_URI_HEAD = r"data:([A-Za-z0-9][A-Za-z0-9.+-]*/[A-Za-z0-9][A-Za-z0-9.+-]*);base64,"
_DATA_URI_PREFIX_RE = re.compile("^" + _DATA_URI_HEAD)
_BARE_BASE64_RE = re.compile(_BASE64_BODY)
_STRING_RE = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"')
_JSON_CHAR_RE = re.compile(
    r"\\u[dD][89aAbB][0-9a-fA-F]{2}\\u[dD][c-fC-F][0-9a-fA-F]{2}"
    r"|\\u[0-9a-fA-F]{4}|\\.|[^\\]+"
)


def _media_field(key: str, parent: dict) -> bool:
    """仅在明确的媒体字段接纳裸编码，普通 content/text/result 保留原文。"""

    if key in {"image", "b64_json", "partial_image_b64"}:
        return True
    if key == "result":
        return parent.get("type") == "image_generation_call"
    if key == "data":
        mime = parent.get("mimeType") or parent.get("mime_type") or parent.get("media_type")
        return isinstance(mime, str) and mime.startswith(("image/", "audio/", "video/"))
    return False


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _string_offsets(raw: str, positions: set[int]) -> dict[int, int]:
    """仅映射载荷边界，避免为大载荷的每个字符保留一个索引。"""

    pending = iter(sorted(positions))
    target = next(pending, None)
    offsets = {}
    decoded_start = 0
    for match in _JSON_CHAR_RE.finditer(raw):
        piece = match.group()
        escaped = piece.startswith("\\")
        length = len(json.loads('"' + piece + '"')) if escaped else len(piece)
        while target is not None and target < decoded_start + length:
            offsets[target] = match.start() + (0 if escaped else target - decoded_start)
            target = next(pending, None)
        decoded_start += length
        if target is None:
            break
    if target == decoded_start:
        offsets[target] = len(raw)
    return offsets


def _visit_json_values(node, tokens, text, depth, key="", parent=None):
    if isinstance(node, dict):
        for name, child in node.items():
            next(tokens)  # JSON 对象键，遍历顺序与原文一致。
            yield from _visit_json_values(child, tokens, text, depth, name, node)
    elif isinstance(node, list):
        for child in node:
            yield from _visit_json_values(child, tokens, text, depth)
    elif isinstance(node, str):
        token = next(tokens)
        raw = token.group(1)
        mime = match_payload_mime(node)
        if mime is not None and (mime or _media_field(key, parent or {})):
            if raw == node:
                yield token.start(1), token.end(1), mime
        elif node.lstrip().startswith(("{", "[")):
            nested = _json_payloads(node, depth + 1)
            if nested:
                offsets = _string_offsets(raw, {point for cut in nested for point in cut[:2]})
                for start, end, nested_mime in nested:
                    source_start = token.start(1) + offsets[start]
                    source_end = token.start(1) + offsets[end]
                    if "\\" not in text[source_start:source_end]:
                        yield source_start, source_end, nested_mime


def _json_payloads(text: str, depth: int = 0) -> list[tuple[int, int, str]]:
    """使用 JSON 结构确定媒体字段，再由字符串 token 保留原始字节表达。"""

    if depth > 4:
        return []
    try:
        value = json.loads(text, object_pairs_hook=_unique_object)
        tokens = iter(_STRING_RE.finditer(text))
        return list(_visit_json_values(value, tokens, text, depth))
    except (ValueError, TypeError, RecursionError, StopIteration):
        return []


def resolve_min_bytes(environ: dict[str, str] | None = None) -> int:
    """读取 ``LLM_TRACE_MEDIA_MIN_BYTES``；未设、非法或 <= 0 表示关闭截断。"""

    raw = (environ if environ is not None else os.environ).get(MEDIA_MIN_BYTES_ENV, "")
    text = str(raw).strip()
    if not text:
        return 0
    try:
        value = int(text)
    except ValueError:
        logger.warning("%s=%r 不是整数，按关闭处理（原样存储）", MEDIA_MIN_BYTES_ENV, raw)
        return 0
    return max(0, value)


def match_payload_mime(content: str) -> str | None:
    """判定字符串内容是否为 base64 载荷。

    返回声明的 mime（``""`` 表示未声明，如裸 base64），非载荷返回 ``None``。
    """

    if len(content) < _MIN_BARE_BASE64_CHARS:
        return None
    prefix = _DATA_URI_PREFIX_RE.match(content)
    body = content[prefix.end():] if prefix else content
    if not _BARE_BASE64_RE.fullmatch(body) or len(body) % 4:
        return None
    try:
        base64.b64decode(body, validate=True)
    except (binascii.Error, ValueError):
        return None
    return prefix.group(1) if prefix else ""


def placeholder_for(sha256: str, size: int) -> str:
    """占位符是纯 ASCII 且不含 JSON 需转义的字符，替换后报文仍是合法 JSON。"""

    return f"[qq:blob sha256={sha256} bytes={size}]"


def decode_payload(payload: str) -> tuple[bytes, str] | None:
    """把 blob 里的载荷解成二进制，返回 ``(bytes, mime)``。

    blob 存的是载荷原文（data URI 含 ``data:...;base64,`` 前缀），下载端点
    要把它还原成可供图片预览的二进制。解码失败返回 ``None``。
    """

    mime = ""
    body = payload
    prefix = _DATA_URI_PREFIX_RE.match(payload)
    if prefix is not None:
        mime = prefix.group(1)
        body = payload[prefix.end():]
    try:
        return base64.b64decode(body, validate=True), mime
    except (binascii.Error, ValueError):
        return None


@dataclass(slots=True)
class Splice:
    """一处替换：截断后文本中的占位符位置，以及被摘走的载荷元信息。"""

    offset: int
    span: int
    orig_bytes: int
    sha256: str
    mime: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "offset": self.offset,
            "span": self.span,
            "orig_bytes": self.orig_bytes,
            "sha256": self.sha256,
            "mime": self.mime,
        }


@dataclass(slots=True)
class TruncationOutcome:
    """一次截断的结果；``manifest`` 为 ``None`` 表示原样未动。"""

    text: str
    manifest: dict[str, object] | None = None
    saved_bytes: int = 0


@dataclass(slots=True)
class FieldManifest:
    """单个文本字段的 splice 清单与全文哈希。"""

    full_sha256: str
    full_bytes: int
    truncated_sha256: str
    splices: list[Splice] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "full_sha256": self.full_sha256,
            "full_bytes": self.full_bytes,
            "truncated_sha256": self.truncated_sha256,
            "splices": [splice.as_dict() for splice in self.splices],
        }


def _sync_directory(path: Path) -> None:
    # Python 在 Windows 上不提供可用于 fsync 的目录描述符。
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_blob_directory(path: Path) -> None:
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    path.mkdir(parents=True, exist_ok=True)
    for created in reversed(missing):
        _sync_directory(created.parent)


class MediaBlobStore:
    """内容寻址 blob 库：``<root>/<sha[:2]>/<sha>.b64``，同哈希天然一份。

    写入用「临时文件 + fsync + hardlink」：hardlink 在目标已存在时失败，
    因此并发写同一哈希不会相互覆盖，也不会产生第二份副本（rename 会覆盖，
    白白多写一次盘）。
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def path_for(self, sha256: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValueError("invalid blob digest")
        return self.root / sha256[:2] / f"{sha256}{BLOB_SUFFIX}"

    def store(self, payload: str) -> tuple[str, int]:
        """写入载荷并返回 ``(sha256, 字节数)``；已存在则直接复用。"""

        encoded = payload.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        destination = self.path_for(digest)
        if destination.exists():
            return digest, len(encoded)

        _ensure_blob_directory(destination.parent)
        handle, tmp_name = tempfile.mkstemp(dir=str(destination.parent), prefix=_TMP_PREFIX)
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(tmp_path, destination)
            except FileExistsError:
                # 并发写入同一哈希：盘上已有同一份内容，无需覆盖。
                pass
            _sync_directory(destination.parent)
        finally:
            tmp_path.unlink(missing_ok=True)
        return digest, len(encoded)

    def load(self, sha256: str) -> str | None:
        try:
            return self.path_for(sha256).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def collect_orphaned(self, referenced: set[str], grace_seconds: float) -> int:
        """mark-sweep：删除未被引用、且 mtime 早于保守带的 blob。

        选扫描式而非引用计数：对任意删除路径（含运维手工清库）免疫，不存在
        计数漂移。调用者须在引用扫描至清理结束期间持有与写入相同的跨进程锁。
        """

        if not self.root.is_dir():
            return 0
        cutoff = time.time() - grace_seconds
        removed = 0
        try:
            shards = list(self.root.iterdir())
        except OSError:
            return 0
        for shard in shards:
            if not shard.is_dir():
                continue
            try:
                entries = list(shard.iterdir())
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.name.startswith(_TMP_PREFIX):
                        # 进程崩溃留下的临时文件：同样按保守带清理。
                        if entry.stat().st_mtime < cutoff:
                            entry.unlink()
                        continue
                    if entry.suffix != BLOB_SUFFIX:
                        continue
                    if entry.stem in referenced:
                        continue
                    if entry.stat().st_mtime >= cutoff:
                        continue
                    entry.unlink()
                    removed += 1
                except OSError:
                    logger.debug("媒体 blob 清理失败：%s", entry)
            try:
                if not any(shard.iterdir()):
                    shard.rmdir()
            except OSError:
                pass
        return removed


class MediaTruncator:
    """把报文文本里的内联媒体载荷换成占位符，并可回拼原文。"""

    def __init__(self, blob_store: MediaBlobStore, *, min_bytes: int = 0) -> None:
        self.blob_store = blob_store
        self.min_bytes = max(0, int(min_bytes))

    @property
    def enabled(self) -> bool:
        return self.min_bytes > 0

    def truncate(self, text: str) -> TruncationOutcome:
        """截断一处文本；无载荷、未达门槛或畸形时原样返回。"""

        if not self.enabled or not text:
            return TruncationOutcome(text=text)

        cuts: list[tuple[int, int, Splice]] = []
        for start, end, mime in self._iter_payloads(text):
            payload = text[start:end]
            size = len(payload.encode("utf-8"))
            if size < self.min_bytes:
                continue
            try:
                digest, _ = self.blob_store.store(payload)
            except OSError:
                # 落盘失败就放弃这一处截断：宁可不存，也不产出无法回拼的文本。
                logger.exception("媒体 blob 写入失败，该处按原样保留")
                continue
            cuts.append(
                (
                    start,
                    end,
                    Splice(offset=0, span=0, orig_bytes=size, sha256=digest, mime=mime),
                )
            )

        if not cuts:
            return TruncationOutcome(text=text)

        pieces: list[str] = []
        written = 0
        cursor = 0
        splices: list[Splice] = []
        for start, end, splice in cuts:
            if start < cursor:
                # 区间重叠不应出现；防御性跳过，绝不产出错位文本。
                continue
            chunk = text[cursor:start]
            pieces.append(chunk)
            written += len(chunk)
            placeholder = placeholder_for(splice.sha256, splice.orig_bytes)
            splice.offset = written
            splice.span = len(placeholder)
            pieces.append(placeholder)
            written += len(placeholder)
            splices.append(splice)
            cursor = end
        pieces.append(text[cursor:])
        truncated = "".join(pieces)

        manifest = FieldManifest(
            full_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            full_bytes=len(text.encode("utf-8")),
            truncated_sha256=hashlib.sha256(truncated.encode("utf-8")).hexdigest(),
            splices=splices,
        )
        return TruncationOutcome(
            text=truncated,
            manifest=manifest.as_dict(),
            saved_bytes=manifest.full_bytes - len(truncated.encode("utf-8")),
        )

    def restore(self, text: str, manifest: dict[str, object]) -> str:
        """按清单回拼字节级原文；任一校验不通过即抛 ``ValueError``。"""

        _validate_field_manifest(manifest)
        expected_truncated = manifest.get("truncated_sha256")
        if expected_truncated:
            actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if actual != expected_truncated:
                raise ValueError("trace 文本与 manifest 不匹配（truncated_sha256 校验失败）")

        raw_splices = manifest.get("splices") or []
        if not isinstance(raw_splices, list):
            raise ValueError("manifest.splices 不是列表")

        pieces: list[str] = []
        cursor = 0
        for item in raw_splices:
            if not isinstance(item, dict):
                raise ValueError("manifest.splices 条目不是对象")
            offset = int(item.get("offset", -1))
            span = int(item.get("span", -1))
            digest = str(item.get("sha256", ""))
            if offset < cursor or span <= 0 or offset + span > len(text) or not digest:
                raise ValueError("manifest.splices 条目越界或字段缺失")
            pieces.append(text[cursor:offset])
            payload = self.blob_store.load(digest)
            if payload is None:
                raise ValueError(f"媒体 blob 缺失：{digest}")
            if hashlib.sha256(payload.encode("utf-8")).hexdigest() != digest:
                raise ValueError(f"媒体 blob 哈希校验失败：{digest}")
            if len(payload.encode("utf-8")) != item["orig_bytes"]:
                raise ValueError("媒体 blob 字节数校验失败")
            if text[offset:offset + span] != placeholder_for(digest, item["orig_bytes"]):
                raise ValueError("媒体占位符与清单不匹配")
            pieces.append(payload)
            cursor = offset + span
        pieces.append(text[cursor:])
        restored = "".join(pieces)

        if len(restored.encode("utf-8")) != manifest["full_bytes"]:
            raise ValueError("回拼正文的字节数不匹配")
        expected_full = manifest.get("full_sha256")
        if expected_full:
            actual = hashlib.sha256(restored.encode("utf-8")).hexdigest()
            if actual != expected_full:
                raise ValueError("回拼结果与 full_sha256 不符")
        return restored

    def _iter_payloads(self, text: str) -> Iterator[tuple[int, int, str]]:
        """读取完整 JSON 或 SSE data 行；不改动不完整记录。"""

        if text.lstrip().startswith(("{", "[", '"')):
            yield from _json_payloads(text)
            return
        offset = 0
        for line in text.splitlines(keepends=True):
            if line.startswith("data:"):
                body = line[5:].lstrip(" ")
                start = offset + len(line) - len(body)
                for begin, end, mime in _json_payloads(body):
                    yield start + begin, start + end, mime
            offset += len(line)


def _iter_field_manifests(payload: dict[str, object] | None) -> Iterator[dict[str, object]]:
    """兼容两种落库形态，逐个产出字段级 manifest。

    - 单字段：``truncate`` 的直接产出，顶层就带 ``splices``；
    - 分字段包装：``{"v": 1, "request": {...}, "response": {...}}``，
      这是 trace 落库时把三个文本字段的清单合成一列后的形态。
    """

    if payload is None:
        return
    if "splices" in payload:
        yield payload
        return
    for value in payload.values():
        if isinstance(value, dict) and "splices" in value:
            yield value


def collect_manifest_shas(manifest_json: str | None) -> set[str]:
    """从落库的 manifest JSON 里收集全部 blob sha（GC 的 mark 集合）。"""

    collected: set[str] = set()
    for field_manifest in _iter_field_manifests(parse_manifest(manifest_json, allow_field=True)):
        for item in field_manifest.get("splices") or []:
            if isinstance(item, dict):
                digest = item.get("sha256")
                if isinstance(digest, str) and digest:
                    collected.add(digest)
    return collected


def find_manifest_mime(manifest_json: str | None, sha256: str) -> str | None:
    """在 manifest JSON 里查某个 blob 的 mime。"""

    for field_manifest in _iter_field_manifests(parse_manifest(manifest_json, allow_field=True)):
        for item in field_manifest.get("splices") or []:
            if isinstance(item, dict) and item.get("sha256") == sha256:
                mime = item.get("mime")
                return mime if isinstance(mime, str) else ""
    return None


def _validate_field_manifest(payload: dict) -> None:
    for key in ("full_sha256", "truncated_sha256"):
        if not isinstance(payload.get(key), str) or not re.fullmatch(
            r"[0-9a-f]{64}", payload[key],
        ):
            raise ValueError("invalid manifest hash")
    if type(payload.get("full_bytes")) is not int or payload["full_bytes"] < 0:
        raise ValueError("invalid manifest byte count")
    splices = payload.get("splices")
    if not isinstance(splices, list) or not splices:
        raise ValueError("invalid manifest splices")
    for item in splices:
        if not isinstance(item, dict):
            raise ValueError("invalid manifest splice")
        for key in ("offset", "span", "orig_bytes"):
            if type(item.get(key)) is not int or item[key] < (0 if key == "offset" else 1):
                raise ValueError("invalid manifest splice bounds")
        if not isinstance(item.get("sha256"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", item["sha256"],
        ):
            raise ValueError("invalid manifest digest")
        if not isinstance(item.get("mime", ""), str):
            raise ValueError("invalid manifest MIME")


def parse_manifest(
    raw: str | None, *, allow_field: bool = False,
) -> dict[str, object] | None:
    """SQL NULL 表示原样记录；非空清单必须具有有效版本、字段和恢复校验。"""

    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError) as error:
        raise ValueError("invalid media manifest JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("invalid media manifest")
    if allow_field and "splices" in payload:
        _validate_field_manifest(payload)
        return payload
    fields = set(payload) - {"v"}
    if payload.get("v") != MANIFEST_VERSION or not fields or not fields <= {
        "request", "response", "response_raw",
    }:
        raise ValueError("invalid media manifest version or fields")
    for key in fields:
        if not isinstance(payload[key], dict):
            raise ValueError("invalid media field manifest")
        _validate_field_manifest(payload[key])
    return payload


def merge_field_manifests(
    existing_json: str | None,
    additions: dict[str, dict[str, object] | None],
) -> str | None:
    """把新字段的清单并入已有 manifest，避免后写的一次覆盖前一次。

    ``begin_call`` 落 request，``finish_call`` 落 response 与 response_raw，
    三者共用一个 ``media_truncation`` 列，必须合并而非覆盖。全部字段都无
    截断时返回 ``None``——该行就是「原样存储」。
    """

    payload = parse_manifest(existing_json) or {}
    for field_name, manifest in additions.items():
        if manifest is None:
            payload.pop(field_name, None)
        else:
            payload[field_name] = manifest
    if not any(name != "v" for name in payload):
        return None
    payload["v"] = MANIFEST_VERSION
    return json.dumps(payload, ensure_ascii=False)
