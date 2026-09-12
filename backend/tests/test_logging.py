import logging
import pytest

from test_api import login


@pytest.mark.parametrize("invalid_api_error", [False, True])
def test_unexpected_error_logs_only_request_id_and_exception_class(
    client, monkeypatch, caplog, invalid_api_error
):
    import wiseway.app as app_module

    login(client)
    secret = "/private/secret/path password=top-secret query=private session=token"

    def fail(*_args, **_kwargs):
        if invalid_api_error:
            from wiseway.common import ApiError

            raise ApiError("INTERNAL_ERROR", secret, 418)
        raise RuntimeError(secret)

    monkeypatch.setattr(app_module, "dispatch", fail)
    caplog.set_level(logging.ERROR, logger="wiseway")
    response = client.get("/api/v1/app-config")

    assert response.status_code == 500
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert response.headers["x-request-id"] in rendered
    assert "RuntimeError" in rendered
    assert secret not in rendered
    assert not any(record.exc_info for record in caplog.records)
