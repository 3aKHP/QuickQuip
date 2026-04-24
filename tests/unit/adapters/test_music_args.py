from quickquip.adapters.nonebot.commands import _parse_music_args


def test_parse_music_args_for_generation_with_model_and_lyrics():
    parsed = _parse_music_args(
        'minimax-music --title "海边晚风" --lyrics "[Verse]\\n海风轻吹" 独立民谣',
        {"minimax-music"},
    )

    assert parsed.action == "generate"
    assert parsed.model_id == "minimax-music"
    assert parsed.title == "海边晚风"
    assert parsed.lyrics == "[Verse]\\n海风轻吹"
    assert parsed.prompt == "独立民谣"
    assert parsed.instrumental is False


def test_parse_music_args_for_lyrics_edit():
    parsed = _parse_music_args(
        'lyrics edit --title 夏夜小调 保持副歌更洗脑',
        {"minimax-music"},
    )

    assert parsed.action == "lyrics_edit"
    assert parsed.title == "夏夜小调"
    assert parsed.prompt == "保持副歌更洗脑"


def test_parse_music_args_for_instrumental():
    parsed = _parse_music_args(
        "--instrumental synthwave night drive",
        {"minimax-music"},
    )

    assert parsed.action == "generate"
    assert parsed.instrumental is True
    assert parsed.prompt == "synthwave night drive"
