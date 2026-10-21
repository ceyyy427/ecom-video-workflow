CREATE TABLE agent_runs (
 id TEXT PRIMARY KEY,
 request_id TEXT NOT NULL UNIQUE,
 command_hash TEXT NOT NULL,
 command TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('proposed','failed')),
 result TEXT NOT NULL,
 created_at REAL NOT NULL
);
CREATE TABLE agent_events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT,
 run_id TEXT NOT NULL REFERENCES agent_runs(id),
 type TEXT NOT NULL CHECK(type IN ('request_accepted','proposal_ready','tool_failed')),
 payload TEXT NOT NULL,
 created_at REAL NOT NULL
);
CREATE INDEX agent_events_run ON agent_events(run_id,seq);
