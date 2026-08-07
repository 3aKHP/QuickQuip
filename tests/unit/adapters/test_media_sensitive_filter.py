from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from quickquip.adapters.nonebot.command_parts import media
from quickquip.common import sensitive_filter as sensitive_filter_module
from quickquip.common.sensitive_filter import DEFAULT_OUTPUT_FALLBACK, SensitiveFilter
from quickquip.generation.music import LyricsGenerationResult


class _CommandFinished(Exception):
    pass


class _FakeCommand:
    def __init__(self) -> None:
        self.handler_fn = None
        self.sent: list[object] = []

    def handle(self):
        def decorator(fn):
            self.handler_fn = fn
            return fn

        return decorator

    async def finish(self, value=None):
        raise _CommandFinished(value)

    async def send(self, value=None):
        self.sent.append(value)


class _FakeMessage(list):
    def __init__(self, text: str = "") -> None:
        super().__init__()
        self.text = text

    def __str__(self) -> str:
        return self.text


class _FakeSegment:
    @staticmethod
    def image(value):
        return ("image", value)

    @staticmethod
    def record(value):
        return ("record", value)


class _FakeEvent:
    user_id = 2002
    group_id = 1001
    reply = None

    def __init__(self, text: str) -> None:
        self._message = _FakeMessage(text)

    def get_message(self):
        return self._message


def _filter(tmp_path, section: str, word: str = "blocked") -> SensitiveFilter:
    path = tmp_path / f"{section}.toml"
    path.write_text(
        f'[{section}.test]\nwords = ["{word}"]\n',
        encoding="utf-8",
    )
    return SensitiveFilter.from_toml(path)


def _generation_config():
    resolved = SimpleNamespace(
        id="default",
        model_config=SimpleNamespace(),
        provider=SimpleNamespace(),
    )

    def section():
        return SimpleNamespace(
            enabled=True,
            models={"default": SimpleNamespace()},
            default_model="default",
            prompt_blocklist=[],
            resolve_model=lambda model_id=None: (
                resolved if model_id in {None, "default"} else None
            ),
        )

    return SimpleNamespace(
        load_error="",
        image=section(),
        audio=section(),
        music=section(),
    )


def _register(monkeypatch, sensitive_filter: SensitiveFilter):
    commands: dict[str, _FakeCommand] = {}

    def on_command(name, **kwargs):
        command = _FakeCommand()
        commands[name] = command
        return command

    monkeypatch.setattr(media.generation_service, "get_config", _generation_config)
    monkeypatch.setattr(media.rate_limiter, "allow", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        sensitive_filter_module,
        "get_filter",
        lambda: sensitive_filter,
    )
    media.register_media_commands(on_command, _FakeMessage, _FakeSegment)
    return commands


@pytest.mark.parametrize(
    ("command_name", "message", "provider_function"),
    [
        ("draw", "/draw blocked", "generate_image"),
        ("tts", "/tts blocked", "generate_audio"),
        ("music", "/music blocked", "generate_music"),
    ],
)
async def test_generation_input_block_stops_provider_call(
    monkeypatch,
    tmp_path,
    command_name,
    message,
    provider_function,
):
    commands = _register(monkeypatch, _filter(tmp_path, "block"))
    provider_call = AsyncMock()
    monkeypatch.setattr(media, provider_function, provider_call)

    with pytest.raises(_CommandFinished) as exc_info:
        await commands[command_name].handler_fn(object(), _FakeEvent(message))

    assert "不允许" in str(exc_info.value.args[0])
    provider_call.assert_not_awaited()


def test_generation_soft_hit_and_unloaded_filter_do_not_block(monkeypatch, tmp_path):
    event = _FakeEvent("unused")
    monkeypatch.setattr(
        sensitive_filter_module,
        "get_filter",
        lambda: _filter(tmp_path, "soft"),
    )
    assert not media._sensitive_text_blocked(
        event,
        "contains blocked text",
        "generation_input:test",
    )

    monkeypatch.setattr(sensitive_filter_module, "get_filter", SensitiveFilter.empty)
    assert not media._sensitive_text_blocked(
        event,
        "contains blocked text",
        "generation_input:test",
    )


async def test_generated_lyrics_block_stops_music_provider_and_user_output(
    monkeypatch,
    tmp_path,
):
    commands = _register(monkeypatch, _filter(tmp_path, "block"))
    monkeypatch.setattr(
        media,
        "generate_lyrics",
        AsyncMock(return_value=LyricsGenerationResult(lyrics="blocked lyrics")),
    )
    generate_music = AsyncMock()
    send_lyrics = AsyncMock()
    monkeypatch.setattr(media, "generate_music", generate_music)
    monkeypatch.setattr(media, "_send_lyrics_forward", send_lyrics)

    with pytest.raises(_CommandFinished) as exc_info:
        await commands["music"].handler_fn(object(), _FakeEvent("/music safe theme"))

    assert exc_info.value.args[0] == DEFAULT_OUTPUT_FALLBACK
    generate_music.assert_not_awaited()
    send_lyrics.assert_not_awaited()
