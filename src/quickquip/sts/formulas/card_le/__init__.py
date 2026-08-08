"""公式「xxx了」：卡牌/遗物名 + 了。

两条触发路径：
- 被动（``passive``）：群友发言里整句「X了」未命中词表时，LLM 找最近真名回复。
- 主动：``/turmfluch`` 命令。命令注册在 ``adapters/nonebot/command_parts/sts.py``，
  LLM 编排在 ``LLMService.generate_turmfluch_reply``，prompt 在 ``prompting``。
"""
