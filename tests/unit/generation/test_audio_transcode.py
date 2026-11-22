from __future__ import annotations

import asyncio
import io
import math
from pathlib import Path
import struct
import sys
import tempfile
import wave

import pilk_nogil
import pytest

from quickquip.generation.audio_transcode import (
    AMR_NB_MAGIC,
    AMR_WB_MAGIC,
    SILK_MAGIC,
    TARGET_WAV_CHANNELS,
    TARGET_WAV_SAMPLE_RATE,
    TARGET_WAV_SAMPLE_WIDTH,
    TENCENT_SILK_MAGIC,
    detect_audio_format,
    normalize_audio_for_asr,
    validate_amr_stream,
    validate_silk_stream,
    validate_wav_bytes,
)
from quickquip.generation.errors import GenerationProviderError


def _make_sine_pcm(sample_rate: int = 24000, duration_s: float = 0.2, freq: float = 440.0) -> bytes:
    count = int(sample_rate * duration_s)
    samples = [int(12000 * math.sin(2.0 * math.pi * freq * i / sample_rate)) for i in range(count)]
    return struct.pack(f"<{count}h", *samples)


def _make_wav_bytes(
    sample_rate: int = TARGET_WAV_SAMPLE_RATE,
    duration_s: float = 0.1,
) -> bytes:
    pcm = _make_sine_pcm(sample_rate=sample_rate, duration_s=duration_s)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(TARGET_WAV_CHANNELS)
        wav_file.setsampwidth(TARGET_WAV_SAMPLE_WIDTH)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)
    return buf.getvalue()


def _make_silk_bytes(*, tencent: bool, duration_s: float = 0.2) -> bytes:
    pcm = _make_sine_pcm(sample_rate=24000, duration_s=duration_s)
    return pilk_nogil.encode(pcm, None, pcm_rate=24000, tencent=tencent)


def _make_amr_nb_sample(frames: int = 4) -> bytes:
    # RFC 4867: FT=7 (12.2 kbps) -> TOC = (7 << 3) | 0x04 = 0x3C, payload = 31 bytes
    return AMR_NB_MAGIC + (bytes([0x3C]) + b"\x11" * 31) * frames


def _make_amr_wb_sample(frames: int = 4) -> bytes:
    # RFC 4867: FT=0 (6.60 kbps) -> TOC = (0 << 3) | 0x04 = 0x04, payload = 17 bytes
    return AMR_WB_MAGIC + (bytes([0x04]) + b"\x22" * 17) * frames


def _pcm_rms(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        frames = wav_file.readframes(wav_file.getnframes())
    samples = struct.unpack(f"<{len(frames) // 2}h", frames)
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (SILK_MAGIC + b"\x04\x001234", "silk"),
        (TENCENT_SILK_MAGIC + b"\x04\x001234", "tencent_silk"),
        (AMR_NB_MAGIC + b"\x3c" + b"\x00" * 31, "amr_nb"),
        (AMR_WB_MAGIC + b"\x04" + b"\x00" * 17, "amr_wb"),
        (_make_wav_bytes(), "wav"),
        (b"ID3\x03\x00\x00\x00\x00\x00\x10" + b"\x00" * 16, "mp3"),
        (b"\xff\xfb\x90\x00" + b"\x00" * 32, "mp3"),
        (b"OggS\x00\x02" + b"\x00" * 20, "ogg"),
        (b"fLaC\x00\x00\x00\x22" + b"\x00" * 20, "flac"),
        (b"\x00\x00\x00\x18ftypM4A ", "mp4"),
        (b"\x1a\x45\xdf\xa3\x9f\x42", "webm"),
        (b"<html>403 Forbidden</html>", "unknown"),
        (b"plain text audio", "unknown"),
        (b"", "unknown"),
    ],
)
def test_detect_audio_format_uses_magic_bytes(payload: bytes, expected: str):
    assert detect_audio_format(payload) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tencent", "expected_source", "input_name"),
    [
        (False, "silk", "record.amr"),
        (True, "tencent_silk", "download"),
        (True, "tencent_silk", "misleading.mp3"),
    ],
)
async def test_normalize_silk_decodes_to_valid_wav_ignoring_extension(
    tencent: bool,
    expected_source: str,
    input_name: str,
):
    silk_bytes = _make_silk_bytes(tencent=tencent, duration_s=0.2)

    result = await normalize_audio_for_asr(silk_bytes, filename=input_name)

    assert result.transcoded is True
    assert result.source_format == expected_source
    assert result.mime_type == "audio/wav"
    assert result.filename.endswith(".wav")
    channels, sampwidth, framerate, nframes = validate_wav_bytes(
        result.data,
        expected_sample_rate=TARGET_WAV_SAMPLE_RATE,
        expected_channels=TARGET_WAV_CHANNELS,
        expected_sample_width=TARGET_WAV_SAMPLE_WIDTH,
    )
    assert (channels, sampwidth, framerate) == (1, 2, 16000)
    assert nframes == 3200
    assert _pcm_rms(result.data) > 500.0


