ALTER TABLE jobs ADD COLUMN provenance TEXT;
CREATE TABLE products (
 id TEXT PRIMARY KEY, title TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('collecting','facts_confirmed','script_draft','script_confirmed')),
 revision INTEGER NOT NULL DEFAULT 0, current_review_id TEXT, current_draft_id TEXT,
 created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE product_sources (
 id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(id),
 kind TEXT NOT NULL CHECK(kind IN ('document','url')), file_name TEXT NOT NULL,
 original_url TEXT, final_url TEXT, path TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL,
 extracted TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE product_facts (
 id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(id),
 source_id TEXT NOT NULL REFERENCES product_sources(id), unit_id TEXT NOT NULL,
 text TEXT NOT NULL, locator TEXT NOT NULL, created_at REAL NOT NULL,
 UNIQUE(source_id,unit_id,text)
);
CREATE TABLE fact_reviews (
 id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(id), fact_ids TEXT NOT NULL,
 facts_hash TEXT NOT NULL, reviewer TEXT NOT NULL, note TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE script_drafts (
 id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(id), facts_review_id TEXT NOT NULL REFERENCES fact_reviews(id),
 mode TEXT NOT NULL, model TEXT, payload TEXT NOT NULL, script_hash TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE script_approvals (
 id TEXT PRIMARY KEY, draft_id TEXT NOT NULL UNIQUE REFERENCES script_drafts(id),
 job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id), reviewer TEXT NOT NULL,
 note TEXT NOT NULL, script_hash TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE product_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, product_id TEXT NOT NULL REFERENCES products(id),
 revision INTEGER NOT NULL, message TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE INDEX product_sources_product ON product_sources(product_id);
CREATE INDEX product_facts_product ON product_facts(product_id);
CREATE INDEX script_drafts_product ON script_drafts(product_id);
