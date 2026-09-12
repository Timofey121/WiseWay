"""Additional API plus real-sandbox evidence for file acceptance boundaries."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from test_acceptance_completion import (
    _headers,
    _login,
    _quarantine_one_item,
    _save_simulate_publish_rules,
)

from wiseway.indexer import Indexer
from wiseway.worker import Worker


def _ready_named_items(client, configured, names: list[str]) -> tuple[str, list[dict]]:
    """Discover files twice so the public queue has real READY entries."""
    context = client.app.state.ctx
    Indexer(context).scan()
    with context.store.transaction() as tx:
        for item in tx.list("queue"):
            if item["filename"] in names:
                item["_observed_at"] = configured.clock() - configured.readiness_seconds - 1
                tx.put("queue", item["item_id"], item)
    Indexer(context).scan()
    company = client.get("/api/v1/companies").json()["items"][0]["company_id"]
    response = client.post(
        "/api/v1/sorting/queue/query",
        json={
            "company_id": company,
            "filters": {"statuses": ["READY"], "query_text": "file-acceptance-"},
            "cursor": None,
            "limit": 100,
        },
    )
    assert response.status_code == 200, response.text
    assert {item["filename"] for item in response.json()["items"]} == set(names)
    return company, response.json()["items"]


def test_q031_duplicate_plans_block_every_collision_and_process_an_independent_file(client, configured):
    """No source-ID order can nominate a winner for one planned destination."""
    csrf = _login(client)
    incoming = configured.sandbox_dir / "Incoming" / "Atlas"
    payloads = {
        "file-acceptance-collision-a.pdf": b"collision a",
        "file-acceptance-collision-b.pdf": b"collision b",
        "file-acceptance-safe.pdf": b"safe",
    }
    for filename, content in payloads.items():
        (incoming / filename).write_bytes(content)

    company, items = _ready_named_items(client, configured, list(payloads))
    target = client.get(f"/api/v1/companies/{company}/target-directories", params={"limit": 100})
    assert target.status_code == 200, target.text
    location = {key: target.json()["items"][0][key] for key in ("root_id", "relative_directory")}
    dictionary = client.post(
        f"/api/v1/companies/{company}/dictionaries",
        headers=_headers(csrf),
        json={"name": "File collision acceptance", "description": ""},
    )
    assert dictionary.status_code == 201, dictionary.text
    _save_simulate_publish_rules(
        client,
        csrf,
        dictionary.json(),
        [
            {
                "rule_id": "collision",
                "priority": 1,
                "match_field": "BASENAME",
                "mask": "file-acceptance-collision-*.pdf",
                "target": location,
                "target_stem": "OneDestination",
            },
            {
                "rule_id": "safe",
                "priority": 1,
                "match_field": "BASENAME",
                "mask": "file-acceptance-safe.pdf",
                "target": location,
                "target_stem": "IndependentDestination",
            },
        ],
        comment="Q-031 duplicate target",
    )
    selection = client.post(
        "/api/v1/sorting/selections",
        headers=_headers(csrf),
        json={
            "company_id": company,
            "mode": "EXPLICIT",
            "items": [
                {"item_id": item["item_id"], "item_revision": item["item_revision"]}
                for item in reversed(items)
            ],
        },
    )
    assert selection.status_code == 201, selection.text
    preview = client.post(
        "/api/v1/sorting/previews",
        headers=_headers(csrf),
        json={"selection_id": selection.json()["selection_id"]},
    )
    assert preview.status_code == 201, preview.text
    preview_rows = {row["source"]["relative_path"].rsplit("/", 1)[-1]: row for row in preview.json()["rows"]}
    for filename in ("file-acceptance-collision-a.pdf", "file-acceptance-collision-b.pdf"):
        assert preview_rows[filename]["collision"]["kind"] == "DUPLICATE_PLAN_TARGET"
    batch = client.post(
        "/api/v1/sorting/batches",
        headers=_headers(csrf),
        json={"execution_mode": "DIRECT", "selection_id": selection.json()["selection_id"]},
    )
    assert batch.status_code == 202, batch.text

    assert Worker(client.app.state.ctx).run_once() == 3
    completed = client.get(f"/api/v1/sorting/batches/{batch.json()['batch_id']}")
    assert completed.status_code == 200, completed.text
    outcomes = {
        outcome["source"]["relative_path"].rsplit("/", 1)[-1]: outcome
        for outcome in completed.json()["outcomes"]
    }
    for filename in ("file-acceptance-collision-a.pdf", "file-acceptance-collision-b.pdf"):
        outcome = outcomes[filename]
        assert (outcome["state"], outcome["reason_code"]) == ("REQUIRES_DECISION", "TARGET_OCCUPIED")
        assert (incoming / filename).read_bytes() == payloads[filename]
    safe = outcomes["file-acceptance-safe.pdf"]
    assert safe["state"] == "SORTED"
    assert not (incoming / "file-acceptance-safe.pdf").exists()
    assert (configured.sandbox_dir / safe["actual_location"]["relative_path"]).read_bytes() == payloads[
        "file-acceptance-safe.pdf"
    ]
    Indexer(client.app.state.ctx).scan()
    archive_root = next(
        root for root in client.get("/api/v1/roots").json()["items"] if root["root_id"] == "archive-root"
    )
    searched = client.post(
        "/api/v1/search",
        json={
            "request_state_id": "q033-indexed-move",
            "root_id": archive_root["root_id"],
            "schema_set_version": archive_root["schema_set_version"],
            "selected_marker_ids": [],
            "query_text": '"IndependentDestination"',
            "sort": {"field": "PATH", "direction": "ASC"},
            "facet_prefix": "",
        },
    )
    assert searched.status_code == 200, searched.text
    assert [item["location"] for item in searched.json()["items"]] == [safe["actual_location"]]
    audits = client.post(
        "/api/v1/audit/query",
        json={
            "company_id": company,
            "from": "2020-01-01T00:00:00Z",
            "to": "2099-01-01T00:00:00Z",
            "actor_id": None,
            "action": "FILE_ATTEMPT_FINISHED",
            "result": None,
            "query_text": "",
            "cursor": None,
            "limit": 100,
        },
    )
    assert audits.status_code == 200, audits.text
    event = next(value for value in audits.json()["items"] if value["item_id"] == safe["item_id"])
    assert event["source"] == safe["source"] and event["target"] == safe["actual_location"]


def test_q026_preview_rejects_an_externally_occupied_calculated_destination(client, configured):
    """Destination availability is a server-side preview dependency, not a browser check."""
    csrf = _login(client)
    filename = "file-acceptance-preview-target.pdf"
    (configured.sandbox_dir / "Incoming" / "Atlas" / filename).write_bytes(b"preview source")
    company, items = _ready_named_items(client, configured, [filename])
    target_response = client.get(f"/api/v1/companies/{company}/target-directories", params={"limit": 100})
    assert target_response.status_code == 200, target_response.text
    target = {key: target_response.json()["items"][0][key] for key in ("root_id", "relative_directory")}
    dictionary = client.post(
        f"/api/v1/companies/{company}/dictionaries",
        headers=_headers(csrf),
        json={"name": "Preview destination dependency", "description": ""},
    )
    assert dictionary.status_code == 201, dictionary.text
    _save_simulate_publish_rules(
        client,
        csrf,
        dictionary.json(),
        [
            {
                "rule_id": "preview-destination",
                "priority": 1,
                "match_field": "BASENAME",
                "mask": filename,
                "target": target,
                "target_stem": "PreviewDestination",
            }
        ],
        comment="preview destination dependency",
    )
    selection = client.post(
        "/api/v1/sorting/selections",
        headers=_headers(csrf),
        json={
            "company_id": company,
            "mode": "EXPLICIT",
            "items": [{"item_id": items[0]["item_id"], "item_revision": items[0]["item_revision"]}],
        },
    )
    assert selection.status_code == 201, selection.text
    preview = client.post(
        "/api/v1/sorting/previews",
        headers=_headers(csrf),
        json={"selection_id": selection.json()["selection_id"]},
    )
    assert preview.status_code == 201, preview.text
    occupied = (
        configured.sandbox_dir / "Archive" / "Atlas" / "Orion_2031" / "Reports" / "PreviewDestination.pdf"
    )
    occupied.write_bytes(b"external destination occupant")
    accepted = client.post(
        "/api/v1/sorting/batches",
        headers=_headers(csrf),
        json={
            "execution_mode": "PREVIEWED",
            "selection_id": selection.json()["selection_id"],
            "preview_id": preview.json()["preview_id"],
        },
    )
    assert accepted.status_code == 409
    assert accepted.json()["error"]["code"] == "STALE_PREVIEW"
    assert (configured.sandbox_dir / "Incoming" / "Atlas" / filename).read_bytes() == b"preview source"


def test_q038_return_rejects_stale_or_occupied_original_without_touching_quarantine(
    client, configured, monkeypatch
):
    """Failed return preconditions leave the durable quarantine item intact."""
    csrf, item, quarantine = _quarantine_one_item(client, configured, monkeypatch)
    context = client.app.state.ctx
    with context.store.transaction(write=False) as tx:
        quarantine_path = context.physical(tx, quarantine["location"])
        original_path = context.physical(tx, quarantine["original_location"])
    original_bytes = (configured.sandbox_dir / quarantine_path).read_bytes()

    stale = client.post(
        f"/api/v1/quarantine/{quarantine['quarantine_id']}/return",
        headers=_headers(csrf),
        json={"expected_revision": quarantine["revision"] + 1, "comment": "stale revision"},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "QUARANTINE_VERSION_CONFLICT"

    occupied_path = configured.sandbox_dir / original_path
    occupied_path.parent.mkdir(parents=True, exist_ok=True)
    occupied_path.write_bytes(b"new incoming entry")
    occupied = client.post(
        f"/api/v1/quarantine/{quarantine['quarantine_id']}/return",
        headers=_headers(csrf),
        json={"expected_revision": quarantine["revision"], "comment": "do not overwrite incoming"},
    )
    assert occupied.status_code == 409
    assert occupied.json()["error"]["code"] == "ORIGINAL_PATH_OCCUPIED"
    assert occupied_path.read_bytes() == b"new incoming entry"
    assert (configured.sandbox_dir / quarantine_path).read_bytes() == original_bytes
    listed = client.get("/api/v1/quarantine", params={"company_id": item["company_id"], "limit": 100})
    assert listed.status_code == 200, listed.text
    restored_card = next(
        card for card in listed.json()["items"] if card["quarantine_id"] == quarantine["quarantine_id"]
    )
    assert restored_card["revision"] == quarantine["revision"]
    assert restored_card["can_return"] is False


def test_q037_known_source_is_recorded_when_quarantine_destination_is_unavailable(
    client, configured, monkeypatch
):
    """A pre-move quarantine conflict is not an ambiguous file placement."""
    csrf = _login(client)
    incoming = configured.sandbox_dir / "Incoming" / "Atlas"
    filename = "file-acceptance-quarantine-unavailable.pdf"
    (incoming / filename).write_bytes(b"known source payload")
    company, items = _ready_named_items(client, configured, [filename])
    item = items[0]
    selection = client.post(
        "/api/v1/sorting/selections",
        headers=_headers(csrf),
        json={
            "company_id": company,
            "mode": "EXPLICIT",
            "items": [{"item_id": item["item_id"], "item_revision": item["item_revision"]}],
        },
    )
    assert selection.status_code == 201, selection.text
    batch = client.post(
        "/api/v1/sorting/batches",
        headers=_headers(csrf),
        json={"execution_mode": "DIRECT", "selection_id": selection.json()["selection_id"]},
    )
    assert batch.status_code == 202, batch.text
    context = client.app.state.ctx
    with context.store.transaction(write=False) as tx:
        attempt = next(value for value in tx.list("attempt") if value["batch_id"] == batch.json()["batch_id"])
    quarantine = configured.sandbox_dir / "Quarantine" / "Atlas" / f"{attempt['attempt_id']}_{filename}"
    quarantine.write_bytes(b"existing quarantine entry")
    real_move = context.fs.rename_no_replace

    def fail_only_the_primary_move(source, target, fingerprint):
        if target.startswith("ManualReview/"):
            raise OSError("synthetic primary fault")
        return real_move(source, target, fingerprint)

    monkeypatch.setattr(context.fs, "rename_no_replace", fail_only_the_primary_move)
    assert Worker(context).run_once() == 1
    result = client.get(f"/api/v1/sorting/batches/{batch.json()['batch_id']}")
    assert result.status_code == 200, result.text
    outcome = result.json()["outcomes"][0]
    assert (outcome["state"], outcome["reason_code"]) == ("RECOVERY_REQUIRED", "RECOVERY_REQUIRED")
    assert outcome["actual_location"] == item["source"]
    assert (incoming / filename).read_bytes() == b"known source payload"
    assert quarantine.read_bytes() == b"existing quarantine entry"


def test_q035_real_manual_review_name_collision_leaves_both_files_intact(client, configured):
    """A manual-review destination never receives a suffix or replaces its occupant."""
    csrf = _login(client)
    filename = "file-acceptance-manual-collision.pdf"
    incoming = configured.sandbox_dir / "Incoming" / "Atlas"
    manual = configured.sandbox_dir / "ManualReview" / "Atlas" / filename
    source = incoming / filename
    source.write_bytes(b"incoming manual collision")
    manual.write_bytes(b"existing manual decision")
    company, items = _ready_named_items(client, configured, [filename])
    selection = client.post(
        "/api/v1/sorting/selections",
        headers=_headers(csrf),
        json={
            "company_id": company,
            "mode": "EXPLICIT",
            "items": [{"item_id": items[0]["item_id"], "item_revision": items[0]["item_revision"]}],
        },
    )
    assert selection.status_code == 201, selection.text
    batch = client.post(
        "/api/v1/sorting/batches",
        headers=_headers(csrf),
        json={"execution_mode": "DIRECT", "selection_id": selection.json()["selection_id"]},
    )
    assert batch.status_code == 202, batch.text
    assert Worker(client.app.state.ctx).run_once() == 1
    outcome = client.get(f"/api/v1/sorting/batches/{batch.json()['batch_id']}").json()["outcomes"][0]
    assert (outcome["state"], outcome["reason_code"]) == (
        "REQUIRES_DECISION",
        "MANUAL_REVIEW_NAME_OCCUPIED",
    )
    assert source.read_bytes() == b"incoming manual collision"
    assert manual.read_bytes() == b"existing manual decision"


def test_q034_later_file_with_published_rule_conflict_moves_to_manual_review(client, configured):
    """A conflict can arise from a later incoming file after each dictionary passed publication."""
    csrf = _login(client)
    company = client.get("/api/v1/companies").json()["items"][0]["company_id"]
    targets = client.get(f"/api/v1/companies/{company}/target-directories", params={"limit": 100})
    assert targets.status_code == 200, targets.text
    location = {key: targets.json()["items"][0][key] for key in ("root_id", "relative_directory")}
    filename = "file-acceptance-rule-conflict.pdf"
    for number, stem in ((1, "ConflictOne"), (2, "ConflictTwo")):
        dictionary = client.post(
            f"/api/v1/companies/{company}/dictionaries",
            headers=_headers(csrf),
            json={"name": f"Later conflict dictionary {number}", "description": ""},
        )
        assert dictionary.status_code == 201, dictionary.text
        _save_simulate_publish_rules(
            client,
            csrf,
            dictionary.json(),
            [
                {
                    "rule_id": f"conflict-{number}",
                    "priority": 1,
                    "match_field": "BASENAME",
                    "mask": filename,
                    "target": location,
                    "target_stem": stem,
                }
            ],
            comment=f"publish future conflicting rule {number}",
        )
    source = configured.sandbox_dir / "Incoming" / "Atlas" / filename
    payload = b"later conflict source"
    source.write_bytes(payload)
    _, items = _ready_named_items(client, configured, [filename])
    selection = client.post(
        "/api/v1/sorting/selections",
        headers=_headers(csrf),
        json={
            "company_id": company,
            "mode": "EXPLICIT",
            "items": [{"item_id": items[0]["item_id"], "item_revision": items[0]["item_revision"]}],
        },
    )
    assert selection.status_code == 201, selection.text
    batch = client.post(
        "/api/v1/sorting/batches",
        headers=_headers(csrf),
        json={"execution_mode": "DIRECT", "selection_id": selection.json()["selection_id"]},
    )
    assert batch.status_code == 202, batch.text
    assert Worker(client.app.state.ctx).run_once() == 1
    outcome = client.get(f"/api/v1/sorting/batches/{batch.json()['batch_id']}").json()["outcomes"][0]
    assert (outcome["state"], outcome["reason_code"]) == ("MANUAL_REVIEW", "RULE_CONFLICT")
    assert not source.exists()
    assert (
        configured.sandbox_dir / "ManualReview" / outcome["actual_location"]["relative_path"]
    ).read_bytes() == payload


@pytest.mark.parametrize(
    ("placement", "expected_done", "expected_location"),
    [
        ("source_only", True, "target"),
        ("target_only", True, "target"),
        ("both", False, "source"),
        ("neither", False, None),
        ("target_changed", False, "source"),
        ("source_changed", False, None),
    ],
)
def test_q037_recovery_distinguishes_all_observable_intent_placements(
    client, configured, placement, expected_done, expected_location
):
    """Recovery only completes an intent when exactly one expected placement proves it."""
    csrf = _login(client)
    filename = f"file-acceptance-recovery-{placement}.pdf"
    source = configured.sandbox_dir / "Incoming" / "Atlas" / filename
    source.write_bytes(b"original identity")
    company, items = _ready_named_items(client, configured, [filename])
    selection = client.post(
        "/api/v1/sorting/selections",
        headers=_headers(csrf),
        json={
            "company_id": company,
            "mode": "EXPLICIT",
            "items": [{"item_id": items[0]["item_id"], "item_revision": items[0]["item_revision"]}],
        },
    )
    assert selection.status_code == 201, selection.text
    batch = client.post(
        "/api/v1/sorting/batches",
        headers=_headers(csrf),
        json={"execution_mode": "DIRECT", "selection_id": selection.json()["selection_id"]},
    )
    assert batch.status_code == 202, batch.text
    context = client.app.state.ctx
    with context.store.transaction() as tx:
        attempt = next(value for value in tx.list("attempt") if value["batch_id"] == batch.json()["batch_id"])
        target = context.location(tx, "manual-root", f"Atlas/{filename}")
        saved = tx.require("attempt", attempt["attempt_id"])
        saved.update(
            phase="INTENT",
            intent_target=target,
            intended_state="MANUAL_REVIEW",
            intended_reason="NO_SCENARIO",
        )
        saved["outcome"].update(state="PROCESSING", started_at="2026-01-01T00:00:00Z")
        tx.put("attempt", saved["attempt_id"], saved)
        target_path = configured.sandbox_dir / context.physical(tx, target)
        fingerprint = saved["item"]["_fingerprint"]

    if placement == "target_only":
        context.fs.rename_no_replace(
            f"Incoming/Atlas/{filename}", f"ManualReview/Atlas/{filename}", fingerprint
        )
    elif placement == "both":
        os.link(source, target_path)
    elif placement == "neither":
        source.unlink()
    elif placement == "target_changed":
        target_path.write_bytes(b"different target identity")
    elif placement == "source_changed":
        source.write_bytes(b"different source identity")

    assert Worker(context).recover(attempt["attempt_id"]) is expected_done
    outcome = client.get(f"/api/v1/sorting/batches/{batch.json()['batch_id']}").json()["outcomes"][0]
    if expected_done:
        assert (outcome["state"], outcome["reason_code"], outcome["actual_location"]) == (
            "MANUAL_REVIEW",
            "NO_SCENARIO",
            target,
        )
        assert not source.exists()
        assert target_path.read_bytes() == b"original identity"
    else:
        assert (outcome["state"], outcome["reason_code"]) == ("RECOVERY_REQUIRED", "RECOVERY_REQUIRED")
        expected = items[0]["source"] if expected_location == "source" else None
        assert outcome["actual_location"] == expected
        if placement == "both":
            assert source.read_bytes() == target_path.read_bytes() == b"original identity"
        elif placement == "neither":
            assert not source.exists() and not target_path.exists()
        elif placement == "target_changed":
            assert source.read_bytes() == b"original identity"
            assert target_path.read_bytes() == b"different target identity"
        else:
            assert source.read_bytes() == b"different source identity"
            assert not target_path.exists()
    with context.store.transaction(write=False) as tx:
        first_actions = [
            event["action"] for event in tx.events() if event.get("attempt_id") == attempt["attempt_id"]
        ]
    assert first_actions == (["FILE_ATTEMPT_FINISHED"] if expected_done else ["RECOVERY_REQUIRED"])
    assert Worker(context).recover(attempt["attempt_id"]) is expected_done
    with context.store.transaction(write=False) as tx:
        repeated_actions = [
            event["action"] for event in tx.events() if event.get("attempt_id") == attempt["attempt_id"]
        ]
    assert repeated_actions == first_actions


@pytest.mark.parametrize("mutation", ["missing", "changed"])
def test_q038_return_refuses_missing_or_changed_quarantine_source(client, configured, monkeypatch, mutation):
    """Return preflight never moves an absent or substituted quarantine entry."""
    csrf, item, quarantine = _quarantine_one_item(client, configured, monkeypatch)
    context = client.app.state.ctx
    with context.store.transaction(write=False) as tx:
        path = configured.sandbox_dir / context.physical(tx, quarantine["location"])
        event_count = len(tx.events())
    if mutation == "missing":
        path.unlink()
    else:
        path.write_bytes(b"substituted quarantine entry")
    response = client.post(
        f"/api/v1/quarantine/{quarantine['quarantine_id']}/return",
        headers=_headers(csrf),
        json={"expected_revision": quarantine["revision"], "comment": f"{mutation} quarantine entry"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE"
    with context.store.transaction(write=False) as tx:
        stored = tx.require("quarantine", quarantine["quarantine_id"])
        assert stored["can_return"] is True
        assert stored["recovery_operation_id"] is None
        assert tx.list("return") == []
        assert len(tx.events()) == event_count
    if mutation == "changed":
        assert path.read_bytes() == b"substituted quarantine entry"
    assert (
        client.get("/api/v1/quarantine", params={"company_id": item["company_id"], "limit": 100}).status_code
        == 200
    )


@pytest.mark.parametrize("comment", ["x", "x" * 500])
def test_q038_return_accepts_comment_boundaries(client, configured, monkeypatch, comment):
    """Both inclusive contract comment lengths complete one real return."""
    csrf, item, quarantine = _quarantine_one_item(client, configured, monkeypatch)
    response = client.post(
        f"/api/v1/quarantine/{quarantine['quarantine_id']}/return",
        headers=_headers(csrf),
        json={"expected_revision": quarantine["revision"], "comment": comment},
    )
    assert response.status_code == 200, response.text
    assert response.json()["item"]["status"] == "WAITING_READY"
    assert response.json()["return_operation_id"]
    with client.app.state.ctx.store.transaction(write=False) as tx:
        assert tx.require("quarantine", quarantine["quarantine_id"])["_returned"] is True
        assert tx.require("queue", item["item_id"])["_departed"] is False


@pytest.mark.parametrize("comment", ["", "   ", "x" * 501])
def test_q038_return_rejects_invalid_comment_without_mutating_card_or_file(
    client, configured, monkeypatch, comment
):
    """Contract-boundary rejection happens before durable return intent or filesystem mutation."""
    csrf, item, quarantine = _quarantine_one_item(client, configured, monkeypatch)
    context = client.app.state.ctx
    with context.store.transaction(write=False) as tx:
        location = configured.sandbox_dir / context.physical(tx, quarantine["location"])
    original = location.read_bytes()
    response = client.post(
        f"/api/v1/quarantine/{quarantine['quarantine_id']}/return",
        headers=_headers(csrf),
        json={"expected_revision": quarantine["revision"], "comment": comment},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert location.read_bytes() == original
    with context.store.transaction(write=False) as tx:
        stored = tx.require("quarantine", quarantine["quarantine_id"])
        assert stored["revision"] == quarantine["revision"]
        assert stored["can_return"] is True
        assert tx.list("return") == []
        assert tx.require("queue", item["item_id"])["_departed"] is True


@pytest.mark.parametrize(("boundary", "returncode"), [("before", 91), ("after", 92)])
def test_q038_return_process_crash_keeps_a_durable_nonduplicating_result(
    client, configured, monkeypatch, boundary, returncode
):
    """A restart observes a persisted return intent instead of repeating an unknown move."""
    csrf, item, quarantine = _quarantine_one_item(client, configured, monkeypatch)
    context = client.app.state.ctx
    with context.store.transaction(write=False) as tx:
        quarantine_path = configured.sandbox_dir / context.physical(tx, quarantine["location"])
        original_path = configured.sandbox_dir / context.physical(tx, quarantine["original_location"])
    original_bytes = quarantine_path.read_bytes()
    request_key = str(uuid4())
    child = """
