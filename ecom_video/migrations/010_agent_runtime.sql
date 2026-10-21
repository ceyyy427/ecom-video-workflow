CREATE TABLE agent_executions (
 run_id TEXT PRIMARY KEY REFERENCES agent_runs(id),
 revision INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL CHECK(status IN ('proposed','queued','running','paused','waiting_human','completed','failed','cancelled','unknown')),
 plan_hash TEXT NOT NULL, policy TEXT NOT NULL,
 project_id TEXT NOT NULL REFERENCES customer_projects(product_id),
 project_revision INTEGER NOT NULL, product_revision INTEGER NOT NULL,
 input_hash TEXT NOT NULL, job_id TEXT REFERENCES jobs(id), board_revision INTEGER,
 waiting_for TEXT, error TEXT,
 steps_used INTEGER NOT NULL DEFAULT 0, model_calls INTEGER NOT NULL DEFAULT 0,
 deadline REAL, lease_token TEXT, lease_until REAL,
 created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE agent_steps (
 run_id TEXT NOT NULL REFERENCES agent_executions(run_id), step_key TEXT NOT NULL,
 status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 1,
 started_at REAL NOT NULL, finished_at REAL, error TEXT,
 model_calls_at_start INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(run_id,step_key)
);
CREATE TABLE agent_effects (
 run_id TEXT NOT NULL REFERENCES agent_executions(run_id), step_key TEXT NOT NULL,
 target_kind TEXT NOT NULL, target_id TEXT NOT NULL, owned INTEGER NOT NULL,
 receipt TEXT NOT NULL, created_at REAL NOT NULL,
 PRIMARY KEY(run_id,step_key)
);
CREATE INDEX agent_effect_target ON agent_effects(target_kind,target_id);
CREATE TABLE agent_choices (
 run_id TEXT PRIMARY KEY REFERENCES agent_executions(run_id),
 style_id TEXT NOT NULL, direction_basis TEXT NOT NULL,
 reviewer TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE resource_leases (
 name TEXT PRIMARY KEY, token TEXT NOT NULL, expires_at REAL NOT NULL
);
ALTER TABLE agent_events RENAME TO agent_events_v9;
CREATE TABLE agent_events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT,
 run_id TEXT NOT NULL REFERENCES agent_runs(id), type TEXT NOT NULL,
 payload TEXT NOT NULL, created_at REAL NOT NULL
);
INSERT INTO agent_events SELECT * FROM agent_events_v9;
DROP TABLE agent_events_v9;
CREATE INDEX agent_events_run ON agent_events(run_id,seq);
