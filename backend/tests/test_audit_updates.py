from test_api import login
from wiseway.audit import emit


def test_new_event_with_equal_timestamp_is_detected_even_with_lower_opaque_id(client, monkeypatch):
    login(client)
    ctx = client.app.state.ctx
    actor = client.get("/api/v1/session").json()["actor"]
    ids = iter(["event-zzz", "event-aaa"])
    monkeypatch.setattr("wiseway.audit.uid", lambda _: next(ids))
    with ctx.store.transaction() as tx:
        first = emit(tx, actor, "DRAFT_SAVED", "request-a", now=ctx.settings.clock())
    seen = client.get("/api/v1/audit/updates", params={"after_event_id": first["event_id"]})
    assert seen.json() == {"has_new_events": False}
    from wiseway.common import timestamp

    with ctx.store.transaction() as tx:
        second = emit(tx, actor, "DRAFT_SAVED", "request-b", now=timestamp(first["occurred_at"]))
    updated = client.get("/api/v1/audit/updates", params={"after_event_id": first["event_id"]})
    assert updated.json() == {"has_new_events": True}
    result = client.post(
        "/api/v1/audit/query",
        json={
            "company_id": None,
            "from": "2020-01-01T00:00:00Z",
            "to": "2099-01-01T00:00:00Z",
            "actor_id": None,
            "action": None,
            "result": None,
            "query_text": "",
            "cursor": None,
            "limit": 100,
        },
    ).json()
    assert result["newest_event_id"] == second["event_id"]
    # Presentation order remains the contract's timestamp / opaque ID order.
    assert [e["event_id"] for e in result["items"]] == [first["event_id"], second["event_id"]]
    assert client.get("/api/v1/audit/updates", params={"after_event_id": second["event_id"]}).json() == {
        "has_new_events": False
    }
