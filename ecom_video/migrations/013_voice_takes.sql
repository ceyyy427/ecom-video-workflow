CREATE TABLE voice_takes (
 id TEXT PRIMARY KEY,
 product_id TEXT NOT NULL REFERENCES customer_projects(product_id),
 draft_id TEXT NOT NULL, script_hash TEXT NOT NULL,
 scope TEXT NOT NULL CHECK(scope IN ('preview','full')),
 params TEXT NOT NULL, request_hash TEXT NOT NULL,
 path TEXT NOT NULL, sha256 TEXT NOT NULL,
 size INTEGER NOT NULL CHECK(size>0), duration REAL NOT NULL CHECK(duration>0),
 created_at REAL NOT NULL
);
CREATE INDEX voice_takes_project ON voice_takes(product_id,created_at);
CREATE UNIQUE INDEX voice_preview_cache ON voice_takes(product_id,request_hash) WHERE scope='preview';
