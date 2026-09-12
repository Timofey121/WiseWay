"""Compact, SQL-backed immutable pages for the append-only audit journal."""

from __future__ import annotations

import json

from .audit import query_bounds
from .common import ApiError, digest


_EVENT_ID = "json_extract(body, '$.event_id')"


def _normalized_utc(value):
    """Canonical UTC microsecond string without SQLite's fractional rounding."""
    tail = f"substr({value}, 20)"
    timezone_position = (
        f"CASE WHEN instr({tail}, 'Z') > 0 THEN instr({tail}, 'Z') "
        f"WHEN instr({tail}, '+') > 0 THEN instr({tail}, '+') ELSE instr({tail}, '-') END"
    )
    timezone = (
        f"CASE WHEN instr({tail}, 'Z') > 0 THEN 'Z' "
        f"WHEN instr({tail}, '+') > 0 THEN substr({value}, 19 + instr({tail}, '+')) "
        f"ELSE substr({value}, 19 + instr({tail}, '-')) END"
    )
    fraction = (
        f"CASE WHEN substr({value}, 20, 1)='.' THEN substr({value}, 21, ({timezone_position}) - 2) "
        "ELSE '' END"
    )
    return (
        f"strftime('%Y-%m-%dT%H:%M:%S', replace(substr({value}, 1, 19), 't', 'T') || {timezone}) || '.' || "
        f"substr(({fraction}) || '000000', 1, 6)"
    )


_OCCURRED = _normalized_utc("json_extract(body, '$.occurred_at')")


def _casefold_contains(value, needle):
    return int(isinstance(value, str) and isinstance(needle, str) and needle.casefold() in value.casefold())


def _casefold_startswith(value, prefix):
    return int(
        isinstance(value, str) and isinstance(prefix, str) and value.casefold().startswith(prefix.casefold())
    )


def _signature(body):
    return digest({key: value for key, value in body.items() if key not in ("cursor", "limit")})


def is_sql_cursor(tx, cursor):
    return bool(cursor and (saved := tx.get("cursor", cursor)) and saved.get("audit_keyset") is True)


def _where(actor, body, cutoff_seq, after=None):
    clauses = [
        "seq <= :cutoff_seq",
        f"{_OCCURRED} >= {_normalized_utc(':from_value')}",
        f"{_OCCURRED} < {_normalized_utc(':to_value')}",
    ]
    values = {"cutoff_seq": cutoff_seq, "from_value": body["from"], "to_value": body["to"]}
    if actor["role"] != "ADMIN":
        clauses.append("json_extract(body, '$.category')='BUSINESS'")
    for field in ("company_id", "action", "result"):
        if body[field] is not None:
            clauses.append(f"json_extract(body, '$.{field}')=:{field}")
            values[field] = body[field]
    if body["actor_id"] is not None:
        clauses.append("json_extract(body, '$.actor.user_id')=:actor_id")
        values["actor_id"] = body["actor_id"]
    if body["query_text"]:
        clauses.append(
            "(wiseway_casefold_contains(json_extract(body, '$.source.display_path'), :query_text) "
            "OR wiseway_casefold_contains(json_extract(body, '$.target.display_path'), :query_text))"
        )
        values["query_text"] = body["query_text"]
    if after is not None:
        clauses.append(
            f"({_OCCURRED} < {_normalized_utc(':after_occurred_at')} "
            f"OR ({_OCCURRED} = {_normalized_utc(':after_occurred_at')} AND {_EVENT_ID} < :after_event_id))"
        )
        values["after_occurred_at"] = after["occurred_at"]
        values["after_event_id"] = after["event_id"]
    return " AND ".join(clauses), values


def _events(tx, actor, body, cutoff_seq, limit, after=None):
    tx.connection.create_function("wiseway_casefold_contains", 2, _casefold_contains, deterministic=True)
    where, values = _where(actor, body, cutoff_seq, after)
    values["row_limit"] = limit + 1
    rows = tx.connection.execute(
        f"SELECT body FROM audit WHERE {where} ORDER BY {_OCCURRED} DESC, {_EVENT_ID} DESC LIMIT :row_limit",
        values,
    ).fetchall()
    return [json.loads(row[0]) for row in rows]


