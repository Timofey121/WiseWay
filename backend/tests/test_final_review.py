from __future__ import annotations

from test_api import login
from test_workflows import headers


def _ready(client, configured):
    from wiseway.indexer import Indexer

    ctx = client.app.state.ctx
    with ctx.store.transaction() as tx:
        for value in tx.list("queue"):
            value["_observed_at"] = configured.clock() - 6
            tx.put("queue", value["item_id"], value)
    Indexer(ctx).scan()
    company = client.get("/api/v1/companies").json()["items"][0]["company_id"]
    queue = client.post(
        "/api/v1/sorting/queue/query",
        json={
            "company_id": company,
            "filters": {"statuses": ["READY"], "query_text": ""},
            "cursor": None,
            "limit": 100,
        },
    ).json()
    return company, queue["items"][0]


def test_previewed_batch_reports_stale_preview_when_source_changes(client, configured):
    csrf = login(client)
    company, item = _ready(client, configured)
    selection = client.post(
        "/api/v1/sorting/selections",
        headers=headers(csrf),
        json={
            "company_id": company,
            "mode": "EXPLICIT",
            "items": [{"item_id": item["item_id"], "item_revision": item["item_revision"]}],
        },
    ).json()
    preview = client.post(
        "/api/v1/sorting/previews", headers=headers(csrf), json={"selection_id": selection["selection_id"]}
    )
    assert preview.status_code == 201, preview.text
    (configured.sandbox_dir / "Incoming" / "Atlas" / item["filename"]).write_bytes(b"changed")
    response = client.post(
        "/api/v1/sorting/batches",
        headers=headers(csrf),
        json={
            "selection_id": selection["selection_id"],
            "execution_mode": "PREVIEWED",
            "preview_id": preview.json()["preview_id"],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STALE_PREVIEW"


def test_new_key_on_returned_quarantine_is_invalid_state_before_revision_check(client):
    csrf = login(client)
    ctx = client.app.state.ctx
    with ctx.store.transaction() as tx:
        tx.put(
            "quarantine",
            "quarantine-returned",
            {
                "quarantine_id": "quarantine-returned",
                "revision": 2,
                "item_id": "unused-item",
                "company_id": "company-atlas",
                "filename": "old.pdf",
                "location": {},
                "original_location": {},
                "reason_code": "TECHNICAL_ERROR",
                "quarantined_at": "2026-01-01T00:00:00Z",
                "source_attempt_id": "attempt-old",
                "recovery_operation_id": None,
                "can_return": False,
                "_returned": True,
            },
        )
    response = client.post(
        "/api/v1/quarantine/quarantine-returned/return",
        headers=headers(csrf),
        json={"expected_revision": 1, "comment": "already returned"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE"


def test_quarantine_postcondition_stat_failure_persists_recovery_required(client, configured, monkeypatch):
    from wiseway.worker import Worker

    csrf = login(client)
    company, item = _ready(client, configured)
    selection = client.post(
        "/api/v1/sorting/selections",
        headers=headers(csrf),
        json={
            "company_id": company,
            "mode": "EXPLICIT",
            "items": [{"item_id": item["item_id"], "item_revision": item["item_revision"]}],
        },
    ).json()
    batch = client.post(
        "/api/v1/sorting/batches",
        headers=headers(csrf),
        json={"execution_mode": "DIRECT", "selection_id": selection["selection_id"]},
    )
    assert batch.status_code == 202, batch.text
    real_move = client.app.state.ctx.fs.rename_no_replace

    def fail_primary(source, target, expected):
        if not target.startswith("Quarantine/"):
            raise OSError("move error")
        return real_move(source, target, expected)

    monkeypatch.setattr(client.app.state.ctx.fs, "rename_no_replace", fail_primary)
    Worker(client.app.state.ctx).run_once()
    monkeypatch.setattr(client.app.state.ctx.fs, "rename_no_replace", real_move)
    quarantine = client.get("/api/v1/quarantine", params={"company_id": company}).json()["items"][0]
    real_stat = client.app.state.ctx.fs.stat
    calls = {"count": 0}

    def unreadable_after_preflight(path):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_stat(path)
        raise OSError("unreadable")

    monkeypatch.setattr(client.app.state.ctx.fs, "stat", unreadable_after_preflight)
    response = client.post(
        f"/api/v1/quarantine/{quarantine['quarantine_id']}/return",
        headers=headers(csrf),
        json={"expected_revision": quarantine["revision"], "comment": "verify placement"},
    )
    monkeypatch.setattr(client.app.state.ctx.fs, "stat", real_stat)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RECOVERY_REQUIRED"
    assert response.json()["error"]["operation_id"]
