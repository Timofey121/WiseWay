"""Additional real-backend acceptance scenarios with durable filesystem evidence."""

from __future__ import annotations

from uuid import uuid4

from wiseway.indexer import Indexer
from wiseway.worker import Worker


def _login(client) -> str:
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://localhost:8000"},
        json={"login": "worker-atlas", "password": "synthetic-test-password"},
    )
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def _headers(csrf: str, key: str | None = None) -> dict[str, str]:
    return {
        "Origin": "http://localhost:8000",
        "X-CSRF-Token": csrf,
        "Idempotency-Key": key or str(uuid4()),
    }


def _ready_item(client, configured) -> tuple[str, dict]:
    ctx = client.app.state.ctx
    with ctx.store.transaction() as tx:
        for item in tx.list("queue"):
            item["_observed_at"] = configured.clock() - configured.readiness_seconds - 1
            tx.put("queue", item["item_id"], item)
    Indexer(ctx).scan()
    company = client.get("/api/v1/companies").json()["items"][0]["company_id"]
    queued = client.post(
        "/api/v1/sorting/queue/query",
        json={
            "company_id": company,
            "filters": {"statuses": ["READY"], "query_text": "invoice-1001"},
            "cursor": None,
            "limit": 100,
        },
    )
    assert queued.status_code == 200, queued.text
    assert len(queued.json()["items"]) == 1
    return company, queued.json()["items"][0]


def _quarantine_one_item(client, configured, monkeypatch) -> tuple[str, dict, dict]:
    """Create one actual quarantine record by failing only its primary move."""
    csrf = _login(client)
    company, item = _ready_item(client, configured)
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
    accepted = client.post(
        "/api/v1/sorting/batches",
        headers=_headers(csrf),
        json={"execution_mode": "DIRECT", "selection_id": selection.json()["selection_id"]},
    )
    assert accepted.status_code == 202, accepted.text
    context = client.app.state.ctx
    real_move = context.fs.rename_no_replace

    def fail_primary(source, target, fingerprint):
        if not target.startswith("Quarantine/"):
            raise OSError("synthetic primary failure")
        return real_move(source, target, fingerprint)

    monkeypatch.setattr(context.fs, "rename_no_replace", fail_primary)
    Worker(context).run_once()
    monkeypatch.setattr(context.fs, "rename_no_replace", real_move)
    quarantined = client.get("/api/v1/quarantine", params={"company_id": company, "limit": 100})
    assert quarantined.status_code == 200, quarantined.text
    assert len(quarantined.json()["items"]) == 1
    return csrf, item, quarantined.json()["items"][0]


def _save_simulate_publish(
    client, csrf, dictionary, target, *, stem: str, comment: str, key: str | None = None
):
    saved = client.put(
        f"/api/v1/dictionaries/{dictionary['dictionary_id']}/draft",
        headers=_headers(csrf),
        json={
            "expected_draft_revision": dictionary["draft"]["draft_revision"],
            "name": dictionary["name"],
            "description": dictionary["description"],
            "rules": [
                {
                    "rule_id": "invoice-rule",
                    "priority": 1,
                    "match_field": "BASENAME",
                    "mask": "invoice-????.pdf",
                    "target": target,
                    "target_stem": stem,
                }
            ],
        },
    )
    assert saved.status_code == 200, saved.text
    simulation = client.post(
        f"/api/v1/dictionaries/{dictionary['dictionary_id']}/simulate",
        headers=_headers(csrf),
        json={"expected_draft_revision": saved.json()["draft"]["draft_revision"]},
    )
    assert simulation.status_code == 201, simulation.text
    published = client.post(
        f"/api/v1/dictionaries/{dictionary['dictionary_id']}/publish",
        headers=_headers(csrf, key),
        json={
            "expected_draft_revision": saved.json()["draft"]["draft_revision"],
            "simulation_id": simulation.json()["simulation_id"],
            "acknowledge_no_scenario": False,
            "comment": comment,
        },
    )
    assert published.status_code == 201, published.text
    return saved.json(), simulation.json(), published


