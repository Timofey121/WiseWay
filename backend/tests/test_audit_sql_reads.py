"""Polling and actor lookup must not materialize the full audit journal."""

from __future__ import annotations

from test_api import login
from wiseway.audit import emit
from wiseway.common import digest
from wiseway.storage import UnitOfWork


def test_updates_and_actors_use_sql_and_keep_oldest_actor_snapshot(client, monkeypatch):
    login(client, "admin")
    context = client.app.state.ctx
    old = {"user_id": "actor-history", "login": "old-login", "display_name": "Old name", "role": "WORKER"}
    newer = {"user_id": "actor-history", "login": "new-login", "display_name": "New name", "role": "ADMIN"}
    with context.store.transaction() as tx:
        first = emit(tx, old, "DRAFT_SAVED", "request-actor-old", now=context.settings.clock() - 1)
        emit(tx, newer, "DRAFT_SAVED", "request-actor-new", now=context.settings.clock())

    def reject_full_audit(self):
        raise AssertionError("polling must not decode every audit event")

    monkeypatch.setattr(UnitOfWork, "events", reject_full_audit)
    updates = client.get("/api/v1/audit/updates", params={"after_event_id": first["event_id"]})
    actors = client.get("/api/v1/audit/actors", params={"prefix": "old", "limit": 100})
    assert updates.status_code == 200 and updates.json() == {"has_new_events": True}
    assert actors.status_code == 200
    assert actors.json()["items"] == [old]


def test_invalid_and_legacy_audit_cursors_do_not_materialize_audit(client, monkeypatch):
    login(client, "admin")
    actor = client.get("/api/v1/session").json()["actor"]
    context = client.app.state.ctx
    with context.store.transaction() as tx:
        first = emit(tx, actor, "DRAFT_SAVED", "request-legacy-first", now=context.settings.clock() - 1)
        second = emit(tx, actor, "DRAFT_SAVED", "request-legacy-second", now=context.settings.clock())
        body = {
            "company_id": None,
            "from": "2020-01-01T00:00:00Z",
            "to": "2099-01-01T00:00:00Z",
            "actor_id": None,
            "action": None,
            "result": None,
            "query_text": "",
            "cursor": "legacy-audit-cursor",
            "limit": 1,
        }
        tx.put(
            "cursor",
            "legacy-audit-cursor",
            {
                "scope": "queryAuditEvents",
                "owner": actor["user_id"],
                "query": digest(
                    {key: value for key, value in body.items() if key not in ("cursor", "limit")}
                ),
                "payload": {"items": [second, first], "newest_event_id": second["event_id"]},
                "offset": 1,
                "expires": context.settings.clock() + 86400,
            },
        )

    monkeypatch.setattr(
        UnitOfWork, "events", lambda self: (_ for _ in ()).throw(AssertionError("full audit read"))
    )
    invalid = client.post("/api/v1/audit/query", json={**body, "cursor": "unknown-audit-cursor"})
    legacy = client.post("/api/v1/audit/query", json=body)
    assert invalid.status_code == 422
    assert legacy.status_code == 200
    assert legacy.json() == {"items": [first], "newest_event_id": second["event_id"], "next_cursor": None}


def test_system_only_events_do_not_consume_worker_page_snapshots(client):
    from test_audit_pagination_scale import _event, _query

    login(client)
    actor = client.get("/api/v1/session").json()["actor"]
    ctx = client.app.state.ctx
    with ctx.store.transaction() as tx:
        for number in range(3):
            tx.append_event(_event(f"visible-{number}", "2031-01-01T00:00:00Z", actor))
    first = client.post("/api/v1/audit/query", json=_query(limit=1))
    assert first.status_code == 200
    with ctx.store.transaction() as tx:
        emit(tx, actor, "LOGIN_SUCCEEDED", "unrelated-system-event", now=ctx.settings.clock())
    second = client.post("/api/v1/audit/query", json=_query(limit=1))
    assert second.status_code == 200
    assert second.json() == first.json()
    with ctx.store.transaction(write=False) as tx:
        assert len([row for row in tx.list("page_snapshot") if row.get("kind") == "audit-seq"]) == 1
