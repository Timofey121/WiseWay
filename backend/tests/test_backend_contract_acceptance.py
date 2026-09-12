"""Backend-only Q-043: successful HTTP operations, published examples and input gates."""

from copy import deepcopy
import re
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from test_api import login
from wiseway.contract import Contract


CONTRACT = Contract()
OPERATIONS = [
    (path, method, operation)
    for path, item in CONTRACT.spec["paths"].items()
    for method, operation in item.items()
    if method in {"get", "post", "put"}
]
BODY_OPERATIONS = [
    (path, method, operation) for path, method, operation in OPERATIONS if "requestBody" in operation
]
WRITE_OPERATIONS = [
    (path, method, operation)
    for path, method, operation in OPERATIONS
    if any(
        CONTRACT.resolve(parameter).get("name") == "X-CSRF-Token"
        for parameter in operation.get("parameters", [])
    )
]


def examples():
    for path, method, operation in OPERATIONS:
        containers = []
        if "requestBody" in operation:
            containers.append(("request", CONTRACT.resolve(operation["requestBody"])))
        containers.extend(
            (status, CONTRACT.resolve(response)) for status, response in operation["responses"].items()
        )
        for label, container in containers:
            for media in container.get("content", {}).values():
                for name, example in media.get("examples", {}).items():
                    yield pytest.param(
                        media["schema"],
                        CONTRACT.resolve(example)["value"],
                        id=f"{method}:{path}:{label}:{name}",
                    )


@pytest.mark.parametrize(("schema", "value"), list(examples()))
def test_published_example_satisfies_its_schema(schema, value):
    # A stale/null/unknown-field example must fail even if normal API tests never send it.
    errors = list(CONTRACT.validator(schema).iter_errors(value))
    assert not errors, [(list(error.path), error.message) for error in errors]


def _state(client):
    with client.app.state.ctx.store.transaction(write=False) as tx:
        return (
            tx.connection.execute("SELECT kind,id,body FROM objects ORDER BY kind,id").fetchall(),
            tx.connection.execute("SELECT id,body FROM audit ORDER BY seq").fetchall(),
        )


