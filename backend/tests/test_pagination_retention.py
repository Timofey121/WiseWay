import pytest

from wiseway.common import ApiError, Settings, digest
from wiseway.maintenance import Maintenance
from wiseway.services import Context


def make_context(tmp_path, now):
    from wiseway.seed import initialize

    settings = Settings(data_dir=tmp_path / "state", sandbox_dir=tmp_path / "sandbox", clock=lambda: now[0])
    initialize(settings, password="synthetic-test-password")
    return Context(settings)


def page(ctx, actor, payload, *, cursor=None):
    with ctx.store.transaction() as tx:
        return ctx.page(
            tx,
            "retention-test",
            actor,
            {"company_id": "company-atlas", "cursor": cursor, "limit": 2},
            payload,
            cursor=cursor,
            limit=2,
        )


def records(ctx, kind):
    with ctx.store.transaction(write=False) as tx:
        return tx.list(kind)


def test_pagination_keeps_one_snapshot_and_replay_does_not_copy_payload(tmp_path):
    now = [2_000_000_000.0]
    ctx = make_context(tmp_path, now)
    actor = {"user_id": "user-a"}
    payload = {"items": [{"value": n} for n in range(6)], "total": 6}
    try:
        first = page(ctx, actor, payload)
        second = page(ctx, actor, payload, cursor=first["next_cursor"])
        replay = page(ctx, actor, payload, cursor=first["next_cursor"])
        cursors = records(ctx, "cursor")
        snapshots = records(ctx, "page_snapshot")
        assert second == replay
        assert len(snapshots) == 1
        assert len(cursors) == 2
        assert all("payload" not in cursor for cursor in cursors)
        assert all(cursor["snapshot_id"] == snapshots[0]["snapshot_id"] for cursor in cursors)
    finally:
        ctx.close()


def test_single_page_response_does_not_consume_snapshot_quota(tmp_path):
    now = [2_000_000_000.0]
    ctx = make_context(tmp_path, now)
    actor = {"user_id": "user-a"}
    try:
        for number in range(65):
            result = page(ctx, actor, {"items": [number], "total": 1})
            assert result["next_cursor"] is None
        assert records(ctx, "page_snapshot") == []
        assert records(ctx, "cursor") == []
    finally:
        ctx.close()


def test_single_read_page_does_not_acquire_writer(configured, monkeypatch):
    ctx = Context(configured)
    try:
        with ctx.store.transaction(write=False) as tx:

            def reject_writer(*args, **kwargs):
                raise AssertionError("Single page acquired SQLite writer")

            monkeypatch.setattr(ctx.store, "transaction", reject_writer)
            assert ctx.page(tx, "read", {"user_id": "user-a"}, {}, {"items": [1]}) == {
                "items": [1],
                "next_cursor": None,
            }
    finally:
        ctx.close()


def test_old_payload_cursor_remains_usable(tmp_path):
    now = [2_000_000_000.0]
    ctx = make_context(tmp_path, now)
    actor = {"user_id": "user-a"}
    payload = {"items": [{"value": n} for n in range(4)], "total": 4}
    try:
        with ctx.store.transaction() as tx:
            tx.put(
                "cursor",
                "cursor-old",
                {
                    "scope": "retention-test",
                    "owner": actor["user_id"],
                    "query": digest({"legacy": True}),
                    "payload": payload,
                    "offset": 2,
                    "expires": now[0] + 86400,
                },
            )
        with ctx.store.transaction() as tx:
            result = ctx.page(
                tx,
                "retention-test",
                actor,
                {"legacy": True, "cursor": "cursor-old", "limit": 2},
                {"items": [], "total": 0},
                cursor="cursor-old",
                limit=2,
            )
        assert result["items"] == [{"value": 2}, {"value": 3}]
    finally:
        ctx.close()


