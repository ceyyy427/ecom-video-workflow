CREATE TABLE voice_patches (
 id TEXT PRIMARY KEY,
 product_id TEXT NOT NULL REFERENCES customer_projects(product_id),
 job_id TEXT NOT NULL REFERENCES jobs(id),
 board_revision INTEGER NOT NULL,
 shot_id TEXT NOT NULL,
 sentence_index INTEGER NOT NULL,
 basis TEXT NOT NULL,
 params TEXT NOT NULL,
 files TEXT NOT NULL,
 size INTEGER NOT NULL CHECK(size>0),
 duration REAL NOT NULL CHECK(duration>=1 AND duration<=15),
 alignment TEXT NOT NULL,
 result_job_id TEXT REFERENCES jobs(id),
 reviewer TEXT,
 created_at REAL NOT NULL
);
CREATE INDEX voice_patches_project ON voice_patches(product_id,created_at);