@pytest.mark.parametrize(
    ("path", "method", "operation"), BODY_OPERATIONS, ids=[o[2]["operationId"] for o in BODY_OPERATIONS]
)
def test_each_body_operation_rejects_unknown_fields_without_mutation(client, path, method, operation):
    csrf = login(client)
    media = CONTRACT.resolve(operation["requestBody"])["content"]["application/json"]
    body = deepcopy(CONTRACT.resolve(next(iter(media["examples"].values())))["value"])
    body["unexpected_authority"] = "ADMIN"
    before = _state(client)
    response = client.request(
        method.upper(),
        "/api/v1" + re.sub(r"\{[^}]+\}", "unknown-object", path),
        json=body,
        headers={"Origin": "http://localhost:8000", "X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["request_id"] == response.headers["x-request-id"]
    assert error["operation_id"] is None
    assert response.headers["cache-control"] == "no-store"
    assert "unexpected_authority" not in response.text
    assert _state(client) == before


def test_disallowed_cors_origin_receives_no_credentials_allowance(client):
    login(client)
    response = client.options(
        "/api/v1/sorting/batches",
        headers={"Origin": "https://untrusted.example", "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
    allowed = client.options(
        "/api/v1/sorting/batches",
        headers={
            "Origin": "http://localhost:8000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type,X-CSRF-Token,Idempotency-Key",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:8000"
    assert allowed.headers["access-control-allow-credentials"] == "true"


@pytest.mark.parametrize("gate", ["csrf", "origin"])
@pytest.mark.parametrize(
    ("path", "method", "operation"), WRITE_OPERATIONS, ids=[o[2]["operationId"] for o in WRITE_OPERATIONS]
)
def test_every_declared_write_checks_browser_authority_before_mutating(client, gate, path, method, operation):
    csrf = login(client)
    headers = {
        "Origin": "https://untrusted.example" if gate == "origin" else "http://localhost:8000",
        "X-CSRF-Token": "invalid-token" if gate == "csrf" else csrf,
        "Idempotency-Key": str(uuid4()),
    }
    before = _state(client)
    response = client.request(
        method.upper(),
        "/api/v1" + re.sub(r"\{[^}]+\}", "unknown-object", path),
        headers=headers,
    )
    assert response.status_code == 403, response.text
    error = response.json()["error"]
    assert error["code"] == ("FORBIDDEN" if gate == "origin" else "CSRF_FAILED")
    assert error["operation_id"] is None
    assert error["request_id"] == response.headers["x-request-id"]
    assert response.headers["cache-control"] == "no-store"
    assert _state(client) == before


def test_every_operation_returns_a_valid_success_over_real_http(client, configured, monkeypatch):
    from test_acceptance_completion import _headers, _quarantine_one_item
    from test_backend_dictionary_acceptance import _create, _publish, _ready_items, _save, _simulate
    from wiseway.worker import Worker

    observed = set()
    real_request = client.request

    def checked_request(method, url, **kwargs):
        path = urlsplit(str(url)).path.removeprefix("/api/v1")
        matches = [
            operation
            for template, verb, operation in OPERATIONS
            if verb == method.lower() and re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", template), path)
        ]
        assert len(matches) == 1, (method, path)
        operation = matches[0]
        if "requestBody" in operation:
            media = CONTRACT.resolve(operation["requestBody"])["content"]["application/json"]
            assert CONTRACT.validator(media["schema"]).is_valid(kwargs["json"])
        # Observe the client boundary; app routing, authentication, services, SQLite
        # and filesystem operations execute normally. Validate without the response cache.
        response = real_request(method, url, **kwargs)
        assert 200 <= response.status_code < 300, (operation["operationId"], response.text)
        assert str(response.status_code) in operation["responses"]
        declared = CONTRACT.resolve(operation["responses"][str(response.status_code)])
        if "application/json" in declared.get("content", {}):
            schema = declared["content"]["application/json"]["schema"]
            assert CONTRACT.validator(schema).is_valid(response.json()), response.text
        else:
            assert response.content == b""
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-request-id"]
        observed.add(operation["operationId"])
        return response

    monkeypatch.setattr(client, "request", checked_request)
    assert client.get("/api/v1/health").json() == {"status": "ok"}
    csrf, item, quarantined = _quarantine_one_item(client, configured, monkeypatch)
    returned = client.post(
        f"/api/v1/quarantine/{quarantined['quarantine_id']}/return",
        headers=_headers(csrf),
        json={"expected_revision": quarantined["revision"], "comment": "Resume recovered file"},
    ).json()
    assert returned["item"]["status"] == "WAITING_READY"
    assert client.get("/api/v1/session").json()["csrf_token"] == csrf
    assert client.get("/api/v1/app-config").json()["api_contract_version"] == CONTRACT.spec["info"]["version"]

    root = client.get("/api/v1/roots").json()["items"][0]
    search = {
        "request_state_id": "all-operations",
        "root_id": root["root_id"],
        "schema_set_version": root["schema_set_version"],
        "selected_marker_ids": [],
        "query_text": "atlas",
        "facet_prefix": "",
    }
    assert (
        client.post(
            "/api/v1/search", json={**search, "sort": {"field": "RELEVANCE", "direction": "DESC"}}
        ).json()["total"]
        > 0
    )
    assert client.post("/api/v1/search/facet", json=search).json()["request_state_id"] == "all-operations"
    company = item["company_id"]
    ready = _ready_items(client, configured, company)[0]
    target = client.get(f"/api/v1/companies/{company}/target-directories").json()["items"][0]
    assert (
        client.post(
            f"/api/v1/companies/{company}/target-directories/resolve",
            json={"display_path": target["display_path"]},
        ).json()
        == target
    )

    dictionary = _create(client, csrf, company, "Complete HTTP contract")
    dictionary_id = dictionary["dictionary_id"]
    assert dictionary_id in {
        value["dictionary_id"]
        for value in client.get(f"/api/v1/companies/{company}/dictionaries").json()["items"]
    }
    assert client.get(f"/api/v1/dictionaries/{dictionary_id}").json() == dictionary
    dictionary = _save(
        client,
        csrf,
        dictionary,
        [
            {
                "rule_id": "all-http-rule",
                "priority": 1,
                "match_field": "BASENAME",
                "mask": "invoice-????.pdf",
                "target": {key: target[key] for key in ("root_id", "relative_directory")},
                "target_stem": "Contract",
            }
        ],
    )
    simulation = _simulate(client, csrf, dictionary)
    assert client.get(f"/api/v1/simulations/{simulation['simulation_id']}").json()["total"] == 1
    version = _publish(client, csrf, dictionary, simulation).json()["published_version"]
    assert client.get(f"/api/v1/dictionaries/{dictionary_id}/versions").json()["items"] == [version]
    assert (
        client.get(f"/api/v1/dictionaries/{dictionary_id}/versions/{version['version_id']}").json() == version
    )
    restored = client.post(
        f"/api/v1/dictionaries/{dictionary_id}/restore-draft",
        headers=_headers(csrf),
        json={
            "version_id": version["version_id"],
            "expected_draft_revision": dictionary["draft"]["draft_revision"],
        },
    ).json()
    assert restored["draft"]["based_on_version_id"] == version["version_id"]
    selection = client.post(
        "/api/v1/sorting/selections",
        headers=_headers(csrf),
        json={
            "company_id": company,
            "mode": "EXPLICIT",
            "items": [{"item_id": ready["item_id"], "item_revision": ready["item_revision"]}],
        },
    ).json()
    preview = client.post(
        "/api/v1/sorting/previews", headers=_headers(csrf), json={"selection_id": selection["selection_id"]}
    ).json()
    assert client.get(f"/api/v1/sorting/previews/{preview['preview_id']}").json()["total"] == 1
    batch = client.post(
        "/api/v1/sorting/batches",
        headers=_headers(csrf),
        json={
            "execution_mode": "PREVIEWED",
            "selection_id": selection["selection_id"],
            "preview_id": preview["preview_id"],
        },
    ).json()
    assert Worker(client.app.state.ctx).run_once() == 1
    finished = client.get(f"/api/v1/sorting/batches/{batch['batch_id']}").json()
    assert finished["status"] == "COMPLETED"
    assert finished["outcomes"][0]["state"] == "SORTED"
    assert batch["batch_id"] in {
        value["batch_id"]
        for value in client.get("/api/v1/sorting/batches", params={"company_id": company}).json()["items"]
    }
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
    ).json()["items"]
    assert any(event["action"] == "QUARANTINE_RETURNED" for event in events)
    assert client.get("/api/v1/audit/updates").json()["has_new_events"] is True
    assert client.get("/api/v1/audit/actors").json()["items"]
    assert client.post("/api/v1/auth/logout", headers=_headers(csrf)).status_code == 204
    assert observed == {operation["operationId"] for _, _, operation in OPERATIONS}
