from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class DefectifyPrompt:
    system_prompt: str
    user_prompt: str


def build_defectify_prompt(
    *,
    prompt: str,
    image_urls: list[str] | None = None,
    quoted_text: str = "",
    quoted_image_urls: list[str] | None = None,
    quoted_sender_name: str = "",
    quoted_user_id: str = "",
) -> DefectifyPrompt:
    normalized_prompt = prompt.strip()
    normalized_image_urls = [url.strip() for url in (image_urls or []) if url.strip()]
    normalized_quoted_text = quoted_text.strip()
    normalized_quoted_image_urls = [url.strip() for url in (quoted_image_urls or []) if url.strip()]

    system_prompt = """
你执行"故障化"任务：把任意输入内容转写为五个汉字，读音依次贴近「故·障·机·器·人」的五个音，同时每个字须从输入里取得语义落点。

五个音槽及候选字（以下仅列常用字，不必局限于此）：
- 槽1 [gu]：故 固 顾 孤 蛊 骨 鼓 估 菇 …
- 槽2 [zhang]：障 账 涨 胀 仗 章 掌 张 脏 …
- 槽3 [ji]：机 鸡 迹 计 记 寄 积 急 击 疾 籍 …
- 槽4 [qi]：器 气 弃 骑 欺 乞 泣 期 齐 戚 …
- 槽5 [ren]：人 忍 认 刃 任 韧 润 仁 仍 …

语音匹配原则（宽松）：声调不限；声母 n/l 可互换；韵母前鼻（an/en/in）与后鼻（ang/eng/ing）可互换；总体形近音近即可。

选字步骤：
1. 先从输入里提炼 5 个有梗的点（人物/动作/情绪/结果/场景/物品/评价等）；
2. 把 5 个点逐一分配给 5 个音槽；
3. 在该槽候选字里选语义最贴合的字；候选字均不合适时可另选近音字。

输出格式（仅输出以下两行，不要其他内容）：
[五字]
笑点解析：[一句自然语言，串联五字如何命中输入，不超过 80 字]

示例1
素材：小偷
孤赃极乞润
笑点解析：孤身作案，一路攒赃，极品乞讨路线的终极实践，案发后润走——五字走完了一趟完整的偷窃职业规划。

示例2
素材：真菌兽（蘑菇）
菇仗寄气人
笑点解析：菇字本尊亲自下场，仗着腐木寄生，浑身散发菌气，真菌兽就这么被收编进了人字结尾的五字组合。

示例3
素材：刚被邻居在电梯里认出来，就是昨晚打游戏吵到凌晨三点的那个
孤张迹气认
笑点解析：孤身进电梯，那张昨夜吵到凌晨的脸就这么被认出来了，行迹当场败露，气氛凝固，只剩一个认字和漫长的七楼。

约束：
- 每个字的解释必须来自输入内容，禁止以"与原字同音/近音"为语义理由；
- 禁止输出 JSON、代码块、多余前言或思考过程。
""".strip()

    lines = ["素材如下，请按格式输出，不要输出思考过程。"]
    if normalized_prompt:
        lines.append(f"文字：{normalized_prompt}")
    if normalized_image_urls:
        lines.append(f"图片：{len(normalized_image_urls)} 张，请直接分析图片内容作为素材。")
    if normalized_quoted_text or normalized_quoted_image_urls:
        speaker = quoted_sender_name.strip() or quoted_user_id.strip() or "未知用户"
        lines.append(f"引用（{speaker}）：")
        if normalized_quoted_text:
            lines.append(normalized_quoted_text)
        if normalized_quoted_image_urls:
            lines.append(f"引用附图：{len(normalized_quoted_image_urls)} 张，请一并理解。")

    return DefectifyPrompt(
        system_prompt=system_prompt,
        user_prompt="\n".join(lines),
    )
