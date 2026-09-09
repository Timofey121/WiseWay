"""Focused real-backend acceptance coverage for Q-039 and a Q-040 failure point."""

from __future__ import annotations

import hashlib

from test_api import login
from test_workflows import headers


def _checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ready(ctx, configured):
    from wiseway.indexer import Indexer

    Indexer(ctx).scan()
    with ctx.store.transaction() as tx:
        for item in tx.list("queue"):
            item["_observed_at"] = configured.clock() - 6
            tx.put("queue", item["item_id"], item)
    Indexer(ctx).scan()


def _queue(client, company, text):
    response = client.post(
        "/api/v1/sorting/queue/query",
        json={
            "company_id": company,
            "filters": {"statuses": ["READY"], "query_text": text},
            "cursor": None,
            "limit": 100,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _accept(client, csrf, company, items):
    selection = client.post(
        "/api/v1/sorting/selections",
        headers=headers(csrf),
        json={
            "company_id": company,
            "mode": "EXPLICIT",
            "items": [{"item_id": item["item_id"], "item_revision": item["item_revision"]} for item in items],
        },
    )
    assert selection.status_code == 201, selection.text
    batch = client.post(
        "/api/v1/sorting/batches",
        headers=headers(csrf),
        json={"execution_mode": "DIRECT", "selection_id": selection.json()["selection_id"]},
    )
    assert batch.status_code == 202, batch.text
    return batch.json()


def _publish_mixed_rules(client, csrf, company):
    target_response = client.get(f"/api/v1/companies/{company}/target-directories")
    assert target_response.status_code == 200, target_response.text
    target = {key: target_response.json()["items"][0][key] for key in ("root_id", "relative_directory")}
    created = client.post(
        f"/api/v1/companies/{company}/dictionaries",
        headers=headers(csrf),
        json={"name": "Mixed acceptance", "description": ""},
    )
    assert created.status_code == 201, created.text
    dictionary = created.json()
    rules = [
        {
            "rule_id": "sort",
            "priority": 1,
            "match_field": "BASENAME",
            "mask": "mixed-sort.pdf",
            "target": target,
            "target_stem": "MixedSorted",
        },
        {
            "rule_id": "occupied",
            "priority": 2,
            "match_field": "BASENAME",
            "mask": "mixed-occupied.pdf",
            "target": target,
            "target_stem": "MixedOccupied",
        },
        {
            "rule_id": "quarantine",
            "priority": 3,
            "match_field": "BASENAME",
            "mask": "mixed-quarantine.pdf",
            "target": target,
            "target_stem": "MixedQuarantine",
        },
    ]
    saved = client.put(
        f"/api/v1/dictionaries/{dictionary['dictionary_id']}/draft",
        headers=headers(csrf),
        json={
            "expected_draft_revision": dictionary["draft"]["draft_revision"],
            "name": "Mixed acceptance",
            "description": "",
            "rules": rules,
        },
    )
    assert saved.status_code == 200, saved.text
    revision = saved.json()["draft"]["draft_revision"]
    simulation = client.post(
        f"/api/v1/dictionaries/{dictionary['dictionary_id']}/simulate",
        headers=headers(csrf),
        json={"expected_draft_revision": revision},
    )
    assert simulation.status_code == 201, simulation.text
    published = client.post(
        f"/api/v1/dictionaries/{dictionary['dictionary_id']}/publish",
        headers=headers(csrf),
        json={
            "expected_draft_revision": revision,
            "simulation_id": simulation.json()["simulation_id"],
            "acknowledge_no_scenario": True,
            "comment": "Q-039 mixed outcomes",
        },
    )
    assert published.status_code == 201, published.text


def _events(tx, batch_id):
    return [event for event in tx.events() if event.get("batch_id") == batch_id]


def test_q039_real_mixed_batch_preserves_content_outcomes_and_audit(client, configured, monkeypatch):
    from wiseway.worker import Worker

    ctx = client.app.state.ctx
    incoming = configured.sandbox_dir / "Incoming" / "Atlas"
    archive = configured.sandbox_dir / "Archive" / "Atlas" / "Orion_2031" / "Reports"
    payloads = {
        "mixed-sort.pdf": b"sort payload",
        "mixed-manual.pdf": b"manual payload",
        "mixed-occupied.pdf": b"occupied source",
        "mixed-quarantine.pdf": b"quarantine payload",
    }
    for name, payload in payloads.items():
        (incoming / name).write_bytes(payload)
    source_checksums = {name: _checksum(incoming / name) for name in payloads}
    occupied = archive / "MixedOccupied.pdf"
    occupied.write_bytes(b"preexisting destination")
    occupied_checksum = _checksum(occupied)

    _ready(ctx, configured)
    csrf = login(client)
    company = client.get("/api/v1/companies").json()["items"][0]["company_id"]
    _publish_mixed_rules(client, csrf, company)
    batch = _accept(client, csrf, company, _queue(client, company, "mixed-"))
    real_move = ctx.fs.rename_no_replace
    move_count = {"count": 0}

    def move_with_quarantine_fault(source, target, fingerprint):
        move_count["count"] += 1
        if target.endswith("MixedQuarantine.pdf"):
            raise OSError("Q-039 primary move fault")
        return real_move(source, target, fingerprint)

    monkeypatch.setattr(ctx.fs, "rename_no_replace", move_with_quarantine_fault)
    assert Worker(ctx).run_once() == 4
    result = client.get(f"/api/v1/sorting/batches/{batch['batch_id']}").json()
    outcomes = {
        outcome["source"]["relative_path"].rsplit("/", 1)[-1]: outcome for outcome in result["outcomes"]
    }
    assert {name: outcome["state"] for name, outcome in outcomes.items()} == {
        "mixed-sort.pdf": "SORTED",
        "mixed-manual.pdf": "MANUAL_REVIEW",
        "mixed-occupied.pdf": "REQUIRES_DECISION",
        "mixed-quarantine.pdf": "QUARANTINED",
    }
    assert {name: outcome["reason_code"] for name, outcome in outcomes.items()} == {
        "mixed-sort.pdf": None,
        "mixed-manual.pdf": "NO_SCENARIO",
        "mixed-occupied.pdf": "TARGET_OCCUPIED",
        "mixed-quarantine.pdf": "TECHNICAL_ERROR",
    }
    assert result["status"] == "COMPLETED_WITH_ISSUES"
    assert result["completed_count"] == result["selected_count"] == 4
    assert result["counts"] == {
        "sorted": 1,
        "manual_review": 1,
        "requires_decision": 1,
        "quarantined": 1,
        "skipped": 0,
        "recovery_required": 0,
    }
    assert result["finished_at"] is not None
    assert (
        _checksum(configured.sandbox_dir / outcomes["mixed-sort.pdf"]["actual_location"]["relative_path"])
        == source_checksums["mixed-sort.pdf"]
    )
    assert (
        _checksum(
            configured.sandbox_dir
            / "ManualReview"
            / outcomes["mixed-manual.pdf"]["actual_location"]["relative_path"]
        )
        == source_checksums["mixed-manual.pdf"]
    )
    assert (
        _checksum(
            configured.sandbox_dir
            / "Quarantine"
            / outcomes["mixed-quarantine.pdf"]["actual_location"]["relative_path"]
        )
        == source_checksums["mixed-quarantine.pdf"]
    )
    assert _checksum(occupied) == occupied_checksum
    assert (incoming / "mixed-occupied.pdf").exists()
    assert _checksum(incoming / "mixed-occupied.pdf") == source_checksums["mixed-occupied.pdf"]
    for name in ("mixed-sort.pdf", "mixed-manual.pdf", "mixed-quarantine.pdf"):
        assert not (incoming / name).exists()
    with ctx.store.transaction(write=False) as tx:
        attempts = [attempt for attempt in tx.list("attempt") if attempt["batch_id"] == batch["batch_id"]]
        events = _events(tx, batch["batch_id"])
    assert len(attempts) == 4
    assert [event["action"] for event in events].count("BATCH_ACCEPTED") == 1
    for attempt in attempts:
        attempt_events = [event for event in events if event.get("attempt_id") == attempt["attempt_id"]]
        assert [event["action"] for event in attempt_events] == [
            "FILE_ATTEMPT_FINISHED",
            "FILE_ATTEMPT_STARTED",
        ]
        assert all(event["actor"] == attempt["actor"] for event in attempt_events)
        assert all(event["request_id"] == attempt["request_id"] for event in attempt_events)
    event_count, moves_before_repeat = len(events), move_count["count"]
    assert Worker(ctx).run_once() == 0
    with ctx.store.transaction(write=False) as tx:
        assert len(_events(tx, batch["batch_id"])) == event_count
    assert move_count["count"] == moves_before_repeat


def test_q040_finish_transaction_rollback_recovers_without_second_move(client, configured, monkeypatch):
    """One injected finish-transaction failure; this is partial Q-040 coverage, not all crash points."""
    from wiseway.storage import UnitOfWork
    from wiseway.worker import Worker

    ctx = client.app.state.ctx
    incoming = configured.sandbox_dir / "Incoming" / "Atlas"
    (incoming / "finish-rollback.pdf").write_bytes(b"finish rollback payload")
    source_checksum = _checksum(incoming / "finish-rollback.pdf")
    _ready(ctx, configured)
    csrf = login(client)
    company = client.get("/api/v1/companies").json()["items"][0]["company_id"]
    batch = _accept(client, csrf, company, _queue(client, company, "finish-rollback"))
    real_move, real_append = ctx.fs.rename_no_replace, UnitOfWork.append_event
    move_count, failed = {"count": 0}, {"once": False}

    def count_move(*args):
        move_count["count"] += 1
        return real_move(*args)

    def fail_finished_event(self, event):
        if event["action"] == "FILE_ATTEMPT_FINISHED" and not failed["once"]:
            failed["once"] = True
            raise OSError("Q-040 injected audit write failure")
        return real_append(self, event)

    monkeypatch.setattr(ctx.fs, "rename_no_replace", count_move)
    monkeypatch.setattr(UnitOfWork, "append_event", fail_finished_event)
    assert Worker(ctx).run_once() == 1
    with ctx.store.transaction(write=False) as tx:
        attempt = next(attempt for attempt in tx.list("attempt") if attempt["batch_id"] == batch["batch_id"])
        assert attempt["phase"] == "RECOVERY_REQUIRED"
        events = _events(tx, batch["batch_id"])
        assert [event["action"] for event in events].count("FILE_ATTEMPT_FINISHED") == 0
        assert [event["action"] for event in events].count("RECOVERY_REQUIRED") == 1
    assert failed["once"] and move_count["count"] == 1
    assert Worker(ctx).recover(attempt["attempt_id"])
    result = client.get(f"/api/v1/sorting/batches/{batch['batch_id']}").json()
    outcome = result["outcomes"][0]
    assert outcome["state"] == "MANUAL_REVIEW"
    assert result["completed_count"] == result["selected_count"] == 1
    assert result["counts"] == {
        "sorted": 0,
        "manual_review": 1,
        "requires_decision": 0,
        "quarantined": 0,
        "skipped": 0,
        "recovery_required": 0,
    }
    assert result["finished_at"] is not None
    assert not (incoming / "finish-rollback.pdf").exists()
    assert (
        _checksum(configured.sandbox_dir / "ManualReview" / outcome["actual_location"]["relative_path"])
        == source_checksum
    )
    assert move_count["count"] == 1
    with ctx.store.transaction(write=False) as tx:
        events = _events(tx, batch["batch_id"])
        actions = [event["action"] for event in events]
        assert actions.count("FILE_ATTEMPT_STARTED") == 1
        assert actions.count("RECOVERY_REQUIRED") == 1
        assert actions.count("FILE_ATTEMPT_FINISHED") == 1
        assert all(event["actor"] == result["actor"] for event in events if event["actor"] is not None)
    count_before_repeat = len(events)
    assert Worker(ctx).run_once() == 0
    assert Worker(ctx).recover(attempt["attempt_id"])
    assert move_count["count"] == 1
    with ctx.store.transaction(write=False) as tx:
        assert len(_events(tx, batch["batch_id"])) == count_before_repeat
