"""Read a deployment decision on the host without loading application dependencies."""

import json
from pathlib import Path
import sys


def status(root, release):
    root = Path(root)
    journal = root / ".deploy" / f"{release}.transaction.json"
    record = json.loads(journal.read_text()) if journal.exists() else {}
    receipt = root / ".deploy" / f"{release}.exit"
    code = receipt.read_text().strip() if receipt.exists() else "pending"
    if record.get("committed") or code == "0":
        return "0" if (root / "current").resolve().name == release else "superseded"
    if "committed" not in record and (root / "releases" / release / ".complete").exists():
        return "unknown"
    return code


if __name__ == "__main__":
    print(status(sys.argv[1], sys.argv[2]))