def test_maintenance_removes_only_expired_pagination_sessions_and_login_rate(tmp_path):
    now = [2_000_000_000.0]
    ctx = make_context(tmp_path, now)
    try:
        with ctx.store.transaction() as tx:
            tx.put("cursor", "cursor-expired", {"expires": now[0] - 1})
            tx.put(
                "page_snapshot",
                "snapshot-expired",
                {"snapshot_id": "snapshot-expired", "expires": now[0] - 1},
            )
            tx.put("session", "session-expired", {"created": now[0] - 28801, "touched": now[0] - 1})
            tx.put("login_rate", "rate-expired", [now[0] - 61])
            tx.append_event({"event_id": "audit-keep"})
            tx.put("idempotency", "idempotency-keep", {"result": {}})
            tx.put("batch", "batch-keep", {"batch_id": "batch-keep"})
        assert Maintenance(ctx).run_once() == {
            "cursor": 1,
            "page_snapshot": 1,
            "session": 1,
            "login_rate": 1,
        }
        with ctx.store.transaction(write=False) as tx:
            assert tx.events() == [{"event_id": "audit-keep"}]
            assert tx.get("idempotency", "idempotency-keep") == {"result": {}}
            assert tx.get("batch", "batch-keep") == {"batch_id": "batch-keep"}
    finally:
        ctx.close()


def test_snapshot_expiry_is_fixed_and_owner_binding_remains(tmp_path):
    now = [2_000_000_000.0]
    ctx = make_context(tmp_path, now)
    owner, other = {"user_id": "user-a"}, {"user_id": "user-b"}
    payload = {"items": list(range(6)), "total": 6}
    try:
        first = page(ctx, owner, payload)
        with pytest.raises(ApiError) as denied:
            page(ctx, other, payload, cursor=first["next_cursor"])
        assert denied.value.code == "VALIDATION_ERROR"
        now[0] += 86399
        page(ctx, owner, payload, cursor=first["next_cursor"])
        now[0] += 2
        with pytest.raises(ApiError) as expired:
            page(ctx, owner, payload, cursor=first["next_cursor"])
        assert expired.value.code == "VALIDATION_ERROR"
    finally:
        ctx.close()


def test_snapshot_cap_rejects_without_erasing_audit(tmp_path):
    now = [2_000_000_000.0]
    ctx = make_context(tmp_path, now)
    actor = {"user_id": "user-a"}
    try:
        with ctx.store.transaction() as tx:
            tx.append_event({"event_id": "audit-keep"})
        for number in range(64):
            page(ctx, actor, {"items": [number, number + 1, number + 2]})
        with pytest.raises(ApiError) as limited:
            page(ctx, actor, {"items": ["one", "two", "three"]})
        assert limited.value.code == "RATE_LIMITED"
        with ctx.store.transaction(write=False) as tx:
            assert tx.events() == [{"event_id": "audit-keep"}]
        assert len(records(ctx, "page_snapshot")) == 64
    finally:
        ctx.close()


def test_snapshot_quota_uses_metadata_without_materializing_snapshot_payloads(tmp_path):
    now = [2_000_000_000.0]
    ctx = make_context(tmp_path, now)
    actor = {"user_id": "user-a"}
    try:
        with ctx.store.transaction() as tx:
            for number in range(64):
                tx.put(
                    "page_snapshot",
                    f"snapshot-{number}",
                    {
                        "snapshot_id": f"snapshot-{number}",
                        "owner": actor["user_id"],
                        "payload_bytes": 1,
                        "expires": now[0] + 86400,
                        "payload": {"items": ["x" * 100000]},
                    },
                )
        with ctx.store.transaction() as tx:
            original_list = tx.list

            def reject_snapshot_materialization(kind):
                if kind == "page_snapshot":
                    raise AssertionError("snapshot payload was materialized")
                return original_list(kind)

            tx.list = reject_snapshot_materialization
            with pytest.raises(ApiError) as limited:
                ctx.page(
                    tx,
                    "retention-test",
                    actor,
                    {"company_id": "company-atlas", "cursor": None, "limit": 2},
                    {"items": [1, 2, 3]},
                    limit=2,
                )
        assert limited.value.code == "RATE_LIMITED"
    finally:
        ctx.close()
