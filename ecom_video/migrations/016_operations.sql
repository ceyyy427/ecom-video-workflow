CREATE TABLE operation_objects (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, basis TEXT NOT NULL UNIQUE,
 payload TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE INDEX operation_objects_kind ON operation_objects(kind,created_at);
CREATE TABLE operation_files (
 object_id TEXT NOT NULL REFERENCES operation_objects(id), path TEXT NOT NULL,
 sha256 TEXT NOT NULL, PRIMARY KEY(object_id,path)
);
CREATE TABLE operation_oauth_states (
 state_hash TEXT PRIMARY KEY, config_id TEXT NOT NULL REFERENCES operation_objects(id),
 status TEXT NOT NULL CHECK(status IN ('pending','consumed','failed')),
 expires_at REAL NOT NULL, created_at REAL NOT NULL
);
