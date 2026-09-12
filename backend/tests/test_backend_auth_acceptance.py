"""API-level acceptance checks for authentication and the immutable audit journal."""

from uuid import uuid4

from test_api import login
from wiseway.audit import emit
from wiseway.common import timestamp


def _audit_request(**overrides):
    request = {
        "company_id": None,
        "from": "2020-01-01T00:00:00Z",
        "to": "2099-01-01T00:00:00Z",
        "actor_id": None,
        "action": None,
        "result": None,
        "query_text": "",
        "cursor": None,
        "limit": 100,
    }
    request.update(overrides)
    return request


def test_admin_reads_every_declared_system_audit_action(client):
    """New local-account events must remain readable after API schema validation."""
    from wiseway.accounts import AccountService

    ctx = client.app.state.ctx
    accounts = AccountService(ctx)
    created = accounts.create_user("admin", "audit-user", "Audit User", "WORKER", "synthetic-test-password")
    accounts.block_user("admin", "audit-user")
    accounts.unblock_user("admin", "audit-user")
    accounts.reset_password("admin", "audit-user", "changed-synthetic-password")

    login(client, "admin")
    admin = client.get("/api/v1/session").json()["actor"]
    expected = {
        "ACCOUNT_CREATED": "Created account: audit-user",
        "ACCOUNT_UNBLOCKED": "Unblocked account: audit-user",
        "PASSWORD_CHANGED": "Password changed: audit-user",
    }
    for action, comment in expected.items():
        response = client.post("/api/v1/audit/query", json=_audit_request(action=action))
        assert response.status_code == 200, response.text
        assert len(response.json()["items"]) == 1
        assert response.json()["items"][0]["category"] == "SYSTEM"
        assert response.json()["items"][0]["actor"] == admin
        assert response.json()["items"][0]["comment"] == comment
    assert created["login"] == "audit-user"


def test_audit_filters_interval_text_and_cursor_keep_a_fixed_journal_snapshot(client):
    """Q-041: server-side journal filters and cursors must not drift when it grows."""
    login(client, "worker-atlas")
    worker = client.get("/api/v1/session").json()["actor"]
    ctx = client.app.state.ctx
    first = timestamp("2031-05-10T09:00:00Z")
    source = {
        "root_id": "archive-root",
        "relative_path": "Incoming/Atlas/quarterly-2031.txt",
        "display_path": "DEMO:/SandboxRoot/Incoming/Atlas/quarterly-2031.txt",
    }
    with ctx.store.transaction() as tx:
        oldest = emit(
            tx,
            worker,
            "DRAFT_SAVED",
            "request-audit-oldest",
            now=first,
            company_id="company-atlas",
            source=source,
        )
        middle = emit(
            tx,
            worker,
            "DRAFT_SAVED",
            "request-audit-middle",
            now=first + 60,
            company_id="company-atlas",
            target=source,
        )
        newest = emit(
            tx,
            worker,
            "DRAFT_SAVED",
            "request-audit-newest",
            now=first + 120,
            company_id="company-atlas",
            source=source,
        )

    query = _audit_request(
        **{
            "company_id": "company-atlas",
            "from": "2031-05-10T09:00:00Z",
            "to": "2031-05-10T09:03:00Z",
            "actor_id": worker["user_id"],
            "action": "DRAFT_SAVED",
            "result": "SUCCESS",
            "query_text": "QUARTERLY-2031",
            "limit": 1,
        }
    )
    page_one = client.post("/api/v1/audit/query", json=query)
    assert page_one.status_code == 200, page_one.text
    assert [event["event_id"] for event in page_one.json()["items"]] == [newest["event_id"]]

    with ctx.store.transaction() as tx:
        later = emit(
            tx,
            worker,
            "DRAFT_SAVED",
            "request-audit-later",
            now=first + 121,
            company_id="company-atlas",
            source=source,
        )
    query["cursor"] = page_one.json()["next_cursor"]
    page_two = client.post("/api/v1/audit/query", json=query)
    assert page_two.status_code == 200, page_two.text
    assert [event["event_id"] for event in page_two.json()["items"]] == [middle["event_id"]]
    assert later["event_id"] not in {event["event_id"] for event in page_two.json()["items"]}

    interval = client.post(
        "/api/v1/audit/query",
        json=_audit_request(
            **{
                "company_id": "company-atlas",
                "from": "2031-05-10T09:00:00Z",
                "to": "2031-05-10T09:02:00Z",
                "actor_id": worker["user_id"],
                "action": "DRAFT_SAVED",
            }
        ),
    )
    assert interval.status_code == 200, interval.text
    assert [event["event_id"] for event in interval.json()["items"]] == [
        middle["event_id"],
        oldest["event_id"],
    ]


