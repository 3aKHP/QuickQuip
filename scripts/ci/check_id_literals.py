"""Guard against real-looking QQ/group ID literals in public files.

Scans tracked files under a fixed set of public-facing paths for 9-11 digit
decimal literals and fails if any hit is not in the synthetic allowlist. The
script intentionally contains no real IDs; the allowlist holds only the
project's synthetic placeholders.

Exits with non-zero if any file contains a disallowed literal.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

# 9-11 digit literals that are immediately followed by a decimal point are
# epoch-second floats (e.g. 1600000000.0), not identifiers; skip those.
PATTERN = re.compile(r"\b[1-9]\d{8,10}\b(?!\.)")

# Synthetic placeholders used across fixtures, docs, and example configs.
ALLOWLIST = {"1000000000", "1000000001", "123456789", "987654321"}

SCAN_PATHS = (
    "tests",
    "docs",
    "config",
    "prod.example",
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
)

# Within config/, only example templates are public-safe to assert on; real
# config/*.toml are gitignored and may legitimately hold private IDs.
CONFIG_SUFFIXES = (".example",)


def _tracked_files() -> list[pathlib.Path]:
    out = subprocess.run(
        ["git", "ls-files", *SCAN_PATHS],
        capture_output=True,
        text=True,
        check=True,
    )
    return [pathlib.Path(p) for p in out.stdout.splitlines() if p]


def _in_scope(path: pathlib.Path) -> bool:
    parts = path.parts
    if parts and parts[0] == "config":
        # config/personas.example/*.toml end with .toml, keep them via parent dir
        if "personas.example" in parts:
            return True
        return path.name.endswith(CONFIG_SUFFIXES)
    return True


def main() -> int:
    failed = 0
    for f in _tracked_files():
        if not _in_scope(f) or not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for m in PATTERN.finditer(line):
                if m.group(0) in ALLOWLIST:
                    continue
                print(
                    f"FAIL {f}:{lineno}: 9-11 digit literal not in synthetic "
                    "allowlist (possible real QQ/group ID). Use a synthetic "
                    "value from the allowlist or a smaller placeholder.",
                    file=sys.stderr,
                )
                failed += 1

    if failed:
        print(f"\n{failed} disallowed literal(s).", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
