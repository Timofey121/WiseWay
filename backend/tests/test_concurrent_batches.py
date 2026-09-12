from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import monotonic
from uuid import uuid4

from fastapi.testclient import TestClient

from wiseway.app import create_app
from wiseway.indexer import Indexer
from wiseway.worker import Worker


def _login(client: TestClient, login: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://localhost:8000"},
        json={"login": login, "password": "synthetic-test-password"},
    )
    assert response.status_code == 200, response.text
    return {
        "Origin": "http://localhost:8000",
        "X-CSRF-Token": response.json()["csrf_token"],
        "Idempotency-Key": str(uuid4()),
    }


def _ready_three_items(client: TestClient, configured) -> tuple[str, list[dict]]:
    for name in ("concurrent-shared.pdf", "concurrent-left.pdf", "concurrent-right.pdf"):
        (configured.sandbox_dir / "Incoming" / "Atlas" / name).write_bytes(name.encode())
    ctx = client.app.state.ctx
    Indexer(ctx).scan()  # discovery
    with ctx.store.transaction() as tx:
        for item in tx.list("queue"):
            item["_observed_at"] = configured.clock() - 6
            tx.put("queue", item["item_id"], item)
    Indexer(ctx).scan()  # second equal observation
    company = client.get("/api/v1/companies").json()["items"][0]["company_id"]
    queue = client.post(
        "/api/v1/sorting/queue/query",
        json={
            "company_id": company,
            "filters": {"statuses": ["READY"], "query_text": "concurrent-"},
            "cursor": None,
            "limit": 100,
        },
    )
    assert queue.status_code == 200, queue.text
    values = queue.json()["items"]
    assert len(values) == 3
    return company, values


def _selection(client: TestClient, headers: dict[str, str], company: str, values: list[dict]) -> str:
    response = client.post(
        "/api/v1/sorting/selections",
        headers=headers,
        json={
            "company_id": company,
            "mode": "EXPLICIT",
            "items": [
                {"item_id": value["item_id"], "item_revision": value["item_revision"]} for value in values
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["selection_id"]


def test_concurrent_overlapping_batches_claim_once_and_finish_without_claims(client, configured):
    _login(client, "worker-atlas")
    company, values = _ready_three_items(client, configured)
    by_name = {value["filename"]: value for value in values}
    with (
        TestClient(create_app(configured), base_url="http://localhost:8000") as left,
        TestClient(create_app(configured), base_url="http://localhost:8000") as right,
    ):
        left_headers = _login(left, "worker-atlas")
        right_headers = _login(right, "worker-nova")
        left_selection = _selection(
            left, left_headers, company, [by_name["concurrent-shared.pdf"], by_name["concurrent-left.pdf"]]
        )
        right_selection = _selection(
            right, right_headers, company, [by_name["concurrent-shared.pdf"], by_name["concurrent-right.pdf"]]
        )
        barrier = Barrier(2)

        def accept(http: TestClient, auth: dict[str, str], selection_id: str):
            barrier.wait(timeout=5)
            began = monotonic()
            response = http.post(
                "/api/v1/sorting/batches",
                headers=auth,
                json={"execution_mode": "DIRECT", "selection_id": selection_id},
            )
            return began, monotonic(), response

        with ThreadPoolExecutor(max_workers=2) as pool:
            left_future = pool.submit(accept, left, left_headers, left_selection)
            right_future = pool.submit(accept, right, right_headers, right_selection)
            left_started, left_finished, left_response = left_future.result(timeout=15)
            right_started, right_finished, right_response = right_future.result(timeout=15)
        assert left_response.status_code == right_response.status_code == 202
        # Both requests had crossed the same barrier before either received a response.
        assert max(left_started, right_started) <= min(left_finished, right_finished)
        batch_ids = [left_response.json()["batch_id"], right_response.json()["batch_id"]]

        Worker(left.app.state.ctx).run_once()
        batches = [left.get(f"/api/v1/sorting/batches/{batch_id}").json() for batch_id in batch_ids]
        assert all(batch["status"] == "COMPLETED_WITH_ISSUES" for batch in batches)
        outcomes = [outcome for batch in batches for outcome in batch["outcomes"]]
        shared = [
            outcome
            for outcome in outcomes
            if outcome["item_id"] == by_name["concurrent-shared.pdf"]["item_id"]
        ]
        assert sorted(outcome["state"] for outcome in shared) == ["MANUAL_REVIEW", "SKIPPED"]
        assert (
            next(outcome for outcome in shared if outcome["state"] == "SKIPPED")["reason_code"]
            == "ALREADY_PROCESSING"
        )
        moved = [outcome for outcome in outcomes if outcome["state"] == "MANUAL_REVIEW"]
        assert len(moved) == 3
        with left.app.state.ctx.store.transaction() as tx:
            assert tx.list("claim") == []
            accepted = [
                event
                for event in tx.events()
                if event["action"] == "BATCH_ACCEPTED" and event["batch_id"] in batch_ids
            ]
            assert len(accepted) == 2
