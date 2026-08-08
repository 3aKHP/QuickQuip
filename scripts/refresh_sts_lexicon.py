#!/usr/bin/env python3
"""从 nkhoit/spire-archive 重建杀戮尖塔（1+2 代）卡牌/遗物中文词表。

词表是 STS 公式化模块的地基。本脚本从上游两代游戏的 cards/relics 数据 +
简中本地化做 join、按中文名跨代去重，输出一份带元信息的 JSON，供
``quickquip.sts.lexicon`` 加载。

设计要点：
- vendored 文件保持**完整**（与上游去重结果一致，含"打击""防御"等标准打防牌）。
  具体排除项（歧义词、标准打防）在 ``quickquip.sts.config.EXCLUDED_NAMES`` 维护，
  加载时套用——这样刷新不会回退排除，新增排除也无需重跑数据。
- pin 上游 commit SHA 保证可复现；要刷新时改 ``SOURCE_SHA`` 重跑即可。

用法：``python3 scripts/refresh_sts_lexicon.py``
"""

from __future__ import annotations

import json
import sys
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

# 上游仓库与快照。刷新时核对 spire-archive 最新 commit 后改这里重跑。
SOURCE_REPO = "nkhoit/spire-archive"
SOURCE_SHA = "14e05c09dc38"
SOURCE_DATE = "2026-07-23"  # 上游 commit 日期，人工核对

# 两代游戏各自的 cards/relics 数据 + 简中本地化（相对仓库根的路径）。
FILES = {
    "sts1": {
        "cards": "data/sts1/cards.json",
        "relics": "data/sts1/relics.json",
        "zh": "data/sts1/localization/zh.json",
    },
    "sts2": {
        "cards": "data/sts2/cards.json",
        "relics": "data/sts2/relics.json",
        "zh": "data/sts2/localization/zh.json",
        "versions": "data/sts2/history/versions.json",
    },
}

KINDSEC = {"card": "cards", "relic": "relics"}  # 本地化顶层键是复数

# 输出路径（仓库根 / src/quickquip/sts/sts_lexicon.json；不放在 data/ 子目录——
# 根 .gitignore 的 `data/` 规则会忽略任意层级的 data 目录）
OUT = Path(__file__).resolve().parent.parent / "src" / "quickquip" / "sts" / "sts_lexicon.json"


def _fetch(path: str) -> object:
    url = f"https://raw.githubusercontent.com/{SOURCE_REPO}/{SOURCE_SHA}/{path}"
    with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 — 只读公开 raw
        return json.loads(resp.read().decode("utf-8"))


def _zh_name(loc: dict, kind: str, cid: str) -> str | None:
    entry = loc.get(KINDSEC[kind], {}).get(cid)
    if entry and entry.get("name"):
        return entry["name"].strip()
    return None


def _entries(items: list[dict], loc: dict, kind: str, game: str) -> list[dict]:
    out = []
    for it in items:
        name = _zh_name(loc, kind, it["id"])
        if not name:
            continue  # 缺译条目跳过（如 STS1 IMPULSE，上游简中遗漏）
        e = {"name": name, "kind": kind, "game": game, "en": it.get("name"), "id": it["id"]}
        if kind == "card":
            e["meta"] = {k: it.get(k) for k in ("color", "type", "rarity") if it.get(k) is not None}
        else:
            e["meta"] = {k: it.get(k) for k in ("tier",) if it.get(k) is not None}
        out.append(e)
    return out


def main() -> int:
    raw: dict[str, dict] = {}
    for game, paths in FILES.items():
        raw[game] = {key: _fetch(p) for key, p in paths.items() if key != "versions"}
        if "versions" in paths:
            raw[game]["versions"] = _fetch(paths["versions"])

    all_entries: list[dict] = []
    for game in ("sts1", "sts2"):
        loc = raw[game]["zh"]
        all_entries += _entries(raw[game]["cards"], loc, "card", game)
        all_entries += _entries(raw[game]["relics"], loc, "relic", game)

    # 按中文名跨代去重，合并 games/kind/en/ids
    by_name: dict[str, list[dict]] = defaultdict(list)
    for e in all_entries:
        by_name[e["name"]].append(e)

    names: dict[str, dict] = {}
    for name, es in by_name.items():
        games = sorted({e["game"] for e in es})
        names[name] = {
            "en": sorted({e["en"] for e in es if e["en"]}),
            "kind": sorted({e["kind"] for e in es}),
            "games": games,
            # 多 ID（如各职业各自的"打击"）只保留每代首个用于溯源
            "ids": {e["game"]: e["id"] for e in es},
            "meta": es[0]["meta"],
        }

    # versions.json 按新版在前排列，取首个为当前快照
    _versions = raw.get("sts2", {}).get("versions") or []
    sts2_version = _versions[0].get("version", "?") if _versions else "?"

    document = {
        "_meta": {
            "source": f"github.com/{SOURCE_REPO}",
            "source_sha": SOURCE_SHA,
            "source_date": SOURCE_DATE,
            "sts2_version": sts2_version,
            "generated": date.today().isoformat(),
            "count": len(names),
            "note": "完整词表（含标准打防牌）；排除项见 quickquip.sts.config.EXCLUDED_NAMES",
        },
        "names": names,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(document, ensure_ascii=False, indent=1), encoding="utf-8")

    cards = sum(1 for v in names.values() if "card" in v["kind"])
    relics = sum(1 for v in names.values() if "relic" in v["kind"])
    both = sum(1 for v in names.values() if v["games"] == ["sts1", "sts2"])
    print(f"写出 {OUT} ({OUT.stat().st_size} bytes)")
    print(f"  唯一中文名 {len(names)}（卡牌 {cards} / 遗物 {relics}；两代共有 {both}）")
    print(f"  上游 {SOURCE_SHA} ({SOURCE_DATE})，STS2 快照 {sts2_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
