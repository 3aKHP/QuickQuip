"""公式「故障化」：把输入转写成读音贴近「故障机器人」的五字梗。

「故障机器人」是《杀戮尖塔》初始角色 Defect 的官方中文名，本公式与
``/turmfluch`` 同为尖塔梗。触发路径只有主动命令 ``/defectify``：
命令注册在 ``adapters/nonebot/command_parts/sts.py``，LLM 编排在
``LLMService.generate_defectify_reply``，prompt 在 ``prompting``。
"""
