CREATE TABLE idea_uploads (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL, kind TEXT NOT NULL,
 sha256 TEXT NOT NULL, size INTEGER NOT NULL, metadata TEXT NOT NULL,
 source_note TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE idea_plans (
 id TEXT PRIMARY KEY, basis TEXT NOT NULL UNIQUE, plan TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('draft','queued','rendering','ready','failed','cancelled')),
 previews TEXT NOT NULL DEFAULT '{}', error TEXT, lease_token TEXT,
 created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX idea_plan_queue ON idea_plans(status,created_at);
CREATE TABLE idea_adoptions (
 plan_id TEXT NOT NULL REFERENCES idea_plans(id), option_id TEXT NOT NULL,
 product_id TEXT NOT NULL UNIQUE REFERENCES products(id), created_at REAL NOT NULL,
 PRIMARY KEY(plan_id,option_id)
);
