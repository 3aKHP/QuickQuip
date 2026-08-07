from __future__ import annotations

from pathlib import Path

from quickquip.common.sensitive_filter import SensitiveFilter


def make_sensitive_filter(
    base_dir: Path,
    section: str,
    word: str = "blocked",
) -> SensitiveFilter:
    path = base_dir / f"sensitive-{section}.toml"
    path.write_text(
        f'[{section}.test]\nwords = ["{word}"]\n',
        encoding="utf-8",
    )
    return SensitiveFilter.from_toml(path)
