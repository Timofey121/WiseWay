"""Regression coverage for SQL-backed immutable audit pages."""

from __future__ import annotations

import json

from test_api import login


def _event(event_id: str, occurred_at: str, actor: dict) -> dict:
    return {
        "event_id": event_id,
        "occurred_at": occurred_at,
        "actor": actor,
        "category": "BUSINESS",
        "action": "DRAFT_SAVED",
        "result": "SUCCESS",
        "request_id": f"request-{event_id}",
        "operation_id": None,
        "source_attempt_id": None,
        "company_id": "company-atlas",
        "dictionary_id": None,
        "version_id": None,
        "rule_set_id": None,
        "batch_id": None,
        "attempt_id": None,
        "item_id": None,
        "source": {
            "root_id": "archive-root",
            "relative_path": f"Incoming/{event_id}.txt",
            "display_path": event_id,
        },
        "target": None,
        "reason_code": None,
        "comment": None,
    }


def _query(*, cursor=None, limit=2):
    return {
        "company_id": "company-atlas",
        "from": "2029-01-01T00:00:00Z",
        "to": "2032-01-01T00:00:00Z",
        "actor_id": None,
        "action": "DRAFT_SAVED",
        "result": "SUCCESS",
        "query_text": "",
        "cursor": cursor,
        "limit": limit,
    }


def test_audit_sql_pages_scale_past_payload_limit_and_keep_utc_order(client):
    login(client, "admin")
    actor = client.get("/api/v1/session").json()["actor"]
    context = client.app.state.ctx
    bulk = [_event(f"bulk-{number:05d}", "2030-01-01T00:00:00Z", actor) for number in range(20_000)]
    timezone_events = [
        _event("timezone-a", "2031-01-01T07:00:00Z", actor),
        _event("timezone-b", "2031-01-01T07:30:00Z", actor),
        _event("timezone-c", "2031-01-01T07:00:00Z", actor),
    ]
    with context.store.transaction() as tx:
        tx.connection.executemany(
            "INSERT INTO audit(id, body) VALUES (?, ?)",
            [(event["event_id"], json.dumps(event, ensure_ascii=False)) for event in bulk + timezone_events],
        )

    first = client.post("/api/v1/audit/query", json=_query())
    assert first.status_code == 200, first.text
    assert [event["event_id"] for event in first.json()["items"]] == ["timezone-b", "timezone-c"]
    assert first.json()["next_cursor"]
    with context.store.transaction(write=False) as tx:
        snapshots = tx.list("page_snapshot")
    audit_snapshots = [snapshot for snapshot in snapshots if snapshot.get("kind") == "audit-seq"]
    assert len(audit_snapshots) == 1
    assert "payload" not in audit_snapshots[0]
    assert audit_snapshots[0]["payload_bytes"] < 10_000

    later = _event("later-after-snapshot", "2031-01-01T09:00:00Z", actor)
    with context.store.transaction() as tx:
        tx.connection.execute(
            "INSERT INTO audit(id, body) VALUES (?, ?)", (later["event_id"], json.dumps(later))
        )
    second = client.post("/api/v1/audit/query", json=_query(cursor=first.json()["next_cursor"]))
    assert second.status_code == 200, second.text
    assert [event["event_id"] for event in second.json()["items"]] == ["timezone-a", "bulk-19999"]
    assert later["event_id"] not in {event["event_id"] for event in second.json()["items"]}


def test_audit_sql_uses_utc_not_lexical_timestamp_order(client):
    from wiseway.audit_pagination import _events

    context = client.app.state.ctx
    actor = {"user_id": "utc-test", "login": "utc-test", "display_name": "UTC", "role": "ADMIN"}
    events = [
        _event("utc-a", "2031-01-01T10:00:00+03:00", actor),  # 07:00 UTC
        _event("utc-b", "2031-01-01T07:30:00Z", actor),  # 07:30 UTC
        _event("utc-c", "2031-01-01T08:00:00+01:00", actor),  # 07:00 UTC
    ]
    with context.store.transaction() as tx:
        tx.connection.executemany(
            "INSERT INTO audit(id, body) VALUES (?, ?)",
            [(event["event_id"], json.dumps(event)) for event in events],
        )
    body = _query(limit=10)
    with context.store.transaction(write=False) as tx:
        cutoff = tx.connection.execute("SELECT MAX(seq) FROM audit").fetchone()[0]
        ordered = _events(tx, actor, body, cutoff, 10)
    assert [event["event_id"] for event in ordered] == ["utc-b", "utc-c", "utc-a"]


