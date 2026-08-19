"""跨域共享常量。

只放纯常量：本模块不得产生任何 import 副作用（文件 IO、配置解析等），
供 chat/llm/app 等域零成本复用。
"""
from __future__ import annotations

# 项目统计与展示统一使用的业务时区（北京时间为准）。
BEIJING_TIMEZONE = "Asia/Shanghai"