import os
from wiseway.common import Settings
from wiseway.quarantine import QuarantineService
from wiseway.services import Context

ctx = Context(Settings())
with ctx.store.transaction(write=False) as tx:
    actor = tx.require('user', 'user-worker-atlas')['actor']
    q = tx.require('quarantine', os.environ['WISEWAY_TEST_QUARANTINE_ID'])
original = ctx.fs.rename_no_replace
def terminate(source, target, fingerprint):
    if os.environ['WISEWAY_TEST_CRASH_BOUNDARY'] == 'before':
        os._exit(91)
    original(source, target, fingerprint)
    os._exit(92)
ctx.fs.rename_no_replace = terminate
QuarantineService(ctx).return_item(
    actor,
    {'quarantine_id': q['quarantine_id'], 'Idempotency-Key': os.environ['WISEWAY_TEST_RETURN_KEY']},
    {'expected_revision': q['revision'], 'comment': 'crash boundary return'},
    'child-return-request',
)
"""
    child_env = {
        **os.environ,
        "WISEWAY_DATA_DIR": str(configured.data_dir),
        "WISEWAY_SANDBOX_DIR": str(configured.sandbox_dir),
        "WISEWAY_TEST_QUARANTINE_ID": quarantine["quarantine_id"],
        "WISEWAY_TEST_RETURN_KEY": request_key,
        "WISEWAY_TEST_CRASH_BOUNDARY": boundary,
    }
    crashed = subprocess.run(
        [sys.executable, "-c", child],
        cwd=Path(__file__).resolve().parents[1],
        env=child_env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert crashed.returncode == returncode, crashed.stderr

    from wiseway.quarantine import QuarantineService

    QuarantineService(context).reconcile()
    listed = client.get("/api/v1/quarantine", params={"company_id": item["company_id"], "limit": 100})
    assert listed.status_code == 200, listed.text
    if boundary == "before":
        card = next(
            card for card in listed.json()["items"] if card["quarantine_id"] == quarantine["quarantine_id"]
        )
        assert card["can_return"] is False
        with client.app.state.ctx.store.transaction(write=False) as tx:
            operation = next(
                value for value in tx.list("return") if value["quarantine_id"] == quarantine["quarantine_id"]
            )
            assert operation["phase"] == "RECOVERY_REQUIRED"
            events = [
                event for event in tx.events() if event.get("operation_id") == operation["operation_id"]
            ]
            assert [event["action"] for event in events] == ["RECOVERY_REQUIRED"]
        assert quarantine_path.read_bytes() == original_bytes
        assert not original_path.exists()
        response = client.post(
            f"/api/v1/quarantine/{quarantine['quarantine_id']}/return",
            headers=_headers(csrf),
            json={"expected_revision": card["revision"], "comment": "must not repeat return"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "INVALID_STATE"
    else:
        assert all(card["quarantine_id"] != quarantine["quarantine_id"] for card in listed.json()["items"])
        with client.app.state.ctx.store.transaction(write=False) as tx:
            operation = next(
                value for value in tx.list("return") if value["quarantine_id"] == quarantine["quarantine_id"]
            )
            assert operation["phase"] == "DONE"
            assert tx.require("queue", item["item_id"])["status"] == "WAITING_READY"
            events = [
                event for event in tx.events() if event.get("operation_id") == operation["operation_id"]
            ]
            assert [event["action"] for event in events] == ["QUARANTINE_RETURNED"]
        assert original_path.read_bytes() == original_bytes
        assert not quarantine_path.exists()


def test_q044_dictionary_cannot_target_another_company_directory_over_the_api(client):
    """A valid logical target is still rejected outside the dictionary company scope."""
    csrf = _login(client)
    atlas = "company-atlas"
    nova = "company-nova"
    target = client.get(f"/api/v1/companies/{nova}/target-directories", params={"limit": 100})
    assert target.status_code == 200, target.text
    foreign = {key: target.json()["items"][0][key] for key in ("root_id", "relative_directory")}
    created = client.post(
        f"/api/v1/companies/{atlas}/dictionaries",
        headers=_headers(csrf),
        json={"name": "Foreign target refusal", "description": ""},
    )
    assert created.status_code == 201, created.text
    saved = client.put(
        f"/api/v1/dictionaries/{created.json()['dictionary_id']}/draft",
        headers=_headers(csrf),
        json={
            "expected_draft_revision": created.json()["draft"]["draft_revision"],
            "name": "Foreign target refusal",
            "description": "",
            "rules": [
                {
                    "rule_id": "wrong-company-target",
                    "priority": 1,
                    "match_field": "BASENAME",
                    "mask": "*.pdf",
                    "target": foreign,
                    "target_stem": "NoCrossCompanyMove",
                }
            ],
        },
    )
    assert saved.status_code == 422
    assert saved.json()["error"]["code"] == "INVALID_TARGET"
