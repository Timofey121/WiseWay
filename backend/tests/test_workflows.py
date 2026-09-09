from uuid import uuid4

from test_api import login


def headers(csrf):
    return {"Origin": "http://localhost:8000", "X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4())}


def test_real_dictionary_selection_batch_and_index(client, configured):
    from wiseway.indexer import Indexer
    from wiseway.worker import Worker

    csrf = login(client)
    ctx = client.app.state.ctx
    # Deterministic readiness: use the same clock seam as an elapsed observation interval.
    with ctx.store.transaction() as tx:
        for item in tx.list("queue"):
            item["_observed_at"] = configured.clock() - 6
            tx.put("queue", item["item_id"], item)
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
    )
    assert queue.status_code == 200, queue.text
    assert queue.json()["eligible_count"] > 0
    item = queue.json()["items"][0]
    dictionary = client.post(
        f"/api/v1/companies/{company}/dictionaries",
        headers=headers(csrf),
        json={"name": "Invoices", "description": ""},
    )
    assert dictionary.status_code == 201, dictionary.text
    d = dictionary.json()
    targets = client.get(f"/api/v1/companies/{company}/target-directories").json()["items"]
    target = {k: targets[0][k] for k in ("root_id", "relative_directory")}
    saved = client.put(
        f"/api/v1/dictionaries/{d['dictionary_id']}/draft",
        headers=headers(csrf),
        json={
            "expected_draft_revision": d["draft"]["draft_revision"],
            "name": "Invoices",
            "description": "",
            "rules": [
                {
                    "rule_id": "rule-all",
                    "priority": 1,
                    "match_field": "BASENAME",
                    "mask": "*",
                    "target": target,
                    "target_stem": "Processed",
                }
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    revision = saved.json()["draft"]["draft_revision"]
    simulated = client.post(
        f"/api/v1/dictionaries/{d['dictionary_id']}/simulate",
        headers=headers(csrf),
        json={"expected_draft_revision": revision},
    )
    assert simulated.status_code == 201, simulated.text
    sim = simulated.json()
    published = client.post(
        f"/api/v1/dictionaries/{d['dictionary_id']}/publish",
        headers=headers(csrf),
        json={
            "expected_draft_revision": revision,
            "simulation_id": sim["simulation_id"],
            "acknowledge_no_scenario": False,
            "comment": "First version",
        },
    )
    assert published.status_code == 201, published.text
    selected = client.post(
        "/api/v1/sorting/selections",
        headers=headers(csrf),
        json={
            "company_id": company,
            "mode": "EXPLICIT",
            "items": [{"item_id": item["item_id"], "item_revision": item["item_revision"]}],
        },
    )
    assert selected.status_code == 201, selected.text
    key = headers(csrf)
    body = {"execution_mode": "DIRECT", "selection_id": selected.json()["selection_id"]}
    started = client.post("/api/v1/sorting/batches", headers=key, json=body)
    assert started.status_code == 202, started.text
    repeat = client.post("/api/v1/sorting/batches", headers=key, json=body)
    assert repeat.json() == started.json()
    Worker(ctx).run_once()
    batch = client.get("/api/v1/sorting/batches/" + started.json()["batch_id"])
    assert batch.status_code == 200, batch.text
    assert batch.json()["status"] == "COMPLETED"
    assert batch.json()["outcomes"][0]["state"] == "SORTED"
    with ctx.store.transaction() as tx:
        assert ctx.fs.stat(ctx.physical(tx, item["source"])) is None
        assert ctx.fs.stat(ctx.physical(tx, batch.json()["outcomes"][0]["actual_location"])) is not None
