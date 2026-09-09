CREATE INDEX IF NOT EXISTS attempt_batch_lookup
ON objects(json_extract(body, '$.batch_id'))
WHERE kind='attempt';

CREATE INDEX IF NOT EXISTS queue_company_order
ON objects(json_extract(body, '$.company_id'), id)
WHERE kind='queue';