@pytest.mark.asyncio
async def test_normalize_passthrough_preserves_wav_and_mp3_bytes():
    wav_bytes = _make_wav_bytes(sample_rate=22050, duration_s=0.1)
    wav_result = await normalize_audio_for_asr(wav_bytes, filename="clip.bin")
    assert wav_result.transcoded is False
    assert wav_result.source_format == "wav"
    assert wav_result.data == wav_bytes
    assert wav_result.mime_type == "audio/wav"
    assert wav_result.filename == "clip.wav"

    mp3_bytes = b"ID3\x03\x00\x00\x00\x00\x00\x10" + b"\x00" * 32
    mp3_result = await normalize_audio_for_asr(mp3_bytes, filename="voice.silk")
    assert mp3_result.transcoded is False
    assert mp3_result.source_format == "mp3"
    assert mp3_result.data == mp3_bytes
    assert mp3_result.mime_type == "audio/mpeg"
    assert mp3_result.filename == "voice.mp3"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_payload",
    [
        b"",
        b"<html>403 Forbidden</html>",
        b"not audio at all",
        SILK_MAGIC,
        TENCENT_SILK_MAGIC,
        SILK_MAGIC + b"\xff\xff",
        SILK_MAGIC + b"\x10\x00" + b"\xaa" * 4,  # 帧截断
        TENCENT_SILK_MAGIC + b"\x00\x00",  # 非法 0 长度帧
        TENCENT_SILK_MAGIC + (b"\x10\x00" + b"\xaa" * 16) * 4,  # 畸形帧触发 SDK 解码报错
        _make_silk_bytes(tencent=False) + b"\x00",  # EOF 标记后多余字节
        AMR_NB_MAGIC,
        AMR_NB_MAGIC + b"\x80" + b"\x00" * 12,  # 非法保留位
        AMR_NB_MAGIC + b"\x4c" + b"\x00" * 12,  # 保留 FT=9
        AMR_NB_MAGIC + b"\x3c" + b"\x00" * 5,  # 帧截断
        AMR_WB_MAGIC + b"\x54" + b"\x00" * 17,  # 保留 FT=10
    ],
)
async def test_normalize_rejects_non_audio_and_corrupted_streams(bad_payload: bytes):
    with pytest.raises(GenerationProviderError):
        await normalize_audio_for_asr(bad_payload, filename="voice.amr", ffmpeg_path="")


@pytest.mark.asyncio
async def test_normalize_enforces_input_and_decoded_size_limits():
    silk_bytes = _make_silk_bytes(tencent=True, duration_s=0.2)

    with pytest.raises(GenerationProviderError, match="过大"):
        await normalize_audio_for_asr(silk_bytes, max_audio_bytes=len(silk_bytes) - 1)

    # 0.2s @ 16kHz 16-bit mono = 6444 bytes WAV；设置小于该值触发解码上限
    with pytest.raises(GenerationProviderError, match="上限"):
        await normalize_audio_for_asr(silk_bytes, max_decoded_bytes=2000)


@pytest.mark.asyncio
async def test_normalize_amr_skips_cleanly_when_ffmpeg_unavailable():
    for sample in (_make_amr_nb_sample(), _make_amr_wb_sample()):
        with pytest.raises(GenerationProviderError, match="ffmpeg"):
            await normalize_audio_for_asr(sample, filename="voice.amr", ffmpeg_path="")


def test_validate_amr_stream_accepts_rfc4867_nb_and_wb():
    assert validate_amr_stream(_make_amr_nb_sample(frames=3)) == ("amr_nb", 3)
    assert validate_amr_stream(_make_amr_wb_sample(frames=5)) == ("amr_wb", 5)


def test_validate_silk_stream_accepts_standard_and_tencent():
    assert validate_silk_stream(_make_silk_bytes(tencent=False))[0] == "silk"
    assert validate_silk_stream(_make_silk_bytes(tencent=True))[0] == "tencent_silk"


