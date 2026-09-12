from __future__ import annotations

import os
import json
import subprocess
import sys

import pytest

import wiseway.indexer as indexer_module

from wiseway.indexer import Indexer
from wiseway.seed import initialize
from wiseway.services import Context
from wiseway.storage import Store, UnitOfWork


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


def test_large_rebuild_uses_bounded_checkpoint_writes(tmp_path, monkeypatch):
    """A checkpoint must stay small instead of serializing every prior item."""
    _, ctx = make_context(tmp_path)
    try:
        directory = ctx.settings.sandbox_dir / "Archive" / "Atlas" / "checkpoint-profile"
        directory.mkdir()
        for number in range(1_005):
            (directory / f"report-{number:04d}.pdf").touch()
        with ctx.store.transaction() as tx:
            root = tx.require("root", "archive-root")
            root["schema_set_version"] = "schema-checkpoint-profile"
            tx.put("root", root["root_id"], root)

        checkpoint_sizes = []
        original = Indexer._checkpoint

        def checkpoint(*args, **kwargs):
            result = original(*args, **kwargs)
            with ctx.store.transaction(write=False) as tx:
                progress = tx.require("index_progress", "archive-root")
            checkpoint_sizes.append(len(json.dumps(progress, sort_keys=True)))
            return result

        monkeypatch.setattr(Indexer, "_checkpoint", checkpoint)
        Indexer(ctx)._scan_search_root(root)

        with ctx.store.transaction(write=False) as tx:
            index = tx.require("index", "archive-root")
            progress = tx.require("index_progress", "archive-root")
        assert progress["status"] == "COMPLETE"
        assert len(index["items"]) >= 1_005
        assert checkpoint_sizes
        assert max(checkpoint_sizes) < 1_024
    finally:
        ctx.close()


def test_interrupted_rebuild_persists_linear_checkpoint_chunks_and_resumes(tmp_path, monkeypatch):
    _, ctx = make_context(tmp_path)
    try:
        directory = ctx.settings.sandbox_dir / "Archive" / "Atlas" / "chunked-checkpoint"
        directory.mkdir()
        for number in range(250):
            (directory / f"report-{number:04d}.pdf").touch()
        with ctx.store.transaction() as tx:
            root = tx.require("root", "archive-root")
            root["schema_set_version"] = "schema-chunked-checkpoint"
            tx.put("root", root["root_id"], root)

        original = indexer_module.build_item
        built = 0

        def interrupted(*args, **kwargs):
            nonlocal built
            built += 1
            if built == 201:
                raise RuntimeError("interrupt after two durable chunks")
            return original(*args, **kwargs)

        monkeypatch.setattr(indexer_module, "build_item", interrupted)
        Indexer(ctx)._scan_search_root(root)
        with ctx.store.transaction(write=False) as tx:
            progress = tx.require("index_progress", root["root_id"])
            chunks = tx.list("index_progress_chunk")
        assert progress["status"] == "FAILED"
        assert progress["count"] == 200
        assert progress["_run_id"]
        assert "_found" not in progress and "_items" not in progress
        assert [len(chunk["items"]) for chunk in chunks] == [100, 100]
        assert [len(chunk["found"]) for chunk in chunks] == [100, 100]

        resumed = 0

        def count_resume(*args, **kwargs):
            nonlocal resumed
            resumed += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(indexer_module, "build_item", count_resume)
        Indexer(ctx)._scan_search_root(root)
        with ctx.store.transaction(write=False) as tx:
            progress = tx.require("index_progress", root["root_id"])
            index = tx.require("index", root["root_id"])
            chunks = tx.list("index_progress_chunk")
        assert progress["status"] == "COMPLETE"
        assert resumed == len(index["items"]) - 200
        assert chunks == []
    finally:
        ctx.close()


