from __future__ import annotations

import os
from contextlib import contextmanager
from threading import Event

import wiseway.sqlite_search as sqlite_search

from wiseway.large_indexer import LargeIndexer
from wiseway.services import Context


def _root(ctx):
    with ctx.store.transaction(write=False) as tx:
        return tx.require("root", "archive-root")


def _large_index(ctx):
    with ctx.store.transaction(write=False) as tx:
        return tx.require("index", "archive-root")


def _entry_ids(ctx, run_id):
    with ctx.store.transaction(write=False) as tx:
        return dict(
            tx.connection.execute(
                "SELECT path,item_id FROM large_scan_entries WHERE run_id=? ORDER BY path", (run_id,)
            )
        )


def test_large_indexer_stages_in_batches_and_publishes_one_sqlite_generation(configured):
    ctx = Context(configured)
    try:
        directory = configured.sandbox_dir / "Archive/Atlas/Orion_2031/Reports/large"
        directory.mkdir()
        for number in range(1_001):
            (directory / f"file-{number:04d}.txt").write_text("x")

        LargeIndexer(ctx).scan(_root(ctx))

        index = _large_index(ctx)
        assert index["_storage"] == "sqlite"
        assert index["items"] == []
        with ctx.store.transaction(write=False) as tx:
            run = tx.connection.execute(
                "SELECT state,entry_count FROM large_scan_runs WHERE run_id=?", (index["_scan_run_id"],)
            ).fetchone()
            generation = tx.connection.execute(
                "SELECT state FROM search_generations WHERE generation_id=?", (index["_generation"],)
            ).fetchone()
            count = tx.connection.execute(
                "SELECT COUNT(*) FROM search_items WHERE generation_id=?", (index["_generation"],)
            ).fetchone()[0]
        assert run == ("PUBLISHED", 1_006)
        assert generation == ("ACTIVE",)
        assert count == 1_006
    finally:
        ctx.close()


def test_large_indexer_keeps_entry_id_for_unambiguous_rename(configured):
    ctx = Context(configured)
    try:
        LargeIndexer(ctx).scan(_root(ctx))
        before = _large_index(ctx)
        before_ids = _entry_ids(ctx, before["_scan_run_id"])
        old_path = "Archive/Atlas/Orion_2031/Reports/Atlas-Main.pdf"
        source = configured.sandbox_dir / old_path
        new_path = old_path.replace("Atlas-Main.pdf", "renamed-report-2031.pdf")
        os.rename(source, configured.sandbox_dir / new_path)
        assert not source.exists()

        LargeIndexer(ctx).scan(_root(ctx))

        after = _large_index(ctx)
        after_ids = _entry_ids(ctx, after["_scan_run_id"])
        assert after_ids[new_path] == before_ids[old_path]
    finally:
        ctx.close()


def test_large_indexer_gives_hardlinked_entries_separate_ids(configured):
    ctx = Context(configured)
    try:
        directory = configured.sandbox_dir / "Archive/Atlas/Orion_2031/Reports/links"
        directory.mkdir()
        first = directory / "first.txt"
        first.write_text("x")
        os.link(first, directory / "second.txt")

        LargeIndexer(ctx).scan(_root(ctx))

        index = _large_index(ctx)
        entries = _entry_ids(ctx, index["_scan_run_id"])
        assert (
            entries["Archive/Atlas/Orion_2031/Reports/links/first.txt"]
            != entries["Archive/Atlas/Orion_2031/Reports/links/second.txt"]
        )
    finally:
        ctx.close()


def test_unchanged_large_scan_reuses_published_generation(configured):
    ctx = Context(configured)
    try:
        LargeIndexer(ctx).scan(_root(ctx))
        before = _large_index(ctx)

        LargeIndexer(ctx).scan(_root(ctx))

        after = _large_index(ctx)
        assert after["_generation"] == before["_generation"]
        assert after["freshness"]["status"] == "CURRENT"
        with ctx.store.transaction(write=False) as tx:
            assert (
                tx.connection.execute(
                    "SELECT COUNT(*) FROM large_scan_runs WHERE root_id=?", ("archive-root",)
                ).fetchone()[0]
                == 1
            )
    finally:
        ctx.close()


