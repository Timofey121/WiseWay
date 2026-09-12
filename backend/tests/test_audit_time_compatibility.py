from test_api import login
from test_audit_pagination_scale import _event, _query


def test_audit_accepts_lowercase_rfc3339_time_separator(client):
    login(client, "admin")
    actor = client.get("/api/v1/session").json()["actor"]
    event = _event("lowercase-time-bound", "2031-01-01T00:00:00.000001Z", actor)
    with client.app.state.ctx.store.transaction() as tx:
        tx.append_event(event)
    body = {**_query(), "from": "2031-01-01t00:00:00Z", "to": "2031-01-02t00:00:00Z"}
    response = client.post("/api/v1/audit/query", json=body)
    assert response.status_code == 200, response.text
    assert [row["event_id"] for row in response.json()["items"]] == [event["event_id"]]
