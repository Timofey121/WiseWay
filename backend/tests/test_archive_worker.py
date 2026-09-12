"""The file worker must not rebuild a large archive as a JSON blob."""

from threading import Event

from wiseway import cli
from wiseway.indexer import Indexer
from wiseway.large_indexer import LargeIndexer
from wiseway.services import Context


def test_regular_worker_preserves_persistent_archive(configured):
    ctx = Context(configured)
    try:
        with ctx.store.transaction(write=False) as tx:
            root = tx.require("root", "archive-root")
        LargeIndexer(ctx).scan(root)
        with ctx.store.transaction(write=False) as tx:
            before = tx.require("index", "archive-root")
        Indexer(ctx).scan()
        with ctx.store.transaction(write=False) as tx:
            after = tx.require("index", "archive-root")
        assert after == before
        assert after["_storage"] == "sqlite"
    finally:
        ctx.close()


def test_archive_cli_builds_persistent_roots_and_returns_success(configured, monkeypatch):
    monkeypatch.setattr(cli, "Settings", lambda: configured)
    cli.main(["index-archive"])
    ctx = Context(configured)
    try:
        with ctx.store.transaction(write=False) as tx:
            root = tx.require("root", "archive-root")
            index = tx.require("index", "archive-root")
            count = tx.connection.execute(
                "SELECT COUNT(*) FROM search_items WHERE generation_id=?", (index["_generation"],)
            ).fetchone()[0]
        assert root["_index_storage"] == "sqlite"
        assert index["_storage"] == "sqlite"
        assert count == 5
    finally:
        ctx.close()


def test_doctor_detects_stopped_archive_indexer(configured, monkeypatch):
    from dataclasses import replace
    from wiseway.archive_worker import run
    from wiseway.operations import doctor, record_worker_heartbeat

    now = [configured.clock()]
    settings = replace(configured, clock=lambda: now[0])
    ctx = Context(settings)
    try:
        run(ctx)
        record_worker_heartbeat(ctx)
        assert doctor(ctx)["ready"] is True
        now[0] += settings.worker_stale_seconds + 1
        record_worker_heartbeat(ctx)
        result = doctor(ctx)
        assert result["ready"] is False
        assert "archive_indexer_heartbeat_stale" in result["reasons"]
    finally:
        ctx.close()


def test_stop_before_archive_cycle_does_not_write_success_heartbeat(configured):
    from wiseway.archive_worker import run

    stop = Event()
    stop.set()
    ctx = Context(configured)
    try:
        assert run(ctx, stop=stop) is True
        with ctx.store.transaction(write=False) as tx:
            assert tx.get("operator_state", "archive_indexer") is None
    finally:
        ctx.close()
