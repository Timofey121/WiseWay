from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from wiseway.app import create_app
from wiseway.common import Settings
from wiseway.indexer import Indexer
from wiseway.seed import initialize


def _headers(csrf):
    return {"Origin": "http://localhost:8000", "X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4())}


@pytest.fixture
def bulk_client(tmp_path):
    now = [2_000_000_000.0]
    settings = Settings(data_dir=tmp_path / "state", sandbox_dir=tmp_path / "sandbox", clock=lambda: now[0])
    initialize(settings, password="synthetic-test-password")
    incoming = settings.sandbox_dir / "Incoming" / "Atlas"
    for path in incoming.iterdir():
        path.unlink()
    with TestClient(create_app(settings), base_url="http://localhost:8000") as client:
        yield client, settings, now


def _login(client):
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://localhost:8000"},
        json={"login": "worker-atlas", "password": "synthetic-test-password"},
    )
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def _add_files(settings, start, count):
    incoming = settings.sandbox_dir / "Incoming" / "Atlas"
    for number in range(start, start + count):
        (incoming / f"bulk-{number:04}.pdf").write_bytes(f"bulk {number}".encode())


def _scan_ready(client, now):
    Indexer(client.app.state.ctx).scan()
    now[0] += 6
    Indexer(client.app.state.ctx).scan()


def _queue(client, *, cursor=None, limit=100, query_text=""):
    return client.post(
        "/api/v1/sorting/queue/query",
        json={
            "company_id": "company-atlas",
            "filters": {"statuses": ["READY"], "query_text": query_text},
            "cursor": cursor,
            "limit": limit,
        },
    )


def _all_matching(client, csrf, expected):
    return client.post(
        "/api/v1/sorting/selections",
        headers=_headers(csrf),
        json={
            "company_id": "company-atlas",
            "mode": "ALL_MATCHING",
            "filters": {"statuses": ["READY"], "query_text": ""},
            "expected_eligible_count": expected,
        },
    )


def test_q024_q025_all_matching_uses_full_snapshot_and_never_partially_persists(bulk_client):
    client, settings, now = bulk_client
    csrf = _login(client)
    _add_files(settings, 0, 120)
    _scan_ready(client, now)

    first = _queue(client)
    assert first.status_code == 200, first.text
    second = _queue(client, cursor=first.json()["next_cursor"])
    assert second.status_code == 200, second.text
    initial_ids = {item["item_id"] for item in first.json()["items"] + second.json()["items"]}
    assert first.json()["eligible_count"] == len(initial_ids) == 120
    assert len(first.json()["items"]) == 100 and len(second.json()["items"]) == 20

    empty = client.post(
        "/api/v1/sorting/selections",
        headers=_headers(csrf),
        json={
            "company_id": "company-atlas",
            "mode": "ALL_MATCHING",
            "filters": {"statuses": ["READY"], "query_text": "absent-token"},
            "expected_eligible_count": 0,
        },
    )
    assert empty.status_code == 422 and empty.json()["error"]["code"] == "EMPTY_SELECTION"

    _add_files(settings, 120, 1)
    _scan_ready(client, now)
    changed = _all_matching(client, csrf, 120)
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "SELECTION_CHANGED"

    selected = _all_matching(client, csrf, 121)
    assert selected.status_code == 201, selected.text
    selection_id = selected.json()["selection_id"]
    with client.app.state.ctx.store.transaction(write=False) as tx:
        selected_ids = {item["item_id"] for item in tx.require("selection", selection_id)["_items"]}
    assert len(selected_ids) == 121 and initial_ids <= selected_ids

    _add_files(settings, 121, 1)
    _scan_ready(client, now)
    current = _queue(client)
    current_second = _queue(client, cursor=current.json()["next_cursor"])
    late_id = next(
        item["item_id"]
        for item in current.json()["items"] + current_second.json()["items"]
        if item["filename"] == "bulk-0121.pdf"
    )
    assert late_id not in selected_ids

    _add_files(settings, 122, 879)
    _scan_ready(client, now)
    over_limit = _all_matching(client, csrf, 1001)
    assert over_limit.status_code == 422 and over_limit.json()["error"]["code"] == "BATCH_LIMIT_EXCEEDED"
    with client.app.state.ctx.store.transaction(write=False) as tx:
        assert [s["selection_id"] for s in tx.list("selection")] == [selection_id]
        assert tx.list("batch") == [] and tx.list("attempt") == []
    assert len(list((settings.sandbox_dir / "Incoming" / "Atlas").iterdir())) == 1001


