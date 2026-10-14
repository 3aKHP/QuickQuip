"""Extract release notes for a given tag from CHANGELOG.md.

Run from the project root:
    python scripts/ci/extract_release_notes.py v1.16.2

Writes release_notes.md in the current working directory. A prerelease tag
such as v1.16.2-rc.1 selects the base 1.16.2 section. Missing or empty sections
produce a nonzero exit code.
"""
from __future__ import annotations

import pathlib
import re
import sys


def main(tag: str) -> int:
    # Prerelease tags (v1.12.2-rc.1) resolve to their base version section (## [1.12.2]).
    version = tag.lstrip("v").split("-", 1)[0]
    text = pathlib.Path("CHANGELOG.md").read_text(encoding="utf-8")
    pattern = rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=\n^## |\Z)"
    match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    if not match:
        print(f"ERROR: No '## [{version}]' section found in CHANGELOG.md", file=sys.stderr)
        return 1
    notes = match.group(1).strip()
    if not notes:
        print(f"ERROR: '## [{version}]' section is empty", file=sys.stderr)
        return 1
    pathlib.Path("release_notes.md").write_text(notes, encoding="utf-8")
    print(f"Extracted {len(notes)} chars of release notes")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python extract_release_notes.py <tag>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
