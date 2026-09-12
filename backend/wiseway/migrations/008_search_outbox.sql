CREATE TABLE search_outbox (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT NOT NULL UNIQUE,
    root_id TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX search_outbox_root_seq ON search_outbox(root_id,seq);
