import sqlite3
from pathlib import Path

from ecom_video.db import SCHEMA_VERSION, Store


def test_v3_report_rows_and_sync_references_survive_current_schema(tmp_path):
    path = tmp_path / "workflow.db"
    c = sqlite3.connect(path)
    folder = Path("ecom_video/migrations")
    for name in ("001_initial.sql", "002_products.sql", "003_distribution.sql"):
        c.executescript((folder / name).read_text())
    c.execute("PRAGMA user_version=3")
    c.execute(
        "INSERT INTO platform_accounts VALUES('a','账户','qianchuan','123','','CNY','Asia/Shanghai',0)"
    )
    c.execute(
        "INSERT INTO report_batches(id,account_id,start_date,end_date,source,sha256,path,actor,metadata,created_at) VALUES('b','a','2026-10-01','2026-10-01','csv','sha','path','人','{}',0)"
    )
    c.execute("INSERT INTO report_rows VALUES('b','2026-10-01','123','{}')")
    c.execute(
        "INSERT INTO report_syncs(id,account_id,start_date,end_date,status,actor,batch_id,created_at,updated_at) VALUES('s','a','2026-10-01','2026-10-01','completed','人','b',0,0)"
    )
    c.commit()
    c.close()
    store = Store(path)
    with store.connect() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        assert c.execute("SELECT batch_id FROM report_rows").fetchone()[0] == "b"
        assert c.execute("SELECT batch_id FROM report_syncs").fetchone()[0] == "b"
