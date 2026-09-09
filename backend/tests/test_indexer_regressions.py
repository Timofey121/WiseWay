from __future__ import annotations

import os
import json

import wiseway.indexer as indexer_module

from wiseway.indexer import Indexer
from wiseway.seed import initialize
from wiseway.services import Context
from wiseway.storage import Store


def make_context(tmp_path):
    from wiseway.common import Settings

    settings = Settings(data_dir=tmp_path / "state", sandbox_dir=tmp_path / "sandbox")
    initialize(settings, password="test-password")
    return settings, Context(settings)


def ready(ctx):
    with ctx.store.transaction() as tx:
        item = tx.list("queue")[0]
        item["_observed_at"] = ctx.settings.clock() - ctx.settings.readiness_seconds - 1
        tx.put("queue", item["item_id"], item)
    Indexer(ctx).scan()
    with ctx.store.transaction() as tx:
        return tx.list("queue")[0]


def test_rename_with_same_inode_resets_ready_item_and_increments_revision(tmp_path):
    _, ctx = make_context(tmp_path)
    try:
        before = ready(ctx)
        old = ctx.settings.sandbox_dir / "Incoming/Atlas/invoice-1001.pdf"
        renamed = old.with_name("invoice-renamed.pdf")
        os.rename(old, renamed)

        Indexer(ctx).scan()
        with ctx.store.transaction() as tx:
            after = tx.require("queue", before["item_id"])
        assert after["item_revision"] == before["item_revision"] + 1
        assert after["source"]["relative_path"].endswith("invoice-renamed.pdf")
        assert after["status"] == "WAITING_READY"
        assert not after["selectable"]
    finally:
        ctx.close()


def test_missing_item_reappearing_becomes_waiting_ready_with_new_revision(tmp_path):
    _, ctx = make_context(tmp_path)
    try:
        before = ready(ctx)
        source = ctx.settings.sandbox_dir / "Incoming/Atlas/invoice-1001.pdf"
        source.unlink()
        Indexer(ctx).scan()
        source.write_bytes(b"replacement")
        Indexer(ctx).scan()
        with ctx.store.transaction() as tx:
            after = tx.require("queue", before["item_id"])
        assert after["status"] == "WAITING_READY"
        assert after["item_revision"] == before["item_revision"] + 2
    finally:
        ctx.close()


def test_scanner_does_not_change_claimed_item_when_source_disappears(tmp_path):
    _, ctx = make_context(tmp_path)
    try:
        item = ready(ctx)
        with ctx.store.transaction() as tx:
            claimed = tx.require("queue", item["item_id"])
            claimed.update(status="PROCESSING", selectable=False, active_attempt_id="attempt-1")
            tx.put("queue", claimed["item_id"], claimed)
        (ctx.settings.sandbox_dir / "Incoming/Atlas/invoice-1001.pdf").unlink()

        Indexer(ctx).scan()
        with ctx.store.transaction() as tx:
            after = tx.require("queue", item["item_id"])
        assert after["status"] == "PROCESSING"
        assert after["active_attempt_id"] == "attempt-1"
    finally:
        ctx.close()


def test_departed_record_stays_hidden_until_an_external_reappearance_is_observed(tmp_path):
    _, ctx = make_context(tmp_path)
    try:
        item = ready(ctx)
        with ctx.store.transaction() as tx:
            departed = tx.require("queue", item["item_id"])
            departed.update(status="MISSING", reason_code="SOURCE_MISSING", selectable=False, _departed=True)
            tx.put("queue", departed["item_id"], departed)

        Indexer(ctx).scan()
        with ctx.store.transaction() as tx:
            after = tx.require("queue", item["item_id"])
        assert after["status"] == "WAITING_READY"
        assert after["_departed"] is False
        assert after["item_revision"] == item["item_revision"] + 1
    finally:
        ctx.close()


def test_temporary_incoming_files_never_become_ready_and_technical_search_files_are_excluded(tmp_path):
    _, ctx = make_context(tmp_path)
    try:
        temporary = ctx.settings.sandbox_dir / "Incoming/Atlas/unfinished.part"
        temporary.write_bytes(b"partial")
        technical = ctx.settings.sandbox_dir / "Archive/Atlas/Orion_2031/Reports/.DS_Store"
        technical.write_bytes(b"metadata")
        Indexer(ctx).scan()
        with ctx.store.transaction() as tx:
            for item in tx.list("queue"):
                item["_observed_at"] = ctx.settings.clock() - ctx.settings.readiness_seconds - 1
                tx.put("queue", item["item_id"], item)
        Indexer(ctx).scan()
        with ctx.store.transaction() as tx:
            incoming = next(item for item in tx.list("queue") if item["filename"] == "unfinished.part")
            archive = tx.require("index", "archive-root")
        assert incoming["status"] == "WAITING_READY"
        assert all(item["filename"] != ".DS_Store" for item in archive["items"])
    finally:
        ctx.close()


