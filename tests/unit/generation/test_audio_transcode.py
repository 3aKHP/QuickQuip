from __future__ import annotations

import asyncio
import io
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import wave

import pilk_nogil
import pytest

from quickquip.generation import audio_worker
from quickquip.generation.audio_transcode import (
    AMR_NB_MAGIC,
    AMR_WB_MAGIC,
    MAX_TRANSCODE_CONCURRENCY,
    SILK_MAGIC,
    TARGET_WAV_CHANNELS,
    TARGET_WAV_SAMPLE_RATE,
    TARGET_WAV_SAMPLE_WIDTH,
    TENCENT_SILK_MAGIC,
    _ffmpeg_env,
    _worker_env,
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


def _make_silk_bytes(*, tencent: bool, duration_s: float = 0.2, use_dtx: bool = False) -> bytes:
    if use_dtx:
        tone = _make_sine_pcm(sample_rate=24000, duration_s=0.3)
        silence = b"\x00" * (24000 * 2)  # 1.0s silence triggers DTX 0-byte frames
        pcm = tone + silence + tone
        return pilk_nogil.encode(pcm, None, pcm_rate=24000, tencent=tencent, use_dtx=True)
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
async def test_normalize_silk_dtx_zero_length_frames_roundtrip():
    """真实移动客户端开启 DTX 会在停顿处产出 0 字节帧，必须正常校验并解码。"""
    silk_dtx = _make_silk_bytes(tencent=True, use_dtx=True)
    # 确认样本确实包含至少一个 0 字节 DTX 帧，避免测试未触发目标路径
    pos = len(TENCENT_SILK_MAGIC)
    zero_frames = 0
    while pos + 2 <= len(silk_dtx):
        (flen,) = struct.unpack_from("<h", silk_dtx, pos)
        pos += 2
        if flen == -1:
            break
        if flen == 0:
            zero_frames += 1
        pos += flen
    assert zero_frames > 0

    result = await normalize_audio_for_asr(silk_dtx, filename="pause.amr")
    assert result.transcoded is True
    assert result.source_format == "tencent_silk"
    channels, sampwidth, framerate, nframes = validate_wav_bytes(
        result.data,
        expected_sample_rate=16000,
        expected_channels=1,
        expected_sample_width=2,
    )
    assert (channels, sampwidth, framerate) == (1, 2, 16000)
    assert nframes == 25600  # 1.6s @ 16 kHz
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
        TENCENT_SILK_MAGIC + b"\x00\x00",  # 全 0 字节 DTX 帧（无有效语音帧）
        TENCENT_SILK_MAGIC + b"\x00\x00" * 4,  # 全 0 字节无语音帧
        TENCENT_SILK_MAGIC + b"\xfe\xff",  # 非 -1 负长度
        TENCENT_SILK_MAGIC + (b"\x10\x00" + b"\xaa" * 16) * 4,  # 畸形帧触发 SDK 解码报错
        _make_silk_bytes(tencent=False) + b"\x00",  # EOF 标记后多余字节
    ],
)
async def test_normalize_rejects_non_audio_and_corrupted_silk(bad_payload: bytes):
    with pytest.raises(GenerationProviderError):
        await normalize_audio_for_asr(bad_payload, filename="voice.silk")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_amr",
    [
        AMR_NB_MAGIC,
        AMR_NB_MAGIC + b"\x80" + b"\x00" * 12,  # 非法保留位
        AMR_NB_MAGIC + b"\x4c" + b"\x00" * 12,  # 保留 FT=9
        AMR_NB_MAGIC + b"\x3c" + b"\x00" * 5,  # 帧截断
        AMR_WB_MAGIC,
        AMR_WB_MAGIC + b"\x54" + b"\x00" * 17,  # 保留 FT=10
    ],
)
async def test_malformed_amr_rejected_before_invoking_ffmpeg(
    bad_amr: bytes,
    monkeypatch: pytest.MonkeyPatch,
):
    """损坏 AMR 必须在校验阶段被拒，绝不能被缺 ffmpeg 分支掩盖或进入子进程。"""
    with pytest.raises(GenerationProviderError):
        validate_amr_stream(bad_amr)

    def forbid_subprocess(*args, **kwargs):
        raise AssertionError("畸形 AMR 不得调用 ffmpeg 子进程")

    monkeypatch.setattr("quickquip.generation.audio_transcode.subprocess.run", forbid_subprocess)
    with pytest.raises(GenerationProviderError):
        await normalize_audio_for_asr(bad_amr, filename="voice.amr", ffmpeg_path="/fake/ffmpeg")


@pytest.mark.asyncio
async def test_normalize_enforces_input_and_decoded_size_limits():
    silk_bytes = _make_silk_bytes(tencent=True, duration_s=0.2)

    with pytest.raises(GenerationProviderError, match="过大"):
        await normalize_audio_for_asr(silk_bytes, max_audio_bytes=len(silk_bytes) - 1)

    # 0.2s @ 16kHz 16-bit mono = 6444 bytes WAV；设置小于该值触发解码上限
    with pytest.raises(GenerationProviderError, match="上限"):
        await normalize_audio_for_asr(silk_bytes, max_decoded_bytes=2000)


