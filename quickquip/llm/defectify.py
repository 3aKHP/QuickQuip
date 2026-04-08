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
你现在只执行一个特定任务：把输入内容转写成一个读音接近“故障机器人”的五字别名。

要求：
1. 输出先给出一个五个汉字的结果，整体读音要明显贴近“故障机器人”。
2. 然后另起一行，以“笑点解析：”开头，解释这五个字为什么能对应输入内容。
3. 解析必须让人看得出这五个字都能从输入素材里找到语义落点，不能空转。
4. 最后一句固定写“令人忍俊不禁。”
5. 不要输出 JSON，不要输出代码块，不要输出多余前言。
6. 解析必须简短，控制在 70 个汉字以内，尽量一整句说完。

强约束：
- 每个字都必须对应输入中的一个具体信息点，例如人物、事件、时间、情绪、动作、评价、场景、画面元素、群聊语境。
- 禁止把“它和故障机器人的原字同音/近音”当作该字的主要解释。
- 禁止写“障对应障”“机对应机”“其对应期”这类无信息量废话。
- 禁止拿谐音本身当语义来源，必须解释这个字为什么适合输入内容，而不是为什么适合故障机器人这五个音。
- 如果某个字找不到来自输入的合理解释，就必须换字，宁可换一个更贴语义的近音字。
- 优先选择能和输入形成笑点的语义映射，而不是最直白的机械对音。

推荐步骤：
- 先从素材里抽出五个最适合拿来做梗的点。
- 再把这五个点分别塞进 gu / zhang / ji / qi / ren 这五个音槽。
- 最后用一整段自然语言解释，不要逐字机械复述，不要写成字典释义。

参考社区语感：
- 故障机器人
- 固障祭砌人
- 蛊瘴急弃人
- 故障叽器人

反例：
- 差的解释：“障对应障，机对应机。”
- 差的解释：“其对应期，因为生日是日期。”
- 好的解释应该像：“第2字借‘障/胀/账/章’去接住卡壳、排场、记账、寿章这类原句里真的存在的意思。”
""".strip()

    lines = ["请根据下面的素材完成转写。"]
    if normalized_prompt:
        lines.append(f"当前用户提供的文字：{normalized_prompt}")
    else:
        lines.append("当前用户没有补充文字。")
    if normalized_image_urls:
        lines.append(f"当前用户附带图片：{len(normalized_image_urls)} 张，请直接理解图片内容。")
    if normalized_quoted_text or normalized_quoted_image_urls:
        speaker = quoted_sender_name.strip() or quoted_user_id.strip() or "未知用户"
        lines.append(f"用户还引用了一条消息，发送者：{speaker}")
        if normalized_quoted_text:
            lines.append(f"引用文字：{normalized_quoted_text}")
        if normalized_quoted_image_urls:
            lines.append(f"引用附图：{len(normalized_quoted_image_urls)} 张，请一并理解。")
    lines.append("请先确保五个字都能被原输入解释，再考虑读音贴近。不要为了凑音牺牲解释力。")
    lines.append("请直接给出最终结果，不要解释你的思考过程。")

    return DefectifyPrompt(
        system_prompt=system_prompt,
        user_prompt="\n".join(lines),
    )
