from test_api import login
from wiseway.storage import UnitOfWork


def test_audit_query_materializes_visible_events_once(client, monkeypatch):
    login(client)
    calls = []
    original = UnitOfWork.events

    def count_reads(self):
        calls.append(True)
        return original(self)

    monkeypatch.setattr(UnitOfWork, "events", count_reads)
    response = client.post(
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
    )
    assert response.status_code == 200
    assert len(calls) <= 1
