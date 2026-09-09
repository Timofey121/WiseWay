"""Local operational checks and SQLite-only recovery artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from .common import timestamp, utc


class OperationError(RuntimeError):
    """A local operator command was rejected before changing an existing file."""


def record_worker_heartbeat(ctx) -> None:
    """Record only that a complete worker cycle returned without an exception."""
    with ctx.store.transaction() as tx:
        tx.put(
            "operator_state",
            "worker",
            {"last_completed_at": utc(ctx.settings.clock())},
        )


def operator_status(ctx) -> dict:
    """Return a bounded status view suitable for an operator terminal."""
    fields = ("root_id", "status", "count", "checkpoint", "estimated_remaining_seconds")
    with ctx.store.transaction(write=False) as tx:
        return {
            "worker": tx.get("operator_state", "worker", {}),
            "index": [{key: row[key] for key in fields if key in row} for row in tx.list("index_progress")],
            "attempts": [
                {"attempt_id": attempt["attempt_id"], "phase": attempt["phase"]}
                for attempt in tx.list("attempt")
                if attempt["phase"] == "RECOVERY_REQUIRED"
            ],
            "returns": [
                {"operation_id": operation["operation_id"], "phase": operation["phase"]}
                for operation in tx.list("return")
                if operation["phase"] in ("INTENT", "RECOVERY_REQUIRED")
            ],
        }


def doctor(ctx) -> dict:
    """Check local dependencies without exposing them through the HTTP API."""
    with ctx.store.transaction(write=False) as tx:
        tx.connection.execute("SELECT 1").fetchone()
        worker = tx.get("operator_state", "worker", {})
        failed_indexes = [
            row["root_id"] for row in tx.list("index_progress") if row.get("status") == "FAILED"
        ]
    reasons = []
    if not ctx.fs.sandbox.is_dir() or not ctx.fs.probe():
        reasons.append("filesystem_unavailable")
    last_completed_at = worker.get("last_completed_at")
    max_age = ctx.settings.worker_stale_seconds
    if not last_completed_at:
        reasons.append("worker_heartbeat_missing")
    elif ctx.settings.clock() - timestamp(last_completed_at) > max_age:
        reasons.append("worker_heartbeat_stale")
    if failed_indexes:
        reasons.append("index_failed")
    return {
        "database": {"ok": True},
        "filesystem": {"atomic_no_replace": ctx.fs.probe()},
        "worker": worker,
        "ready": not reasons,
        "reasons": reasons,
        "failed_index_roots": failed_indexes,
    }


def _resolved(path: Path | str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _inside(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def _new_database_target(settings, destination: Path | str) -> Path:
    requested = Path(destination).expanduser()
    parent = requested.parent.resolve(strict=False)
    target = parent / requested.name
    database = _resolved(settings.database)
    sandbox = _resolved(settings.sandbox_dir)
    if target == database:
        raise OperationError("destination is the active database")
    if _inside(target, sandbox):
        raise OperationError("destination must not be inside the sandbox")
    if target.exists() or target.is_symlink():
        raise OperationError("destination already exists")
    if not target.parent.is_dir():
        raise OperationError("destination parent does not exist")
    return target


def _reserve_new_file(path: Path) -> bool:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise OperationError("destination already exists") from error
    finally:
        if "descriptor" in locals():
            os.close(descriptor)
    path.chmod(0o600)
    return True


def _fsync_file_and_parent(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _integrity(connection: sqlite3.Connection) -> str:
    result = connection.execute("PRAGMA integrity_check").fetchone()
    if result is None or result[0] != "ok":
        raise OperationError("SQLite integrity_check failed")
    return result[0]


def _open_readonly_database(path: Path) -> sqlite3.Connection:
    if not path.is_file() or path.is_symlink():
        raise OperationError("source database is not a regular file")
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)


def _database_identity(connection: sqlite3.Connection) -> dict:
    migrations = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    bootstrap = connection.execute(
        "SELECT body FROM objects WHERE kind='bootstrap' AND id='seed-v1'"
    ).fetchone()
    if migrations is None or migrations[0] is None or bootstrap is None:
        raise OperationError("database is not a Wise Way initialized state")
    try:
        state = json.loads(bootstrap[0])
        complete = isinstance(state, dict) and state.get("complete") is True
    except (TypeError, ValueError):
        complete = False
    if not complete:
        raise OperationError("database bootstrap is incomplete")
    return {"schema_version": migrations[0], "bootstrap_complete": complete}


def _copy_database(source_path: Path, destination: Path) -> tuple[str, dict]:
    created = _reserve_new_file(destination)
    try:
        with (
            closing(_open_readonly_database(source_path)) as source,
            closing(sqlite3.connect(destination)) as target,
        ):
            source.backup(target)
            identity = _database_identity(target)
            integrity = _integrity(target)
        _fsync_file_and_parent(destination)
        return integrity, identity
    except BaseException as error:
        if created:
            destination.unlink(missing_ok=True)
        if isinstance(error, sqlite3.Error):
            raise OperationError("SQLite backup copy failed") from error
        raise


def _sha256(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def backup_database(settings, destination: Path | str) -> dict:
    """Create a new consistent SQLite copy; this does not back up the file tree."""
    target = _new_database_target(settings, destination)
    metadata_path = Path(str(target) + ".json")
    if metadata_path.exists() or metadata_path.is_symlink():
        raise OperationError("backup metadata destination already exists")
    integrity, identity = _copy_database(_resolved(settings.database), target)
    metadata_created = False
    try:
        metadata = {
            "format": "wiseway-sqlite-backup-v1",
            "created_at": utc(),
            "integrity_check": integrity,
            "size_bytes": target.stat().st_size,
            "sha256": _sha256(target),
            **identity,
        }
        metadata_created = _reserve_new_file(metadata_path)
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
        )
        metadata_path.chmod(0o600)
        _fsync_file_and_parent(metadata_path)
    except BaseException:
        if metadata_created:
            metadata_path.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise
    return metadata


def verify_restore(settings, backup: Path | str, destination: Path | str) -> dict:
    """Copy a backup to a new database and validate it without replacing runtime state."""
    source = _resolved(backup)
    metadata_path = Path(str(source) + ".json")
    if (
        not source.is_file()
        or source.is_symlink()
        or not metadata_path.is_file()
        or metadata_path.is_symlink()
    ):
        raise OperationError("backup source is not a regular file")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise OperationError("backup metadata is invalid") from error
    if not isinstance(metadata, dict) or metadata.get("format") != "wiseway-sqlite-backup-v1":
        raise OperationError("backup metadata format is invalid")
    if metadata.get("size_bytes") != source.stat().st_size:
        raise OperationError("backup size does not match metadata")
    if metadata.get("sha256") != _sha256(source):
        raise OperationError("backup checksum does not match metadata")
    target = _new_database_target(settings, destination)
    integrity, identity = _copy_database(source, target)
    try:
        if identity != {key: metadata.get(key) for key in identity}:
            raise OperationError("backup database identity does not match metadata")
        return {
            "format": "wiseway-sqlite-restore-check-v1",
            "integrity_check": integrity,
            "size_bytes": target.stat().st_size,
            "sha256": _sha256(target),
        }
    except BaseException:
        target.unlink(missing_ok=True)
        raise
