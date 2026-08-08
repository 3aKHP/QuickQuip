"""「xxx了」公式的 LLM prompt 构造。

主动路径（/turmfluch）与被动路径（找最近真名）共用同一份合法名字清单
（活跃词表，已排除标准打防牌）。清单注入 system prompt：既约束模型只能从
清单里选名，又落在 system 段以利用 provider 的 prompt 缓存。
"""

from __future__ import annotations

from dataclasses import dataclass

from quickquip.sts import lexicon


@dataclass(slots=True)
class CardLePrompt:
    system_prompt: str
    user_prompt: str


# 活跃名字清单，一次性拼好复用（模块加载时词表已就绪）
_NAME_LIST = "\n".join(sorted(lexicon.NAMES))

_SYSTEM_PROMPT = f"""\
你执行"尖塔化"任务：读懂输入素材，从下方《杀戮尖塔》卡牌与遗物中文名清单里选出**唯一一个**最能概括或调侃这段情境的名字，并把输出写成「<名字>了」。

规则：
- 只能从清单里选名，严禁编造清单外的名字；
- 名字后必须紧跟"了"——例如清单含"疑虑"，则输出"疑虑了"；
- 只输出这一行「<名字>了」，不要解释、引号、标点或任何多余文字。

可选名字清单（每行一个）：
{_NAME_LIST}\
""".rstrip()


def _user_prompt(
    *,
    prompt: str,
    image_urls: list[str] | None,
    quoted_text: str,
    quoted_image_urls: list[str] | None,
    quoted_sender_name: str,
    quoted_user_id: str,
) -> str:
    normalized_prompt = prompt.strip()
    normalized_image_urls = [u.strip() for u in (image_urls or []) if u.strip()]
    normalized_quoted_text = quoted_text.strip()
    normalized_quoted_image_urls = [u.strip() for u in (quoted_image_urls or []) if u.strip()]

    lines = ["素材如下，请从清单中选一个最贴切的名字，按格式输出「<名字>了」，不要输出思考过程。"]
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
    return "\n".join(lines)


def build_turmfluch_prompt(
    *,
    prompt: str,
    image_urls: list[str] | None = None,
    quoted_text: str = "",
    quoted_image_urls: list[str] | None = None,
    quoted_sender_name: str = "",
    quoted_user_id: str = "",
) -> CardLePrompt:
    """/turmfluch 命令的 prompt：把跟随文字/图片/引用提炼成一句「名了」。"""
    return CardLePrompt(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=_user_prompt(
            prompt=prompt,
            image_urls=image_urls,
            quoted_text=quoted_text,
            quoted_image_urls=quoted_image_urls,
            quoted_sender_name=quoted_sender_name,
            quoted_user_id=quoted_user_id,
        ),
    )


def build_nearest_prompt(*, captured: str) -> CardLePrompt:
    """被动路径的 prompt：群友说的「{captured}了」里的 {captured} 不是合法卡牌/
    遗物名，请从清单里挑一个语义/字面最接近的真名，输出「<名字>了」。"""
    user = (
        f"群里有人说了一句「{captured}了」，但「{captured}」不是清单里的卡牌/遗物名。"
        "请从清单里选一个语义或字面最接近的名字，按格式输出「<名字>了」，不要输出思考过程。"
    )
    return CardLePrompt(system_prompt=_SYSTEM_PROMPT, user_prompt=user)
