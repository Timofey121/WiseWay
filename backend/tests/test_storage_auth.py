import sqlite3
import pytest

from wiseway.auth import Auth, HASHER
from wiseway.common import ApiError, Settings
from wiseway.contract import Contract
from wiseway.storage import Store


@pytest.fixture
def account(tmp_path):
    now = [2_000_000_000.0]
    settings = Settings(data_dir=tmp_path / "state", sandbox_dir=tmp_path / "sandbox", clock=lambda: now[0])
    store = Store(settings.database)
    actor = {"user_id": "user-one", "login": "worker", "display_name": "Worker", "role": "WORKER"}
    with store.transaction() as tx:
        tx.put(
            "user",
            "user-one",
            {"actor": actor, "password_hash": HASHER.hash("test-only-password"), "blocked": False},
        )
    return settings, store, Auth(store, settings), now


def test_transaction_rollback_and_append_only_audit(account):
    settings, store, auth, now = account
    with pytest.raises(RuntimeError):
        with store.transaction() as tx:
            tx.put("example", "x", {"value": 1})
            raise RuntimeError("abort")
    with store.transaction() as tx:
        assert tx.get("example", "x") is None
    auth.login({"login": "worker", "password": "test-only-password"}, "request-1", "loopback")
    with store.transaction() as tx:
        assert len(tx.events()) == 1
        with pytest.raises(sqlite3.IntegrityError, match="append only"):
            tx.connection.execute("DELETE FROM audit")
    assert Store(settings.database).path == store.path


def test_idle_absolute_expiry_block_and_restart(account):
    settings, store, auth, now = account
    dto, token = auth.login({"login": "worker", "password": "test-only-password"}, "request-1", "loopback")
    now[0] += 1700
    auth.touch(token)
    # Authentication survives constructing another service/connection.
    assert Auth(Store(settings.database), settings).authenticate(token)[1] == dto["actor"]
    now[0] += 1800
    with pytest.raises(ApiError) as expired:
        auth.authenticate(token)
    assert expired.value.code == "UNAUTHENTICATED"
    dto, token = auth.login({"login": "worker", "password": "test-only-password"}, "request-2", "loopback")
    with store.transaction() as tx:
        user = tx.require("user", "user-one")
        user["blocked"] = True
        tx.put("user", "user-one", user)
    with pytest.raises(ApiError):
        auth.authenticate(token)


def test_failed_login_audit_is_schema_valid_without_credentials(account):
    settings, store, auth, now = account
    with pytest.raises(ApiError) as failed:
        auth.login({"login": "missing", "password": "private-input"}, "request-1", "loopback")
    assert failed.value.code == "LOGIN_FAILED"
    with store.transaction() as tx:
        event = tx.events()[0]
    contract = Contract()
    assert contract.validator(contract.spec["components"]["schemas"]["AuditEvent"]).is_valid(event)
    assert "private-input" not in str(event)
    assert "missing" not in str(event)