@pytest.mark.asyncio
async def test_amr_transcode_via_ffmpeg_subprocess_and_tempdir_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """验证 AMR-NB/AMR-WB 走任务级临时目录调 ffmpeg、校验 WAV 且事后清理临时目录。"""
    created_dirs: list[Path] = []
    real_tempdir = tempfile.TemporaryDirectory

    class TrackingTempDir:
        def __init__(self, *args, **kwargs):
            self._inner = real_tempdir(*args, **kwargs)
            created_dirs.append(Path(self._inner.name))

        def __enter__(self):
            return self._inner.__enter__()

        def __exit__(self, exc_type, exc, tb):
            return self._inner.__exit__(exc_type, exc, tb)

    monkeypatch.setattr(
        "quickquip.generation.audio_transcode.tempfile.TemporaryDirectory",
        TrackingTempDir,
    )

    wav_fixture = _make_wav_bytes(sample_rate=16000, duration_s=0.1)
    fixture_path = tmp_path / "fixture.wav"
    fixture_path.write_bytes(wav_fixture)

    def fake_subprocess_run(command, *, capture_output, timeout, env=None):
        assert "-f" in command and "amr" in command
        out_path = Path(command[-1])
        out_path.write_bytes(fixture_path.read_bytes())

        class Completed:
            returncode = 0
            stdout = b""
            stderr = b""

        return Completed()

    monkeypatch.setattr("quickquip.generation.audio_transcode.subprocess.run", fake_subprocess_run)

    for sample, expected_fmt in (
        (_make_amr_nb_sample(), "amr_nb"),
        (_make_amr_wb_sample(), "amr_wb"),
    ):
        result = await normalize_audio_for_asr(
            sample,
            filename="voice.bin",
            ffmpeg_path="/fake/ffmpeg",
        )
        assert result.transcoded is True
        assert result.source_format == expected_fmt
        assert result.mime_type == "audio/wav"
        assert result.filename == "voice.wav"
        assert validate_wav_bytes(result.data, expected_sample_rate=16000) == (1, 2, 16000, 1600)

    assert len(created_dirs) == 2
    assert created_dirs[0] != created_dirs[1]
    assert all(not path.exists() for path in created_dirs)


@pytest.mark.asyncio
async def test_audio_worker_enforces_decoded_limit_and_cleans_tempdir(
    monkeypatch: pytest.MonkeyPatch,
):
    """验证 worker 子进程自身在解码超限时返回超限退出码且临时目录被清理。"""
    created_dirs: list[Path] = []
    real_tempdir = tempfile.TemporaryDirectory

    class TrackingTempDir:
        def __init__(self, *args, **kwargs):
            self._inner = real_tempdir(*args, **kwargs)
            created_dirs.append(Path(self._inner.name))

        def __enter__(self):
            return self._inner.__enter__()

        def __exit__(self, exc_type, exc, tb):
            return self._inner.__exit__(exc_type, exc, tb)

    monkeypatch.setattr(
        "quickquip.generation.audio_transcode.tempfile.TemporaryDirectory",
        TrackingTempDir,
    )
    # 绕过 Python 侧最小帧估算预检，直达 worker 自身的 max_decoded_bytes 校验
    monkeypatch.setattr(
        "quickquip.generation.audio_transcode.validate_silk_stream",
        lambda data, **kwargs: ("tencent_silk", 10),
    )

    silk_bytes = _make_silk_bytes(tencent=True, duration_s=0.2)
    with pytest.raises(GenerationProviderError, match="上限"):
        await normalize_audio_for_asr(silk_bytes, max_decoded_bytes=1024)

    assert len(created_dirs) == 1
    assert not created_dirs[0].exists()


@pytest.mark.asyncio
async def test_concurrent_silk_transcodes_do_not_deadlock():
    """三并发 SILK 解码（并发闸门=2）必须全部完成且不阻塞事件循环。"""
    samples = [
        _make_silk_bytes(tencent=False, duration_s=0.16),
        _make_silk_bytes(tencent=True, duration_s=0.2),
        _make_silk_bytes(tencent=True, duration_s=0.16),
    ]
    results = await asyncio.wait_for(
        asyncio.gather(
            *(normalize_audio_for_asr(sample, filename="seg.amr") for sample in samples)
        ),
        timeout=30.0,
    )
    assert all(item.transcoded and item.mime_type == "audio/wav" for item in results)
    assert all(validate_wav_bytes(item.data, expected_sample_rate=16000)[3] > 0 for item in results)


def test_audio_worker_cli_usage_error():
    import subprocess

    completed = subprocess.run(
        [sys.executable, "-m", "quickquip.generation.audio_worker"],
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "usage" in completed.stderr
