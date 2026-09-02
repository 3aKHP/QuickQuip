import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter
from loguru import logger

import plugins
from quickquip.common.env import load_root_env_file
from quickquip.common.logging_bridge import install_stdlib_bridge

logger.add(
    "data/logs/quickquip_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="14 days",
    # INFO 以上才落盘：nonebot init 的 DEBUG 配置 dump 含 .env 全部密钥
    # （含 API key 与 WEB_ADMIN_PASSWORD），不得写入文件日志。
    level="INFO",
    encoding="utf-8",
)

# stdlib logging 桥接进 loguru：quickquip.* 的 INFO 观测行（LLM 链路等）
# 才能进入 stdout 与文件槽。桥接级别同样守住 INFO 下限，理由同上。
install_stdlib_bridge()

load_root_env_file()
nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

nonebot.load_plugins(*plugins.__path__)

if __name__ == "__main__":
    nonebot.run()