def test_failed_staging_keeps_the_prior_published_generation(configured):
    ctx = Context(configured)
    try:
        root = _root(ctx)
        LargeIndexer(ctx).scan(root)
        before = _large_index(ctx)

        # Two real overlapping scan prefixes make the staging primary key
        # reject a duplicate path.  This exercises the failure boundary
        # without stubbing filesystem or database operations.
        failed_root = {**root, "_scan_prefixes": ["Archive", "Archive"]}
        LargeIndexer(ctx).scan(failed_root)

        after = _large_index(ctx)
        assert after["_generation"] == before["_generation"]
        assert after["freshness"]["status"] == "STALE"
        with ctx.store.transaction(write=False) as tx:
            assert tx.connection.execute(
                "SELECT state FROM search_generations WHERE generation_id=?", (before["_generation"],)
            ).fetchone() == ("ACTIVE",)
            assert (
                tx.connection.execute(
                    "SELECT COUNT(*) FROM large_scan_runs WHERE root_id=? AND state='FAILED'",
                    ("archive-root",),
                ).fetchone()[0]
                == 1
            )
    finally:
        ctx.close()


def test_partial_build_failure_is_cleaned_before_retry(configured, monkeypatch):
    ctx = Context(configured)
    try:
        root = _root(ctx)
        directory = configured.sandbox_dir / "Archive/Atlas/Orion_2031/Reports/retry"
        directory.mkdir()
        for number in range(501):
            (directory / f"file-{number:04d}.txt").write_text("x")
        original = sqlite_search.add_items
        calls = 0

        def fail_after_first_batch(tx, generation, items):
            nonlocal calls
            calls += 1
            original(tx, generation, items)
            if calls == 2:
                raise OSError("injected interrupted build")

        monkeypatch.setattr(sqlite_search, "add_items", fail_after_first_batch)
        LargeIndexer(ctx).scan(root)
        with ctx.store.transaction(write=False) as tx:
            failed_run = tx.connection.execute(
                "SELECT run_id,generation FROM large_scan_runs WHERE root_id=? AND state='FAILED'",
                ("archive-root",),
            ).fetchone()
            assert failed_run is not None
            assert (
                tx.connection.execute(
                    "SELECT COUNT(*) FROM search_items WHERE generation_id=?", (failed_run[1],)
                ).fetchone()[0]
                > 0
            )

        monkeypatch.setattr(sqlite_search, "add_items", original)
        LargeIndexer(ctx).scan(root)
        index = _large_index(ctx)
        with ctx.store.transaction(write=False) as tx:
            assert (
                tx.connection.execute(
                    "SELECT COUNT(*) FROM large_scan_runs WHERE root_id=? AND state='FAILED'",
                    ("archive-root",),
                ).fetchone()[0]
                == 0
            )
            assert (
                tx.connection.execute(
                    "SELECT COUNT(*) FROM search_generations WHERE root_id=?", ("archive-root",)
                ).fetchone()[0]
                == 1
            )
        assert index["_storage"] == "sqlite"
    finally:
        ctx.close()


def test_old_reader_snapshot_remains_complete_during_publish_and_cleanup(configured):
    ctx = Context(configured)
    try:
        LargeIndexer(ctx).scan(_root(ctx))
        before = _large_index(ctx)
        with ctx.store.transaction(write=False) as reader:
            old_count = reader.connection.execute(
                "SELECT COUNT(*) FROM search_items WHERE generation_id=?", (before["_generation"],)
            ).fetchone()[0]
            path = configured.sandbox_dir / "Archive/Atlas/Orion_2031/Reports/new-during-reader.txt"
            path.write_text("x")
            LargeIndexer(ctx).scan(_root(ctx))
            assert (
                reader.connection.execute(
                    "SELECT COUNT(*) FROM search_items WHERE generation_id=?", (before["_generation"],)
                ).fetchone()[0]
                == old_count
            )
        assert _large_index(ctx)["_generation"] != before["_generation"]
    finally:
        ctx.close()