def test_stream_validators_short_circuit_on_excessive_frames():
    """超额帧数必须在扫描循环内提前短路，不应扫完全部畸形大载荷。"""
    amr_bomb = AMR_NB_MAGIC + bytes([0x7C]) * 200_000  # 200k NO_DATA frames
    with pytest.raises(GenerationProviderError, match="上限"):
        validate_amr_stream(amr_bomb, max_decoded_bytes=2000)

    silk_bomb = TENCENT_SILK_MAGIC + b"\x01\x00\x00" * 100_000
    with pytest.raises(GenerationProviderError, match="上限"):
        validate_silk_stream(silk_bomb, max_decoded_bytes=2000)


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
async def test_amr_transcode_via_ffmpeg_subprocess_args_and_tempdir_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """验证 AMR-NB/AMR-WB 的 ffmpeg 命令行参数契约、隔离目录输入字节、输出校验与目录清理。"""
    created_dirs: list[Path] = []
    real_tempdir = tempfile.TemporaryDirectory

    class TrackingTempDir:
        def __init__(self, *args, **kwargs):
            assert kwargs.get("ignore_cleanup_errors") is True
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
    expected_sample: list[bytes] = []

    def fake_subprocess_run(command, *, capture_output, timeout, env=None):
        assert command[0] == "/fake/ffmpeg"
        assert env is not None
        fmt_idx = command.index("-f")
        assert command[fmt_idx : fmt_idx + 3] == ["-f", "amr", "-i"]
        input_path = Path(command[fmt_idx + 3])
        assert input_path.parent == created_dirs[-1]
        assert input_path.read_bytes() == expected_sample[-1]
        assert ["-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-f", "wav"] == command[-9:-1]
        out_path = Path(command[-1])
        assert out_path.parent == created_dirs[-1]
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
        expected_sample.append(sample)
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
@pytest.mark.parametrize("failure_mode", ["nonzero", "timeout", "oversize"])
async def test_amr_ffmpeg_failure_modes_raise_and_clean_tempdir(
    failure_mode: str,
    monkeypatch: pytest.MonkeyPatch,
):
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

    def fake_run(command, *, capture_output, timeout, env=None):
        if failure_mode == "timeout":
            raise subprocess.TimeoutExpired(command, timeout)
        if failure_mode == "oversize":
            Path(command[-1]).write_bytes(_make_wav_bytes(sample_rate=16000, duration_s=0.2))

            class Ok:
                returncode = 0
                stdout = b""
                stderr = b""

            return Ok()

        class Failed:
            returncode = 1
            stdout = b""
            stderr = b"invalid amr stream"

        return Failed()

    monkeypatch.setattr("quickquip.generation.audio_transcode.subprocess.run", fake_run)

    with pytest.raises(GenerationProviderError):
        await normalize_audio_for_asr(
            _make_amr_nb_sample(frames=2),
            filename="voice.amr",
            max_decoded_bytes=4000,
            ffmpeg_path="/fake/ffmpeg",
        )

    assert len(created_dirs) == 1
    assert not created_dirs[0].exists()


def test_audio_worker_direct_too_large_exit_code_and_no_output(tmp_path: Path):
    """直接调用 worker 入口断言精确 EXIT_TOO_LARGE 退出码且不写出超限文件。"""
    in_path = tmp_path / "in.silk"
    out_path = tmp_path / "out.wav"
    in_path.write_bytes(_make_silk_bytes(tencent=True, duration_s=0.2))

    exit_code = audio_worker.main(
        [str(in_path), str(out_path), "16000", "1024", "0", "0"]
    )

    assert exit_code == audio_worker.EXIT_TOO_LARGE
    assert not out_path.exists()


@pytest.mark.asyncio
async def test_audio_worker_tempdir_oserror_converts_to_provider_error(
    monkeypatch: pytest.MonkeyPatch,
):
    """临时目录 I/O 失败（如磁盘满 ENOSPC）必须收口为 GenerationProviderError。"""

    def broken_tempdir(*args, **kwargs):
        raise OSError("No space left on device")

    monkeypatch.setattr(
        "quickquip.generation.audio_transcode.tempfile.TemporaryDirectory",
        broken_tempdir,
    )

    with pytest.raises(GenerationProviderError, match="临时文件"):
        await normalize_audio_for_asr(_make_silk_bytes(tencent=True), filename="seg.amr")