def test_q024_q025_full_batch_keeps_the_original_snapshot_across_pages(bulk_client):
    from wiseway.worker import Worker

    client, settings, now = bulk_client
    csrf = _login(client)
    _add_files(settings, 0, 120)
    _scan_ready(client, now)
    selected = _all_matching(client, csrf, 120)
    assert selected.status_code == 201, selected.text
    selection = selected.json()
    with client.app.state.ctx.store.transaction(write=False) as tx:
        selected_ids = {
            item["item_id"] for item in tx.require("selection", selection["selection_id"])["_items"]
        }

    assert selection["selected_count"] == len(selected_ids) == 120
    _add_files(settings, 120, 1)
    _scan_ready(client, now)
    # The UI can query a different filter without altering its existing selection.
    changed_filter = _queue(client, query_text="absent-token")
    assert changed_filter.status_code == 200 and changed_filter.json()["eligible_count"] == 0
    preview = client.post(
        "/api/v1/sorting/previews", headers=_headers(csrf), json={"selection_id": selection["selection_id"]}
    )
    assert preview.status_code == 201, preview.text
    preview_first = preview.json()
    preview_second = client.get(
        f"/api/v1/sorting/previews/{preview_first['preview_id']}",
        params={"cursor": preview_first["next_cursor"], "limit": 100},
    )
    assert preview_second.status_code == 200, preview_second.text
    preview_ids = [row["item_id"] for row in preview_first["rows"] + preview_second.json()["rows"]]
    assert set(preview_ids) == selected_ids and len(preview_ids) == 120

    batch = client.post(
        "/api/v1/sorting/batches",
        headers=_headers(csrf),
        json={
            "execution_mode": "PREVIEWED",
            "selection_id": selection["selection_id"],
            "preview_id": preview_first["preview_id"],
        },
    )
    assert batch.status_code == 202, batch.text
    batch_first = batch.json()
    batch_second = client.get(
        f"/api/v1/sorting/batches/{batch_first['batch_id']}",
        params={"cursor": batch_first["next_cursor"], "limit": 100},
    )
    assert batch_second.status_code == 200, batch_second.text
    batch_ids = [row["item_id"] for row in batch_first["outcomes"] + batch_second.json()["outcomes"]]
    assert batch_first["selected_count"] == len(batch_ids) == 120
    assert set(batch_ids) == selected_ids
    assert Worker(client.app.state.ctx).run_once() == 120
    finished = client.get(f"/api/v1/sorting/batches/{batch_first['batch_id']}").json()
    tail = client.get(
        f"/api/v1/sorting/batches/{batch_first['batch_id']}",
        params={"cursor": finished["next_cursor"], "limit": 100},
    ).json()
    outcomes = finished["outcomes"] + tail["outcomes"]
    assert finished["completed_count"] == finished["selected_count"] == 120
    assert len(outcomes) == 120 and {row["item_id"] for row in outcomes} == selected_ids
    assert all(row["state"] == "MANUAL_REVIEW" for row in outcomes)
    incoming = settings.sandbox_dir / "Incoming" / "Atlas"
    assert [path.name for path in incoming.iterdir()] == ["bulk-0120.pdf"]
    for number in range(120):
        target = settings.sandbox_dir / "ManualReview" / "Atlas" / f"bulk-{number:04}.pdf"
        assert target.read_bytes() == f"bulk {number}".encode()
