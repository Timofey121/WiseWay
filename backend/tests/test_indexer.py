from __future__ import annotations

from wiseway.common import Settings
from wiseway.indexer import Indexer
from wiseway.seed import initialize
from wiseway.services import Context


def test_initialize_creates_marked_sandbox_index_and_discovered_queue(tmp_path):
    settings = Settings(data_dir=tmp_path / "state", sandbox_dir=tmp_path / "sandbox")
    initialize(settings, password="test-password")
    assert (settings.sandbox_dir / ".wiseway-sandbox.json").is_file()
    ctx = Context(settings)
    try:
        with ctx.store.transaction() as tx:
            archive = tx.require("index", "archive-root")
            assert archive["root"]["index_generation"]
            assert archive["items"]
            queue = tx.list("queue")
            assert queue and all(value["status"] == "WAITING_READY" for value in queue)
            assert all(not value["selectable"] for value in queue)
            for value in queue:
                value["_observed_at"] = settings.clock() - 6
                tx.put("queue", value["item_id"], value)
        Indexer(ctx).scan()
        with ctx.store.transaction() as tx:
            assert any(value["status"] == "READY" and value["selectable"] for value in tx.list("queue"))
    finally:
        ctx.close()


def test_scan_keeps_previous_generation_when_a_root_cannot_be_read(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "state", sandbox_dir=tmp_path / "sandbox")
    initialize(settings, password="test-password")
    ctx = Context(settings)
    try:
        with ctx.store.transaction() as tx:
            before = tx.require("index", "archive-root")["root"]["index_generation"]
        original = ctx.fs.walk
        monkeypatch.setattr(
            ctx.fs,
            "walk",
            lambda path: (
                (_ for _ in ()).throw(OSError("synthetic failure")) if path == "Archive" else original(path)
            ),
        )
        Indexer(ctx).scan()
        with ctx.store.transaction() as tx:
            after = tx.require("index", "archive-root")
            assert after["root"]["index_generation"] == before
            assert after["freshness"]["status"] == "STALE"
    finally:
        ctx.close()
