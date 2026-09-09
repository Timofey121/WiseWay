CREATE TABLE search_generations (
    generation_id TEXT PRIMARY KEY,
    root_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('BUILDING', 'READY', 'ACTIVE', 'FAILED')),
    created_at TEXT NOT NULL
);

CREATE INDEX search_generations_root_state
ON search_generations(root_id, state, generation_id);

CREATE TABLE search_items (
    row_id INTEGER PRIMARY KEY,
    generation_id TEXT NOT NULL REFERENCES search_generations(generation_id) ON DELETE CASCADE,
    item_no INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    body TEXT NOT NULL CHECK(json_valid(body)),
    filename_key BLOB NOT NULL,
    path_key BLOB NOT NULL,
    relative_path TEXT NOT NULL,
    modified_at TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    UNIQUE(generation_id, item_no),
    UNIQUE(generation_id, item_id)
);

CREATE INDEX search_items_path_order
ON search_items(generation_id, path_key, relative_path, item_id);
CREATE INDEX search_items_name_order
ON search_items(generation_id, filename_key, path_key, relative_path, item_id);
CREATE INDEX search_items_modified_order
ON search_items(generation_id, modified_at, path_key, relative_path, item_id);
CREATE INDEX search_items_size_order
ON search_items(generation_id, size_bytes, path_key, relative_path, item_id);

CREATE TABLE search_item_markers (
    generation_id TEXT NOT NULL REFERENCES search_generations(generation_id) ON DELETE CASCADE,
    row_id INTEGER NOT NULL REFERENCES search_items(row_id) ON DELETE CASCADE,
    depth INTEGER NOT NULL,
    marker_id TEXT NOT NULL,
    PRIMARY KEY(generation_id, row_id, depth)
) WITHOUT ROWID;

CREATE INDEX search_item_markers_selection
ON search_item_markers(generation_id, depth, marker_id, row_id);

CREATE TABLE search_markers (
    generation_id TEXT NOT NULL REFERENCES search_generations(generation_id) ON DELETE CASCADE,
    marker_id TEXT NOT NULL,
    parent_marker_id TEXT,
    depth INTEGER NOT NULL,
    marker_json TEXT NOT NULL CHECK(json_valid(marker_json)),
    unrecognized INTEGER NOT NULL,
    display_folded BLOB NOT NULL,
    display_key BLOB NOT NULL,
    raw_value TEXT NOT NULL,
    PRIMARY KEY(generation_id, marker_id)
) WITHOUT ROWID;

CREATE INDEX search_markers_facet_order
ON search_markers(generation_id, parent_marker_id, unrecognized, display_key, raw_value, marker_id);

-- Values are already tokenized and encoded by wiseway.sqlite_search.  Keeping
-- the FTS tokenizer on ASCII-only words therefore preserves product token
-- semantics while retaining FTS5's compressed inverted index and positions.
CREATE VIRTUAL TABLE search_fts USING fts5(
    generation,
    filename,
    project,
    company,
    markers,
    path,
    tokenize='unicode61 remove_diacritics 0',
    detail=full,
    columnsize=0,
    content=''
);
