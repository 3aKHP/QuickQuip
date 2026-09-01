from __future__ import annotations

from quickquip.adapters.nonebot.commands import register_commands


class _FakeCommand:
    def handle(self):
        def deco(fn):
            return fn

        return deco

    async def finish(self, *args, **kwargs):
        raise AssertionError("finish should not be called during registration")

    async def send(self, *args, **kwargs):
        return None


class _FakeMessage(list):
    pass


class _FakeSegment:
    @staticmethod
    def text(value):
        return ("text", value)

    @staticmethod
    def image(value):
        return ("image", value)

    @staticmethod
    def record(value):
        return ("record", value)


def test_register_commands_keeps_command_count_and_order():
    registered = []

    def on_command(name, **kwargs):
        registered.append((name, kwargs))
        return _FakeCommand()

    register_commands(on_command, _FakeMessage, _FakeSegment)

    assert [name for name, _ in registered] == [
        "start_sesssion",
        "start_session",
        "end_session",
        "resume_session",
        "sessions",
        "delete_session",
        "stats",
        "turmfluch",
        "defectify",
        "llm",
        "search",
        "draw",
        "tts",
        "music",
        "tieba",
        "reset_stats",
        "tieba_peek",
        "disable",
        "enable",
        "rules",
        "reload_rules",
        "reload_personas",
        "remember",
        "memories",
        "forget",
        "forget_all",
        "tell",
        "tells",
        "untell",
        "roll",
        "choose",
        "fortune",
        "vote",
        "profile",
        "find",
        "quote",
        "game",
        "sign",
        "gold",
        "gold_rank",
        "注册牛牛",
        "注销牛牛",
        "我的牛牛",
        "打胶",
        "击剑",
        "牛牛长度排行",
        "牛牛长度总排行",
        "牛牛深度排行",
        "牛牛深度总排行",
        "牛牛总排行",
        "牛牛绝对值排行",
        "牛牛绝对值总排行",
        "我的牛牛战绩",
        "打胶运势",
        "击剑运势",
        "牛牛文案",
    ]
