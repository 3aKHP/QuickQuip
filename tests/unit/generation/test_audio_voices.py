from __future__ import annotations

import asyncio

from quickquip.generation.audio import list_available_voices
from quickquip.generation.config import AudioProviderConfig


def test_list_available_voices_parses_minimax_response(monkeypatch):
    async def fake_http_json(url, *, method, headers, payload, timeout):
        assert url == "https://example.test/v1/get_voice"
        assert method == "POST"
        assert payload == {"voice_type": "all"}
        return {
            "base_resp": {"status_code": 0},
            "system_voice": [
                {
                    "voice_id": "male-qn-qingse",
                    "voice_name": "青涩青年",
                    "description": ["中文", "男声"],
                }
            ],
            "voice_cloning": [],
            "voice_generation": [
                {
                    "voice_id": "gen-1",
                    "voice_name": "实验音色",
                    "description": ["自定义"],
                }
            ],
        }

    monkeypatch.setattr("quickquip.generation.audio._http_json", fake_http_json)
    monkeypatch.setattr("quickquip.generation.audio._get_api_key", lambda provider: "secret")

    provider = AudioProviderConfig(
        id="minimax-audio",
        protocol="minimax_t2a_http",
        base_url="https://example.test/v1",
        api_key_env="MINIMAX_API_KEY",
    )

    voices = asyncio.run(list_available_voices(provider))

    assert voices["system_voice"][0].voice_id == "male-qn-qingse"
    assert voices["system_voice"][0].voice_name == "青涩青年"
    assert voices["voice_generation"][0].voice_id == "gen-1"

