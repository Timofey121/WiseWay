-- Durable, unpublished file observations for the bounded-memory large archive
-- scanner.  A run is never visible to readers until its separate search
-- generation has been published.
CREATE TABLE large_scan_runs (
    run_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('SCANNING', 'FAILED', 'BUILT', 'PUBLISHED')),
    config_digest TEXT NOT NULL,
    fingerprint_digest TEXT,
    entry_count INTEGER NOT NULL DEFAULT 0 CHECK(entry_count >= 0),
    generation TEXT,
    created_at REAL NOT NULL,
    completed_at REAL
);

CREATE INDEX large_scan_runs_root_state
ON large_scan_runs(root_id, state, created_at);

CREATE TABLE large_scan_entries (
    run_id TEXT NOT NULL REFERENCES large_scan_runs(run_id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    dev INTEGER NOT NULL,
    ino INTEGER NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    item_id TEXT,
    PRIMARY KEY(run_id, path)
) WITHOUT ROWID;

CREATE INDEX large_scan_entries_inode
ON large_scan_entries(run_id, dev, ino, path);

CREATE INDEX large_scan_entries_item
ON large_scan_entries(run_id, item_id)
WHERE item_id IS NOT NULL;
