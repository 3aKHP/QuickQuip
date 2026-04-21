"""Validate that all *.toml.example and personas.example/*.toml files parse.

Exits with non-zero if any file fails to parse.
"""
from __future__ import annotations

import pathlib
import sys
import tomllib


def main() -> int:
    files = (
        list(pathlib.Path("config").glob("*.toml.example"))
        + list(pathlib.Path("config/personas.example").glob("*.toml"))
    )
    failed = 0
    for f in files:
        try:
            tomllib.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"FAIL {f}: {e}", file=sys.stderr)
            failed += 1

    if failed:
        print(f"\n{failed} file(s) failed.", file=sys.stderr)
        return 1
    print(f"OK ({len(files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
