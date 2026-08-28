import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter
from loguru import logger

import plugins
from quickquip.common.env import load_root_env_file

logger.add(
    "data/logs/quickquip_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="14 days",
    # INFO 以上才落盘：nonebot init 的 DEBUG 配置 dump 含 .env 全部密钥
    # （含 API key 与 WEB_ADMIN_PASSWORD），不得写入文件日志。
    level="INFO",
    encoding="utf-8",
)

load_root_env_file()
nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

nonebot.load_plugins(*plugins.__path__)

if __name__ == "__main__":
    nonebot.run()