def test_audit_sql_keeps_microsecond_order_when_event_ids_reverse(client):
    from wiseway.audit_pagination import _events

    context = client.app.state.ctx
    actor = {"user_id": "micro-test", "login": "micro-test", "display_name": "Micro", "role": "ADMIN"}
    events = [
        _event("micro-z", "2031-01-01T07:00:00.000001Z", actor),
        _event("micro-a", "2031-01-01T07:00:00.000002Z", actor),
    ]
    with context.store.transaction() as tx:
        tx.connection.executemany(
            "INSERT INTO audit(id, body) VALUES (?, ?)",
            [(event["event_id"], json.dumps(event)) for event in events],
        )
    with context.store.transaction(write=False) as tx:
        cutoff = tx.connection.execute("SELECT MAX(seq) FROM audit").fetchone()[0]
        ordered = _events(tx, actor, _query(limit=10), cutoff, 10)
    assert [event["event_id"] for event in ordered] == ["micro-a", "micro-z"]


def test_audit_utc_normalization_preserves_midnight_and_fractional_precision():
    import sqlite3

    from wiseway.audit_pagination import _normalized_utc

    connection = sqlite3.connect(":memory:")
    try:
        values = {
            "midnight": "2030-12-31T23:59:59.999999-01:00",
            "short_fraction": "2031-01-01T00:00:00.1Z",
            "long_fraction": "2031-01-01T00:00:00.123456789Z",
        }
        normalized = {
            name: connection.execute(f"SELECT {_normalized_utc(':value')}", {"value": value}).fetchone()[0]
            for name, value in values.items()
        }
    finally:
        connection.close()
    assert normalized == {
        "midnight": "2031-01-01T00:59:59.999999",
        "short_fraction": "2031-01-01T00:00:00.100000",
        "long_fraction": "2031-01-01T00:00:00.123456",
    }


def test_expired_audit_cursor_cannot_revive_with_same_cutoff(configured):
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from wiseway.app import create_app

    now = [2_000_000_000.0]
    settings = replace(
        configured,
        clock=lambda: now[0],
        absolute_session_seconds=3 * 86400,
        idle_session_seconds=3 * 86400,
    )
    with TestClient(create_app(settings), base_url="http://localhost:8000") as local_client:
        login(local_client, "admin")
        actor = local_client.get("/api/v1/session").json()["actor"]
        context = local_client.app.state.ctx
        events = [_event(f"expiry-{number}", "2030-01-01T00:00:00Z", actor) for number in range(3)]
        with context.store.transaction() as tx:
            tx.connection.executemany(
                "INSERT INTO audit(id, body) VALUES (?, ?)",
                [(event["event_id"], json.dumps(event)) for event in events],
            )
        first = local_client.post("/api/v1/audit/query", json=_query(limit=1))
        assert first.status_code == 200
        old_cursor = first.json()["next_cursor"]
        with context.store.transaction(write=False) as tx:
            cutoff = tx.connection.execute("SELECT MAX(seq) FROM audit").fetchone()[0]
        now[0] += 86401
        replacement = local_client.post("/api/v1/audit/query", json=_query(limit=1))
        assert replacement.status_code == 200
        assert replacement.json()["next_cursor"] != old_cursor
        with context.store.transaction(write=False) as tx:
            assert tx.connection.execute("SELECT MAX(seq) FROM audit").fetchone()[0] == cutoff
        expired = local_client.post("/api/v1/audit/query", json=_query(cursor=old_cursor, limit=1))
        assert expired.status_code == 422
        assert expired.json()["error"]["code"] == "VALIDATION_ERROR"
