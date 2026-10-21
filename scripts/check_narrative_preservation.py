"""Read-only formal DB, historical files and current-engine verification; evidence writes only."""

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from ecom_video.remotion_renderer import engine_hash

    out = ROOT / "docs/evidence/narrative-samples"
    before = json.loads((out / "formal-before.json").read_text())
    c = sqlite3.connect(f"file:{ROOT / 'var/workflow.db'}?mode=ro", uri=True)
    tables = {}
    for table in before["tables"]:
        rows = c.execute('select * from "' + table + '" order by rowid').fetchall()
        tables[table] = {
            "rows": len(rows),
            "hash": hashlib.sha256(
                json.dumps(rows, ensure_ascii=False, default=str).encode()
            ).hexdigest(),
        }
    changed = [t for t in tables if tables[t] != before["tables"][t]]
    assert set(changed) <= {"workers"}, changed
    for path, sha in before["files"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == sha, path
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert not c.execute("PRAGMA foreign_key_check").fetchall()
    assert c.execute("PRAGMA user_version").fetchone()[0] == 14
    current_engine = engine_hash()
    for style in ("cinema", "social", "lab"):
        for phase in ("film", "single"):
            m = json.loads((out / f"{style}-{phase}-manifest.json").read_text())
            assert m["render"]["engine_hash"] == current_engine
    (out / "formal-after.json").write_text(
        json.dumps(
            {
                "tables": tables,
                "changed_tables": changed,
                "historical_files_verified": len(before["files"]),
                "schema": 14,
                "integrity": "ok",
                "foreign_key_errors": 0,
                "six_manifests_current_engine": current_engine,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(
        f"{len(tables)} tables checked; only heartbeat changes; {len(before['files'])} historical files unchanged; six manifests current"
    )


if __name__ == "__main__":
    main()
