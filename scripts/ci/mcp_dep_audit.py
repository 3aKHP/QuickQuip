"""MCP dual-era dependency audit (Wave 0 gate).

Evaluates the dependency surface of two candidates:

- ``mcp-types==2.0.0`` — lightweight schema-only package (if it exists as a
  standalone distribution)
- ``mcp==2.0.0`` — full SDK v2 (pulls in httpx2, OpenTelemetry, PyJWT, etc.)

Creates a throw-away venv for each, installs the package, and reports the
total installed footprint plus the delta.  Exits 0 on success.

Usage::

    .venv/bin/python scripts/ci/mcp_dep_audit.py
"""
from __future__ import annotations

import subprocess
import tempfile
import venv
from pathlib import Path

CANDIDATES = [
    ("mcp-types (lightweight)", "mcp-types==2.0.0"),
    ("mcp (full SDK v2)", "mcp==2.0.0"),
]


def _create_venv(dirpath: Path) -> str:
    venv.create(dirpath, with_pip=True, clear=True)
    return str(dirpath / "bin" / "pip")


def _install_and_list(pip: str, spec: str) -> set[str] | None:
    """Install *spec* and return the set of installed package names."""
    result = subprocess.run(
        [pip, "install", "--quiet", "--disable-pip-version-check", spec],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  INSTALL FAILED:\n{result.stderr.strip()}")
        return None
    result = subprocess.run(
        [pip, "list", "--format=freeze", "--disable-pip-version-check"],
        capture_output=True,
        text=True,
    )
    return {line.split("==")[0].lower() for line in result.stdout.strip().splitlines() if "==" in line}


def main() -> int:
    results: dict[str, set[str] | None] = {}

    with tempfile.TemporaryDirectory(prefix="mcp-audit-") as tmp:
        tmp_path = Path(tmp)
        for label, spec in CANDIDATES:
            print(f"\n{'=' * 60}")
            print(f"  {label}  ({spec})")
            print(f"{'=' * 60}")
            venv_dir = tmp_path / label.split()[0].replace("-", "_")
            pip = _create_venv(venv_dir)
            packages = _install_and_list(pip, spec)
            results[label] = packages
            if packages is None:
                print("  (package not available or install failed)")
                continue
            # Remove stdlib/pip overhead from count
            non_bootstrap = {p for p in packages if p not in {"pip"}}
            print(f"  Installed {len(non_bootstrap)} packages:")
            for name in sorted(non_bootstrap):
                print(f"    {name}")

    # Delta
    types_pkgs = results.get(CANDIDATES[0][0])
    sdk_pkgs = results.get(CANDIDATES[1][0])
    if types_pkgs is not None and sdk_pkgs is not None:
        sdk_only = sdk_pkgs - types_pkgs
        print(f"\n{'=' * 60}")
        print("  Delta: packages in SDK but NOT in mcp-types")
        print(f"{'=' * 60}")
        print(f"  mcp-types: {len(types_pkgs - {'pip'})} packages")
        print(f"  mcp SDK:   {len(sdk_pkgs - {'pip'})} packages")
        print(f"  SDK-only:  {len(sdk_only)} packages")
        for name in sorted(sdk_only):
            print(f"    {name}")
    elif types_pkgs is None and sdk_pkgs is not None:
        print("\n  mcp-types is not available as a standalone package.")
        print("  The hand-written codec route does not require it.")

    if all(p is None for _, p in results.items()):
        print("\n  Neither package is available yet. This is expected if the")
        print("  MCP 2026-07-28 SDK has not been published to the index you")
        print("  are using. The hand-written codec route has no external deps.")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
