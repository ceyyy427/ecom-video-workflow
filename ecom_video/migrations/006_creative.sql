CREATE TABLE alignments (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
 fingerprint TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('running','needs_review','confirmed','failed')),
 result TEXT, error TEXT, reviewer TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX alignments_job ON alignments(job_id,created_at);
