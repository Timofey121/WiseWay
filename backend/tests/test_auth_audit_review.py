from uuid import uuid4

from test_api import login
from wiseway.audit import emit


def _headers(csrf):
    return {"Origin": "http://localhost:8000", "X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4())}


def _audit_query(client, **filters):
    return client.post(
        "/api/v1/audit/query",
        json={
            "company_id": filters.get("company_id"),
            "from": "2020-01-01T00:00:00Z",
            "to": "2099-01-01T00:00:00Z",
            "actor_id": filters.get("actor_id"),
            "action": filters.get("action"),
            "result": filters.get("result"),
            "query_text": "",
            "cursor": None,
            "limit": 100,
        },
    )


def test_blocked_session_cannot_make_new_requests_but_accepted_work_and_audit_actor_survive(
    client, configured
):
    from wiseway.indexer import Indexer
    from wiseway.worker import Worker

    csrf = login(client)
    ctx = client.app.state.ctx
    with ctx.store.transaction() as tx:
        for item in tx.list("queue"):
            item["_observed_at"] = configured.clock() - 6
            tx.put("queue", item["item_id"], item)
    Indexer(ctx).scan()
    queue = client.post(
        "/api/v1/sorting/queue/query",
        json={
            "company_id": "company-atlas",
            "filters": {"statuses": ["READY"], "query_text": ""},
            "cursor": None,
            "limit": 100,
        },
    ).json()
    item = queue["items"][0]
    selected = client.post(
        "/api/v1/sorting/selections",
        headers=_headers(csrf),
        json={
            "company_id": "company-atlas",
            "mode": "EXPLICIT",
            "items": [{"item_id": item["item_id"], "item_revision": item["item_revision"]}],
        },
    )
    assert selected.status_code == 201, selected.text
    accepted = client.post(
        "/api/v1/sorting/batches",
        headers=_headers(csrf),
        json={"execution_mode": "DIRECT", "selection_id": selected.json()["selection_id"]},
    )
    assert accepted.status_code == 202, accepted.text
    batch_id = accepted.json()["batch_id"]
    original_actor = client.get("/api/v1/session").json()["actor"]

    with ctx.store.transaction() as tx:
        user = tx.require("user", original_actor["user_id"])
        user["blocked"] = True
        tx.put("user", user["actor"]["user_id"], user)
        admin = next(user["actor"] for user in tx.list("user") if user["actor"]["role"] == "ADMIN")
        blocked = emit(
            tx,
            admin,
            "ACCOUNT_BLOCKED",
            "request-blocked",
            now=configured.clock(),
            comment="Blocked account: " + original_actor["login"],
        )

    for response in (
        client.get("/api/v1/session"),
        client.get("/api/v1/companies"),
        client.post(
            "/api/v1/sorting/queue/query",
            json={
                "company_id": "company-atlas",
                "filters": {"statuses": ["READY"], "query_text": ""},
                "cursor": None,
                "limit": 100,
            },
        ),
    ):
        assert response.status_code == 401 and response.json()["error"]["code"] == "UNAUTHENTICATED"

    second_csrf = login(client, "worker-nova")
    visible_before_completion = _audit_query(client, company_id="company-atlas").json()["items"]
    assert visible_before_completion and all(
        event["category"] == "BUSINESS" for event in visible_before_completion
    )
    assert client.get(
        "/api/v1/audit/updates", params={"after_event_id": visible_before_completion[0]["event_id"]}
    ).json() == {"has_new_events": False}
    worker_actors_before_completion = client.get("/api/v1/audit/actors").json()["items"]
    assert admin["user_id"] not in {actor["user_id"] for actor in worker_actors_before_completion}

    Worker(ctx).run_once()
    finished = client.get(f"/api/v1/sorting/batches/{batch_id}")
    assert finished.status_code == 200, finished.text
    assert finished.json()["completed_count"] == 1
    assert finished.json()["actor"] == original_actor

    business = _audit_query(client, company_id="company-atlas")
    assert business.status_code == 200, business.text
    assert "ACCOUNT_BLOCKED" not in {event["action"] for event in business.json()["items"]}
    assert {
        event["actor"]["user_id"] for event in business.json()["items"] if event["batch_id"] == batch_id
    } == {original_actor["user_id"]}
    assert (
        client.post(
            "/api/v1/audit/query",
            json={
                "company_id": None,
                "from": "2020-01-01T00:00:00Z",
                "to": "2099-01-01T00:00:00Z",
                "actor_id": None,
                "action": "ACCOUNT_BLOCKED",
                "result": None,
                "query_text": "",
                "cursor": None,
                "limit": 100,
            },
        ).status_code
        == 403
    )
    assert client.get(
        "/api/v1/audit/updates", params={"after_event_id": visible_before_completion[0]["event_id"]}
    ).json() == {"has_new_events": True}
    worker_actors = client.get("/api/v1/audit/actors").json()["items"]
    assert original_actor["user_id"] in {actor["user_id"] for actor in worker_actors}

    client.post("/api/v1/auth/logout", headers=_headers(second_csrf))
    admin_csrf = login(client, "admin")
    system = _audit_query(client, action="ACCOUNT_BLOCKED")
    assert system.status_code == 200, system.text
    assert system.json()["items"][0]["event_id"] == blocked["event_id"]
    assert system.json()["items"][0]["comment"] == "Blocked account: " + original_actor["login"]
    admin_actors = client.get("/api/v1/audit/actors", headers={"X-CSRF-Token": admin_csrf}).json()["items"]
    assert original_actor["user_id"] in {actor["user_id"] for actor in admin_actors}
