"""Read-only formal-state/history checks and frozen sample binding; writes evidence only."""

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from ecom_video.creative import signature
    from ecom_video.media import digest
    from ecom_video.remotion_renderer import engine_hash

    out = ROOT / "docs/evidence/script-readiness"
    before = json.loads((out / "formal-before.json").read_text())
    c = sqlite3.connect(f"file:{ROOT / 'var/workflow.db'}?mode=ro", uri=True)
    tables = {}
    for t in before["tables"]:
        rows = c.execute('select * from "' + t + '" order by rowid').fetchall()
        tables[t] = {
            "rows": len(rows),
            "hash": hashlib.sha256(
                json.dumps(rows, ensure_ascii=False, default=str).encode()
            ).hexdigest(),
        }
    changed = [t for t in tables if tables[t] != before["tables"][t]]
    assert set(changed) <= {"workers"}, changed
    for relative, sha in before["files"].items():
        assert digest(ROOT / relative) == sha, relative
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert not c.execute("PRAGMA foreign_key_check").fetchall()
    assert c.execute("PRAGMA user_version").fetchone()[0] == 14
    manifest = json.loads((out / "manifest.json").read_text())
    report = json.loads((out / "audit.json").read_text())
    snapshot = json.loads((out / "snapshot.json").read_text())
    assert manifest["render"]["engine_hash"] == engine_hash()
    assert report["snapshot_sha256"] == signature(snapshot)
    assert report["output_sha256"] == digest(ROOT / "examples/readiness-demo/headphones/output.mp4")
    (out / "formal-after.json").write_text(
        json.dumps(
            {
                "changed_tables": changed,
                "tables_checked": len(tables),
                "historical_files_verified": len(before["files"]),
                "schema": 14,
                "integrity": "ok",
                "foreign_key_errors": 0,
                "current_render_engine": engine_hash(),
                "frozen_snapshot_and_output_verified": True,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(
        f"{len(tables)} tables, {len(before['files'])} old files, schema14 and frozen report/video bindings verified"
    )


if __name__ == "__main__":
    main()
