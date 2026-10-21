-- A raw file may be re-declared under a different human-confirmed export window.
-- Preserve every old row/id/seq/reference. Logical dedupe remains inside BEGIN IMMEDIATE.
CREATE TABLE report_batches_v12 (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
 account_id TEXT NOT NULL REFERENCES platform_accounts(id),
 start_date TEXT NOT NULL, end_date TEXT NOT NULL,
 source TEXT NOT NULL CHECK(source IN ('csv','ocean_watch_api','qianchuan_api')),
 sha256 TEXT NOT NULL, path TEXT NOT NULL, actor TEXT NOT NULL,
 metadata TEXT NOT NULL, created_at REAL NOT NULL
);
INSERT INTO report_batches_v12 SELECT * FROM report_batches;
DROP TABLE report_batches;
ALTER TABLE report_batches_v12 RENAME TO report_batches;
CREATE INDEX report_batches_review_window ON report_batches(account_id,seq DESC);
CREATE INDEX report_batches_file_lookup ON report_batches(account_id,start_date,end_date,source,sha256,seq DESC);
CREATE TABLE experiments (
 id TEXT PRIMARY KEY, review_id TEXT NOT NULL REFERENCES review_snapshots(id),
 product_id TEXT NOT NULL REFERENCES customer_projects(product_id),
 parent_job_id TEXT NOT NULL REFERENCES jobs(id), material_id TEXT NOT NULL,
 proposal_hash TEXT NOT NULL, payload TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('proposed','selected','rejected','draft_created','awaiting_data','evaluated')),
 revision INTEGER NOT NULL DEFAULT 0,
 result_job_id TEXT UNIQUE REFERENCES jobs(id), result_script_draft_id TEXT UNIQUE REFERENCES script_drafts(id),
 created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX experiments_review ON experiments(review_id,created_at);
CREATE TABLE experiment_events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, experiment_id TEXT NOT NULL REFERENCES experiments(id),
 type TEXT NOT NULL, actor TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE experiment_commands (
 request_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments(id),
 operation TEXT NOT NULL, command_hash TEXT NOT NULL, result TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE experiment_evaluations (
 id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments(id),
 next_review_id TEXT NOT NULL REFERENCES review_snapshots(id),
 evaluation_hash TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE INDEX experiment_evaluations_parent ON experiment_evaluations(experiment_id,created_at);
CREATE TABLE experiment_styles (
 id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES experiments(id),
 job_id TEXT NOT NULL REFERENCES jobs(id), board_revision INTEGER NOT NULL,
 board_hash TEXT NOT NULL, style_id TEXT NOT NULL, actor TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TRIGGER experiments_content_immutable BEFORE UPDATE OF review_id,product_id,parent_job_id,material_id,proposal_hash,payload,created_at ON experiments BEGIN SELECT RAISE(ABORT,'immutable experiment proposal'); END;
CREATE TRIGGER experiments_no_delete BEFORE DELETE ON experiments BEGIN SELECT RAISE(ABORT,'immutable experiment'); END;
CREATE TRIGGER experiment_events_no_update BEFORE UPDATE ON experiment_events BEGIN SELECT RAISE(ABORT,'immutable experiment event'); END;
CREATE TRIGGER experiment_events_no_delete BEFORE DELETE ON experiment_events BEGIN SELECT RAISE(ABORT,'immutable experiment event'); END;
CREATE TRIGGER experiment_commands_no_update BEFORE UPDATE ON experiment_commands BEGIN SELECT RAISE(ABORT,'immutable experiment command'); END;
CREATE TRIGGER experiment_commands_no_delete BEFORE DELETE ON experiment_commands BEGIN SELECT RAISE(ABORT,'immutable experiment command'); END;
CREATE TRIGGER experiment_evaluations_no_update BEFORE UPDATE ON experiment_evaluations BEGIN SELECT RAISE(ABORT,'immutable experiment evaluation'); END;
CREATE TRIGGER experiment_evaluations_no_delete BEFORE DELETE ON experiment_evaluations BEGIN SELECT RAISE(ABORT,'immutable experiment evaluation'); END;
CREATE TRIGGER experiment_styles_no_update BEFORE UPDATE ON experiment_styles BEGIN SELECT RAISE(ABORT,'immutable experiment style'); END;
CREATE TRIGGER experiment_styles_no_delete BEFORE DELETE ON experiment_styles BEGIN SELECT RAISE(ABORT,'immutable experiment style'); END;
