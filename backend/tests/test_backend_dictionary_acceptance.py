"""Backend-executable acceptance checks for Q-015 through Q-021.

These drive the public HTTP contract against the seeded SQLite sandbox.  They
assert fixed business outcomes and never calculate expected plans with the
dictionary or rules services themselves.
"""

from __future__ import annotations

from uuid import uuid4

from wiseway.indexer import Indexer

from test_api import login


def _headers(csrf: str) -> dict[str, str]:
    return {
        "Origin": "http://localhost:8000",
        "X-CSRF-Token": csrf,
        "Idempotency-Key": str(uuid4()),
    }


def _ready_items(client, configured, company_id: str) -> list[dict]:
    """Advance synthetic incoming objects through the required readiness check."""
    context = client.app.state.ctx
    with context.store.transaction() as tx:
        for item in tx.list("queue"):
            if item["company_id"] == company_id:
                item["_observed_at"] = configured.clock() - configured.readiness_seconds - 1
                tx.put("queue", item["item_id"], item)
    Indexer(context).scan()
    response = client.post(
        "/api/v1/sorting/queue/query",
        json={
            "company_id": company_id,
            "filters": {"statuses": ["READY"], "query_text": ""},
            "cursor": None,
            "limit": 100,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _target(client, company_id: str) -> dict:
    response = client.get(f"/api/v1/companies/{company_id}/target-directories", params={"limit": 100})
    assert response.status_code == 200, response.text
    value = response.json()["items"][0]
    return {key: value[key] for key in ("root_id", "relative_directory")}


def _create(client, csrf: str, company_id: str, name: str) -> dict:
    response = client.post(
        f"/api/v1/companies/{company_id}/dictionaries",
        headers=_headers(csrf),
        json={"name": name, "description": f"{name} acceptance"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _save(client, csrf: str, dictionary: dict, rules: list[dict]) -> dict:
    response = client.put(
        f"/api/v1/dictionaries/{dictionary['dictionary_id']}/draft",
        headers=_headers(csrf),
        json={
            "expected_draft_revision": dictionary["draft"]["draft_revision"],
            "name": dictionary["name"],
            "description": dictionary["description"],
            "rules": rules,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _simulate(client, csrf: str, dictionary: dict) -> dict:
    response = client.post(
        f"/api/v1/dictionaries/{dictionary['dictionary_id']}/simulate",
        headers=_headers(csrf),
        json={"expected_draft_revision": dictionary["draft"]["draft_revision"]},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _publish(client, csrf: str, dictionary: dict, simulation: dict, *, acknowledge: bool = False):
    return client.post(
        f"/api/v1/dictionaries/{dictionary['dictionary_id']}/publish",
        headers=_headers(csrf),
        json={
            "expected_draft_revision": dictionary["draft"]["draft_revision"],
            "simulation_id": simulation["simulation_id"],
            "acknowledge_no_scenario": acknowledge,
            "comment": "acceptance publication",
        },
    )


def test_q015_q017_active_rule_set_and_typed_rules_round_trip_through_http(client, configured):
    csrf = login(client)
    company = "company-atlas"
    ready = _ready_items(client, configured, company)
    assert [item["filename"] for item in ready] == ["invoice-1001.pdf"]
    target = _target(client, company)

    first = _create(client, csrf, company, "Typed first")
    first_rule = {
        "rule_id": "whole-basename",
        "priority": 1,
        "match_field": "BASENAME",
        "mask": "invoice-????.pdf",
        "target": target,
        "target_stem": "Invoice",
    }
    first = _save(client, csrf, first, [first_rule])
    first_simulation = _simulate(client, csrf, first)
    first_publish = _publish(client, csrf, first, first_simulation)
    assert first_publish.status_code == 201, first_publish.text
    first_version = first_publish.json()["published_version"]

    second = _create(client, csrf, company, "Typed second")
    second_rule = {
        "rule_id": "relative-path",
        "priority": 1,
        "match_field": "RELATIVE_PATH",
        "mask": "invoice-????.pdf",
        "target": target,
        "target_stem": "Invoice",
    }
    second = _save(client, csrf, second, [second_rule])
    fetched = client.get(f"/api/v1/dictionaries/{second['dictionary_id']}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["draft"]["rules"] == [second_rule]

    simulation = _simulate(client, csrf, second)
    assert simulation["total"] == 1
    row = simulation["rows"][0]
    assert row["predicted_state"] == "WILL_MOVE"
    assert row["target"]["relative_path"].endswith("/Invoice.pdf")
    assert {reference["dictionary_id"] for reference in row["matched_rules"]} == {
        first["dictionary_id"],
        second["dictionary_id"],
    }
    assert {reference["version_id"] for reference in row["matched_rules"]} == {
        None,
        first_version["version_id"],
    }

    second_publish = _publish(client, csrf, second, simulation)
    assert second_publish.status_code == 201, second_publish.text
    assert second_publish.json()["rule_set"]["members"] == sorted(
        [
            {"dictionary_id": first["dictionary_id"], "version_id": first_version["version_id"]},
            {
                "dictionary_id": second["dictionary_id"],
                "version_id": second_publish.json()["published_version"]["version_id"],
            },
        ],
        key=lambda member: member["dictionary_id"],
    )


def test_q016_q018_to_q021_conflicts_staleness_acknowledgement_and_restore_provenance(client, configured):
    csrf = login(client)
    company = "company-atlas"
    _ready_items(client, configured, company)
    target = _target(client, company)

    first = _create(client, csrf, company, "Conflict first")
    first = _save(
        client,
        csrf,
        first,
        [
            {
                "rule_id": "first",
                "priority": 1,
                "match_field": "BASENAME",
                "mask": "invoice-????.pdf",
                "target": target,
                "target_stem": "First",
            }
        ],
    )
    first_publish = _publish(client, csrf, first, _simulate(client, csrf, first))
    assert first_publish.status_code == 201, first_publish.text

    second = _create(client, csrf, company, "Conflict second")
    second = _save(
        client,
        csrf,
        second,
        [
            {
                "rule_id": "second",
                "priority": 1,
                "match_field": "BASENAME",
                "mask": "invoice-????.pdf",
                "target": target,
                "target_stem": "Second",
            }
        ],
    )
    stale_revision = second["draft"]["draft_revision"]
    stale_write = client.put(
        f"/api/v1/dictionaries/{second['dictionary_id']}/draft",
        headers=_headers(csrf),
        json={
            "expected_draft_revision": stale_revision - 1,
            "name": second["name"],
            "description": second["description"],
            "rules": [],
        },
    )
    assert stale_write.status_code == 409
    assert stale_write.json()["error"]["code"] == "DRAFT_VERSION_CONFLICT"

    conflict_simulation = _simulate(client, csrf, second)
    assert conflict_simulation["counts"]["rule_conflicts"] == 1
    conflict_publish = _publish(client, csrf, second, conflict_simulation)
    assert conflict_publish.status_code == 409
    assert conflict_publish.json()["error"]["code"] == "RULE_CONFLICT"

    # A Nova dictionary has a READY object but no active rule.  Its simulation
    # demonstrates the explicit no-scenario acknowledgement and TTL checks.
    nova = "company-nova"
    _ready_items(client, configured, nova)
    no_scenario = _create(client, csrf, nova, "No scenario")
    no_scenario_simulation = _simulate(client, csrf, no_scenario)
    assert no_scenario_simulation["counts"]["no_scenario"] == 1
    unacknowledged = _publish(client, csrf, no_scenario, no_scenario_simulation)
    assert unacknowledged.status_code == 409
    assert unacknowledged.json()["error"]["code"] == "NO_SCENARIO_ACK_REQUIRED"
    accepted = _publish(client, csrf, no_scenario, no_scenario_simulation, acknowledge=True)
    assert accepted.status_code == 201, accepted.text
    version = accepted.json()["published_version"]

    restored = client.post(
        f"/api/v1/dictionaries/{no_scenario['dictionary_id']}/restore-draft",
        headers=_headers(csrf),
        json={
            "version_id": version["version_id"],
            "expected_draft_revision": no_scenario["draft"]["draft_revision"],
        },
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["draft"]["based_on_version_id"] == version["version_id"]
    saved_after_restore = _save(client, csrf, restored.json(), [])
    assert saved_after_restore["draft"]["based_on_version_id"] is None

    expired_simulation = _simulate(client, csrf, saved_after_restore)
    now = configured.clock()
    object.__setattr__(configured, "clock", lambda: now + configured.ttl + 1)
    expired = _publish(client, csrf, saved_after_restore, expired_simulation, acknowledge=True)
    assert expired.status_code == 409
    assert expired.json()["error"]["code"] == "STALE_SIMULATION"
