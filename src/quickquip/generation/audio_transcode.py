"""ASR 音频格式识别与转码：按魔数分流原始 SILK/AMR 与常规音频。

设计约束：
- 格式识别只依据字节魔数，不依赖文件名扩展名或 HTTP Content-Type。
- SILK（标准 ``#!SILK_V3`` 与腾讯前缀 ``\\x02#!SILK_V3``）先在 Python 侧校验帧边界，
  再经 ``python -m quickquip.generation.audio_worker`` 短命子进程解码为
  16 kHz / 16-bit / 单声道 WAV，避免第三方 C 扩展异常崩溃影响主进程。
- 真 AMR（``#!AMR\\n``）与 AMR-WB（``#!AMR-WB\\n``）按 RFC 4867 校验帧结构后，
  若运行环境存在系统 ``ffmpeg``，通过独立任务临时目录调用子进程转为 WAV；
  未安装 ``ffmpeg`` 时抛出 ``GenerationProviderError``，沿用逐段跳过行为。
- 现有可识别常规音频（WAV/MP3/OGG/FLAC/M4A/WebM）保持原始字节透传，并按检测结果
  归一化文件名后缀与 MIME；无法识别的非音频载荷抛出 ``GenerationProviderError``。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import io
import logging
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import wave

from quickquip.generation.errors import GenerationProviderError

logger = logging.getLogger(__name__)

DEFAULT_ASR_MAX_AUDIO_BYTES = 25 * 1024 * 1024
DEFAULT_ASR_MAX_DECODED_BYTES = 25 * 1024 * 1024

TARGET_WAV_SAMPLE_RATE = 16000
TARGET_WAV_CHANNELS = 1
TARGET_WAV_SAMPLE_WIDTH = 2
_WAV_HEADER_BYTES = 44
_MIN_FRAME_MS = 20

SILK_MAGIC = b"#!SILK_V3"
TENCENT_SILK_MAGIC = b"\x02#!SILK_V3"
AMR_NB_MAGIC = b"#!AMR\n"
AMR_WB_MAGIC = b"#!AMR-WB\n"

# 对应 SILK SDK DECODE_MAX_BYTES_PER_FRAME (1024) * MAX_INPUT_FRAMES (5)
_MAX_SILK_FRAME_BYTES = 5120
_SILK_DECODE_ERROR_MARKER = "SKP_Silk_SDK_Decode returned"

# RFC 4867 §5.1 / §5.3：各 FT 对应的语音帧字节数（不含 1 字节 TOC）
_AMR_NB_FRAME_SIZES: dict[int, int] = {
    0: 12,
    1: 13,
    2: 15,
    3: 17,
    4: 19,
    5: 20,
    6: 26,
    7: 31,
    8: 5,
    15: 0,
}
_AMR_WB_FRAME_SIZES: dict[int, int] = {
    0: 17,
    1: 23,
    2: 32,
    3: 36,
    4: 40,
    5: 46,
    6: 50,
    7: 58,
    8: 60,
    9: 5,
    14: 0,
    15: 0,
}

_PASSTHROUGH_FORMATS: dict[str, tuple[str, str]] = {
    "wav": ("audio/wav", ".wav"),
    "mp3": ("audio/mpeg", ".mp3"),
    "ogg": ("audio/ogg", ".ogg"),
    "flac": ("audio/flac", ".flac"),
    "mp4": ("audio/mp4", ".m4a"),
    "webm": ("audio/webm", ".webm"),
}

WORKER_AS_LIMIT_BYTES = 2 * 1024**3
WORKER_CPU_SECONDS = 10
WORKER_WALL_TIMEOUT_SECONDS = 15.0
MAX_TRANSCODE_CONCURRENCY = 2

_WORKER_EXIT_TOO_LARGE = 2

# 并发闸门仅在工作线程内获取与释放，避免阻塞事件循环
_TRANSCODE_SLOTS = threading.Semaphore(MAX_TRANSCODE_CONCURRENCY)


@dataclass(frozen=True, slots=True)
class NormalizedAudio:
    data: bytes
    filename: str
    mime_type: str
    source_format: str
    transcoded: bool = False


def _looks_like_mp3_frame(data: bytes) -> bool:
    if len(data) < 4:
        return False
    b0, b1, b2 = data[0], data[1], data[2]
    if b0 != 0xFF or (b1 & 0xE0) != 0xE0:
        return False
    mpeg_version = (b1 & 0x18) >> 3
    layer = (b1 & 0x06) >> 1
    bitrate_idx = (b2 & 0xF0) >> 4
    sample_rate_idx = (b2 & 0x0C) >> 2
    if mpeg_version == 1 or layer == 0:
        return False
    if bitrate_idx in (0, 15) or sample_rate_idx == 3:
        return False
    return True


def detect_audio_format(data: bytes) -> str:
    """按内容魔数识别音频格式，忽略文件名扩展名。"""
    if not data:
        return "unknown"
    if data.startswith(TENCENT_SILK_MAGIC):
        return "tencent_silk"
    if data.startswith(SILK_MAGIC):
        return "silk"
    if data.startswith(AMR_WB_MAGIC):
        return "amr_wb"
    if data.startswith(AMR_NB_MAGIC):
        return "amr_nb"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data.startswith(b"OggS"):
        return "ogg"
    if data.startswith(b"fLaC"):
        return "flac"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "mp4"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    if data.startswith(b"ID3") or _looks_like_mp3_frame(data):
        return "mp3"
    return "unknown"


def validate_silk_stream(
    data: bytes,
    *,
    sample_rate: int = TARGET_WAV_SAMPLE_RATE,
    max_decoded_bytes: int = DEFAULT_ASR_MAX_DECODED_BYTES,
) -> tuple[str, int]:
    """校验 SILK v3 帧边界与最小解压体积下界，返回 ``(format, frame_count)``。"""
    if data.startswith(TENCENT_SILK_MAGIC):
        fmt = "tencent_silk"
        pos = len(TENCENT_SILK_MAGIC)
    elif data.startswith(SILK_MAGIC):
        fmt = "silk"
        pos = len(SILK_MAGIC)
    else:
        raise GenerationProviderError("非有效 SILK 音频头，跳过 ASR")

    total = len(data)
    frame_count = 0
    while pos < total:
        if pos + 2 > total:
            raise GenerationProviderError("SILK 音频帧头截断，跳过 ASR")
        (frame_len,) = struct.unpack_from("<h", data, pos)
        pos += 2
        if frame_len == -1:
            if pos != total:
                raise GenerationProviderError("SILK 音频结束标记后存在非法尾部数据，跳过 ASR")
            break
        if frame_len <= 0 or frame_len > _MAX_SILK_FRAME_BYTES:
            raise GenerationProviderError("SILK 音频帧长度非法，跳过 ASR")
        if pos + frame_len > total:
            raise GenerationProviderError("SILK 音频帧数据截断，跳过 ASR")
        pos += frame_len
        frame_count += 1

    # SILK SDK 解码器内部抖动缓冲要求至少 2 个有效分组（>=40ms）才能产出可靠音频
    if frame_count < 2:
        raise GenerationProviderError("SILK 音频有效帧不足，跳过 ASR")

    min_pcm_per_frame = (sample_rate * _MIN_FRAME_MS // 1000) * TARGET_WAV_SAMPLE_WIDTH
    if frame_count * min_pcm_per_frame + _WAV_HEADER_BYTES > max_decoded_bytes:
        raise GenerationProviderError("SILK 解码后音频预计超过大小上限，跳过 ASR")

    return fmt, frame_count


def validate_amr_stream(
    data: bytes,
    *,
    sample_rate: int = TARGET_WAV_SAMPLE_RATE,
    max_decoded_bytes: int = DEFAULT_ASR_MAX_DECODED_BYTES,
) -> tuple[str, int]:
    """按 RFC 4867 校验 AMR-NB / AMR-WB 存储格式帧边界，返回 ``(format, frame_count)``。"""
    if data.startswith(AMR_WB_MAGIC):
        fmt = "amr_wb"
        pos = len(AMR_WB_MAGIC)
        frame_sizes = _AMR_WB_FRAME_SIZES
    elif data.startswith(AMR_NB_MAGIC):
        fmt = "amr_nb"
        pos = len(AMR_NB_MAGIC)
        frame_sizes = _AMR_NB_FRAME_SIZES
    else:
        raise GenerationProviderError("非有效 AMR 音频头，跳过 ASR")

    total = len(data)
    frame_count = 0
    while pos < total:
        toc = data[pos]
        pos += 1
        if (toc & 0x83) != 0:
            raise GenerationProviderError("AMR 帧头保留位非法，跳过 ASR")
        frame_type = (toc >> 3) & 0x0F
        frame_size = frame_sizes.get(frame_type)
        if frame_size is None:
            raise GenerationProviderError("AMR 帧类型非法，跳过 ASR")
        if pos + frame_size > total:
            raise GenerationProviderError("AMR 帧数据截断，跳过 ASR")
        pos += frame_size
        frame_count += 1

    if frame_count == 0:
        raise GenerationProviderError("AMR 音频不含有效帧，跳过 ASR")

    pcm_per_frame = (sample_rate * _MIN_FRAME_MS // 1000) * TARGET_WAV_SAMPLE_WIDTH
    if frame_count * pcm_per_frame + _WAV_HEADER_BYTES > max_decoded_bytes:
        raise GenerationProviderError("AMR 解码后音频预计超过大小上限，跳过 ASR")

    return fmt, frame_count


def validate_wav_bytes(
    data: bytes,
    *,
    expected_sample_rate: int | None = None,
    expected_channels: int | None = None,
    expected_sample_width: int | None = None,
) -> tuple[int, int, int, int]:
    """校验 WAV 头参数与有效音频帧，返回 ``(channels, sampwidth, framerate, nframes)``。"""
    try:
        with wave.open(io.BytesIO(data), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sampwidth = wav_file.getsampwidth()
            framerate = wav_file.getframerate()
            nframes = wav_file.getnframes()
            comptype = wav_file.getcomptype()
            frames = wav_file.readframes(nframes)
    except (wave.Error, EOFError, OSError) as exc:
        raise GenerationProviderError(f"转码产出无效 WAV：{exc}") from exc

    if comptype != "NONE":
        raise GenerationProviderError(f"WAV 压缩类型不受支持：{comptype}")
    if channels <= 0 or sampwidth <= 0 or framerate <= 0 or nframes <= 0:
        raise GenerationProviderError("转码产出空 WAV 音频")
    expected_bytes = nframes * channels * sampwidth
    if len(frames) != expected_bytes:
        raise GenerationProviderError("转码产出 WAV 帧长度不完整")
    if expected_channels is not None and channels != expected_channels:
        raise GenerationProviderError(f"WAV 声道数不符：期望 {expected_channels}，实际 {channels}")
    if expected_sample_width is not None and sampwidth != expected_sample_width:
        raise GenerationProviderError(
            f"WAV 采样位宽不符：期望 {expected_sample_width}，实际 {sampwidth}"
        )
    if expected_sample_rate is not None and framerate != expected_sample_rate:
        raise GenerationProviderError(
            f"WAV 采样率不符：期望 {expected_sample_rate}，实际 {framerate}"
        )
    return channels, sampwidth, framerate, nframes


def _rewrite_filename(filename: str, target_suffix: str) -> str:
    raw_name = Path(filename.strip()).name if filename and filename.strip() else ""
    safe_name = "".join(ch for ch in raw_name if ch not in '\r\n"\\/')
    stem = Path(safe_name).stem if safe_name and safe_name not in (".", "..") else "voice"
    if not stem or stem in (".", ".."):
        stem = "voice"
    return f"{stem}{target_suffix}"


def _worker_env() -> dict[str, str]:
    """子进程环境：兜底将 quickquip 包父目录加入 PYTHONPATH。"""
    env = dict(os.environ)
    package_parent = str(Path(__file__).resolve().parents[2])
    existing = env.get("PYTHONPATH", "")
    parts = [part for part in existing.split(os.pathsep) if part]
    if package_parent not in parts:
        parts.insert(0, package_parent)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def _transcode_silk_sync(
    data: bytes,
    *,
    sample_rate: int,
    max_decoded_bytes: int,
) -> bytes:
    _, frame_count = validate_silk_stream(
        data,
        sample_rate=sample_rate,
        max_decoded_bytes=max_decoded_bytes,
    )
    with _TRANSCODE_SLOTS, tempfile.TemporaryDirectory(prefix="quickquip-asr-silk-") as tmp_dir:
        tmp_root = Path(tmp_dir)
        input_path = tmp_root / "input.silk"
        output_path = tmp_root / "output.wav"
        input_path.write_bytes(data)

        command = [
            sys.executable,
            "-m",
            "quickquip.generation.audio_worker",
            str(input_path),
            str(output_path),
            str(sample_rate),
            str(max_decoded_bytes),
            str(WORKER_AS_LIMIT_BYTES),
            str(WORKER_CPU_SECONDS),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                timeout=WORKER_WALL_TIMEOUT_SECONDS,
                env=_worker_env(),
            )
        except subprocess.TimeoutExpired:
            raise GenerationProviderError(
                f"SILK 解码超时（>{WORKER_WALL_TIMEOUT_SECONDS:.0f}s），跳过 ASR"
            ) from None
        except OSError as exc:
            raise GenerationProviderError(f"无法启动 SILK 解码子进程：{exc}") from exc

        if completed.returncode == _WORKER_EXIT_TOO_LARGE:
            raise GenerationProviderError("SILK 解码后音频超过大小上限，跳过 ASR")
        if completed.returncode != 0:
            stderr_text = completed.stderr.decode("utf-8", errors="replace").strip()
            logger.warning(
                "SILK 解码 worker 退出失败：exitcode=%s stderr=%s",
                completed.returncode,
                stderr_text[:200],
            )
            raise GenerationProviderError(
                f"SILK 解码失败（exitcode={completed.returncode}），跳过 ASR"
            )

        stdout_text = completed.stdout.decode("utf-8", errors="replace")
        decode_errors = stdout_text.count(_SILK_DECODE_ERROR_MARKER)
        if decode_errors > 0 and (
            decode_errors >= max(1, frame_count - 2) or decode_errors * 2 >= frame_count
        ):
            raise GenerationProviderError("SILK 音频帧解码损坏，跳过 ASR")

        if not output_path.is_file():
            raise GenerationProviderError("SILK 解码未生成输出文件，跳过 ASR")
        if output_path.stat().st_size > max_decoded_bytes:
            raise GenerationProviderError("SILK 解码后音频超过大小上限，跳过 ASR")
        wav_bytes = output_path.read_bytes()

    validate_wav_bytes(
        wav_bytes,
        expected_sample_rate=sample_rate,
        expected_channels=TARGET_WAV_CHANNELS,
        expected_sample_width=TARGET_WAV_SAMPLE_WIDTH,
    )
    return wav_bytes


def _transcode_amr_sync(
    data: bytes,
    *,
    sample_rate: int,
    max_decoded_bytes: int,
    ffmpeg_path: str | None = None,
) -> bytes:
    fmt, _ = validate_amr_stream(
        data,
        sample_rate=sample_rate,
        max_decoded_bytes=max_decoded_bytes,
    )
    ffmpeg_bin = ffmpeg_path if ffmpeg_path is not None else shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise GenerationProviderError(
            f"检测到原始 {fmt.upper()} 语音，但运行环境未安装 ffmpeg，跳过 ASR"
        )

    with _TRANSCODE_SLOTS, tempfile.TemporaryDirectory(prefix="quickquip-asr-amr-") as tmp_dir:
        tmp_root = Path(tmp_dir)
        input_path = tmp_root / ("input.awb" if fmt == "amr_wb" else "input.amr")
        output_path = tmp_root / "output.wav"
        input_path.write_bytes(data)

        command = [
            ffmpeg_bin,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "amr",
            "-i",
            str(input_path),
            "-vn",
            "-ac",
            str(TARGET_WAV_CHANNELS),
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            "-f",
            "wav",
            str(output_path),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                timeout=WORKER_WALL_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise GenerationProviderError(
                f"AMR 转码超时（>{WORKER_WALL_TIMEOUT_SECONDS:.0f}s），跳过 ASR"
            ) from None
        except OSError as exc:
            raise GenerationProviderError(f"无法启动 ffmpeg 转码 AMR：{exc}") from exc

        if completed.returncode != 0:
            stderr_text = completed.stderr.decode("utf-8", errors="replace").strip()
            logger.warning(
                "ffmpeg 转码 AMR 失败：exitcode=%s stderr=%s",
                completed.returncode,
                stderr_text[:200],
            )
            raise GenerationProviderError(
                f"AMR 转码失败（exitcode={completed.returncode}），跳过 ASR"
            )

        if not output_path.is_file():
            raise GenerationProviderError("AMR 转码未生成输出文件，跳过 ASR")
        if output_path.stat().st_size > max_decoded_bytes:
            raise GenerationProviderError("AMR 解码后音频超过大小上限，跳过 ASR")
        wav_bytes = output_path.read_bytes()

    validate_wav_bytes(
        wav_bytes,
        expected_sample_rate=sample_rate,
        expected_channels=TARGET_WAV_CHANNELS,
        expected_sample_width=TARGET_WAV_SAMPLE_WIDTH,
    )
    return wav_bytes


def _normalize_sync(
    audio_bytes: bytes,
    *,
    filename: str,
    max_audio_bytes: int,
    max_decoded_bytes: int,
    sample_rate: int,
    ffmpeg_path: str | None,
) -> NormalizedAudio:
    if not audio_bytes:
        raise GenerationProviderError("语音文件为空，跳过 ASR")
    if len(audio_bytes) > max_audio_bytes:
        raise GenerationProviderError("语音文件过大，跳过 ASR")

    detected = detect_audio_format(audio_bytes)
    if detected in ("silk", "tencent_silk"):
        wav_bytes = _transcode_silk_sync(
            audio_bytes,
            sample_rate=sample_rate,
            max_decoded_bytes=max_decoded_bytes,
        )
        return NormalizedAudio(
            data=wav_bytes,
            filename=_rewrite_filename(filename, ".wav"),
            mime_type="audio/wav",
            source_format=detected,
            transcoded=True,
        )

    if detected in ("amr_nb", "amr_wb"):
        wav_bytes = _transcode_amr_sync(
            audio_bytes,
            sample_rate=sample_rate,
            max_decoded_bytes=max_decoded_bytes,
            ffmpeg_path=ffmpeg_path,
        )
        return NormalizedAudio(
            data=wav_bytes,
            filename=_rewrite_filename(filename, ".wav"),
            mime_type="audio/wav",
            source_format=detected,
            transcoded=True,
        )

    passthrough = _PASSTHROUGH_FORMATS.get(detected)
    if passthrough is not None:
        normalized_mime, suffix = passthrough
        return NormalizedAudio(
            data=audio_bytes,
            filename=_rewrite_filename(filename, suffix),
            mime_type=normalized_mime,
            source_format=detected,
            transcoded=False,
        )

    raise GenerationProviderError("无法识别的音频格式（非有效音频数据），跳过 ASR")


async def normalize_audio_for_asr(
    audio_bytes: bytes,
    *,
    filename: str = "voice",
    max_audio_bytes: int = DEFAULT_ASR_MAX_AUDIO_BYTES,
    max_decoded_bytes: int = DEFAULT_ASR_MAX_DECODED_BYTES,
    sample_rate: int = TARGET_WAV_SAMPLE_RATE,
    ffmpeg_path: str | None = None,
) -> NormalizedAudio:
    """将原始语音字节按魔数归一化为 ASR 可接受的音频载荷。

    所有解码、校验与临时文件操作均在工作线程与隔离临时目录内执行，不阻塞事件循环。
    """
    return await asyncio.to_thread(
        _normalize_sync,
        audio_bytes,
        filename=filename,
        max_audio_bytes=max_audio_bytes,
        max_decoded_bytes=max_decoded_bytes,
        sample_rate=sample_rate,
        ffmpeg_path=ffmpeg_path,
    )


__all__ = [
    "AMR_NB_MAGIC",
    "AMR_WB_MAGIC",
    "DEFAULT_ASR_MAX_AUDIO_BYTES",
    "DEFAULT_ASR_MAX_DECODED_BYTES",
    "NormalizedAudio",
    "SILK_MAGIC",
    "TARGET_WAV_CHANNELS",
    "TARGET_WAV_SAMPLE_RATE",
    "TARGET_WAV_SAMPLE_WIDTH",
    "TENCENT_SILK_MAGIC",
    "detect_audio_format",
    "normalize_audio_for_asr",
    "validate_amr_stream",
    "validate_silk_stream",
    "validate_wav_bytes",
]
