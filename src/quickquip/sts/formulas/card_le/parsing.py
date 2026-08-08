"""「xxx了」公式输出的解析与校验。

模型回复必须落在活跃词表里才算合法。命令路径与被动路径共用本提取器，
确保 bot 永远只发出真实卡牌/遗物名 + 了。
"""

from __future__ import annotations

from quickquip.sts import lexicon


def extract_card_le_name(text: str) -> str | None:
    """从模型输出中提取一个合法卡牌/遗物名（不含"了"）。

    优先按「<名>了」尾部剥离；失败则扫描文本里出现的清单名字（取最长命中）。
    无合法命中返回 None。
    """
    cleaned = text.strip().strip("\"'“”‘’").strip()
    if cleaned.endswith("了"):
        candidate = cleaned[:-1].strip()
        if lexicon.is_card_name(candidate):
            return candidate
    # 模型偶尔附带多余文字，兜底扫描清单中出现的名字
    hits = sorted((n for n in lexicon.NAMES if n in cleaned), key=len, reverse=True)
    return hits[0] if hits else None