def test_second_process_resumes_checkpoint_chunks_after_first_process_crashes(tmp_path):
    from wiseway.common import Settings

    settings = Settings(data_dir=tmp_path / "state", sandbox_dir=tmp_path / "sandbox")
    initialize(settings, password="test-password")
    directory = settings.sandbox_dir / "Archive" / "Atlas" / "process-checkpoint"
    directory.mkdir()
    for number in range(250):
        (directory / f"report-{number:04d}.pdf").touch()
    with Store(settings.database).transaction() as tx:
        root = tx.require("root", "archive-root")
        root["schema_set_version"] = "schema-process-checkpoint"
        tx.put("root", root["root_id"], root)

    environment = {
        **os.environ,
        "WISEWAY_DATA_DIR": str(settings.data_dir),
        "WISEWAY_SANDBOX_DIR": str(settings.sandbox_dir),
    }
    crashing_program = """
import sys
import wiseway.indexer as module
from wiseway.common import Settings
from wiseway.indexer import Indexer
from wiseway.services import Context

original = module.build_item
count = 0
def crash_after_two_chunks(*args, **kwargs):
    global count
    count += 1
    if count == 201:
        raise SystemExit(73)
    return original(*args, **kwargs)

module.build_item = crash_after_two_chunks
context = Context(Settings())
try:
    Indexer(context).scan()
finally:
    context.close()
"""
    crashed = subprocess.run(
        [sys.executable, "-c", crashing_program], env=environment, text=True, capture_output=True, timeout=20
    )
    assert crashed.returncode == 73, crashed.stderr
    with Store(settings.database).transaction(write=False) as tx:
        progress = tx.require("index_progress", "archive-root")
        chunks = tx.list("index_progress_chunk")
    assert progress["count"] == 200
    assert len(chunks) == 2

    resumed = subprocess.run(
        [sys.executable, "-m", "wiseway", "tick"], env=environment, text=True, capture_output=True, timeout=20
    )
    assert resumed.returncode == 0, resumed.stderr
    with Store(settings.database).transaction(write=False) as tx:
        progress = tx.require("index_progress", "archive-root")
        index = tx.require("index", "archive-root")
        chunks = tx.list("index_progress_chunk")
    assert progress["status"] == "COMPLETE"
    assert len(index["items"]) >= 250
    assert chunks == []


def test_checkpoint_storage_grows_linearly_when_corpus_doubles(tmp_path, monkeypatch):
    def checkpoint_bytes(name, file_count):
        _, ctx = make_context(tmp_path / name)
        try:
            directory = ctx.settings.sandbox_dir / "Archive" / "Atlas" / "linear-checkpoint"
            directory.mkdir()
            for number in range(file_count):
                (directory / f"report-{number:04d}.pdf").touch()
            with ctx.store.transaction() as tx:
                root = tx.require("root", "archive-root")
                root["schema_set_version"] = f"schema-linear-{file_count}"
                tx.put("root", root["root_id"], root)

            original = Indexer._checkpoint

            def interrupt_after_terminal_checkpoint(self, *args):
                result = original(self, *args)
                if args[7] == len(args[3]):
                    raise SystemExit(74)
                return result

            with monkeypatch.context() as patch:
                patch.setattr(Indexer, "_checkpoint", interrupt_after_terminal_checkpoint)
                with pytest.raises(SystemExit, match="74"):
                    Indexer(ctx)._scan_search_root(root)
            with ctx.store.transaction(write=False) as tx:
                chunks = tx.list("index_progress_chunk")
            return sum(len(json.dumps(chunk, sort_keys=True)) for chunk in chunks)
        finally:
            ctx.close()

    smaller = checkpoint_bytes("smaller", 200)
    larger = checkpoint_bytes("larger", 400)
    assert smaller > 0
    assert larger < smaller * 2.3


