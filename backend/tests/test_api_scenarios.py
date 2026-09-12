"""End-to-end contract scenarios over the real SQLite sandbox."""

from __future__ import annotations

from uuid import uuid4

from test_api import login


def write_headers(csrf: str, *, key: str | None = None) -> dict[str, str]:
    return {"Origin": "http://localhost:8000", "X-CSRF-Token": csrf, "Idempotency-Key": key or str(uuid4())}


def ready_queue(client, configured) -> dict:
    from wiseway.indexer import Indexer

    ctx = client.app.state.ctx
    with ctx.store.transaction() as tx:
        for value in tx.list("queue"):
            value["_observed_at"] = configured.clock() - 6
            tx.put("queue", value["item_id"], value)
    Indexer(ctx).scan()
    company = client.get("/api/v1/companies").json()["items"][0]["company_id"]
    response = client.post(
        "/api/v1/sorting/queue/query",
        json={
            "company_id": company,
            "filters": {"statuses": ["READY"], "query_text": ""},
            "cursor": None,
            "limit": 100,
        },
    )
    assert response.status_code == 200, response.text
    return {"company": company, "item": response.json()["items"][0]}


def test_live_roots_search_facet_targets_and_audit_visibility(client):
    login(client)
    config = client.get("/api/v1/app-config")
    assert config.status_code == 200
    assert config.json()["api_contract_version"] == client.app.state.contract.spec["info"]["version"]
    roots = client.get("/api/v1/roots")
    assert roots.status_code == 200, roots.text
    root = roots.json()["items"][0]
    idle = {
        "request_state_id": "state-idle-live",
        "root_id": root["root_id"],
        "schema_set_version": root["schema_set_version"],
        "selected_marker_ids": [],
        "query_text": "",
        "sort": {"field": "PATH", "direction": "ASC"},
        "facet_prefix": "",
    }
    response = client.post("/api/v1/search", json=idle)
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "IDLE"
    option = response.json()["next_facet"]["options"][0]
    found = client.post(
        "/api/v1/search",
        json={
            **idle,
            "request_state_id": "state-query-live",
            "query_text": "atlas",
            "sort": {"field": "RELEVANCE", "direction": "DESC"},
        },
    )
    assert found.status_code == 200 and found.json()["total"] >= 1
    listed = client.post("/api/v1/search/facet", json={k: idle[k] for k in idle if k != "sort"})
    assert listed.status_code == 200 and listed.json()["facet"]["options"]
    selected = client.post(
        "/api/v1/search",
        json={**idle, "request_state_id": "state-marker-live", "selected_marker_ids": [option["marker_id"]]},
    )
    assert selected.status_code == 200 and selected.json()["mode"] == "RESULTS"

    company = client.get("/api/v1/companies").json()["items"][0]["company_id"]
    targets = client.get(f"/api/v1/companies/{company}/target-directories", params={"limit": 1})
    assert targets.status_code == 200 and targets.json()["items"]
    target = targets.json()["items"][0]
    resolved = client.post(
        f"/api/v1/companies/{company}/target-directories/resolve",
        json={"display_path": target["display_path"]},
    )
    assert resolved.status_code == 200 and resolved.json() == target
    invalid = client.post(
        f"/api/v1/companies/{company}/target-directories/resolve", json={"display_path": "DEMO:/outside"}
    )
    assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "INVALID_TARGET"

    audit_query = {
        "company_id": None,
        "from": "2020-01-01T00:00:00Z",
        "to": "2035-01-01T00:00:00Z",
        "actor_id": None,
        "action": None,
        "result": None,
        "query_text": "",
        "cursor": None,
        "limit": 100,
    }
    worker_events = client.post("/api/v1/audit/query", json=audit_query)
    assert worker_events.status_code == 200
    assert all(event["category"] == "BUSINESS" for event in worker_events.json()["items"])
    login(client, "admin")
    admin_events = client.post("/api/v1/audit/query", json=audit_query)
    assert admin_events.status_code == 200
    assert any(event["category"] == "SYSTEM" for event in admin_events.json()["items"])
    updates = client.get("/api/v1/audit/updates")
    assert updates.status_code == 200 and updates.json()["has_new_events"] is True
    actors = client.get("/api/v1/audit/actors", params={"limit": 100})
    assert actors.status_code == 200 and actors.json()["items"]
    batches = client.get("/api/v1/sorting/batches", params={"company_id": company, "limit": 100})
    assert batches.status_code == 200 and batches.json()["items"] == []


