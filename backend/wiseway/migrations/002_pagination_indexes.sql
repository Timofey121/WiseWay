CREATE INDEX IF NOT EXISTS page_expiry
ON objects(COALESCE(CAST(json_extract(body, '$.expires') AS REAL), 0))
WHERE kind IN ('cursor', 'page_snapshot');
CREATE INDEX IF NOT EXISTS page_owner_bytes
ON objects(json_extract(body, '$.owner'), CAST(json_extract(body, '$.payload_bytes') AS INTEGER))
WHERE kind='page_snapshot';
INSERT OR IGNORE INTO schema_migrations VALUES(2);
