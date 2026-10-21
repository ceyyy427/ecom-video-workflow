CREATE TABLE customer_projects (
 product_id TEXT PRIMARY KEY REFERENCES products(id),
 revision INTEGER NOT NULL DEFAULT 0,
 settings TEXT NOT NULL,
 active_job_id TEXT REFERENCES jobs(id),
 created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE customer_media (
 id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES customer_projects(product_id),
 name TEXT NOT NULL, path TEXT NOT NULL, kind TEXT NOT NULL,
 role TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
 metadata TEXT NOT NULL, source_in REAL NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '',
 created_at REAL NOT NULL
);
CREATE INDEX customer_media_project ON customer_media(product_id);
CREATE TABLE customer_jobs (
 job_id TEXT PRIMARY KEY REFERENCES jobs(id), product_id TEXT NOT NULL REFERENCES customer_projects(product_id),
 input_fingerprint TEXT NOT NULL, basis_fingerprint TEXT NOT NULL, planning_notes TEXT NOT NULL DEFAULT '[]', created_at REAL NOT NULL
);
CREATE INDEX customer_jobs_project ON customer_jobs(product_id);
CREATE TABLE customer_edits (
 request_id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES customer_projects(product_id),
 source_job_id TEXT NOT NULL REFERENCES jobs(id), request_hash TEXT NOT NULL,
 result_job_id TEXT NOT NULL REFERENCES jobs(id), created_at REAL NOT NULL
);
