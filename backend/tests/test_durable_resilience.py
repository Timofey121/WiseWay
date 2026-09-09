"""Crash-boundary recovery of accepted, idempotent batch work."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from test_api import login


def _headers(csrf: str, key: str) -> dict[str, str]:
    return {
        "Origin": "http://localhost:8000",
        "X-CSRF-Token": csrf,
        "Idempotency-Key": key,
    }


def _accept_ready_batch(client, configured):
    from wiseway.indexer import Indexer

    ctx = client.app.state.ctx
    with ctx.store.transaction() as tx:
        for item in tx.list("queue"):
            item["_observed_at"] = configured.clock() - 6
            tx.put("queue", item["item_id"], item)
    Indexer(ctx).scan()
    csrf = login(client)
    company_id = client.get("/api/v1/companies").json()["items"][0]["company_id"]
    queue = client.post(
        "/api/v1/sorting/queue/query",
        json={
            "company_id": company_id,
            "filters": {"statuses": ["READY"], "query_text": ""},
            "cursor": None,
            "limit": 100,
        },
    )
    assert queue.status_code == 200, queue.text
    item = queue.json()["items"][0]
    selection = client.post(
        "/api/v1/sorting/selections",
        headers=_headers(csrf, str(uuid4())),
        json={
            "company_id": company_id,
            "mode": "EXPLICIT",
            "items": [{"item_id": item["item_id"], "item_revision": item["item_revision"]}],
        },
    )
    assert selection.status_code == 201, selection.text
    body = {"execution_mode": "DIRECT", "selection_id": selection.json()["selection_id"]}
    key = str(uuid4())
    batch = client.post("/api/v1/sorting/batches", headers=_headers(csrf, key), json=body)
    assert batch.status_code == 202, batch.text
    return ctx, company_id, csrf, key, body, batch.json()


@pytest.mark.parametrize(("boundary", "returncode"), [("before", 81), ("after", 82)])
def test_worker_process_crash_at_rename_boundary_recovers_once_and_replays_idempotency(
    client, configured, boundary, returncode
):
    """The durable intent is enough to distinguish retry from completed move after SIGKILL-like exit."""
    from wiseway.worker import Worker

    ctx, company_id, csrf, key, body, accepted = _accept_ready_batch(client, configured)
    child = """
import os
from wiseway.common import Settings
from wiseway.services import Context
from wiseway.worker import Worker

ctx = Context(Settings())
original = ctx.fs.rename_no_replace
def terminate(source, target, expected):
    if os.environ[\"WISEWAY_TEST_CRASH_BOUNDARY\"] == \"before\":
        os._exit(81)
    original(source, target, expected)
    os._exit(82)
ctx.fs.rename_no_replace = terminate
Worker(ctx).run_once()
"""
    env = {
        **os.environ,
        "WISEWAY_DATA_DIR": str(configured.data_dir),
        "WISEWAY_SANDBOX_DIR": str(configured.sandbox_dir),
        "WISEWAY_TEST_CRASH_BOUNDARY": boundary,
    }
    crashed = subprocess.run(
        [sys.executable, "-c", child],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert crashed.returncode == returncode, crashed.stderr

    # A fresh worker recovers the exact persisted intent.  It either retries the
    # untouched source or observes the already-renamed target; neither path emits
    # a second business outcome.
    assert Worker(ctx).run_once() == 1
    finished = client.get("/api/v1/sorting/batches/" + accepted["batch_id"])
    assert finished.status_code == 200, finished.text
    outcome = finished.json()["outcomes"][0]
    assert outcome["state"] == "MANUAL_REVIEW"

    replay = client.post("/api/v1/sorting/batches", headers=_headers(csrf, key), json=body)
    assert replay.status_code == 202, replay.text
    assert replay.json() == accepted
    audits = client.post(
        "/api/v1/audit/query",
        json={
            "company_id": company_id,
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
    assert audits.status_code == 200, audits.text
    actions = [
        event["action"] for event in audits.json()["items"] if event["batch_id"] == accepted["batch_id"]
    ]
    assert sorted(actions) == ["BATCH_ACCEPTED", "FILE_ATTEMPT_FINISHED", "FILE_ATTEMPT_STARTED"]
