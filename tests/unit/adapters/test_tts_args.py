from quickquip.adapters.nonebot.commands import _parse_tts_args


def test_parse_tts_args_with_model_and_voice():
    model_id, voice_id, text = _parse_tts_args(
        'minimax-speech --voice female-yujie "你好 世界"',
        {"minimax-speech"},
    )

    assert model_id == "minimax-speech"
    assert voice_id == "female-yujie"
    assert text == "你好 世界"


def test_parse_tts_args_without_model():
    model_id, voice_id, text = _parse_tts_args(
        "--voice male-qn-qingse 这是测试",
        {"minimax-speech"},
    )

    assert model_id is None
    assert voice_id == "male-qn-qingse"
    assert text == "这是测试"