def test_partial_checkpoint_appends_after_growing_corpus_and_retries_publication(tmp_path, monkeypatch):
    _, ctx = make_context(tmp_path)
    try:
        directory = ctx.settings.sandbox_dir / "Archive" / "Atlas" / "partial-checkpoint"
        directory.mkdir()
        for number in range(120):
            (directory / f"report-{number:04d}.pdf").touch()
        with ctx.store.transaction() as tx:
            root = tx.require("root", "archive-root")

        original_put = UnitOfWork.put

        def reject_publication(self, kind, key, value):
            if kind == "index" and key == root["root_id"]:
                raise RuntimeError("publish unavailable")
            return original_put(self, kind, key, value)

        monkeypatch.setattr(UnitOfWork, "put", reject_publication)
        with pytest.raises(RuntimeError, match="publish unavailable"):
            Indexer(ctx)._scan_search_root(root)
        with ctx.store.transaction(write=False) as tx:
            first_progress = tx.require("index_progress", root["root_id"])
            first_chunks = tx.list("index_progress_chunk")
        assert first_progress["count"] == 125
        assert first_progress["_chunk_count"] == 2
        assert [chunk["sequence"] for chunk in first_chunks] == [0, 1]
        with ctx.store.transaction(write=False) as tx:
            assert (
                indexer_module._load_chunks(
                    tx, root["root_id"], first_progress["_run_id"], first_progress["count"]
                )
                is not None
            )
        retained_item_ids = {
            item["location"]["relative_path"]: item["item_id"]
            for chunk in first_chunks
            for item in chunk["items"]
        }

        growth_directory = ctx.settings.sandbox_dir / "Archive" / "zzzz-growth"
        growth_directory.mkdir()
        for number in range(75):
            (growth_directory / f"report-{number:04d}.pdf").touch()
        with pytest.raises(RuntimeError, match="publish unavailable"):
            Indexer(ctx)._scan_search_root(root)
        with ctx.store.transaction(write=False) as tx:
            second_progress = tx.require("index_progress", root["root_id"])
            second_chunks = tx.list("index_progress_chunk")
        assert second_progress["count"] == 200
        assert [chunk["sequence"] for chunk in second_chunks] == [0, 1, 2]
        assert sum(len(chunk["items"]) for chunk in second_chunks) == 200

        monkeypatch.setattr(UnitOfWork, "put", original_put)
        builds = 0
        original_build_item = indexer_module.build_item

        def count_builds(*args, **kwargs):
            nonlocal builds
            builds += 1
            return original_build_item(*args, **kwargs)

        monkeypatch.setattr(indexer_module, "build_item", count_builds)
        Indexer(ctx)._scan_search_root(root)
        with ctx.store.transaction(write=False) as tx:
            progress = tx.require("index_progress", root["root_id"])
            index = tx.require("index", root["root_id"])
        published_ids = {item["location"]["relative_path"]: item["item_id"] for item in index["items"]}
        assert builds == 0
        assert progress["status"] == "COMPLETE"
        assert all(published_ids[path] == item_id for path, item_id in retained_item_ids.items())
    finally:
        ctx.close()


def test_legacy_growing_checkpoint_is_upgraded_before_resume(tmp_path):
    _, ctx = make_context(tmp_path)
    try:
        root_id = "archive-root"
        with ctx.store.transaction() as tx:
            root = tx.require("root", root_id)
        indexer = Indexer(ctx)
        found = [
            (path, meta) for path, meta in indexer._walk(root) if not indexer_module._technical_name(path)
        ]
        path, meta = found[0]
        item = indexer_module.build_item(
            root_id,
            root["display_prefix"],
            path,
            meta["size"],
            indexer_module.utc(meta["mtime_ns"] / 1e9),
            root["_schema"],
            "legacy-item",
        )
        config = {
            "schema_set_version": root["schema_set_version"],
            "schema": root["_schema"],
            "prefixes": root.get("_scan_prefixes", [""]),
            "identity_profile": indexer_module.IDENTITY_PROFILE_VERSION,
        }
        with ctx.store.transaction() as tx:
            tx.put(
                "index_progress",
                root_id,
                {
                    "root_id": root_id,
                    "status": "FAILED",
                    "count": 1,
                    "checkpoint": path,
                    "_config_digest": indexer_module.digest(config),
                    "_found": [[path, meta]],
                    "_items": [item],
                },
            )

        staged_found, staged_items, run_id, _ = indexer._start_search_progress(
            root, indexer_module.digest(config)
        )
        with ctx.store.transaction(write=False) as tx:
            progress = tx.require("index_progress", root_id)
            chunks = tx.list("index_progress_chunk")
        assert staged_found == [(path, meta)]
        assert staged_items == [item]
        assert progress["_run_id"] == run_id
        assert "_found" not in progress and "_items" not in progress
        assert len(chunks) == 1 and chunks[0]["items"] == [item]
    finally:
        ctx.close()