def test_config_change_during_build_does_not_publish_observed_generation(configured, monkeypatch):
    ctx = Context(configured)
    try:
        LargeIndexer(ctx).scan(_root(ctx))
        before = _large_index(ctx)
        (configured.sandbox_dir / "Archive/Atlas/Orion_2031/Reports/config-change.txt").write_text("x")
        original = sqlite_search.add_items
        changed = False

        def change_root_after_add(tx, generation, items):
            nonlocal changed
            result = original(tx, generation, items)
            if not changed:
                changed = True
                root = tx.require("root", "archive-root")
                root["schema_set_version"] = "schema-changed-during-build"
                tx.put("root", "archive-root", root)
            return result

        monkeypatch.setattr(sqlite_search, "add_items", change_root_after_add)
        LargeIndexer(ctx).scan(_root(ctx))

        after = _large_index(ctx)
        assert after["_generation"] == before["_generation"]
        assert after["freshness"]["status"] == "STALE"
        with ctx.store.transaction(write=False) as tx:
            assert tx.connection.execute(
                "SELECT state FROM search_generations WHERE generation_id=?", (before["_generation"],)
            ).fetchone() == ("ACTIVE",)
            assert (
                tx.connection.execute(
                    "SELECT COUNT(*) FROM large_scan_runs WHERE root_id=? AND state='FAILED'",
                    ("archive-root",),
                ).fetchone()[0]
                == 1
            )
    finally:
        ctx.close()


def test_display_prefix_change_rebuilds_public_root_and_item_paths(configured):
    ctx = Context(configured)
    try:
        LargeIndexer(ctx).scan(_root(ctx))
        before = _large_index(ctx)
        with ctx.store.transaction() as tx:
            root = tx.require("root", "archive-root")
            root["display_prefix"] = "NEW:/Archive"
            root["label"] = "Archive v2"
            tx.put("root", "archive-root", root)

        LargeIndexer(ctx).scan(_root(ctx))

        after = _large_index(ctx)
        assert after["_generation"] != before["_generation"]
        assert after["root"]["display_prefix"] == "NEW:/Archive"
        assert after["root"]["label"] == "Archive v2"
        with ctx.store.transaction(write=False) as tx:
            item = tx.connection.execute(
                "SELECT json_extract(body, '$.location.display_path') FROM search_items "
                "WHERE generation_id=? ORDER BY item_no LIMIT 1",
                (after["_generation"],),
            ).fetchone()[0]
        assert item.startswith("NEW:/Archive/")
    finally:
        ctx.close()


def test_stale_unchanged_run_cannot_refresh_after_config_change(configured):
    ctx = Context(configured)
    try:
        root = _root(ctx)
        LargeIndexer(ctx).scan(root)
        before = _large_index(ctx)
        with ctx.store.transaction() as tx:
            current = tx.require("root", "archive-root")
            current["display_prefix"] = "NEW:/Changed"
            tx.put("root", "archive-root", current)

        # The stale root object produces the old fingerprint, but final
        # ownership/configuration validation still rejects its refresh.
        LargeIndexer(ctx).scan(root)

        after = _large_index(ctx)
        assert after["_generation"] == before["_generation"]
        assert after["freshness"]["status"] == "STALE"
    finally:
        ctx.close()


