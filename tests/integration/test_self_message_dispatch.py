"""自消息必须在真实 NoneBot 调度中先于命令和消息管线终止。"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_self_messages_are_isolated_from_commands_and_message_pipeline(tmp_path):
    source_dir = Path(__file__).resolve().parents[2] / "src"
    script = textwrap.dedent(
        """
        import asyncio
        from pathlib import Path
        import sys
        from unittest.mock import AsyncMock, patch

        sys.path.insert(0, sys.argv[1])
        import quickquip.common.env as quickquip_env

        quickquip_env.PROJECT_ROOT = Path.cwd()
        quickquip_env._ROOT_ENV_LOADED = True
        (Path.cwd() / "data").mkdir()

        import nonebot

        nonebot.init(driver="~fastapi", command_start={"/"}, log_level="WARNING")

        from nonebot.adapters.onebot.v11 import Adapter, Bot
        import quickquip.adapters.nonebot.group_messages as group_messages
        import quickquip.adapters.nonebot.tz_tracker_plugin


        def payload(*, post_type, message_type, user_id, message_id, text, role="member"):
            data = {
                "post_type": post_type,
                "message_type": message_type,
                "sub_type": "normal" if message_type == "group" else "friend",
                "time": 1_700_000_000,
                "self_id": 123456789,
                "user_id": user_id,
                "message_id": message_id,
                "font": 0,
                "message": [{"type": "text", "data": {"text": text}}],
                "raw_message": text,
                "sender": {
                    "user_id": user_id,
                    "nickname": "QuickQuip" if user_id == 123456789 else "User",
                    "card": "",
                    "role": role,
                },
            }
            if message_type == "group":
                data["group_id"] = 10001
            return data


        async def main():
            adapter = Adapter(nonebot.get_driver())
            bot = Bot(adapter, "123456789")
            archived = []
            send = AsyncMock(return_value={"message_id": 9001})
            resolve = AsyncMock()

            events = [
                payload(post_type="message_sent", message_type="group", user_id=123456789,
                        message_id=1, text="/roll 1d6"),
                payload(post_type="message_sent", message_type="group", user_id=123456789,
                        message_id=2, text="/reload_rules", role="admin"),
                payload(post_type="message_sent", message_type="private", user_id=123456789,
                        message_id=3, text="/roll 1d6"),
            ]

            def record(*args, **kwargs):
                archived.append((args, kwargs))
                return True

            with patch.object(Bot, "send", send), \
                    patch.object(group_messages, "record_chat_message", record), \
                    patch.object(group_messages, "resolve_reply", resolve):
                for raw_event in events:
                    await bot.handle_event(Adapter.json_to_event(raw_event))

                assert send.await_count == 0
                assert resolve.await_count == 0
                assert len(archived) == 2
                assert [entry[1]["message_id"] for entry in archived] == ["1", "2"]

                await bot.handle_event(Adapter.json_to_event(payload(
                    post_type="message", message_type="group", user_id=20001,
                    message_id=4, text="/roll 1d6",
                )))
                assert send.await_count == 1
                assert resolve.await_count == 0

                await bot.handle_event(Adapter.json_to_event(payload(
                    post_type="message", message_type="group", user_id=20002,
                    message_id=5, text="/disable no-such-rule", role="admin",
                )))
                assert send.await_count == 2
                assert resolve.await_count == 0

                def fail_record(*args, **kwargs):
                    raise RuntimeError("archive unavailable")

                with patch.object(group_messages, "record_chat_message", fail_record):
                    await bot.handle_event(Adapter.json_to_event(payload(
                        post_type="message_sent", message_type="group", user_id=123456789,
                        message_id=6, text="/roll 1d6",
                    )))

                assert send.await_count == 2
                assert resolve.await_count == 0


        asyncio.run(main())
        """
    )

    child_env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONIOENCODING": "utf-8",
    }
    result = subprocess.run(
        [sys.executable, "-c", script, str(source_dir)],
        cwd=tmp_path,
        env=child_env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
