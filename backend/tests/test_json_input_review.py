import logging
from uuid import uuid4

import pytest

from test_api import login


def _json_headers(**headers):
    return {"Content-Type": "application/json", **headers}


def _mutation_headers(csrf):
    return _json_headers(
        Origin="http://localhost:8000",
        **{"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4())},
    )


@pytest.mark.parametrize(
    "payload",
    [
        b"[" * 1100 + b"0" + b"]" * 1100,
        '{"login":"worker-atlas","password":"synthetic-test-password"}'.encode("utf-16"),
        b'{"login":"worker-atlas","password":"\\ud800secret-input"}',
    ],
)
def test_login_rejects_non_utf8_deep_or_unpaired_json_without_logging_or_state_change(
    client, caplog, payload
):
    ctx = client.app.state.ctx
    with ctx.store.transaction(write=False) as tx:
        before_events = tx.events()
        before_rate = tx.list("login_rate")
    with caplog.at_level(logging.ERROR, logger="wiseway"):
        response = client.post(
            "/api/v1/auth/login",
            headers=_json_headers(Origin="http://localhost:8000"),
            content=payload,
        )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "secret-input" not in response.text
    assert "secret-input" not in caplog.text
    with ctx.store.transaction(write=False) as tx:
        assert tx.events() == before_events
        assert tx.list("login_rate") == before_rate


def test_draft_rejects_unpaired_surrogate_without_persisting_or_logging(client, caplog):
    csrf = login(client)
    created = client.post(
        "/api/v1/companies/company-atlas/dictionaries",
        headers=_mutation_headers(csrf),
        json={"name": "Normal", "description": ""},
    )
    assert created.status_code == 201, created.text
    dictionary = created.json()
    ctx = client.app.state.ctx
    with ctx.store.transaction(write=False) as tx:
        before = tx.require("dictionary", dictionary["dictionary_id"])
        before_events = tx.events()
    payload = (
        '{"expected_draft_revision":1,"name":"Normal","description":"\\ud800secret-input","rules":[]}'
    ).encode()
    with caplog.at_level(logging.ERROR, logger="wiseway"):
        response = client.put(
            f"/api/v1/dictionaries/{dictionary['dictionary_id']}/draft",
            headers=_mutation_headers(csrf),
            content=payload,
        )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "secret-input" not in response.text
    assert "secret-input" not in caplog.text
    with ctx.store.transaction(write=False) as tx:
        assert tx.require("dictionary", dictionary["dictionary_id"]) == before
        assert tx.events() == before_events


def test_utf8_cyrillic_and_valid_emoji_surrogate_pair_remain_valid_input(client):
    csrf = login(client)
    created = client.post(
        "/api/v1/companies/company-atlas/dictionaries",
        headers=_mutation_headers(csrf),
        content=b'{"name":"\\u0422\\u0435\\u0441\\u0442 \\ud83d\\ude00","description":"\\u041e\\u043f\\u0438\\u0441\\u0430\\u043d\\u0438\\u0435"}',
    )
    assert created.status_code == 201, created.text
    assert created.json()["name"] == "Тест 😀"
    dictionary = created.json()
    updated = client.put(
        f"/api/v1/dictionaries/{dictionary['dictionary_id']}/draft",
        headers=_mutation_headers(csrf),
        content=(
            b'{"expected_draft_revision":1,"name":"\\u041e\\u0431\\u043d\\u043e\\u0432\\u043b\\u0435\\u043d\\u0438\\u0435 '
            b'\\ud83d\\ude00","description":"\\u041e\\u0431\\u044b\\u0447\\u043d\\u043e","rules":[]}'
        ),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Обновление 😀"
