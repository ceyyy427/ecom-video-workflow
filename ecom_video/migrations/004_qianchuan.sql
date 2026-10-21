CREATE TABLE qianchuan_oauth_sessions (
 state_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES platform_accounts(id),
 config_revision TEXT NOT NULL, expires_at REAL NOT NULL, consumed_at REAL, created_at REAL NOT NULL
);
CREATE TABLE qianchuan_grants (
 account_id TEXT PRIMARY KEY REFERENCES platform_accounts(id), id TEXT NOT NULL UNIQUE,
 config_revision TEXT NOT NULL, secret_ref TEXT NOT NULL UNIQUE,
 status TEXT NOT NULL CHECK(status IN ('authorized','refreshing','reauthorize','revoked')),
 access_expires_at REAL NOT NULL, refresh_expires_at REAL NOT NULL, verified_at REAL NOT NULL,
 created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE qianchuan_tasks (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), account_id TEXT NOT NULL REFERENCES platform_accounts(id),
 status TEXT NOT NULL CHECK(status IN ('draft','upload_queued','uploading','material_pending','checking_material','awaiting_approval','create_queued','creating','submitted','failed','unknown','cancelled')),
 source_snapshot TEXT NOT NULL, parameters TEXT NOT NULL, upload_approval TEXT,
 material TEXT, payload TEXT, snapshot_hash TEXT, prepared_until REAL, approval TEXT, result TEXT,
 config_revision TEXT, grant_id TEXT, stage TEXT, dispatch_started INTEGER NOT NULL DEFAULT 0,
 lease_token TEXT, lease_until REAL, next_check_at REAL, check_attempts INTEGER NOT NULL DEFAULT 0,
 error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX qianchuan_queue ON qianchuan_tasks(status,created_at);
CREATE TABLE qianchuan_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES qianchuan_tasks(id),
 status TEXT NOT NULL, detail TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE report_batches_v4 (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, account_id TEXT NOT NULL REFERENCES platform_accounts(id),
 start_date TEXT NOT NULL, end_date TEXT NOT NULL, source TEXT NOT NULL CHECK(source IN ('csv','ocean_watch_api','qianchuan_api')),
 sha256 TEXT NOT NULL, path TEXT NOT NULL, actor TEXT NOT NULL, metadata TEXT NOT NULL, created_at REAL NOT NULL,
 UNIQUE(account_id,start_date,end_date,source,sha256)
);
INSERT INTO report_batches_v4 SELECT * FROM report_batches;
DROP TABLE report_batches;
ALTER TABLE report_batches_v4 RENAME TO report_batches;