def test_dictionary_version_restore_simulation_and_cursor_failures(client, configured):
    csrf = login(client)
    queue = ready_queue(client, configured)
    company, item = queue["company"], queue["item"]
    created = client.post(
        f"/api/v1/companies/{company}/dictionaries",
        headers=write_headers(csrf),
        json={"name": "Scenario dictionary", "description": ""},
    )
    assert created.status_code == 201, created.text
    dictionary = created.json()
    fetched = client.get(f"/api/v1/dictionaries/{dictionary['dictionary_id']}")
    assert fetched.status_code == 200 and fetched.json()["dictionary_id"] == dictionary["dictionary_id"]
    target_response = client.get(f"/api/v1/companies/{company}/target-directories", params={"limit": 100})
    assert target_response.status_code == 200, target_response.text
    target = target_response.json()["items"][0]
    rule = {
        "rule_id": "scenario-rule",
        "priority": 1,
        "match_field": "BASENAME",
        "mask": "*",
        "target": {key: target[key] for key in ("root_id", "relative_directory")},
        "target_stem": "Scenario",
    }
    saved = client.put(
        f"/api/v1/dictionaries/{dictionary['dictionary_id']}/draft",
        headers=write_headers(csrf),
        json={"expected_draft_revision": 1, "name": dictionary["name"], "description": "", "rules": [rule]},
    )
    assert saved.status_code == 200, saved.text
    revision = saved.json()["draft"]["draft_revision"]
    simulation = client.post(
        f"/api/v1/dictionaries/{dictionary['dictionary_id']}/simulate",
        headers=write_headers(csrf),
        json={"expected_draft_revision": revision},
    )
    assert simulation.status_code == 201, simulation.text
    sim = simulation.json()
    sim_get = client.get(f"/api/v1/simulations/{sim['simulation_id']}", params={"limit": 1})
    assert sim_get.status_code == 200 and sim_get.json()["total"] >= 1
    publish = client.post(
        f"/api/v1/dictionaries/{dictionary['dictionary_id']}/publish",
        headers=write_headers(csrf),
        json={
            "expected_draft_revision": revision,
            "simulation_id": sim["simulation_id"],
            "acknowledge_no_scenario": False,
            "comment": "Publish scenario",
        },
    )
    assert publish.status_code == 201, publish.text
    version = publish.json()["published_version"]
    versions = client.get(f"/api/v1/dictionaries/{dictionary['dictionary_id']}/versions", params={"limit": 1})
    assert versions.status_code == 200 and versions.json()["items"][0]["version_id"] == version["version_id"]
    exact = client.get(f"/api/v1/dictionaries/{dictionary['dictionary_id']}/versions/{version['version_id']}")
    assert exact.status_code == 200
    restored = client.post(
        f"/api/v1/dictionaries/{dictionary['dictionary_id']}/restore-draft",
        headers=write_headers(csrf),
        json={"version_id": version["version_id"], "expected_draft_revision": revision},
    )
    assert (
        restored.status_code == 200
        and restored.json()["draft"]["based_on_version_id"] == version["version_id"]
    )
    bad_cursor = client.get(
        f"/api/v1/dictionaries/{dictionary['dictionary_id']}/versions",
        params={"cursor": "not-a-cursor", "limit": 1},
    )
    assert bad_cursor.status_code == 422

    selection = client.post(
        "/api/v1/sorting/selections",
        headers=write_headers(csrf),
        json={
            "company_id": company,
            "mode": "EXPLICIT",
            "items": [{"item_id": item["item_id"], "item_revision": item["item_revision"]}],
        },
    )
    assert selection.status_code == 201
    preview = client.post(
        "/api/v1/sorting/previews",
        headers=write_headers(csrf),
        json={"selection_id": selection.json()["selection_id"]},
    )
    assert preview.status_code == 201, preview.text
    preview_id = preview.json()["preview_id"]
    fetched_preview = client.get(f"/api/v1/sorting/previews/{preview_id}", params={"limit": 1})
    assert fetched_preview.status_code == 200
    login(client, "worker-nova")
    denied = client.get(f"/api/v1/sorting/previews/{preview_id}", params={"limit": 1})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "FORBIDDEN"


