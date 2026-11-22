"""SILK 音频解码 worker：以 ``python -m`` 独立子进程执行受限解码。

以 ``python -m quickquip.generation.audio_worker`` 方式调用，将第三方 C 扩展
（``pilk_nogil``）的解析与解码隔离在短命子进程内：

- argv：``input_path output_path sample_rate max_decoded_bytes as_limit_bytes cpu_seconds``
- rlimit 在导入 ``pilk_nogil`` 之前生效（POSIX 平台）；畸形帧引发的段错误、
  异常中止或超限不会影响机器人主进程。
- 解码后的 16-bit 单声道 PCM 写入 ``output_path``（标准 WAV 头），避开底层 C SDK
  向 stdout 打印诊断信息对二进制数据的干扰。
- 退出码：``0`` 成功；``2`` 解码结果超过 ``max_decoded_bytes``；``1`` 其他失败。
"""

from __future__ import annotations

from pathlib import Path
import sys
import wave

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_TOO_LARGE = 2

_WAV_HEADER_BYTES = 44
_WAV_CHANNELS = 1
_WAV_SAMPLE_WIDTH = 2


def _apply_limits(as_limit_bytes: int, cpu_seconds: int) -> None:
    """在导入解码库之前应用 POSIX rlimit；非 POSIX 平台静默跳过。"""
    if as_limit_bytes <= 0 and cpu_seconds <= 0:
        return
    try:
        import resource
    except ImportError:
        return
    if as_limit_bytes > 0:
        resource.setrlimit(resource.RLIMIT_AS, (as_limit_bytes, as_limit_bytes))
    if cpu_seconds > 0:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 6:
        sys.stderr.write(
            "ERR usage: audio_worker input_path output_path sample_rate "
            "max_decoded_bytes as_limit_bytes cpu_seconds\n"
        )
        return EXIT_ERROR

    input_path_arg, output_path_arg, sample_rate_arg, max_decoded_arg, as_limit_arg, cpu_arg = args
    try:
        sample_rate = int(sample_rate_arg)
        max_decoded_bytes = int(max_decoded_arg)
        as_limit_bytes = int(as_limit_arg)
        cpu_seconds = int(cpu_arg)
    except ValueError as exc:
        sys.stderr.write(f"ERR invalid arguments: {exc}\n")
        return EXIT_ERROR

    if sample_rate <= 0 or max_decoded_bytes <= _WAV_HEADER_BYTES:
        sys.stderr.write("ERR invalid sample_rate or max_decoded_bytes\n")
        return EXIT_ERROR

    _apply_limits(as_limit_bytes, cpu_seconds)

    try:
        import pilk_nogil

        silk_bytes = Path(input_path_arg).read_bytes()
        pcm_data = pilk_nogil.decode(silk_bytes, None, pcm_rate=sample_rate)
        if not isinstance(pcm_data, (bytes, bytearray)) or not pcm_data:
            sys.stderr.write("ERR empty decoded PCM output\n")
            return EXIT_ERROR
        if len(pcm_data) % _WAV_SAMPLE_WIDTH != 0:
            sys.stderr.write("ERR unaligned PCM sample width\n")
            return EXIT_ERROR
        if len(pcm_data) + _WAV_HEADER_BYTES > max_decoded_bytes:
            sys.stderr.write(
                f"ERR decoded audio exceeds limit: {len(pcm_data) + _WAV_HEADER_BYTES} "
                f"> {max_decoded_bytes}\n"
            )
            return EXIT_TOO_LARGE

        output_path = Path(output_path_arg)
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(_WAV_CHANNELS)
            wav_file.setsampwidth(_WAV_SAMPLE_WIDTH)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_data)

        if output_path.stat().st_size > max_decoded_bytes:
            sys.stderr.write("ERR written WAV exceeds max_decoded_bytes\n")
            return EXIT_TOO_LARGE
        return EXIT_OK
    except BaseException as exc:  # noqa: BLE001 — worker 异常仅通过 stderr 上报
        sys.stderr.write(f"ERR {type(exc).__name__}: {exc}\n")
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
