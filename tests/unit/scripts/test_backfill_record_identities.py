from pathlib import Path
import runpy
import sqlite3


from quickquip.common.record_content import decode, legacy, references
from quickquip.common.record_search import matches
from quickquip.chat.group_quotes import GroupQuoteStore


from tests.fixtures.record_identities import snapshot as snapshot

def test_backfill_preview_repeat_race_backup_and_match_parity(tmp_path, snapshot):
    backfill = runpy.run_path(str(Path(__file__).resolve().parents[3] / "scripts/backfill_record_identities.py"))["backfill"]
    path = tmp_path / "old.db"
    raw = "[CQ:at,name=旧名,qq=12345] 的事实"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE memories(id INTEGER PRIMARY KEY, group_id TEXT, content TEXT)")
        conn.executemany("INSERT INTO memories VALUES (?, '10001', ?)", [(1, raw), (2, raw)])
    preview = backfill(path, "memories")
    assert preview["convertible"] == 2
    assert not list(tmp_path.glob("*.bak"))
    with sqlite3.connect(path) as conn:
        assert "content_parts_json" not in [r[1] for r in conn.execute("PRAGMA table_info(memories)")]
    def race(row):
        if row["id"] == 2:
            with sqlite3.connect(path) as conn:
                conn.execute("UPDATE memories SET content='edited' WHERE id=2")
    result = backfill(path, "memories", apply=True, batch_size=1, before_write=race)
    assert result["written"] == result["concurrent_skipped"] == 1
    with sqlite3.connect(path) as conn:
        content, body = conn.execute("SELECT content, content_parts_json FROM memories WHERE id=1").fetchone()
        assert content == raw
        for q in ["标准名", "别名", "12345", "旧名"]:
            assert matches({"content": raw}, q, snapshot) == matches({"content": raw, "content_parts_json": body}, q, snapshot)
        assert references(decode(content, body)) == {"12345"}
    assert backfill(path, "memories", apply=True)["existing"] == 1
    assert backfill(path, "memories", apply=True)["existing"] == 2
    with sqlite3.connect(sorted(tmp_path.glob("*.bak"))[0]) as backup:
        assert backup.execute("SELECT content FROM memories WHERE id=2").fetchone()[0] == raw


def test_backfill_repairs_only_missing_index_and_failure_exit(tmp_path):
    script = runpy.run_path(str(Path(__file__).resolve().parents[3] / "scripts/backfill_record_identities.py"))
    path = tmp_path / "quotes.db"
    store = GroupQuoteStore(path)
    ident = store.add("10001", "23456", "名字", "", "99999", content_parts=legacy("[CQ:at,qq=12345]"))
    with store._db:
        encoded = store._db.execute("SELECT content_parts_json FROM quotes WHERE id=?", (ident,)).fetchone()[0]
        store._db.execute("DELETE FROM quotes_member_refs")
    store.close()
    result = script["backfill"](path, "quotes", apply=True)
    assert result["index_repaired"] == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT content_parts_json FROM quotes WHERE id=?", (ident,)).fetchone()[0] == encoded
        assert conn.execute("SELECT qq FROM quotes_member_refs").fetchone()[0] == "12345"
        conn.execute("UPDATE quotes SET content_parts_json='invalid'")
    assert script["main"](["--database", "quotes", "--path", str(path), "--preview-limit", "0"]) == 1




def test_backfill_shipped_and_standalone_help(tmp_path):
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[3]
    script = "scripts/backfill_record_identities.py"
    for dockerfile in ("Dockerfile", "prod.example/Dockerfile"):
        assert any(line.startswith("COPY ") and script in line for line in (root / dockerfile).read_text().splitlines())
    assert script in (root / "prod.example/deploy-manifest.txt").read_text().splitlines()
    workflow = (root / ".github/workflows/release.yml").read_text()
    assert "scripts\\backfill_record_identities.py --help" in workflow
    assert any("Copy-Item" in line and "scripts\\backfill_record_identities.py" in line for line in workflow.splitlines())
    result = subprocess.run([sys.executable, "-I", str(root / script), "--help"], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "--apply" in result.stdout
