"""Operational fault checks using real SQLite databases and isolated files."""

import errno
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from wiseway import operations
from wiseway.operations import OperationError, backup_database, verify_restore


@pytest.mark.parametrize("invalid", ["[]", "null", '"invalid"', "false"])
def test_backup_rejects_invalid_bootstrap_without_leaving_artifacts(configured, tmp_path, invalid):
    with sqlite3.connect(configured.database) as connection:
        connection.execute("UPDATE objects SET body=? WHERE kind='bootstrap'", (invalid,))
    destination = tmp_path / "backup.sqlite3"
    with pytest.raises(OperationError, match="bootstrap"):
        backup_database(configured, destination)
    assert not destination.exists()
    assert not destination.with_suffix(".sqlite3.json").exists()


def test_backup_checksum_io_failure_cleans_new_database(configured, tmp_path, monkeypatch):
    def fail_checksum(_path):
        raise OSError(errno.EIO, "injected read failure")

    monkeypatch.setattr(operations, "_sha256", fail_checksum)
    destination = tmp_path / "backup.sqlite3"
    with pytest.raises(OSError):
        backup_database(configured, destination)
    assert not destination.exists()
    assert not destination.with_suffix(".sqlite3.json").exists()


def test_restore_checksum_io_failure_cleans_new_database(configured, tmp_path, monkeypatch):
    backup = tmp_path / "backup.sqlite3"
    backup_database(configured, backup)
    destination = tmp_path / "restored.sqlite3"
    original = operations._sha256

    def fail_checksum(path):
        if path == destination:
            raise OSError(errno.EIO, "injected read failure")
        return original(path)

    monkeypatch.setattr(operations, "_sha256", fail_checksum)
    with pytest.raises(OSError):
        verify_restore(configured, backup, destination)
    assert not destination.exists()
    assert backup.exists() and backup.with_suffix(".sqlite3.json").exists()


def test_backup_sidecar_disk_full_removes_only_new_files(configured, tmp_path, monkeypatch):
    from pathlib import Path

    original = Path.write_text
    destination = tmp_path / "backup.sqlite3"
    sidecar = destination.with_suffix(".sqlite3.json")
    unrelated = tmp_path / "preserve.txt"
    unrelated.write_text("preserve")

    def disk_full(path, data, *args, **kwargs):
        if path == sidecar:
            raise OSError(errno.ENOSPC, "injected disk full")
        return original(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", disk_full)
    with pytest.raises(OSError):
        backup_database(configured, destination)
    assert not destination.exists() and not sidecar.exists()
    assert unrelated.read_text() == "preserve"


def test_online_backup_excludes_uncommitted_rows(configured, tmp_path):
    with sqlite3.connect(configured.database) as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO objects(kind,id,body) VALUES('proof','uncommitted','{}')")
        destination = tmp_path / "snapshot.sqlite3"
        backup_database(configured, destination)
        writer.rollback()
    with sqlite3.connect(destination) as restored:
        assert restored.execute("SELECT id FROM objects WHERE kind='proof'").fetchall() == []
        assert restored.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_competing_backups_cannot_replace_or_delete_winner(configured, tmp_path):
    barrier = Barrier(2)
    destination = tmp_path / "shared.sqlite3"

    def run():
        barrier.wait(timeout=5)
        try:
            return backup_database(configured, destination)
        except OperationError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert sum(result is not None for result in results) == 1
    assert verify_restore(configured, destination, tmp_path / "verified.sqlite3")["integrity_check"] == "ok"


def test_sqlite_full_rolls_back_object_and_audit_together(configured):
    from wiseway.storage import Store

    store = Store(configured.database)
    with store.transaction(write=False) as tx:
        before = tx.connection.execute("SELECT id,body FROM audit ORDER BY seq").fetchall()
    with pytest.raises(sqlite3.OperationalError) as failure:
        with store.transaction() as tx:
            pages = tx.connection.execute("PRAGMA page_count").fetchone()[0]
            tx.connection.execute(f"PRAGMA max_page_count={pages}")
            tx.append_event({"event_id": "atomic-proof", "action": "proof"})
            tx.put("proof", "atomic", {"value": "x" * (4 * 1024 * 1024)})
    assert failure.value.sqlite_errorcode == sqlite3.SQLITE_FULL
    with store.transaction(write=False) as tx:
        assert tx.get("proof", "atomic") is None
        assert tx.connection.execute("SELECT id,body FROM audit ORDER BY seq").fetchall() == before
        assert tx.connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_copied_sandbox_restore_does_not_blindly_resume_old_file_identity(client, configured, tmp_path):
    from dataclasses import replace
    import shutil

    from test_durable_resilience import _accept_ready_batch
    from wiseway.services import Context
    from wiseway.worker import Worker

    ctx, _, _, _, _, accepted = _accept_ready_batch(client, configured)
    with ctx.store.transaction(write=False) as tx:
        attempt = next(row for row in tx.list("attempt") if row["batch_id"] == accepted["batch_id"])
        original = ctx.physical(tx, attempt["item"]["source"])
        target = ctx.location(tx, "manual-root", "Atlas/restored-pending.pdf")
    source = configured.sandbox_dir / original
    original_bytes = source.read_bytes()
    # A durable pre-rename boundary, with no concurrent writers during the copy.
    Worker(ctx)._intent(attempt["attempt_id"], target, "MANUAL_REVIEW", "NO_SCENARIO")
    backup = tmp_path / "backup.sqlite3"
    backup_database(configured, backup)
    restored = replace(
        configured, data_dir=tmp_path / "restored-state", sandbox_dir=tmp_path / "restored-files"
    )
    restored.data_dir.mkdir()
    shutil.copytree(configured.sandbox_dir, restored.sandbox_dir)
    verify_restore(configured, backup, restored.database)
    assert (restored.sandbox_dir / original).stat().st_ino != source.stat().st_ino

    recovered = Context(restored)
    try:
        Worker(recovered).run_once()
        Worker(recovered).run_once()
        with recovered.store.transaction(write=False) as tx:
            outcome = tx.require("attempt", attempt["attempt_id"])["outcome"]
            assert outcome["state"] == "RECOVERY_REQUIRED"
            assert outcome["actual_location"] is None
            events = [row for row in tx.events() if row["attempt_id"] == attempt["attempt_id"]]
            assert sorted(row["action"] for row in events) == ["FILE_ATTEMPT_STARTED", "RECOVERY_REQUIRED"]
            assert recovered.fs.stat(recovered.physical(tx, target)) is None
        assert (restored.sandbox_dir / original).read_bytes() == original_bytes
        assert source.read_bytes() == original_bytes
    finally:
        recovered.close()