def test_subprocess_env_excludes_application_secrets(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-sentinel")
    monkeypatch.setenv("WEB_ADMIN_PASSWORD", "admin-secret-sentinel")
    monkeypatch.setenv("ONEBOT_ACCESS_TOKEN", "onebot-secret-sentinel")

    worker_env = _worker_env()
    ffmpeg_env = _ffmpeg_env()

    for secret_key in ("OPENAI_API_KEY", "WEB_ADMIN_PASSWORD", "ONEBOT_ACCESS_TOKEN"):
        assert secret_key not in worker_env
        assert secret_key not in ffmpeg_env
    assert "PYTHONPATH" in worker_env
    assert "PYTHONPATH" not in ffmpeg_env


def test_worker_clamp_rlimit_never_raises_above_current_hard_limit():
    applied: list[tuple[int, tuple[int, int]]] = []

    class FakeResource:
        RLIM_INFINITY = -1
        RLIMIT_AS = 9
        RLIMIT_CPU = 0

        @staticmethod
        def getrlimit(res_id: int) -> tuple[int, int]:
            if res_id == FakeResource.RLIMIT_AS:
                return (512 * 1024**2, 1024**3)  # 宿主机硬上限 1 GiB < 目标 2 GiB
            return (FakeResource.RLIM_INFINITY, 5)  # 宿主机 CPU 硬上限 5s < 目标 10s

        @staticmethod
        def setrlimit(res_id: int, limits: tuple[int, int]) -> None:
            applied.append((res_id, limits))

    audio_worker._clamp_rlimit(FakeResource, FakeResource.RLIMIT_AS, 2 * 1024**3, 2 * 1024**3)
    audio_worker._clamp_rlimit(FakeResource, FakeResource.RLIMIT_CPU, 10, 11)

    assert applied == [
        (FakeResource.RLIMIT_AS, (512 * 1024**2, 1024**3)),
        (FakeResource.RLIMIT_CPU, (5, 5)),
    ]


@pytest.mark.asyncio
async def test_concurrent_transcodes_do_not_block_event_loop_and_enforce_limit(
    monkeypatch: pytest.MonkeyPatch,
):
    """以同步屏障确定性验证：不阻塞事件循环、在途并发不超过上限、排队任务响应取消。"""
    wav_fixture = _make_wav_bytes(sample_rate=16000, duration_s=0.1)
    lock = threading.Lock()
    in_flight = 0
    max_in_flight = 0
    two_entered = threading.Event()
    release_gate = threading.Event()
    call_count = 0

    def gated_run(command, *, capture_output, timeout, env=None):
        nonlocal in_flight, max_in_flight, call_count
        with lock:
            in_flight += 1
            call_count += 1
            max_in_flight = max(max_in_flight, in_flight)
            if in_flight >= MAX_TRANSCODE_CONCURRENCY:
                two_entered.set()
        try:
            assert release_gate.wait(timeout=10.0), "等待事件循环放行超时（可能阻塞了事件循环）"
            # audio_worker argv: [py, -m, mod, input_path, output_path, ...]
            Path(command[4]).write_bytes(wav_fixture)

            class Ok:
                returncode = 0
                stdout = b""
                stderr = b""

            return Ok()
        finally:
            with lock:
                in_flight -= 1

    monkeypatch.setattr("quickquip.generation.audio_transcode.subprocess.run", gated_run)

    silk = _make_silk_bytes(tencent=True, duration_s=0.16)
    task1 = asyncio.create_task(normalize_audio_for_asr(silk, filename="s1.amr"))
    task2 = asyncio.create_task(normalize_audio_for_asr(silk, filename="s2.amr"))
    task3 = asyncio.create_task(normalize_audio_for_asr(silk, filename="s3.amr"))
    task4_cancelled = asyncio.create_task(normalize_audio_for_asr(silk, filename="s4.amr"))

    # 独立协程在事件循环上轮询，证明转码工作未阻塞事件循环
    ticks = 0
    while not two_entered.is_set() and ticks < 200:
        await asyncio.sleep(0.01)
        ticks += 1
    assert two_entered.is_set()
    assert max_in_flight == MAX_TRANSCODE_CONCURRENCY

    # 取消排队中的第 4 个任务，确认其立即退出且不会进入子进程
    task4_cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task4_cancelled

    release_gate.set()
    results = await asyncio.wait_for(asyncio.gather(task1, task2, task3), timeout=10.0)
    assert len(results) == 3
    assert all(item.transcoded and item.mime_type == "audio/wav" for item in results)
    assert max_in_flight == MAX_TRANSCODE_CONCURRENCY
    assert call_count == 3


def test_audio_worker_cli_usage_error():
    completed = subprocess.run(
        [sys.executable, "-m", "quickquip.generation.audio_worker"],
        capture_output=True,
        text=True,
        env=_worker_env(),
    )
    assert completed.returncode != 0
    assert "usage" in completed.stderr


def test_third_party_notices_included_in_deploy_manifest_and_dockerfiles():
    """防止生产 deploy-v4 缺文件构建失败：通知文件与 Dockerfile COPY 必须保持同步。"""
    repo_root = Path(__file__).resolve().parents[3]
    manifest_lines = {
        line.strip()
        for line in (repo_root / "scripts" / "deploy" / "deploy-manifest.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    for required in ("LICENSE", "THIRD-PARTY-NOTICES.md"):
        assert required in manifest_lines
        assert required in (repo_root / "Dockerfile").read_text(encoding="utf-8")
        assert required in (repo_root / "docker" / "Dockerfile.prod").read_text(encoding="utf-8")