def test_dictionary_listing_and_audit_of_draft_mutations_are_contract_valid(client, configured):
    csrf = login(client)
    queue = ready_queue(client, configured)
    company = queue["company"]
    created = client.post(
        f"/api/v1/companies/{company}/dictionaries",
        headers=write_headers(csrf),
        json={"name": "Audited dictionary", "description": ""},
    )
    assert created.status_code == 201, created.text
    saved = client.put(
        f"/api/v1/dictionaries/{created.json()['dictionary_id']}/draft",
        headers=write_headers(csrf),
        json={
            "expected_draft_revision": 1,
            "name": "Audited dictionary",
            "description": "changed",
            "rules": [],
        },
    )
    assert saved.status_code == 200, saved.text
    events = client.post(
        "/api/v1/audit/query",
        json={
            "company_id": company,
            "from": "2020-01-01T00:00:00Z",
            "to": "2035-01-01T00:00:00Z",
            "actor_id": None,
            "action": None,
            "result": None,
            "query_text": "",
            "cursor": None,
            "limit": 100,
        },
    )
    assert events.status_code == 200, events.text
    assert any(event["action"] == "DRAFT_SAVED" for event in events.json()["items"])
    listed = client.get(f"/api/v1/companies/{company}/dictionaries")
    assert listed.status_code == 200, listed.text
    assert [value["dictionary_id"] for value in listed.json()["items"]] == [created.json()["dictionary_id"]]


def test_expired_simulation_is_readable_as_a_fixed_historical_result(client, configured):
    csrf = login(client)
    queue = ready_queue(client, configured)
    company = queue["company"]
    created = client.post(
        f"/api/v1/companies/{company}/dictionaries",
        headers=write_headers(csrf),
        json={"name": "Historical simulation", "description": ""},
    ).json()
    simulation = client.post(
        f"/api/v1/dictionaries/{created['dictionary_id']}/simulate",
        headers=write_headers(csrf),
        json={"expected_draft_revision": 1},
    )
    assert simulation.status_code == 201, simulation.text
    with client.app.state.ctx.store.transaction() as tx:
        stored = tx.require("simulation", simulation.json()["simulation_id"])
        stored["_expires"] = configured.clock() - 1
        tx.put("simulation", stored["simulation_id"], stored)
    historical = client.get(
        f"/api/v1/simulations/{simulation.json()['simulation_id']}", params={"limit": 100}
    )
    assert historical.status_code == 200, historical.text


def test_initial_simulation_response_is_a_first_page_for_more_than_100_ready_files(client, configured):
    for number in range(101):
        (configured.sandbox_dir / "Incoming" / "Atlas" / f"bulk-{number}.pdf").write_bytes(b"bulk")
    csrf = login(client)
    ready_queue(client, configured)  # discovers the newly created files
    queue = ready_queue(client, configured)  # the second equal observation makes them READY
    created = client.post(
        f"/api/v1/companies/{queue['company']}/dictionaries",
        headers=write_headers(csrf),
        json={"name": "Large simulation", "description": ""},
    ).json()
    simulation = client.post(
        f"/api/v1/dictionaries/{created['dictionary_id']}/simulate",
        headers=write_headers(csrf),
        json={"expected_draft_revision": 1},
    )
    assert simulation.status_code == 201, simulation.text
    assert simulation.json()["total"] > 100
    assert len(simulation.json()["rows"]) == 100
    assert simulation.json()["next_cursor"]