def test_expired_session_loses_api_access_while_its_system_audit_remains(configured):
    """Q-002/003: expiry is final, but it never rewrites an actor's past evidence."""
    from dataclasses import replace

    from fastapi.testclient import TestClient
    from wiseway.app import create_app

    now = [2_000_000_000.0]
    settings = replace(configured, clock=lambda: now[0])
    with TestClient(create_app(settings), base_url="http://localhost:8000") as client:
        worker_csrf = login(client, "worker-atlas")
        worker = client.get("/api/v1/session").json()["actor"]
        now[0] += settings.idle_session_seconds
        expired = client.get("/api/v1/session")
        assert expired.status_code == 401
        assert expired.json()["error"]["code"] == "UNAUTHENTICATED"

        # The prior session credential cannot be used to mutate state at the expiry boundary.
        assert (
            client.post(
                "/api/v1/auth/logout",
                headers={"Origin": "http://localhost:8000", "X-CSRF-Token": worker_csrf},
            ).status_code
            == 401
        )

        login(client, "admin")
        history = client.post(
            "/api/v1/audit/query",
            json=_audit_request(action="LOGIN_SUCCEEDED", actor_id=worker["user_id"]),
        )
        assert history.status_code == 200, history.text
        assert history.json()["items"][0]["actor"] == worker


def test_search_unavailable_returns_retryable_503_and_recovers_at_the_api_boundary(client):
    """Q-003: a stale UI result must be distinguishable from a healthy empty search."""
    login(client)
    root = next(
        root for root in client.get("/api/v1/roots").json()["items"] if root["root_id"] == "archive-root"
    )
    request = {
        "request_state_id": "q003-search-unavailable",
        "root_id": root["root_id"],
        "schema_set_version": root["schema_set_version"],
        "selected_marker_ids": [],
        "query_text": "atlas",
        "sort": {"field": "RELEVANCE", "direction": "DESC"},
        "facet_prefix": "",
    }
    context = client.app.state.ctx
    with context.store.transaction() as tx:
        index = tx.require("index", root["root_id"])
        index["_unavailable"] = True
        tx.put("index", root["root_id"], index)
    unavailable = client.post("/api/v1/search", json=request)
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "SEARCH_UNAVAILABLE"
    assert unavailable.json()["error"]["retryable"] is True
    assert unavailable.json()["error"]["request_id"] == unavailable.headers["x-request-id"]
    assert unavailable.headers["cache-control"] == "no-store"

    with context.store.transaction() as tx:
        index = tx.require("index", root["root_id"])
        index.pop("_unavailable")
        tx.put("index", root["root_id"], index)
    recovered = client.post("/api/v1/search", json=request)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["mode"] == "RESULTS"
    assert recovered.json()["items"]


def test_successful_quarantine_return_keeps_one_audit_event_with_original_attempt_link(
    client, configured, monkeypatch
):
    """Q-041: return replay returns the saved operation instead of duplicating its audit evidence."""
    from test_acceptance_completion import _headers, _quarantine_one_item

    csrf, item, quarantine = _quarantine_one_item(client, configured, monkeypatch)
    actor = client.get("/api/v1/session").json()["actor"]
    body = {"expected_revision": quarantine["revision"], "comment": "Return with linked audit evidence"}
    headers = _headers(csrf, str(uuid4()))
    returned = client.post(
        f"/api/v1/quarantine/{quarantine['quarantine_id']}/return", headers=headers, json=body
    )
    assert returned.status_code == 200, returned.text
    replay = client.post(
        f"/api/v1/quarantine/{quarantine['quarantine_id']}/return", headers=headers, json=body
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == returned.json()

    events = client.post(
        "/api/v1/audit/query",
        json=_audit_request(company_id=item["company_id"], action="QUARANTINE_RETURNED"),
    )
    assert events.status_code == 200, events.text
    matching = [event for event in events.json()["items"] if event["item_id"] == item["item_id"]]
    assert len(matching) == 1
    event = matching[0]
    assert event["operation_id"] == returned.json()["return_operation_id"]
    assert event["source_attempt_id"] == quarantine["source_attempt_id"]
    assert event["source"] == quarantine["location"]
    assert event["target"] == quarantine["original_location"]
    assert event["actor"] == actor
    assert event["result"] == "SUCCESS"
    assert event["comment"] == body["comment"]
