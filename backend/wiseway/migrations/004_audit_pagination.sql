CREATE INDEX IF NOT EXISTS audit_utc_event_order
ON audit(
  strftime(
    '%Y-%m-%dT%H:%M:%S',
    replace(substr(json_extract(body, '$.occurred_at'), 1, 19), 't', 'T') ||
    CASE
      WHEN instr(substr(json_extract(body, '$.occurred_at'), 20), 'Z') > 0 THEN 'Z'
      WHEN instr(substr(json_extract(body, '$.occurred_at'), 20), '+') > 0
        THEN substr(json_extract(body, '$.occurred_at'), 19 + instr(substr(json_extract(body, '$.occurred_at'), 20), '+'))
      ELSE substr(json_extract(body, '$.occurred_at'), 19 + instr(substr(json_extract(body, '$.occurred_at'), 20), '-'))
    END
  ) || '.' ||
  substr(
    (
      CASE WHEN substr(json_extract(body, '$.occurred_at'), 20, 1)='.' THEN substr(
        json_extract(body, '$.occurred_at'),
        21,
        (
          CASE
            WHEN instr(substr(json_extract(body, '$.occurred_at'), 20), 'Z') > 0 THEN instr(substr(json_extract(body, '$.occurred_at'), 20), 'Z')
            WHEN instr(substr(json_extract(body, '$.occurred_at'), 20), '+') > 0 THEN instr(substr(json_extract(body, '$.occurred_at'), 20), '+')
            ELSE instr(substr(json_extract(body, '$.occurred_at'), 20), '-')
          END
        ) - 2
      ) ELSE '' END
    ) || '000000',
    1,
    6
  ) DESC,
  json_extract(body, '$.event_id') DESC
);

CREATE INDEX IF NOT EXISTS audit_business_seq
ON audit(seq DESC)
WHERE json_extract(body, '$.category')='BUSINESS';

CREATE INDEX IF NOT EXISTS audit_actor_first
ON audit(json_extract(body, '$.actor.user_id'), seq)
WHERE json_extract(body, '$.actor.user_id') IS NOT NULL;