def _save_simulate_publish_rules(client, csrf, dictionary, rules, *, comment: str, acknowledge: bool = False):
    saved = client.put(
        f"/api/v1/dictionaries/{dictionary['dictionary_id']}/draft",
        headers=_headers(csrf),
        json={
            "expected_draft_revision": dictionary["draft"]["draft_revision"],
            "name": dictionary["name"],
            "description": dictionary["description"],
            "rules": rules,
        },
    )
    assert saved.status_code == 200, saved.text
    simulation = client.post(
        f"/api/v1/dictionaries/{dictionary['dictionary_id']}/simulate",
        headers=_headers(csrf),
        json={"expected_draft_revision": saved.json()["draft"]["draft_revision"]},
    )
    assert simulation.status_code == 201, simulation.text
    published = client.post(
        f"/api/v1/dictionaries/{dictionary['dictionary_id']}/publish",
        headers=_headers(csrf),
        json={
            "expected_draft_revision": saved.json()["draft"]["draft_revision"],
            "simulation_id": simulation.json()["simulation_id"],
            "acknowledge_no_scenario": acknowledge,
            "comment": comment,
        },
    )
    assert published.status_code == 201, published.text
    return saved.json(), simulation.json(), published


def test_q020_q021_version_history_frozen_batch_and_restore_do_not_undo_files(client, configured):
    """An accepted batch retains v1 while v2 and a restored v3 are published."""
    csrf = _login(client)
    company, item = _ready_item(client, configured)
    target_response = client.get(f"/api/v1/companies/{company}/target-directories", params={"limit": 100})
    assert target_response.status_code == 200
    target = {key: target_response.json()["items"][0][key] for key in ("root_id", "relative_directory")}
    created = client.post(
        f"/api/v1/companies/{company}/dictionaries",
        headers=_headers(csrf),
        json={"name": "Acceptance versions", "description": "durable-version-history"},
    )
    assert created.status_code == 201, created.text

    first_draft, first_simulation, first_publish = _save_simulate_publish(
        client, csrf, created.json(), target, stem="First", comment="publish first"
    )
    first_version = first_publish.json()["published_version"]
    assert first_publish.json()["rule_set"]["members"] == [
        {"dictionary_id": created.json()["dictionary_id"], "version_id": first_version["version_id"]}
    ]

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
    accepted = client.post(
        "/api/v1/sorting/batches",
        headers=_headers(csrf),
        json={"execution_mode": "DIRECT", "selection_id": selection.json()["selection_id"]},
    )
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["rule_set"]["members"][0]["version_id"] == first_version["version_id"]

    # A separate preview remains unaccepted.  Publishing v2 must stale it rather
    # than silently applying its old plan.
    later_file = configured.sandbox_dir / "Incoming" / "Atlas" / "invoice-2002.pdf"
    later_file.write_bytes(b"later acceptance input")
    Indexer(client.app.state.ctx).scan()
    with client.app.state.ctx.store.transaction() as tx:
        for queued in tx.list("queue"):
            if queued["filename"] == "invoice-2002.pdf":
                queued["_observed_at"] = configured.clock() - configured.readiness_seconds - 1
                tx.put("queue", queued["item_id"], queued)
    Indexer(client.app.state.ctx).scan()
    later_queue = client.post(
        "/api/v1/sorting/queue/query",
        json={
            "company_id": company,
            "filters": {"statuses": ["READY"], "query_text": "invoice-2002"},
            "cursor": None,
            "limit": 100,
        },
    )
    assert later_queue.status_code == 200, later_queue.text
    later_item = later_queue.json()["items"][0]
    stale_selection = client.post(
        "/api/v1/sorting/selections",
        headers=_headers(csrf),
        json={
            "company_id": company,
            "mode": "EXPLICIT",
            "items": [{"item_id": later_item["item_id"], "item_revision": later_item["item_revision"]}],
        },
    )
    assert stale_selection.status_code == 201, stale_selection.text
    old_preview = client.post(
        "/api/v1/sorting/previews",
        headers=_headers(csrf),
        json={"selection_id": stale_selection.json()["selection_id"]},
    )
    assert old_preview.status_code == 201, old_preview.text

    second_draft, _, second_publish = _save_simulate_publish(
        client, csrf, first_publish.json()["dictionary"], target, stem="Second", comment="publish second"
    )
    second_version = second_publish.json()["published_version"]
    assert second_version["version_number"] == 2
    assert (
        client.get(
            f"/api/v1/dictionaries/{created.json()['dictionary_id']}/versions/{first_version['version_id']}"
        ).json()
        == first_version
    )
    stale_batch = client.post(
        "/api/v1/sorting/batches",
        headers=_headers(csrf),
        json={
            "execution_mode": "PREVIEWED",
            "selection_id": stale_selection.json()["selection_id"],
            "preview_id": old_preview.json()["preview_id"],
        },
    )
    assert stale_batch.status_code == 409
    assert stale_batch.json()["error"]["code"] == "STALE_PREVIEW"
    assert later_file.is_file()

    Worker(client.app.state.ctx).run_once()
    completed = client.get(f"/api/v1/sorting/batches/{accepted.json()['batch_id']}")
    assert completed.status_code == 200, completed.text
    outcome = completed.json()["outcomes"][0]
    assert outcome["state"] == "SORTED"
    assert outcome["actual_location"]["relative_path"].endswith("/First.pdf")
    with client.app.state.ctx.store.transaction() as tx:
        assert (
            client.app.state.ctx.fs.stat(client.app.state.ctx.physical(tx, outcome["actual_location"]))
            is not None
        )
        assert client.app.state.ctx.fs.stat(client.app.state.ctx.physical(tx, item["source"])) is None

    restored = client.post(
        f"/api/v1/dictionaries/{created.json()['dictionary_id']}/restore-draft",
        headers=_headers(csrf),
        json={
            "version_id": first_version["version_id"],
            "expected_draft_revision": second_draft["draft"]["draft_revision"],
        },
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["draft"]["based_on_version_id"] == first_version["version_id"]
    restored_simulation = client.post(
        f"/api/v1/dictionaries/{created.json()['dictionary_id']}/simulate",
        headers=_headers(csrf),
        json={"expected_draft_revision": restored.json()["draft"]["draft_revision"]},
    )
    assert restored_simulation.status_code == 201, restored_simulation.text
    restored_publish = client.post(
        f"/api/v1/dictionaries/{created.json()['dictionary_id']}/publish",
        headers=_headers(csrf),
        json={
            "expected_draft_revision": restored.json()["draft"]["draft_revision"],
            "simulation_id": restored_simulation.json()["simulation_id"],
            "acknowledge_no_scenario": False,
            "comment": "restore first as third",
        },
    )
    assert restored_publish.status_code == 201, restored_publish.text
    third_version = restored_publish.json()["published_version"]
    assert third_version["version_number"] == 3
    assert third_version["restored_from_version_id"] == first_version["version_id"]
    assert third_version["rules"] == first_version["rules"]
    assert (configured.sandbox_dir / outcome["actual_location"]["relative_path"]).is_file()

    manual_edit = client.put(
        f"/api/v1/dictionaries/{created.json()['dictionary_id']}/draft",
        headers=_headers(csrf),
        json={
            "expected_draft_revision": restored_publish.json()["dictionary"]["draft"]["draft_revision"],
            "name": "Acceptance versions",
            "description": "manual edit after restore",
            "rules": third_version["rules"],
        },
    )
    assert manual_edit.status_code == 200, manual_edit.text
    assert manual_edit.json()["draft"]["based_on_version_id"] is None
    versions = client.get(
        f"/api/v1/dictionaries/{created.json()['dictionary_id']}/versions", params={"limit": 100}
    )
    assert [version["version_id"] for version in versions.json()["items"]] == [
        third_version["version_id"],
        second_version["version_id"],
        first_version["version_id"],
    ]


def test_q029_publish_and_batch_replays_precede_expired_dependencies(client, configured):
    """Idempotent replays return the original durable responses before TTL checks."""
    csrf = _login(client)
    company, item = _ready_item(client, configured)
    target = client.get(f"/api/v1/companies/{company}/target-directories", params={"limit": 100}).json()[
        "items"
    ][0]
    created = client.post(
        f"/api/v1/companies/{company}/dictionaries",
        headers=_headers(csrf),
        json={"name": "Idempotency acceptance", "description": ""},
    ).json()
    publish_key = str(uuid4())
    draft, simulation, publish = _save_simulate_publish(
        client,
        csrf,
        created,
        {key: target[key] for key in ("root_id", "relative_directory")},
        stem="Replay",
        comment="publish once",
        key=publish_key,
    )
    repeated_publish = client.post(
        f"/api/v1/dictionaries/{created['dictionary_id']}/publish",
        headers=_headers(csrf, publish_key),
        json={
            "expected_draft_revision": draft["draft"]["draft_revision"],
            "simulation_id": simulation["simulation_id"],
            "acknowledge_no_scenario": False,
            "comment": "publish once",
        },
    )
    assert repeated_publish.status_code == 201
    assert repeated_publish.json() == publish.json()

    selection = client.post(
        "/api/v1/sorting/selections",
        headers=_headers(csrf),
        json={
            "company_id": company,
            "mode": "EXPLICIT",
            "items": [{"item_id": item["item_id"], "item_revision": item["item_revision"]}],
        },
    ).json()
    batch_key = str(uuid4())
    body = {"execution_mode": "DIRECT", "selection_id": selection["selection_id"]}
    accepted = client.post("/api/v1/sorting/batches", headers=_headers(csrf, batch_key), json=body)
    assert accepted.status_code == 202, accepted.text
    expired_now = configured.clock() + configured.ttl + 1
    object.__setattr__(configured, "clock", lambda: expired_now)
    expired_publish_replay = client.post(
        f"/api/v1/dictionaries/{created['dictionary_id']}/publish",
        headers=_headers(csrf, publish_key),
        json={
            "expected_draft_revision": draft["draft"]["draft_revision"],
            "simulation_id": simulation["simulation_id"],
            "acknowledge_no_scenario": False,
            "comment": "publish once",
        },
    )
    assert expired_publish_replay.status_code == 201
    assert expired_publish_replay.json() == publish.json()
    replayed = client.post("/api/v1/sorting/batches", headers=_headers(csrf, batch_key), json=body)
    assert replayed.status_code == 202
    assert replayed.json() == accepted.json()
    changed = client.post(
        "/api/v1/sorting/batches",
        headers=_headers(csrf, batch_key),
        json={"execution_mode": "DIRECT", "selection_id": "selection-different"},
    )
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_q026_rule_target_change_stales_preview_and_expired_selection_is_rejected(client, configured):
    """Server-side snapshots reject a changed RuleSet and an elapsed selection."""
    csrf = _login(client)
    company, item = _ready_item(client, configured)
    target = client.get(f"/api/v1/companies/{company}/target-directories", params={"limit": 100}).json()[
        "items"
    ][0]
    target = {key: target[key] for key in ("root_id", "relative_directory")}
    created = client.post(
        f"/api/v1/companies/{company}/dictionaries",
        headers=_headers(csrf),
        json={"name": "Stale acceptance", "description": ""},
    )
    assert created.status_code == 201, created.text
    _, _, first_publish = _save_simulate_publish(
        client, csrf, created.json(), target, stem="OriginalTarget", comment="first plan"
    )
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
    preview = client.post(
        "/api/v1/sorting/previews",
        headers=_headers(csrf),
        json={"selection_id": selection.json()["selection_id"]},
    )
    assert preview.status_code == 201, preview.text
    _, _, second_publish = _save_simulate_publish(
        client,
        csrf,
        first_publish.json()["dictionary"],
        target,
        stem="ChangedTarget",
        comment="changed target",
    )
    stale = client.post(
        "/api/v1/sorting/batches",
        headers=_headers(csrf),
        json={
            "execution_mode": "PREVIEWED",
            "selection_id": selection.json()["selection_id"],
            "preview_id": preview.json()["preview_id"],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "STALE_PREVIEW"
    assert second_publish.json()["published_version"]["version_number"] == 2
    assert (configured.sandbox_dir / "Incoming" / "Atlas" / item["filename"]).is_file()

    fresh_selection = client.post(
        "/api/v1/sorting/selections",
        headers=_headers(csrf),
        json={
            "company_id": company,
            "mode": "EXPLICIT",
            "items": [{"item_id": item["item_id"], "item_revision": item["item_revision"]}],
        },
    )
    assert fresh_selection.status_code == 201, fresh_selection.text
    fresh_preview = client.post(
        "/api/v1/sorting/previews",
        headers=_headers(csrf),
        json={"selection_id": fresh_selection.json()["selection_id"]},
    )
    assert fresh_preview.status_code == 201, fresh_preview.text
    expired_now = configured.clock() + configured.ttl + 1
    object.__setattr__(configured, "clock", lambda: expired_now)
    expired_preview = client.post(
        "/api/v1/sorting/batches",
        headers=_headers(csrf),
        json={
            "execution_mode": "PREVIEWED",
            "selection_id": fresh_selection.json()["selection_id"],
            "preview_id": fresh_preview.json()["preview_id"],
        },
    )
    assert expired_preview.status_code == 409
    assert expired_preview.json()["error"]["code"] == "STALE_PREVIEW"
    expired = client.post(
        "/api/v1/sorting/batches",
        headers=_headers(csrf),
        json={"execution_mode": "DIRECT", "selection_id": fresh_selection.json()["selection_id"]},
    )
    assert expired.status_code == 409
    assert expired.json()["error"]["code"] == "SELECTION_EXPIRED"


def test_q015_two_published_dictionaries_round_trip_typed_rules_and_plan_real_files(client, configured):
    """Both active versions participate in a real READY-set simulation."""
    csrf = _login(client)
    company, _ = _ready_item(client, configured)
    incoming = configured.sandbox_dir / "Incoming" / "Atlas"
    files = {
        "q015-archive.tar.gz": b"archive",
        ".env": b"hidden",
        "README": b"readme",
        "name.": b"trailing dot",
        "q015-case.TXT": b"case",
        "q015-path/ab.TXT": b"path",
    }
    for name, content in files.items():
        path = incoming / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    Indexer(client.app.state.ctx).scan()
    with client.app.state.ctx.store.transaction() as tx:
        for queued in tx.list("queue"):
            if queued["source"]["relative_path"] in files:
                queued["_observed_at"] = configured.clock() - configured.readiness_seconds - 1
                tx.put("queue", queued["item_id"], queued)
    Indexer(client.app.state.ctx).scan()
    ready = client.post(
        "/api/v1/sorting/queue/query",
        json={
            "company_id": company,
            "filters": {"statuses": ["READY"], "query_text": ""},
            "cursor": None,
            "limit": 100,
        },
    )
    assert ready.status_code == 200, ready.text
    assert {
        item["source"]["relative_path"]
        for item in ready.json()["items"]
        if item["source"]["relative_path"] in files
    } == set(files)
    target_response = client.get(f"/api/v1/companies/{company}/target-directories", params={"limit": 100})
    target = {key: target_response.json()["items"][0][key] for key in ("root_id", "relative_directory")}

    first = client.post(
        f"/api/v1/companies/{company}/dictionaries",
        headers=_headers(csrf),
        json={"name": "Typed basename rules", "description": "round-trip all suffix cases"},
    )
    assert first.status_code == 201, first.text
    basename_rules = [
        {
            "rule_id": rule_id,
            "priority": priority,
            "match_field": "BASENAME",
            "mask": mask,
            "target": target,
            "target_stem": stem,
        }
        for rule_id, priority, mask, stem in (
            ("invoice", 1, "invoice-????.pdf", "InvoiceResult"),
            ("archive", 2, "q015-archive.tar.gz", "ArchiveResult"),
            ("hidden", 3, ".env", "HiddenResult"),
            ("readme", 4, "README", "ReadmeResult"),
            ("trailing", 5, "name.", "TrailingResult"),
            ("case-star", 6, "q015-*.txt", "CaseResult"),
        )
    ]
    first_saved, first_simulation, first_published = _save_simulate_publish_rules(
        client, csrf, first.json(), basename_rules, comment="publish typed basename", acknowledge=True
    )
    assert first_saved["draft"]["rules"] == basename_rules
    assert first_published.json()["published_version"]["rules"] == basename_rules
    assert first_simulation["counts"]["no_scenario"] == 1

    second = client.post(
        f"/api/v1/companies/{company}/dictionaries",
        headers=_headers(csrf),
        json={"name": "Typed path rules", "description": "slash and one-character wildcard"},
    )
    assert second.status_code == 201, second.text
    path_rules = [
        {
            "rule_id": "path-question",
            "priority": 7,
            "match_field": "RELATIVE_PATH",
            "mask": "q015-path/??.TXT",
            "target": target,
            "target_stem": "PathResult",
        }
    ]
    second_saved, second_simulation, second_published = _save_simulate_publish_rules(
        client, csrf, second.json(), path_rules, comment="publish typed path"
    )
    assert second_saved["draft"]["rules"] == path_rules
    assert second_published.json()["published_version"]["rules"] == path_rules
    assert second_simulation["counts"]["no_scenario"] == 0
    assert len(second_published.json()["rule_set"]["members"]) == 2
    targets = {
        row["filename"]: row["target"]["relative_path"].rsplit("/", 1)[-1]
        for row in second_simulation["rows"]
        if row["source"]["relative_path"] in files
    }
    assert targets == {
        "q015-archive.tar.gz": "ArchiveResult.gz",
        ".env": "HiddenResult",
        "README": "ReadmeResult",
        "name.": "TrailingResult",
        "q015-case.TXT": "CaseResult.TXT",
        "ab.TXT": "PathResult.TXT",
    }
    invalid_mask = client.put(
        f"/api/v1/dictionaries/{second.json()['dictionary_id']}/draft",
        headers=_headers(csrf),
        json={
            "expected_draft_revision": second_published.json()["dictionary"]["draft"]["draft_revision"],
            "name": "Typed path rules",
            "description": "reject unsupported glob",
            "rules": [{**path_rules[0], "mask": "**"}],
        },
    )
    assert invalid_mask.status_code == 422
    assert invalid_mask.json()["error"]["code"] == "VALIDATION_ERROR"


def test_q029_quarantine_return_replay_precedes_ttl_and_rejects_changed_or_new_requests(
    client, configured, monkeypatch
):
    """The durable return protocol has its own replay record and lifecycle."""
    csrf, source_item, quarantined = _quarantine_one_item(client, configured, monkeypatch)
    body = {"expected_revision": quarantined["revision"], "comment": "return after storage repair"}
    key = str(uuid4())
    returned = client.post(
        f"/api/v1/quarantine/{quarantined['quarantine_id']}/return",
        headers=_headers(csrf, key),
        json=body,
    )
    assert returned.status_code == 200, returned.text
    assert returned.json()["item"]["status"] == "WAITING_READY"
    assert returned.json()["item"]["item_id"] == source_item["item_id"]
    with client.app.state.ctx.store.transaction() as tx:
        assert (
            client.app.state.ctx.fs.stat(client.app.state.ctx.physical(tx, source_item["source"])) is not None
        )
        assert (
            client.app.state.ctx.fs.stat(client.app.state.ctx.physical(tx, quarantined["location"])) is None
        )

    expired_now = configured.clock() + configured.ttl + 1
    object.__setattr__(configured, "clock", lambda: expired_now)
    replayed = client.post(
        f"/api/v1/quarantine/{quarantined['quarantine_id']}/return",
        headers=_headers(csrf, key),
        json=body,
    )
    assert replayed.status_code == 200, replayed.text
    assert replayed.json() == returned.json()
    changed_body = client.post(
        f"/api/v1/quarantine/{quarantined['quarantine_id']}/return",
        headers=_headers(csrf, key),
        json={**body, "comment": "changed body"},
    )
    assert changed_body.status_code == 409
    assert changed_body.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    new_key = client.post(
        f"/api/v1/quarantine/{quarantined['quarantine_id']}/return",
        headers=_headers(csrf),
        json=body,
    )
    assert new_key.status_code == 409
    assert new_key.json()["error"]["code"] == "INVALID_STATE"
