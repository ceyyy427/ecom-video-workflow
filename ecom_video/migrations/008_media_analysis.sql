CREATE TABLE media_analyses (
 id TEXT PRIMARY KEY, media_id TEXT NOT NULL REFERENCES customer_media(id) ON DELETE CASCADE,
 source_sha256 TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL DEFAULT '',
 result TEXT, error TEXT, lease_token TEXT, lease_until REAL,
 created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX media_analyses_media ON media_analyses(media_id,created_at);