def test_successful_unchanged_scan_recovers_current_freshness_and_schema_change_rebuilds(
    tmp_path, monkeypatch
):
    _, ctx = make_context(tmp_path)
    try:
        with ctx.store.transaction() as tx:
            original = tx.require("index", "archive-root")
            generation = original["root"]["index_generation"]
        walk = ctx.fs.walk
        monkeypatch.setattr(
            ctx.fs, "walk", lambda path: (_ for _ in ()).throw(OSError()) if path == "Archive" else walk(path)
        )
        Indexer(ctx).scan()
        monkeypatch.setattr(ctx.fs, "walk", walk)
        Indexer(ctx).scan()
        with ctx.store.transaction() as tx:
            recovered = tx.require("index", "archive-root")
            root = tx.require("root", "archive-root")
            root["schema_set_version"] = "schema-demo-2"
            tx.put("root", root["root_id"], root)
        assert recovered["freshness"]["status"] == "CURRENT"
        assert recovered["root"]["index_generation"] == generation
        Indexer(ctx).scan()
        with ctx.store.transaction() as tx:
            rebuilt = tx.require("index", "archive-root")
        assert rebuilt["root"]["index_generation"] != generation
    finally:
        ctx.close()


def test_interrupted_initial_rebuild_reuses_verified_checkpoint_without_publishing_partial_generation(
    tmp_path, monkeypatch
):
    _, ctx = make_context(tmp_path)
    try:
        monkeypatch.setattr(indexer_module, "CHECKPOINT_INTERVAL", 1)
        with ctx.store.transaction() as tx:
            root = tx.require("root", "archive-root")
            root["schema_set_version"] = "schema-demo-resume"
            tx.put("root", root["root_id"], root)
            old_generation = tx.require("index", root["root_id"])["root"]["index_generation"]

        original = indexer_module.build_item
        attempts = 0

        def interrupted(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                raise RuntimeError("interrupted after checkpoint")
            return original(*args, **kwargs)

        monkeypatch.setattr(indexer_module, "build_item", interrupted)
        Indexer(ctx)._scan_search_root(root)
        with ctx.store.transaction() as tx:
            progress = tx.require("index_progress", root["root_id"])
            published = tx.require("index", root["root_id"])
        assert progress["status"] == "FAILED"
        assert progress["count"] == 1
        assert progress["checkpoint"]
        assert published["root"]["index_generation"] == old_generation

        resumed = 0

        def count_resume(*args, **kwargs):
            nonlocal resumed
            resumed += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(indexer_module, "build_item", count_resume)
        Indexer(ctx)._scan_search_root(root)
        with ctx.store.transaction() as tx:
            progress = tx.require("index_progress", root["root_id"])
            published = tx.require("index", root["root_id"])
        assert resumed == len(published["items"]) - 1
        assert progress["status"] == "COMPLETE"
        assert published["root"]["index_generation"] != old_generation
    finally:
        ctx.close()


def test_repeat_seed_does_not_restore_moved_incoming_file_or_unblock_user(tmp_path):
    from wiseway.common import Settings

    settings = Settings(data_dir=tmp_path / "state", sandbox_dir=tmp_path / "sandbox")
    initialize(settings, password="initial-password")
    source = settings.sandbox_dir / "Incoming/Atlas/invoice-1001.pdf"
    moved = settings.sandbox_dir / "Archive/Atlas/Orion_2031/Reports/invoice-1001.pdf"
    os.rename(source, moved)
    store = Context(settings).store
    with store.transaction() as tx:
        user = tx.require("user", "user-admin")
        user["blocked"] = True
        tx.put("user", "user-admin", user)

    initialize(settings, password="different-password")
    with store.transaction() as tx:
        user = tx.require("user", "user-admin")
    assert not source.exists()
    assert moved.exists()
    assert user["blocked"] is True


def test_incomplete_marker_with_only_migrated_database_resumes_full_bootstrap(tmp_path):
    from wiseway.common import Settings

    settings = Settings(data_dir=tmp_path / "state", sandbox_dir=tmp_path / "sandbox")
    settings.sandbox_dir.mkdir()
    (settings.sandbox_dir / ".wiseway-sandbox.json").write_text(
        json.dumps({"product": "Wise Way", "synthetic": True, "bootstrap_complete": False})
    )
    Store(settings.database)

    initialize(settings, password="test-password")

    ctx = Context(settings)
    try:
        with ctx.store.transaction() as tx:
            assert tx.require("bootstrap", "seed-v1")["complete"] is True
            assert tx.require("user", "user-admin")["blocked"] is False
            assert tx.require("index", "archive-root")["items"]
    finally:
        ctx.close()
