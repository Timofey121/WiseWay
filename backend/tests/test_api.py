def login(client, name="worker-atlas"):
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://localhost:8000"},
        json={"login": name, "password": "synthetic-test-password"},
    )
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def test_health_auth_and_contract_errors(client):
    assert client.get("/api/v1/health").json() == {"status": "ok"}
    denied = client.get("/api/v1/session")
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "UNAUTHENTICATED"
    assert denied.json()["error"]["request_id"] == denied.headers["x-request-id"]
    assert denied.headers["cache-control"] == "no-store"
    csrf = login(client)
    session = client.get("/api/v1/session").json()
    assert session["csrf_token"] == csrf
    assert session["actor"]["role"] == "WORKER"
    assert (
        "HttpOnly"
        in client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://localhost:8000"},
            json={"login": "worker-atlas", "password": "synthetic-test-password"},
        ).headers["set-cookie"]
    )


def test_origin_csrf_and_logout(client):
    bad = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "https://evil.example"},
        json={"login": "worker-atlas", "password": "synthetic-test-password"},
    )
    assert bad.status_code == 403
    csrf = login(client)
    assert client.post("/api/v1/auth/logout").status_code == 403
    response = client.post(
        "/api/v1/auth/logout", headers={"Origin": "http://localhost:8000", "X-CSRF-Token": csrf}
    )
    assert response.status_code == 204
    assert client.get("/api/v1/session").status_code == 401


def test_malformed_payload_does_not_leak_or_ignore_fields(client):
    denied = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://localhost:8000"},
        json={"login": "worker-atlas", "password": "bad", "admin": True},
    )
    assert denied.status_code == 422
    assert denied.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "bad" not in denied.text


def test_every_declared_operation_is_registered(client):
    spec = client.app.state.contract.spec
    registered = {
        (r.path.removeprefix("/api/v1"), method.lower())
        for r in client.app.routes
        for method in getattr(r, "methods", ())
        if r.path.startswith("/api/v1")
    }
    expected = {
        (path, method)
        for path, item in spec["paths"].items()
        for method in item
        if method in {"get", "post", "put"}
    }
    assert expected <= registered
