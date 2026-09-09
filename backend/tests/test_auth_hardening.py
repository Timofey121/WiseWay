import pytest

from wiseway.common import Settings


@pytest.mark.parametrize(
    "origin",
    [
        "localhost:8000",
        "ftp://localhost:8000",
        "http://localhost:8000/path",
        "http://localhost:8000?query=value",
        "http://user@localhost:8000",
        "https://",
        42,
    ],
)
def test_settings_rejects_non_origin_values(origin, tmp_path):
    with pytest.raises(ValueError):
        Settings(data_dir=tmp_path / "state", sandbox_dir=tmp_path / "sandbox", allowed_origins=(origin,))


def test_settings_accepts_loopback_http_and_secure_https(tmp_path):
    local = Settings(
        data_dir=tmp_path / "local-state",
        sandbox_dir=tmp_path / "local-sandbox",
        allowed_origins=("http://localhost:8000", "http://[::1]:5173"),
    )
    secure = Settings(
        data_dir=tmp_path / "secure-state",
        sandbox_dir=tmp_path / "secure-sandbox",
        allowed_origins=("https://wiseway.example",),
        secure_cookie=True,
    )
    assert local.secure_cookie is False
    assert secure.secure_cookie is True


def test_trusted_proxy_headers_are_explicit_and_cli_limits_them_to_loopback(monkeypatch, tmp_path):
    import sys
    from types import SimpleNamespace

    secure = Settings(
        data_dir=tmp_path / "state",
        sandbox_dir=tmp_path / "sandbox",
        allowed_origins=("https://wiseway.example",),
        secure_cookie=True,
        trusted_proxy_headers=True,
    )
    assert secure.trusted_proxy_headers is True
    calls = []
    monkeypatch.setattr("wiseway.cli.Settings", lambda: secure)
    monkeypatch.setitem(
        sys.modules, "uvicorn", SimpleNamespace(run=lambda *args, **kwargs: calls.append(kwargs))
    )
    from wiseway.cli import main

    main(["serve"])
    assert calls == [
        {
            "factory": True,
            "host": "127.0.0.1",
            "port": 8000,
            "access_log": False,
            "proxy_headers": True,
            "forwarded_allow_ips": "127.0.0.1,::1",
        }
    ]
    with pytest.raises(SystemExit):
        main(["serve", "--host", "0.0.0.0"])


def test_untrusted_forwarded_for_cannot_split_login_rate_limit(configured, monkeypatch):
    from fastapi.testclient import TestClient
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    from wiseway.app import create_app

    monkeypatch.setattr("wiseway.auth.LOGIN_ATTEMPTS_PER_IP", 10)

    app = ProxyHeadersMiddleware(create_app(configured), trusted_hosts="127.0.0.1")
    with TestClient(app, base_url="http://localhost:8000", client=("198.51.100.4", 5555)) as client:
        for index in range(10):
            response = client.post(
                "/api/v1/auth/login",
                headers={"Origin": "http://localhost:8000", "X-Forwarded-For": f"203.0.113.{index}"},
                json={"login": "unknown", "password": "wrong-password"},
            )
            assert response.status_code == 401
        response = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://localhost:8000", "X-Forwarded-For": "203.0.113.250"},
            json={"login": "worker-atlas", "password": "synthetic-test-password"},
        )
    assert response.status_code == 429


@pytest.mark.parametrize("origin", ["http://wiseway.example", "https://wiseway.example"])
def test_insecure_cookie_rejects_nonloopback_origin(origin, tmp_path):
    with pytest.raises(ValueError):
        Settings(
            data_dir=tmp_path / "state",
            sandbox_dir=tmp_path / "sandbox",
            allowed_origins=(origin,),
        )


def test_non_ascii_csrf_header_is_forbidden_not_internal_error(client):
    from test_api import login

    login(client)
    response = client.post(
        "/api/v1/auth/logout",
        headers={"Origin": "http://localhost:8000", "X-CSRF-Token": b"\xff"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_FAILED"


def test_cli_rejects_nonloopback_http_binding():
    from wiseway.cli import main

    with pytest.raises(SystemExit) as error:
        main(["serve", "--host", "0.0.0.0"])
    assert error.value.code == 2


def test_login_rate_limit_survives_failed_attempts_and_expires_at_boundary(configured):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from wiseway.app import create_app

    now = [2_000_000_000.0]
    with TestClient(
        create_app(replace(configured, clock=lambda: now[0])), base_url="http://localhost:8000"
    ) as client:
        headers = {"Origin": "http://localhost:8000"}
        for _ in range(10):
            response = client.post(
                "/api/v1/auth/login",
                headers=headers,
                json={"login": "worker-atlas", "password": "wrong-password"},
            )
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "LOGIN_FAILED"
        credentials = {"login": "worker-atlas", "password": "synthetic-test-password"}
        for elapsed in (0, 59.999):
            now[0] = 2_000_000_000.0 + elapsed
            response = client.post("/api/v1/auth/login", headers=headers, json=credentials)
            assert response.status_code == 429
            assert response.json()["error"]["code"] == "RATE_LIMITED"
            assert response.headers["retry-after"] == "60"
            assert "set-cookie" not in response.headers
        now[0] = 2_000_000_060.0
        assert client.post("/api/v1/auth/login", headers=headers, json=credentials).status_code == 200


def test_login_limit_is_scoped_to_ip_and_login_with_ip_wide_ceiling(configured):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from wiseway.app import create_app

    now = [2_000_000_000.0]
    with TestClient(
        create_app(replace(configured, clock=lambda: now[0])), base_url="http://localhost:8000"
    ) as client:
        headers = {"Origin": "http://localhost:8000"}
        for _ in range(10):
            assert (
                client.post(
                    "/api/v1/auth/login", headers=headers, json={"login": "worker-atlas", "password": "wrong"}
                ).status_code
                == 401
            )
        assert (
            client.post(
                "/api/v1/auth/login",
                headers=headers,
                json={"login": "worker-nova", "password": "synthetic-test-password"},
            ).status_code
            == 200
        )

        for index in range(89):
            assert (
                client.post(
                    "/api/v1/auth/login",
                    headers=headers,
                    json={"login": f"unknown-{index}", "password": "wrong"},
                ).status_code
                == 401
            )
        assert (
            client.post(
                "/api/v1/auth/login", headers=headers, json={"login": "new-login", "password": "wrong"}
            ).status_code
            == 429
        )


def test_every_private_operation_rejects_missing_session_before_body_validation(client):
    import re

    for path, methods in client.app.state.contract.spec["paths"].items():
        for method, operation in methods.items():
            if not isinstance(operation, dict) or "operationId" not in operation:
                continue
            if operation["operationId"] in {"getHealth", "login"}:
                continue
            response = client.request(method, "/api/v1" + re.sub(r"\{[^}]+\}", "unknown-id", path))
            assert response.status_code == 401, (operation["operationId"], response.text)
            assert response.json()["error"]["code"] == "UNAUTHENTICATED"
