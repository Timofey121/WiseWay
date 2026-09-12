-- ``modified_at`` remains the exact public RFC3339 UTC spelling. A separate
-- normalized key makes lexical ordering chronological with mixed precision.
ALTER TABLE search_items ADD COLUMN modified_key TEXT NOT NULL DEFAULT '';

UPDATE search_items
SET modified_key =
    substr(modified_at, 1, 19) || '.' ||
    CASE
        WHEN instr(modified_at, '.') = 0 THEN ''
        ELSE rtrim(substr(modified_at, instr(modified_at, '.') + 1, length(modified_at) - instr(modified_at, '.') - 1), '0')
    END;

DROP INDEX search_items_modified_order;
CREATE INDEX search_items_modified_order
ON search_items(generation_id, modified_key, path_key, relative_path, item_id);
