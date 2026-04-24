from __future__ import annotations

import asyncio

from quickquip.generation.config import MusicModelConfig, MusicProviderConfig
from quickquip.generation.music import generate_lyrics, generate_music


def test_generate_lyrics_minimax(monkeypatch):
    async def fake_http_json(url, *, method, headers, payload, timeout):
        assert url == "https://example.test/v1/lyrics_generation"
        assert method == "POST"
        assert payload["mode"] == "write_full_song"
        assert payload["prompt"] == "夏日海边"
        assert payload["title"] == "海风约定"
        return {
            "song_title": "海风约定",
            "style_tags": "Mandopop, Summer",
            "lyrics": "[Verse]\n海风吹",
            "base_resp": {"status_code": 0},
        }

    provider = MusicProviderConfig(
        id="minimax-music",
        protocol="minimax_music",
        base_url="https://example.test/v1",
        api_key_env="MINIMAX_API_KEY",
    )

    monkeypatch.setattr("quickquip.generation.music._http_json", fake_http_json)
    monkeypatch.setattr("quickquip.generation.music._get_api_key", lambda provider: "secret")

    result = asyncio.run(
        generate_lyrics(provider, "夏日海边", mode="write_full_song", title="海风约定")
    )

    assert result.title == "海风约定"
    assert result.style_tags == "Mandopop, Summer"
    assert result.lyrics == "[Verse]\n海风吹"


def test_generate_music_minimax_hex(monkeypatch):
    async def fake_http_json(url, *, method, headers, payload, timeout):
        assert url == "https://example.test/v1/music_generation"
        assert method == "POST"
        assert payload["model"] == "music-2.6"
        assert payload["prompt"] == "Mandopop, Summer"
        assert payload["lyrics"] == "[Verse]\n海风吹"
        assert payload["audio_setting"]["format"] == "mp3"
        assert payload["lyrics_optimizer"] is True
        return {
            "base_resp": {"status_code": 0},
            "data": {
                "audio": "68656c6c6f",
                "status": 2,
            },
            "extra_info": {"music_duration": 12345},
        }

    provider = MusicProviderConfig(
        id="minimax-music",
        protocol="minimax_music",
        base_url="https://example.test/v1",
        api_key_env="MINIMAX_API_KEY",
    )
    model = MusicModelConfig(
        id="minimax-music",
        model="music-2.6",
        format="mp3",
        lyrics_optimizer=True,
    )

    monkeypatch.setattr("quickquip.generation.music._http_json", fake_http_json)
    monkeypatch.setattr("quickquip.generation.music._get_api_key", lambda provider: "secret")

    result = asyncio.run(generate_music(model, provider, "Mandopop, Summer", lyrics="[Verse]\n海风吹"))

    assert result.audio_bytes == b"hello"
    assert result.mime_type == "audio/mpeg"
    assert result.extra_info == {"music_duration": 12345}
