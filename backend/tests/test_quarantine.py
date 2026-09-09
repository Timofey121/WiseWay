from test_api import login
from test_workflows import headers


def test_quarantine_return_is_real_and_idempotent(client, configured, monkeypatch):
    from wiseway.indexer import Indexer
    from wiseway.worker import Worker

    ctx = client.app.state.ctx
    with ctx.store.transaction() as tx:
        for q in tx.list("queue"):
            q["_observed_at"] = configured.clock() - 6
            tx.put("queue", q["item_id"], q)
    Indexer(ctx).scan()
    csrf = login(client)
    with ctx.store.transaction() as tx:
        item = next(q for q in tx.list("queue") if q["selectable"])
    selection = client.post(
        "/api/v1/sorting/selections",
        headers=headers(csrf),
        json={
            "company_id": item["company_id"],
            "mode": "EXPLICIT",
            "items": [{"item_id": item["item_id"], "item_revision": item["item_revision"]}],
        },
    )
    assert selection.status_code == 201, selection.text
    batch = client.post(
        "/api/v1/sorting/batches",
        headers=headers(csrf),
        json={"execution_mode": "DIRECT", "selection_id": selection.json()["selection_id"]},
    )
    assert batch.status_code == 202, batch.text
    real_move = ctx.fs.rename_no_replace

    def fail_primary(source, target, expected):
        if not target.startswith("Quarantine/"):
            raise OSError(5, "synthetic I/O failure")
        return real_move(source, target, expected)

    monkeypatch.setattr(ctx.fs, "rename_no_replace", fail_primary)
    Worker(ctx).run_once()
    monkeypatch.setattr(ctx.fs, "rename_no_replace", real_move)
    quarantined = client.get("/api/v1/quarantine", params={"company_id": item["company_id"]})
    assert quarantined.status_code == 200, quarantined.text
    q = quarantined.json()["items"][0]
    key = headers(csrf)
    body = {"expected_revision": q["revision"], "comment": "Retry after correcting synthetic storage fault"}
    returned = client.post("/api/v1/quarantine/" + q["quarantine_id"] + "/return", headers=key, json=body)
    assert returned.status_code == 200, returned.text
    assert returned.json()["item"]["status"] == "WAITING_READY"
    repeated = client.post("/api/v1/quarantine/" + q["quarantine_id"] + "/return", headers=key, json=body)
    assert repeated.json() == returned.json()
    with ctx.store.transaction() as tx:
        assert ctx.fs.stat(ctx.physical(tx, item["source"]))
        assert not ctx.fs.stat(ctx.physical(tx, q["location"]))
