"""QuickQuip Bot entrypoint with a configuration lifetime lease."""

from quickquip.common.env import PROJECT_ROOT
from quickquip.configuration.activity import service_guard


def main():
    with service_guard(PROJECT_ROOT, "bot"):
        import nonebot
        from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter
        from loguru import logger
        import plugins
        from quickquip.common.env import load_root_env_file
        from quickquip.configuration.migration import require_fresh_layout
        from quickquip.common.logging_bridge import install_stdlib_bridge

        # DEBUG configuration dumps can contain environment secrets.
        logger.add(
            "data/logs/quickquip_{time:YYYY-MM-DD}.log",
            rotation="00:00",
            retention="14 days",
            level="INFO",
            encoding="utf-8",
        )
        install_stdlib_bridge()
        load_root_env_file()
        require_fresh_layout(PROJECT_ROOT)
        nonebot.init()
        driver = nonebot.get_driver()
        driver.register_adapter(OneBotV11Adapter)
        nonebot.load_plugins(*plugins.__path__)
        nonebot.run()


if __name__ == "__main__":
    main()
