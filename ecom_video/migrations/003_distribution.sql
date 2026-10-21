CREATE TABLE platform_accounts (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, platform TEXT NOT NULL CHECK(platform IN ('qianchuan','oceanengine')),
 advertiser_id TEXT NOT NULL, auth_account_id TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'CNY',
 timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai', created_at REAL NOT NULL,
 UNIQUE(platform,advertiser_id)
);
CREATE TABLE distribution_tasks (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), account_id TEXT NOT NULL REFERENCES platform_accounts(id),
 status TEXT NOT NULL CHECK(status IN ('awaiting_approval','queued','exporting','awaiting_manual','submitted','active','paused','rejected','completed','failed','cancelled')),
 snapshot TEXT NOT NULL, snapshot_hash TEXT NOT NULL, approval TEXT, receipt TEXT,
 package_path TEXT, package_hash TEXT, error TEXT, lease_token TEXT, lease_until REAL,
 created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX distribution_queue ON distribution_tasks(status,created_at);
CREATE TABLE distribution_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES distribution_tasks(id),
 status TEXT NOT NULL, detail TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE report_batches (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, account_id TEXT NOT NULL REFERENCES platform_accounts(id),
 start_date TEXT NOT NULL, end_date TEXT NOT NULL, source TEXT NOT NULL CHECK(source IN ('csv','ocean_watch_api')),
 sha256 TEXT NOT NULL, path TEXT NOT NULL, actor TEXT NOT NULL, metadata TEXT NOT NULL, created_at REAL NOT NULL,
 UNIQUE(account_id,start_date,end_date,source,sha256)
);
CREATE TABLE report_rows (
 batch_id TEXT NOT NULL REFERENCES report_batches(id), date TEXT NOT NULL, material_id TEXT NOT NULL,
 metrics TEXT NOT NULL, PRIMARY KEY(batch_id,date,material_id)
);
CREATE TABLE material_bindings (
 account_id TEXT NOT NULL REFERENCES platform_accounts(id), material_id TEXT NOT NULL,
 job_id TEXT NOT NULL REFERENCES jobs(id), video_sha256 TEXT NOT NULL, actor TEXT NOT NULL, created_at REAL NOT NULL,
 PRIMARY KEY(account_id,material_id)
);
CREATE TABLE report_syncs (
 id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES platform_accounts(id), start_date TEXT NOT NULL, end_date TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('queued','fetching','completed','failed')), actor TEXT NOT NULL, batch_id TEXT REFERENCES report_batches(id),
 lease_token TEXT, lease_until REAL, error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX report_sync_queue ON report_syncs(status,created_at);