def test_malformed_legacy_checkpoint_is_discarded_before_resume(tmp_path):
    _, ctx = make_context(tmp_path)
    try:
        root_id = "archive-root"
        with ctx.store.transaction() as tx:
            root = tx.require("root", root_id)
        config = {
            "schema_set_version": root["schema_set_version"],
            "schema": root["_schema"],
            "prefixes": root.get("_scan_prefixes", [""]),
            "identity_profile": indexer_module.IDENTITY_PROFILE_VERSION,
        }
        with ctx.store.transaction() as tx:
            tx.put(
                "index_progress",
                root_id,
                {
                    "root_id": root_id,
                    "status": "FAILED",
                    "count": 1,
                    "_config_digest": indexer_module.digest(config),
                    "_found": [["Archive/Atlas/broken.pdf", {"size": 0}]],
                    "_items": ["not-an-index-item"],
                },
            )

        staged_found, staged_items, _, _ = Indexer(ctx)._start_search_progress(
            root, indexer_module.digest(config)
        )
        with ctx.store.transaction(write=False) as tx:
            progress = tx.require("index_progress", root_id)
            chunks = tx.list("index_progress_chunk")
        assert staged_found == []
        assert staged_items == []
        assert progress["count"] == 0
        assert chunks == []
    finally:
        ctx.close()


def test_malformed_chunk_without_item_id_is_discarded_before_resume(tmp_path):
    _, ctx = make_context(tmp_path)
    try:
        root_id = "archive-root"
        with ctx.store.transaction() as tx:
            root = tx.require("root", root_id)
            root["schema_set_version"] = "schema-malformed-chunk"
            tx.put("root", root_id, root)
        indexer = Indexer(ctx)
        found = [
            (path, meta) for path, meta in indexer._walk(root) if not indexer_module._technical_name(path)
        ]
        path, meta = found[0]
        config = {
            "schema_set_version": root["schema_set_version"],
            "schema": root["_schema"],
            "prefixes": root.get("_scan_prefixes", [""]),
            "identity_profile": indexer_module.IDENTITY_PROFILE_VERSION,
        }
        run_id = "index-run-malformed"
        with ctx.store.transaction() as tx:
            tx.put(
                "index_progress_chunk",
                indexer_module._chunk_prefix(root_id, run_id) + "00000000",
                {
                    "root_id": root_id,
                    "run_id": run_id,
                    "sequence": 0,
                    "found": [[path, meta]],
                    "items": [{"location": {"root_id": root_id, "relative_path": path}}],
                },
            )
            tx.put(
                "index_progress",
                root_id,
                {
                    "root_id": root_id,
                    "status": "FAILED",
                    "count": 1,
                    "_config_digest": indexer_module.digest(config),
                    "_run_id": run_id,
                    "_chunk_count": 1,
                },
            )

        indexer._scan_search_root(root)
        with ctx.store.transaction(write=False) as tx:
            progress = tx.require("index_progress", root_id)
            index = tx.require("index", root_id)
            chunks = tx.list("index_progress_chunk")
        assert progress["status"] == "COMPLETE"
        assert len(index["items"]) == len(found)
        assert chunks == []
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