def _newest_visible_event_id(tx, actor, cutoff_seq):
    visibility = "" if actor["role"] == "ADMIN" else " AND json_extract(body, '$.category')='BUSINESS'"
    row = tx.connection.execute(
        f"SELECT {_EVENT_ID} FROM audit WHERE seq <= ?{visibility} ORDER BY seq DESC LIMIT 1", (cutoff_seq,)
    ).fetchone()
    return row[0] if row else None


def _visible_cutoff(tx, actor):
    visibility = "" if actor["role"] == "ADMIN" else " WHERE json_extract(body, '$.category')='BUSINESS'"
    row = tx.connection.execute(f"SELECT MAX(seq) FROM audit{visibility}").fetchone()
    return row[0] or 0


def newest_visible_event_id(tx, actor):
    """Read one append-order row for polling without decoding the journal."""
    return _newest_visible_event_id(tx, actor, _visible_cutoff(tx, actor))


def audit_actors(tx, actor, prefix):
    """Return the legacy oldest actor document for every visible actor ID."""
    tx.connection.create_function("wiseway_casefold_startswith", 2, _casefold_startswith, deterministic=True)
    visibility = "" if actor["role"] == "ADMIN" else " AND json_extract(body, '$.category')='BUSINESS'"
    rows = tx.connection.execute(
        "SELECT json_extract(a.body, '$.actor') FROM audit AS a JOIN ("
        "SELECT json_extract(body, '$.actor.user_id') AS actor_id, MIN(seq) AS first_seq "
        "FROM audit WHERE json_extract(body, '$.actor.user_id') IS NOT NULL"
        f"{visibility} GROUP BY actor_id"
        ") AS first ON a.seq=first.first_seq "
        "WHERE wiseway_casefold_startswith(json_extract(a.body, '$.actor.display_name'), :prefix) "
        "OR wiseway_casefold_startswith(json_extract(a.body, '$.actor.login'), :prefix)",
        {"prefix": prefix},
    ).fetchall()
    items = [json.loads(row[0]) for row in rows]
    return sorted(items, key=lambda value: (value["display_name"].casefold(), value["user_id"]))


def _snapshot_for_cursor(tx, actor, signature, cursor, now):
    saved = tx.get("cursor", cursor)
    if (
        saved is None
        or saved.get("audit_keyset") is not True
        or saved.get("scope") != "queryAuditEvents"
        or saved.get("owner") != actor["user_id"]
        or saved.get("query") != signature
        or saved.get("expires", 0) <= now
        or not isinstance(saved.get("occurred_at"), str)
        or not isinstance(saved.get("event_id"), str)
    ):
        raise ApiError("VALIDATION_ERROR", "Недействительный курсор страницы.", 422)
    snapshot = tx.get("page_snapshot", saved.get("snapshot_id"))
    if (
        snapshot is None
        or snapshot.get("kind") != "audit-seq"
        or snapshot.get("owner") != actor["user_id"]
        or snapshot.get("query") != signature
        or snapshot.get("expires", 0) <= now
    ):
        raise ApiError("VALIDATION_ERROR", "Недействительный курсор страницы.", 422)
    return snapshot, {"occurred_at": saved.get("occurred_at"), "event_id": saved.get("event_id")}


def query_page(ctx, tx, actor, body):
    """Return a stable audit page without serializing all matching events."""
    query_bounds(actor, body)
    signature = _signature(body)
    now = ctx.settings.clock()
    if body["cursor"]:
        snapshot, after = _snapshot_for_cursor(tx, actor, signature, body["cursor"], now)
        cutoff_seq, newest_event_id = snapshot["cutoff_seq"], snapshot["newest_event_id"]
    else:
        cutoff_seq = _visible_cutoff(tx, actor)
        newest_event_id = _newest_visible_event_id(tx, actor, cutoff_seq)
        snapshot = after = None
    rows = _events(tx, actor, body, cutoff_seq, body["limit"], after)
    items, more = rows[: body["limit"]], len(rows) > body["limit"]
    next_cursor = None
    if more:
        if snapshot is None:
            snapshot = ctx.reserve_audit_snapshot(actor, signature, cutoff_seq, newest_event_id)
        last = items[-1]
        next_cursor = ctx.create_audit_cursor(
            actor, signature, snapshot, last["occurred_at"], last["event_id"]
        )
    return {"items": items, "next_cursor": next_cursor, "newest_event_id": newest_event_id}
