import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter
from loguru import logger

logger.add(
    "data/logs/quickquip_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="14 days",
    level="DEBUG",
    encoding="utf-8",
)

nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

nonebot.load_plugins("plugins")

if __name__ == "__main__":
    nonebot.run()