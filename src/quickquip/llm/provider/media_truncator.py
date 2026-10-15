"""内联媒体载荷的单副本存储（issue #291）。

trace 落库前把报文里的 base64 媒体载荷摘出来，按内容哈希写进 blob 库，
正文里只留 ``[qq:blob sha256=<hex> bytes=<n>]`` 占位符。三个膨胀源因此
坍缩：同一次调用重组体与原始帧各含一份同一张图 → 两个占位符指向同一
blob；历史重放 → N 个约 80 字节的占位符；DB 增长从此只与文本量相关，
与图片数、对话长度、重放次数解耦。

纪律是「存坏比存大严重得多」：

- 只截断**被引号正确闭合的完整 JSON 字符串**；中途截断、畸形输入、
  未达门槛一律原样保留；
- 回拼先校验输入文本、再逐项校验 blob 哈希，任一不符即抛 ``ValueError``；
- 嵌套 JSON 的 ``\\"`` 场景要求开闭引号的转义形态一致，否则视为畸形。

本模块只做文本变换与内容寻址存储，不碰请求发送路径：发往上游的报文
一字节不变（见 issue #291「边界与非目标」）。
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
DEFAULT_MIN_BYTES = 65536
MANIFEST_VERSION = 1
BLOB_SUFFIX = ".b64"

_TMP_PREFIX = ".tmp-"
# 裸 base64 的廉价初筛门槛：普通短字符串（UUID、token、路径）走原样路径，
# 只有足够长的连续 base64 游程才值得进一步做完整闭合判定。
_MIN_BARE_BASE64_CHARS = 64
_BASE64_BODY = r"[A-Za-z0-9+/=\s]"
# data URI 只认 ``data:<type>/<subtype>;base64,`` 这一种规范形态；带 charset
# 等参数或畸形声明的形态一律不匹配（保守，宁可原样存储）。
_DATA_URI_HEAD = r"data:([A-Za-z0-9][A-Za-z0-9.+-]*/[A-Za-z0-9][A-Za-z0-9.+-]*);base64,"
_DATA_URI_PREFIX_RE = re.compile("^" + _DATA_URI_HEAD)
_DATA_URI_RE = re.compile("^" + _DATA_URI_HEAD + _BASE64_BODY + r"+$")
_BARE_BASE64_RE = re.compile(_BASE64_BODY + r"+$")
# 完整 JSON 字符串（含转义规则）：``\\.`` 吞掉转义对，因此内层 ``\"`` 不结束
# 字符串。未闭合的尾巴不匹配任何一项，天然走「原样保留」路径。
_STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
# 字符串内容里的内层 JSON 字符串：开闭都必须是转义形态，天然一致。
# 内容用排除式字符类而非贪婪匹配——贪婪会让正则从内层第一个 ``\"`` 一路
# 吃到最后一个，把 ``img\": \"`` 之类前缀并进载荷，导致判定失败。内层若
# 自带转义（base64 载荷不会），此处不匹配，按畸形原样保留。
_ESCAPED_STRING_RE = re.compile(r'\\"([^"\\]*)\\"')


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
    data_uri = _DATA_URI_RE.match(content)
    if data_uri is not None:
        return data_uri.group(1)
    if _BARE_BASE64_RE.match(content):
        return ""
    return None


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
        return base64.b64decode(body, validate=False), mime
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


class MediaBlobStore:
    """内容寻址 blob 库：``<root>/<sha[:2]>/<sha>.b64``，同哈希天然一份。

    写入用「临时文件 + fsync + hardlink」：hardlink 在目标已存在时失败，
    因此并发写同一哈希不会相互覆盖，也不会产生第二份副本（rename 会覆盖，
    白白多写一次盘）。
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def path_for(self, sha256: str) -> Path:
        return self.root / sha256[:2] / f"{sha256}{BLOB_SUFFIX}"

    def store(self, payload: str) -> tuple[str, int]:
        """写入载荷并返回 ``(sha256, 字节数)``；已存在则直接复用。"""

        encoded = payload.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        destination = self.path_for(digest)
        if destination.exists():
            return digest, len(encoded)

        destination.parent.mkdir(parents=True, exist_ok=True)
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
        计数漂移。保守带规避「blob 已写入、引用行尚未提交」的并发窗口。
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
            if offset < cursor or span < 0 or not digest:
                raise ValueError("manifest.splices 条目越界或字段缺失")
            pieces.append(text[cursor:offset])
            payload = self.blob_store.load(digest)
            if payload is None:
                raise ValueError(f"媒体 blob 缺失：{digest}")
            if hashlib.sha256(payload.encode("utf-8")).hexdigest() != digest:
                raise ValueError(f"媒体 blob 哈希校验失败：{digest}")
            pieces.append(payload)
            cursor = offset + span
        pieces.append(text[cursor:])
        restored = "".join(pieces)

        expected_full = manifest.get("full_sha256")
        if expected_full:
            actual = hashlib.sha256(restored.encode("utf-8")).hexdigest()
            if actual != expected_full:
                raise ValueError("回拼结果与 full_sha256 不符")
        return restored

    def _iter_payloads(self, text: str) -> Iterator[tuple[int, int, str]]:
        """产出可替换载荷的 ``(start, end, mime)``，按文本位置升序。"""

        for match in _STRING_RE.finditer(text):
            content_start, content_end = match.start(1), match.end(1)
            content = match.group(1)
            mime = match_payload_mime(content)
            if mime is not None:
                yield content_start, content_end, mime
                continue
            if '\\"' not in content:
                continue
            for inner in _ESCAPED_STRING_RE.finditer(content):
                inner_mime = match_payload_mime(inner.group(1))
                if inner_mime is not None:
                    yield (
                        content_start + inner.start(1),
                        content_start + inner.end(1),
                        inner_mime,
                    )


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
    for field_manifest in _iter_field_manifests(_load_manifest(manifest_json)):
        for item in field_manifest.get("splices") or []:
            if isinstance(item, dict):
                digest = item.get("sha256")
                if isinstance(digest, str) and digest:
                    collected.add(digest)
    return collected


def find_manifest_mime(manifest_json: str | None, sha256: str) -> str | None:
    """在 manifest JSON 里查某个 blob 的 mime。"""

    for field_manifest in _iter_field_manifests(_load_manifest(manifest_json)):
        for item in field_manifest.get("splices") or []:
            if isinstance(item, dict) and item.get("sha256") == sha256:
                mime = item.get("mime")
                return mime if isinstance(mime, str) else ""
    return None


def _load_manifest(manifest_json: str | None) -> dict[str, object] | None:
    if not manifest_json:
        return None
    try:
        payload = json.loads(manifest_json)
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None
