CREATE TABLE creative_features (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
 video_sha256 TEXT NOT NULL, input_snapshot_hash TEXT NOT NULL,
 feature_version TEXT NOT NULL, feature_hash TEXT NOT NULL,
 payload TEXT NOT NULL, created_at REAL NOT NULL,
 UNIQUE(job_id,video_sha256,input_snapshot_hash,feature_version)
);
CREATE TABLE creative_labels (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
 feature_id TEXT NOT NULL REFERENCES creative_features(id),
 origin TEXT NOT NULL CHECK(origin IN ('human','model')), label_key TEXT NOT NULL,
 request_id TEXT NOT NULL UNIQUE, command_hash TEXT NOT NULL,
 payload TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE INDEX creative_labels_feature ON creative_labels(feature_id,origin,label_key,seq);
CREATE INDEX report_batches_review_window ON report_batches(account_id,seq DESC);
CREATE TABLE review_snapshots (
 id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, command_hash TEXT NOT NULL,
 account_id TEXT NOT NULL REFERENCES platform_accounts(id),
 start_date TEXT NOT NULL, end_date TEXT NOT NULL,
 snapshot_hash TEXT NOT NULL, payload TEXT NOT NULL,
 actor TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE INDEX review_snapshot_account ON review_snapshots(account_id,created_at);
CREATE TABLE review_sources (
 review_id TEXT NOT NULL REFERENCES review_snapshots(id),
 batch_id TEXT NOT NULL REFERENCES report_batches(id),
 path TEXT NOT NULL, sha256 TEXT NOT NULL,
 selected_dates TEXT NOT NULL, selected_rows_hash TEXT NOT NULL,
 PRIMARY KEY(review_id,batch_id)
);
CREATE TABLE review_feature_links (
 review_id TEXT NOT NULL REFERENCES review_snapshots(id), material_id TEXT NOT NULL,
 feature_id TEXT REFERENCES creative_features(id), job_id TEXT REFERENCES jobs(id),
 PRIMARY KEY(review_id,material_id)
);
CREATE TRIGGER creative_features_no_update BEFORE UPDATE ON creative_features BEGIN SELECT RAISE(ABORT,'immutable creative feature'); END;
CREATE TRIGGER creative_features_no_delete BEFORE DELETE ON creative_features BEGIN SELECT RAISE(ABORT,'immutable creative feature'); END;
CREATE TRIGGER creative_labels_no_update BEFORE UPDATE ON creative_labels BEGIN SELECT RAISE(ABORT,'immutable creative label'); END;
CREATE TRIGGER creative_labels_no_delete BEFORE DELETE ON creative_labels BEGIN SELECT RAISE(ABORT,'immutable creative label'); END;
CREATE TRIGGER review_snapshots_no_update BEFORE UPDATE ON review_snapshots BEGIN SELECT RAISE(ABORT,'immutable review snapshot'); END;
CREATE TRIGGER review_snapshots_no_delete BEFORE DELETE ON review_snapshots BEGIN SELECT RAISE(ABORT,'immutable review snapshot'); END;
CREATE TRIGGER review_sources_no_update BEFORE UPDATE ON review_sources BEGIN SELECT RAISE(ABORT,'immutable review source'); END;
CREATE TRIGGER review_sources_no_delete BEFORE DELETE ON review_sources BEGIN SELECT RAISE(ABORT,'immutable review source'); END;
CREATE TRIGGER review_feature_links_no_update BEFORE UPDATE ON review_feature_links BEGIN SELECT RAISE(ABORT,'immutable review feature link'); END;
CREATE TRIGGER review_feature_links_no_delete BEFORE DELETE ON review_feature_links BEGIN SELECT RAISE(ABORT,'immutable review feature link'); END;
