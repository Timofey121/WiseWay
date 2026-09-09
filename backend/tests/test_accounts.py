import pytest

from wiseway.auth import Auth
from wiseway.common import ApiError


def test_account_administration_requires_active_admin_and_preserves_auth_boundaries(configured):
    from wiseway.accounts import AccountService
    from wiseway.services import Context

    ctx = Context(configured)
    try:
        accounts = AccountService(ctx)
        with pytest.raises(ApiError):
            accounts.create_user("worker-atlas", "new-user", "New User", "WORKER", "valid-password-123")
        created = accounts.create_user("admin", "new-user", "New User", "WORKER", "valid-password-123")
        assert created == {
            "user_id": created["user_id"],
            "login": "new-user",
            "display_name": "New User",
            "role": "WORKER",
        }
        with pytest.raises(ApiError):
            accounts.create_user("admin", "NEW-USER", "Duplicate", "WORKER", "valid-password-123")
        with pytest.raises(ApiError):
            accounts.create_user("admin", "bad login", "Bad", "WORKER", "valid-password-123")
        with pytest.raises(ApiError):
            accounts.create_user("admin", "short-unicode", "Short", "WORKER", "пароль")
        accounts.create_user("admin", "unicode-boundary", "Boundary", "WORKER", "абвгдеёжзийкл")

        auth = Auth(ctx.store, configured)
        _, token = auth.login({"login": "new-user", "password": "valid-password-123"}, "login", "loopback")
        accounts.reset_password("admin", "new-user", "new-password-456")
        with pytest.raises(ApiError):
            auth.authenticate(token)
        _, refreshed = auth.login(
            {"login": "new-user", "password": "new-password-456"}, "login-2", "loopback"
        )
        accounts.block_user("admin", "new-user")
        with pytest.raises(ApiError):
            auth.authenticate(refreshed)
        accounts.unblock_user("admin", "new-user")
        with pytest.raises(ApiError):
            auth.authenticate(refreshed)
        _, final = auth.login({"login": "new-user", "password": "new-password-456"}, "login-3", "loopback")
        assert auth.authenticate(final)[1]["login"] == "new-user"
        with ctx.store.transaction(write=False) as tx:
            assert {event["action"] for event in tx.events()} >= {
                "ACCOUNT_CREATED",
                "PASSWORD_CHANGED",
                "ACCOUNT_BLOCKED",
                "ACCOUNT_UNBLOCKED",
            }
    finally:
        ctx.close()


def test_cannot_block_last_active_administrator(configured):
    from wiseway.accounts import AccountService
    from wiseway.services import Context

    ctx = Context(configured)
    try:
        with pytest.raises(ApiError):
            AccountService(ctx).block_user("admin", "admin")
    finally:
        ctx.close()
