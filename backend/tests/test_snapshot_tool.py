"""Offline snapshot tool acceptance tests."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import sqlite3
import subprocess
import sys
import fcntl
from pathlib import Path

import pytest


TOOL_PATH = Path(__file__).parents[2] / "infra" / "scripts" / "snapshot.py"


@pytest.fixture(scope="module")
def snapshot_tool():
    spec = importlib.util.spec_from_file_location("wiseway_snapshot_tool", TOOL_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _snapshot_hashes(snapshot: Path) -> dict[str, str]:
    return {
        path.relative_to(snapshot).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(snapshot.rglob("*"))
        if path.is_file()
    }


def test_create_and_restore_cold_copy_preserve_bytes_and_database(
    configured, tmp_path: Path, snapshot_tool
) -> None:
    data, sandbox = configured.data_dir, configured.sandbox_dir
    snapshot = tmp_path / "snapshot"
    restored = tmp_path / "restored"

    created = snapshot_tool.create_snapshot(data, sandbox, snapshot)
    restored_result = snapshot_tool.restore_snapshot(snapshot, restored)

    assert created == snapshot
    assert restored_result == restored
    assert (restored / "sandbox" / "Incoming" / "Atlas").is_dir()
    assert (restored / "sandbox" / "ManualReview" / "Atlas").is_dir()
    assert (restored / "data" / "wiseway.sqlite3").read_bytes() == (data / "wiseway.sqlite3").read_bytes()
    with sqlite3.connect(f"file:{restored / 'data' / 'wiseway.sqlite3'}?mode=ro", uri=True) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["format"] == "wiseway-offline-snapshot-v1"
    assert {
        "data/wiseway.sqlite3",
        "sandbox/.wiseway-sandbox.json",
    }.issubset({entry["path"] for entry in manifest["files"]})
    assert "sandbox/ManualReview/Atlas" in manifest["directories"]

    from wiseway.common import Settings
    from wiseway.indexer import Indexer
    from wiseway.operations import doctor, record_worker_heartbeat
    from wiseway.services import Context

    restored_settings = Settings(data_dir=restored / "data", sandbox_dir=restored / "sandbox")
    context = Context(restored_settings)
    try:
        Indexer(context).scan()
        record_worker_heartbeat(context)
        assert doctor(context)["ready"] is True
    finally:
        context.close()


def test_command_line_create_and_restore(configured, tmp_path: Path) -> None:
    data, sandbox = configured.data_dir, configured.sandbox_dir
    snapshot = tmp_path / "snapshot"
    restored = tmp_path / "restored"
    create = subprocess.run(
        [
            sys.executable,
            str(TOOL_PATH),
            "create",
            "--data-dir",
            str(data),
            "--sandbox-dir",
            str(sandbox),
            "--destination",
            str(snapshot),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert create.returncode == 0, create.stderr
    restore = subprocess.run(
        [
            sys.executable,
            str(TOOL_PATH),
            "restore",
            "--snapshot",
            str(snapshot),
            "--destination",
            str(restored),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert restore.returncode == 0, restore.stderr
    assert json.loads(restore.stdout)["destination"] == str(restored)


def test_wal_snapshot_validation_does_not_mutate_snapshot(configured, tmp_path: Path, snapshot_tool) -> None:
    database = configured.data_dir / "wiseway.sqlite3"
    writer = sqlite3.connect(database)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
        writer.execute("CREATE TABLE snapshot_wal_probe (value TEXT)")
        writer.execute("INSERT INTO snapshot_wal_probe VALUES ('present')")
        writer.commit()
        assert database.with_name("wiseway.sqlite3-wal").is_file()
        snapshot = tmp_path / "snapshot"
        snapshot_tool.create_snapshot(configured.data_dir, configured.sandbox_dir, snapshot)
    finally:
        writer.close()

    before = _snapshot_hashes(snapshot)
    snapshot_tool.restore_snapshot(snapshot, tmp_path / "restored")
    assert _snapshot_hashes(snapshot) == before


def test_create_rejects_active_archive_indexer_lock(configured, tmp_path: Path, snapshot_tool) -> None:
    lock_path = configured.data_dir / "archive-indexer.lock"
    descriptor = lock_path.open("a+b")
    try:
        fcntl.flock(descriptor.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        destination = tmp_path / "blocked-snapshot"
        with pytest.raises(snapshot_tool.SnapshotError, match="Archive indexer is running"):
            snapshot_tool.create_snapshot(configured.data_dir, configured.sandbox_dir, destination)
        assert not destination.exists()
    finally:
        fcntl.flock(descriptor.fileno(), fcntl.LOCK_UN)
        descriptor.close()


def test_snapshot_restores_complete_large_sqlite_generation(
    configured, tmp_path: Path, snapshot_tool
) -> None:
    from wiseway.large_indexer import LargeIndexer
    from wiseway.services import Context

    context = Context(configured)
    try:
        with context.store.transaction(write=False) as tx:
            root = tx.require("root", "archive-root")
        LargeIndexer(context).scan(root)
    finally:
        context.close()
    snapshot = tmp_path / "large-snapshot"
    restored = tmp_path / "large-restored"
    snapshot_tool.create_snapshot(configured.data_dir, configured.sandbox_dir, snapshot)
    snapshot_tool.restore_snapshot(snapshot, restored)
    with sqlite3.connect(restored / "data" / "wiseway.sqlite3") as connection:
        raw = connection.execute(
            "SELECT body FROM objects WHERE kind='index' AND id='archive-root'"
        ).fetchone()[0]
        index = json.loads(raw)
        assert index["_storage"] == "sqlite"
        assert connection.execute(
            "SELECT state FROM search_generations WHERE generation_id=?", (index["_generation"],)
        ).fetchone() == ("ACTIVE",)
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM search_items WHERE generation_id=?", (index["_generation"],)
            ).fetchone()[0]
            > 0
        )


def test_existing_destinations_are_never_overwritten(configured, tmp_path: Path, snapshot_tool) -> None:
    data, sandbox = configured.data_dir, configured.sandbox_dir
    existing_snapshot = tmp_path / "existing-snapshot"
    existing_snapshot.mkdir()
    (existing_snapshot / "keep").write_text("keep", encoding="utf-8")

    with pytest.raises(snapshot_tool.SnapshotError):
        snapshot_tool.create_snapshot(data, sandbox, existing_snapshot)
    assert (existing_snapshot / "keep").read_text(encoding="utf-8") == "keep"

    snapshot = tmp_path / "snapshot"
    snapshot_tool.create_snapshot(data, sandbox, snapshot)
    existing_restore = tmp_path / "existing-restore"
    existing_restore.mkdir()
    (existing_restore / "keep").write_text("keep", encoding="utf-8")
    with pytest.raises(snapshot_tool.SnapshotError):
        snapshot_tool.restore_snapshot(snapshot, existing_restore)
    assert (existing_restore / "keep").read_text(encoding="utf-8") == "keep"


def test_create_rejects_non_initialized_database_or_marker(tmp_path: Path, snapshot_tool) -> None:
    data = tmp_path / "data"
    sandbox = tmp_path / "sandbox"
    data.mkdir()
    sandbox.mkdir()
    with sqlite3.connect(data / "wiseway.sqlite3") as connection:
        connection.execute("CREATE TABLE objects (kind TEXT, id TEXT, body TEXT)")
    (sandbox / ".wiseway-sandbox.json").write_text('{"version": 1}', encoding="utf-8")

    with pytest.raises(snapshot_tool.SnapshotError):
        snapshot_tool.create_snapshot(data, sandbox, tmp_path / "snapshot")


def test_restore_rejects_corruption_and_path_escape(configured, tmp_path: Path, snapshot_tool) -> None:
    data, sandbox = configured.data_dir, configured.sandbox_dir
    snapshot = tmp_path / "snapshot"
    snapshot_tool.create_snapshot(data, sandbox, snapshot)
    (snapshot / "sandbox" / ".wiseway-sandbox.json").write_bytes(b"changed")
    with pytest.raises(snapshot_tool.SnapshotError):
        snapshot_tool.restore_snapshot(snapshot, tmp_path / "corrupt-restore")

    complete = tmp_path / "complete"
    snapshot_tool.create_snapshot(data, sandbox, complete)
    (complete / "sandbox" / "unlisted-empty-directory").mkdir()
    with pytest.raises(snapshot_tool.SnapshotError):
        snapshot_tool.restore_snapshot(complete, tmp_path / "unlisted-restore")

    escaped = tmp_path / "escaped"
    (escaped / "data").mkdir(parents=True)
    (escaped / "sandbox").mkdir()
    (escaped / "data" / "wiseway.sqlite3").write_bytes((data / "wiseway.sqlite3").read_bytes())
    (escaped / "manifest.json").write_text(
        json.dumps(
            {
                "format": "wiseway-offline-snapshot-v1",
                "directories": ["data", "sandbox"],
                "files": [{"path": "data/../escape", "sha256": "0" * 64, "size_bytes": 0}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(snapshot_tool.SnapshotError):
        snapshot_tool.restore_snapshot(escaped, tmp_path / "escaped-restore")


def test_links_are_rejected_on_create_and_restore(configured, tmp_path: Path, snapshot_tool) -> None:
    data, sandbox = configured.data_dir, configured.sandbox_dir
    (sandbox / "linked").symlink_to(sandbox / ".wiseway-sandbox.json")
    with pytest.raises(snapshot_tool.SnapshotError):
        snapshot_tool.create_snapshot(data, sandbox, tmp_path / "link-create")

    from wiseway.common import Settings
    from wiseway.seed import initialize

    safe = Settings(data_dir=tmp_path / "safe" / "state", sandbox_dir=tmp_path / "safe" / "sandbox")
    initialize(safe, password="synthetic-test-password")
    snapshot = tmp_path / "snapshot"
    snapshot_tool.create_snapshot(safe.data_dir, safe.sandbox_dir, snapshot)
    (snapshot / "sandbox" / "linked").symlink_to(snapshot / "sandbox" / ".wiseway-sandbox.json")
    with pytest.raises(snapshot_tool.SnapshotError):
        snapshot_tool.restore_snapshot(snapshot, tmp_path / "link-restore")


def test_pending_durable_work_blocks_create_and_restore(configured, tmp_path: Path, snapshot_tool) -> None:
    data, sandbox = configured.data_dir, configured.sandbox_dir
    with sqlite3.connect(data / "wiseway.sqlite3") as connection:
        connection.execute(
            "INSERT INTO objects VALUES (?, ?, ?)",
            (
                "batch",
                "batch-accepted",
                json.dumps({"batch_id": "batch-accepted", "status": "ACCEPTED", "selected_count": 1}),
            ),
        )
        connection.commit()
    with pytest.raises(snapshot_tool.SnapshotError):
        snapshot_tool.create_snapshot(data, sandbox, tmp_path / "pending-snapshot")

    from wiseway.common import Settings
    from wiseway.seed import initialize

    safe = Settings(data_dir=tmp_path / "safe" / "state", sandbox_dir=tmp_path / "safe" / "sandbox")
    initialize(safe, password="synthetic-test-password")
    snapshot = tmp_path / "snapshot"
    snapshot_tool.create_snapshot(safe.data_dir, safe.sandbox_dir, snapshot)
    with sqlite3.connect(snapshot / "data" / "wiseway.sqlite3") as connection:
        connection.execute(
            "INSERT INTO objects VALUES (?, ?, ?)",
            ("return", "return-1", json.dumps({"phase": "INTENT"})),
        )
        connection.commit()
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        if entry["path"] == "data/wiseway.sqlite3":
            db = snapshot / entry["path"]
            entry["sha256"] = hashlib.sha256(db.read_bytes()).hexdigest()
            entry["size_bytes"] = db.stat().st_size
    (snapshot / "manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    with pytest.raises(snapshot_tool.SnapshotError):
        snapshot_tool.restore_snapshot(snapshot, tmp_path / "pending-restore")
