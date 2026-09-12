import json
import sqlite3

import pytest


def test_worker_heartbeat_and_status_redact_index_payload(configured):
    from wiseway.operations import operator_status, record_worker_heartbeat
    from wiseway.services import Context

    with sqlite3.connect(configured.database) as connection:
        connection.execute(
            "INSERT INTO objects(kind,id,body) VALUES(?,?,?) "
            "ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body",
            (
                "index_progress",
                "archive-root",
                json.dumps(
                    {
                        "root_id": "archive-root",
                        "status": "SCANNING",
                        "count": 12,
                        "checkpoint": "Archive/visible.pdf",
                        "estimated_remaining_seconds": 3.5,
                        "_items": [{"private": "not shown"}],
                        "_found": [["private", {}]],
                    }
                ),
            ),
        )

    context = Context(configured)
    try:
        record_worker_heartbeat(context)
        status = operator_status(context)
    finally:
        context.close()

    assert status["worker"]["last_completed_at"]
    archived = next(row for row in status["index"] if row["root_id"] == "archive-root")
    assert archived == {
        "root_id": "archive-root",
        "status": "SCANNING",
        "count": 12,
        "checkpoint": "Archive/visible.pdf",
        "estimated_remaining_seconds": 3.5,
    }
    assert "_items" not in json.dumps(status)
    assert "_found" not in json.dumps(status)


def test_online_backup_is_integrity_checked_and_contains_committed_data(configured, tmp_path):
    from wiseway.operations import backup_database

    with sqlite3.connect(configured.database) as connection:
        connection.execute(
            "INSERT INTO objects(kind,id,body) VALUES(?,?,?)",
            ("operator_state", "backup-proof", json.dumps({"committed": True})),
        )

    destination = tmp_path / "backup.sqlite3"
    metadata = backup_database(configured, destination)

    assert metadata["integrity_check"] == "ok"
    assert destination.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "backup.sqlite3.json").stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(destination) as connection:
        row = connection.execute(
            "SELECT body FROM objects WHERE kind='operator_state' AND id='backup-proof'"
        ).fetchone()
    assert json.loads(row[0]) == {"committed": True}


def test_backup_refuses_existing_destination_and_sandbox(configured, tmp_path):
    from wiseway.operations import OperationError, backup_database

    existing = tmp_path / "existing.sqlite3"
    existing.write_text("preserve", encoding="utf-8")
    with pytest.raises(OperationError, match="already exists"):
        backup_database(configured, existing)
    assert existing.read_text(encoding="utf-8") == "preserve"

    with pytest.raises(OperationError, match="sandbox"):
        backup_database(configured, configured.sandbox_dir / "backup.sqlite3")


def test_restore_check_requires_new_non_active_destination(configured, tmp_path):
    from wiseway.operations import OperationError, backup_database, verify_restore

    backup = tmp_path / "backup.sqlite3"
    backup_database(configured, backup)

    restored = tmp_path / "restored.sqlite3"
    metadata = verify_restore(configured, backup, restored)
    assert metadata["integrity_check"] == "ok"
    assert restored.is_file()

    with pytest.raises(OperationError, match="active database"):
        verify_restore(configured, backup, configured.database)


def test_restore_check_rejects_tampered_backup_sidecar(configured, tmp_path):
    from wiseway.operations import OperationError, backup_database, verify_restore

    backup = tmp_path / "backup.sqlite3"
    backup_database(configured, backup)
    backup.write_bytes(backup.read_bytes() + b"tampered")

    with pytest.raises(OperationError, match="size|checksum"):
        verify_restore(configured, backup, tmp_path / "restored.sqlite3")


def test_restore_check_rejects_non_object_metadata(configured, tmp_path):
    from wiseway.operations import OperationError, backup_database, verify_restore

    backup = tmp_path / "backup.sqlite3"
    backup_database(configured, backup)
    backup.with_suffix(".sqlite3.json").write_text("[]", encoding="utf-8")
    with pytest.raises(OperationError, match="metadata"):
        verify_restore(configured, backup, tmp_path / "restored.sqlite3")
    assert not (tmp_path / "restored.sqlite3").exists()


def test_backup_rejects_missing_source_database(configured, tmp_path):
    from wiseway.operations import OperationError, backup_database

    configured.database.unlink()
    with pytest.raises(OperationError, match="source database"):
        backup_database(configured, tmp_path / "backup.sqlite3")


def test_doctor_reports_local_database_filesystem_and_worker_state(configured):
    from wiseway.operations import doctor
    from wiseway.services import Context

    context = Context(configured)
    try:
        result = doctor(context)
    finally:
        context.close()

    assert result["database"] == {"ok": True}
    assert result["filesystem"] == {"atomic_no_replace": True}
    assert result["worker"] == {}
    assert result["ready"] is False
    assert result["reasons"] == ["worker_heartbeat_missing"]


def test_doctor_uses_configured_worker_stale_threshold(configured):
    from dataclasses import replace
    from wiseway.operations import doctor, record_worker_heartbeat
    from wiseway.services import Context

    now = [1000.0]
    settings = replace(configured, clock=lambda: now[0], worker_stale_seconds=120)
    context = Context(settings)
    try:
        record_worker_heartbeat(context)
        now[0] += 121
        result = doctor(context)
    finally:
        context.close()

    assert result["ready"] is False
    assert "worker_heartbeat_stale" in result["reasons"]


def test_cli_backup_does_not_require_sandbox(configured, monkeypatch, tmp_path):
    from wiseway import cli

    for child in configured.sandbox_dir.rglob("*"):
        if child.is_file():
            child.unlink()
    for child in sorted(configured.sandbox_dir.rglob("*"), reverse=True):
        if child.is_dir():
            child.rmdir()
    configured.sandbox_dir.rmdir()
    monkeypatch.setattr(cli, "Settings", lambda: configured)

    cli.main(["backup", str(tmp_path / "backup.sqlite3")])

    assert (tmp_path / "backup.sqlite3").is_file()


def test_cli_restore_check_does_not_require_live_database_or_sandbox(configured, monkeypatch, tmp_path):
    from wiseway import cli
    from wiseway.operations import backup_database

    backup = tmp_path / "backup.sqlite3"
    backup_database(configured, backup)
    configured.database.unlink()
    for child in configured.sandbox_dir.rglob("*"):
        if child.is_file():
            child.unlink()
    for child in sorted(configured.sandbox_dir.rglob("*"), reverse=True):
        if child.is_dir():
            child.rmdir()
    configured.sandbox_dir.rmdir()
    monkeypatch.setattr(cli, "Settings", lambda: configured)

    cli.main(["restore-check", str(backup), str(tmp_path / "restored.sqlite3")])

    assert (tmp_path / "restored.sqlite3").is_file()


def test_doctor_reports_search_maintenance_staleness(configured):
    from wiseway.services import Context
    from wiseway.operations import doctor, record_worker_heartbeat

    ctx = Context(configured)
    try:
        record_worker_heartbeat(ctx)
        with ctx.store.transaction() as tx:
            tx.put(
                "index", "external", {"root": {"root_id": "external"}, "_storage": "opensearch", "items": []}
            )
        assert "search_heartbeat_missing" in doctor(ctx)["reasons"]
    finally:
        ctx.close()
