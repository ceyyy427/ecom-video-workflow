CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, script TEXT NOT NULL,
 seconds REAL NOT NULL CHECK(seconds BETWEEN 1 AND 15),
 status TEXT NOT NULL CHECK(status IN ('draft','queued','validating','rendering','auditing','needs_review','ready','rejected','blocked','failed','cancelled')),
 script_hash TEXT, snapshot TEXT, audit TEXT, error TEXT,
 attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
 lease_token TEXT, lease_until REAL, worker_id TEXT,
 created_at REAL NOT NULL, updated_at REAL NOT NULL,
 parent_id TEXT REFERENCES jobs(id)
);
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status, created_at);
CREATE TABLE IF NOT EXISTS assets (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
 name TEXT NOT NULL, path TEXT NOT NULL UNIQUE, kind TEXT NOT NULL CHECK(kind IN ('image','video','audio')),
 sha256 TEXT NOT NULL, size INTEGER NOT NULL, position INTEGER NOT NULL,
 metadata TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS assets_job ON assets(job_id, position);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(id),
 from_status TEXT, to_status TEXT NOT NULL, message TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
 kind TEXT NOT NULL, path TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
 attempt INTEGER NOT NULL, UNIQUE(job_id, kind)
);
CREATE TABLE IF NOT EXISTS reviews (
 id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(id),
 decision TEXT NOT NULL CHECK(decision IN ('ready','rejected')), reviewer TEXT NOT NULL,
 note TEXT NOT NULL, checklist_confirmed INTEGER NOT NULL CHECK(checklist_confirmed=1),
 script_hash TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS workers (id TEXT PRIMARY KEY, heartbeat_at REAL NOT NULL);