def test_stop_during_streaming_stage_leaves_no_published_generation(configured, monkeypatch):
    ctx = Context(configured)
    try:
        stop = Event()
        original = ctx.fs.iter_files

        def stop_after_first_row(*args, **kwargs):
            for row in original(*args, **kwargs):
                yield row
                stop.set()

        monkeypatch.setattr(ctx.fs, "iter_files", stop_after_first_row)
        assert LargeIndexer(ctx).scan(_root(ctx), stop=stop) is False
        with ctx.store.transaction(write=False) as tx:
            progress = tx.require("index_progress", "archive-root")
            assert progress["status"] == "STOPPED"
            assert (
                tx.connection.execute(
                    "SELECT COUNT(*) FROM search_generations WHERE root_id=?", ("archive-root",)
                ).fetchone()[0]
                == 0
            )
    finally:
        ctx.close()


def test_stop_during_build_never_publishes_partial_generation(configured, monkeypatch):
    ctx = Context(configured)
    try:
        directory = configured.sandbox_dir / "Archive/Atlas/Orion_2031/Reports/stop"
        directory.mkdir()
        for number in range(501):
            (directory / f"file-{number:04d}.txt").write_text("x")
        stop = Event()
        original = sqlite_search.add_items

        def stop_after_first_add(tx, generation, items):
            result = original(tx, generation, items)
            stop.set()
            return result

        monkeypatch.setattr(sqlite_search, "add_items", stop_after_first_add)
        assert LargeIndexer(ctx).scan(_root(ctx), stop=stop) is False
        with ctx.store.transaction(write=False) as tx:
            progress = tx.require("index_progress", "archive-root")
            assert progress["status"] == "STOPPED"
            assert (
                tx.connection.execute(
                    "SELECT COUNT(*) FROM objects WHERE kind='index' AND id='archive-root'"
                ).fetchone()[0]
                == 1
            )
            assert tx.connection.execute(
                "SELECT state FROM search_generations WHERE root_id=?", ("archive-root",)
            ).fetchone() == ("BUILDING",)
    finally:
        ctx.close()


def test_mass_id_reconciliation_batches_writes_and_keeps_rename_identity(configured, monkeypatch):
    ctx = Context(configured)
    try:
        directory = configured.sandbox_dir / "Archive/Atlas/Orion_2031/Reports/mass-ids"
        directory.mkdir()
        for number in range(1_001):
            (directory / f"file-{number:04d}.txt").write_text("x")
        LargeIndexer(ctx).scan(_root(ctx))
        before = _large_index(ctx)
        before_ids = _entry_ids(ctx, before["_scan_run_id"])
        old_path = "Archive/Atlas/Orion_2031/Reports/mass-ids/file-0000.txt"
        new_path = old_path.replace("file-0000.txt", "renamed.txt")
        os.rename(configured.sandbox_dir / old_path, configured.sandbox_dir / new_path)

        original = ctx.store.transaction
        reconcile_statements: list[int] = []
        probed = False

        @contextmanager
        def observed_transaction(write=True):
            nonlocal probed
            statements: list[str] = []
            with original(write) as tx:
                tx.connection.set_trace_callback(statements.append)
                yield tx
            current_updates = sum(
                statement.startswith("UPDATE large_scan_entries AS current") for statement in statements
            )
            if current_updates:
                reconcile_statements.append(current_updates)
                if not probed:
                    probe = ctx.store.connect()
                    try:
                        probe.execute("BEGIN IMMEDIATE")
                        probe.rollback()
                    finally:
                        probe.close()
                    probed = True

        monkeypatch.setattr(ctx.store, "transaction", observed_transaction)
        LargeIndexer(ctx).scan(_root(ctx))

        after = _large_index(ctx)
        after_ids = _entry_ids(ctx, after["_scan_run_id"])
        assert probed is True
        assert len(reconcile_statements) >= 2
        assert all(count <= 2_000 for count in reconcile_statements)
        assert after_ids[new_path] == before_ids[old_path]
        assert (
            after_ids["Archive/Atlas/Orion_2031/Reports/mass-ids/file-1000.txt"]
            == before_ids["Archive/Atlas/Orion_2031/Reports/mass-ids/file-1000.txt"]
        )
    finally:
        ctx.close()
