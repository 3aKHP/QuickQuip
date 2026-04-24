from quickquip.generation.audio import VoiceInfo
from quickquip.generation.config import (
    AudioGenerationConfig,
    AudioModelConfig,
    AudioProviderConfig,
    ResolvedAudioModel,
)
from quickquip.adapters.nonebot.commands import _format_tts_models, _format_voice_groups


def test_format_tts_models_includes_default_and_voice():
    provider = AudioProviderConfig(
        id="minimax-audio",
        protocol="minimax_t2a_http",
        base_url="https://example.test/v1",
        api_key_env="MINIMAX_API_KEY",
    )
    resolved = ResolvedAudioModel(
        id="minimax-speech",
        provider=provider,
        model_config=AudioModelConfig(
            id="minimax-speech",
            model="speech-2.8-hd",
            label="MiniMax Speech 2.8 HD",
            voice_id="male-qn-qingse",
        ),
    )
    config = AudioGenerationConfig(
        enabled=True,
        default_model="minimax-speech",
        models={"minimax-speech": resolved},
    )

    text = _format_tts_models(config)

    assert "minimax-speech" in text
    assert "默认音色 male-qn-qingse" in text
    assert "默认" in text


def test_format_voice_groups_supports_keyword_filter():
    groups = {
        "system_voice": [
            VoiceInfo(voice_id="male-qn-qingse", voice_name="青涩青年", description=["中文男声"]),
            VoiceInfo(voice_id="female-yujie", voice_name="御姐", description=["中文女声"]),
        ],
        "voice_cloning": [],
        "voice_generation": [],
    }

    text = _format_voice_groups(groups, keyword="御姐")

    assert "female-yujie" in text
    assert "male-qn-qingse" not in text
