#!/usr/bin/env python3
"""Create and restore verified cold copies of a stopped Wise Way installation.

The caller must stop the API and regular worker before invoking this tool.  It
also acquires the archive-indexer lock for the complete copy, so an active
separate archive indexer is rejected rather than copied concurrently.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sqlite3
import stat
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable


FORMAT = "wiseway-offline-snapshot-v1"
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_FILES = 100_000
MAX_NODES = 100_000
MAX_DEPTH = 128
CHUNK_SIZE = 1024 * 1024


class SnapshotError(RuntimeError):
    """The requested copy cannot be proven safe enough to perform."""


def _fail(message: str) -> None:
    raise SnapshotError(message)


def _lstat(path: Path, description: str) -> os.stat_result:
    try:
        result = path.lstat()
    except OSError as error:
        _fail(f"Cannot inspect {description}: {error}")
    if stat.S_ISLNK(result.st_mode):
        _fail(f"Symbolic links are not permitted: {description}")
    return result


def _require_directory(path: Path, description: str) -> Path:
    details = _lstat(path, description)
    if not stat.S_ISDIR(details.st_mode):
        _fail(f"Expected a directory: {description}")
    try:
        return path.resolve(strict=True)
    except OSError as error:
        _fail(f"Cannot resolve {description}: {error}")


def _is_within(path: Path, ancestor: Path) -> bool:
    try:
        path.relative_to(ancestor)
        return True
    except ValueError:
        return False


def _new_destination(destination: Path, sources: Iterable[Path]) -> Path:
    if destination.exists() or destination.is_symlink():
        _fail("Destination must be a directory that does not already exist.")
    parent = _require_directory(destination.parent, "destination parent")
    target = parent / destination.name
    for source in sources:
        if _is_within(target, source) or _is_within(source, target):
            _fail("Destination must be outside every source directory.")
    try:
        os.mkdir(target, 0o700)
    except FileExistsError:
        _fail("Destination must be a directory that does not already exist.")
    except OSError as error:
        _fail(f"Cannot create destination: {error}")
    return target


def _private_directory(path: Path) -> None:
    os.mkdir(path, 0o700)
    os.chmod(path, 0o700)


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError as error:
        _fail(f"Cannot fsync directory {path}: {error}")
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _archive_indexer_lock(data_dir: Path):
    """Exclude the separate archive-index writer for the whole cold copy."""
    path = data_dir / "archive-indexer.lock"
    try:
        descriptor = os.open(
            path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
    except OSError as error:
        _fail(f"Cannot inspect archive indexer lock: {error}")
    try:
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _fail("Archive indexer is running; stop it before creating a snapshot.")
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _remove_created_tree(path: Path) -> None:
    """Remove only a destination this process created; never follow links."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
        with os.scandir(path) as entries:
            for entry in entries:
                child = path / entry.name
                child_info = child.lstat()
                if stat.S_ISDIR(child_info.st_mode) and not stat.S_ISLNK(child_info.st_mode):
                    _remove_created_tree(child)
                else:
                    os.unlink(child)
        os.rmdir(path)
    else:
        os.unlink(path)


def _scan_tree(root: Path, prefix: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Return an immutable description of regular files; reject unsafe nodes."""
    files: list[dict[str, Any]] = []
    directories: list[str] = [prefix]

    def visit(directory: Path, relative: Path) -> None:
        try:
            with os.scandir(directory) as entries:
                sorted_entries = sorted(entries, key=lambda entry: entry.name)
        except OSError as error:
            _fail(f"Cannot read directory {directory}: {error}")
        for entry in sorted_entries:
            child = directory / entry.name
            details = _lstat(child, str(child))
            child_relative = relative / entry.name
            if len(child_relative.parts) > MAX_DEPTH:
                _fail(f"Directory tree is deeper than {MAX_DEPTH} levels.")
            if stat.S_ISDIR(details.st_mode):
                directories.append(f"{prefix}/{child_relative.as_posix()}")
                visit(child, child_relative)
            elif stat.S_ISREG(details.st_mode):
                files.append(
                    {
                        "path": f"{prefix}/{child_relative.as_posix()}",
                        "source": child,
                        "fingerprint": (
                            details.st_dev,
                            details.st_ino,
                            details.st_size,
                            details.st_mtime_ns,
                            stat.S_IMODE(details.st_mode),
                        ),
                    }
                )
                if len(files) > MAX_FILES or len(files) + len(directories) > MAX_NODES:
                    _fail(f"Snapshot contains more than {MAX_FILES} files.")
            else:
                _fail(f"Only regular files and directories are permitted: {child}")

    visit(root, Path())
    if len(files) + len(directories) > MAX_NODES:
        _fail(f"Snapshot contains more than {MAX_NODES} filesystem nodes.")
    return files, directories


def _hash_and_copy(
    source: Path, target: Path, expected: tuple[int, int, int, int, int] | None = None
) -> tuple[str, int]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        source_fd = os.open(source, flags)
    except OSError as error:
        _fail(f"Cannot open source file {source}: {error}")
    try:
        source_info = os.fstat(source_fd)
        current = (
            source_info.st_dev,
            source_info.st_ino,
            source_info.st_size,
            source_info.st_mtime_ns,
            stat.S_IMODE(source_info.st_mode),
        )
        if not stat.S_ISREG(source_info.st_mode) or (expected is not None and current != expected):
            _fail(f"Source changed while copying: {source}")
        target_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            digest = hashlib.sha256()
            total = 0
            while chunk := os.read(source_fd, CHUNK_SIZE):
                digest.update(chunk)
                total += len(chunk)
                view = memoryview(chunk)
                while view:
                    written = os.write(target_fd, view)
                    view = view[written:]
            os.fsync(target_fd)
        finally:
            os.close(target_fd)
        after = os.fstat(source_fd)
        if (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            stat.S_IMODE(after.st_mode),
        ) != current:
            _fail(f"Source changed while copying: {source}")
        os.chmod(target, 0o600)
        return digest.hexdigest(), total
    finally:
        os.close(source_fd)


def _hash_file(source: Path, expected: tuple[int, int, int, int, int]) -> tuple[str, int]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags)
    except OSError as error:
        _fail(f"Cannot open snapshot file {source}: {error}")
    try:
        before = os.fstat(descriptor)
        current = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            stat.S_IMODE(before.st_mode),
        )
        if not stat.S_ISREG(before.st_mode) or current != expected:
            _fail(f"Snapshot changed while validating: {source}")
        digest = hashlib.sha256()
        total = 0
        while chunk := os.read(descriptor, CHUNK_SIZE):
            digest.update(chunk)
            total += len(chunk)
        after = os.fstat(descriptor)
        if (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            stat.S_IMODE(after.st_mode),
        ) != current:
            _fail(f"Snapshot changed while validating: {source}")
        return digest.hexdigest(), total
    finally:
        os.close(descriptor)


def _copy_tree(
    files: list[dict[str, Any]], target_root: Path, source_prefix: str, directories: list[str]
) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for directory_name in sorted(directories, key=lambda item: (item.count("/"), item)):
        relative = Path(directory_name).relative_to(source_prefix)
        if relative.parts:
            _private_directory(target_root / relative)
    for item in files:
        relative = Path(item["path"]).relative_to(source_prefix)
        target = target_root / relative
        digest, size = _hash_and_copy(item["source"], target, item.get("fingerprint"))
        manifest.append({"path": item["path"], "sha256": digest, "size_bytes": size})
    for directory_name in sorted(directories, key=lambda item: (item.count("/"), item), reverse=True):
        relative = Path(directory_name).relative_to(source_prefix)
        _fsync_directory(target_root / relative)
    return manifest


def _open_database(path: Path) -> sqlite3.Connection:
    details = _lstat(path, "SQLite database")
    if not stat.S_ISREG(details.st_mode):
        _fail("SQLite database must be a regular file.")
    try:
        wal = path.with_name(path.name + "-wal")
        uri = path.as_uri() + "?mode=ro"
        if not wal.exists():
            uri += "&immutable=1"
        return sqlite3.connect(uri, uri=True)
    except sqlite3.Error as error:
        _fail(f"Cannot open SQLite database read-only: {error}")


def _validate_database(data_dir: Path) -> None:
    """Validate a private SQLite copy so readonly WAL inspection cannot alter input."""
    with tempfile.TemporaryDirectory(prefix="wiseway-snapshot-check-") as temporary:
        target_dir = Path(temporary)
        for suffix in ("", "-wal", "-shm"):
            source = data_dir / f"wiseway.sqlite3{suffix}"
            if suffix and not source.exists():
                continue
            details = _lstat(source, f"SQLite database{suffix}")
            if not stat.S_ISREG(details.st_mode):
                _fail(f"SQLite database{suffix} must be a regular file.")
            _hash_and_copy(source, target_dir / source.name)
        _validate_database_copy(target_dir)


def _validate_database_copy(data_dir: Path) -> None:
    database = data_dir / "wiseway.sqlite3"
    connection = _open_database(database)
    try:
        check = connection.execute("PRAGMA integrity_check").fetchone()
        if check != ("ok",):
            _fail("SQLite integrity_check did not return ok.")
        try:
            migration = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
            bootstrap = connection.execute(
                "SELECT body FROM objects WHERE kind='bootstrap' AND id='seed-v1'"
            ).fetchone()
            if migration is None or migration[0] is None or bootstrap is None:
                _fail("Database is not an initialized Wise Way state.")
            bootstrap_body = json.loads(bootstrap[0])
            if not isinstance(bootstrap_body, dict) or bootstrap_body.get("complete") is not True:
                _fail("Database bootstrap is incomplete.")
            rows = connection.execute(
                "SELECT kind, id, body FROM objects WHERE kind IN ('batch', 'attempt', 'return')"
            ).fetchall()
        except (sqlite3.Error, TypeError, json.JSONDecodeError) as error:
            _fail(f"Cannot inspect durable work: {error}")
    finally:
        connection.close()

    batches: dict[str, dict[str, Any]] = {}
    attempts: dict[str, list[dict[str, Any]]] = {}
    for kind, identifier, raw_body in rows:
        try:
            body = json.loads(raw_body)
        except (TypeError, json.JSONDecodeError) as error:
            _fail(f"Invalid durable-work record {kind}/{identifier}: {error}")
        if not isinstance(body, dict):
            _fail(f"Invalid durable-work record {kind}/{identifier}.")
        if kind == "batch":
            batches[str(identifier)] = body
        elif kind == "attempt":
            phase = body.get("phase")
            batch_id = body.get("batch_id")
            if not isinstance(phase, str) or not isinstance(batch_id, str):
                _fail(f"Invalid attempt record {identifier}.")
            if phase != "DONE":
                _fail(f"Pending attempt {identifier} is in phase {phase}.")
            attempts.setdefault(batch_id, []).append(body)
        else:
            phase = body.get("phase")
            if phase not in ("DONE", "REJECTED"):
                _fail(f"Pending return operation {identifier} is in phase {phase!r}.")

    for identifier, batch in batches.items():
        batch_id = batch.get("batch_id", identifier)
        if not isinstance(batch_id, str):
            _fail(f"Invalid batch record {identifier}.")
        selected_count = batch.get("selected_count")
        if not isinstance(selected_count, int) or isinstance(selected_count, bool) or selected_count < 0:
            _fail(f"Invalid batch record {identifier}.")
        related = attempts.get(batch_id, [])
        if selected_count > 0 and len(related) < selected_count:
            _fail(f"Batch {identifier} is accepted or running without completed attempts.")
        if batch.get("status") == "RUNNING":
            _fail(f"Batch {identifier} is running.")


def _validate_marker(sandbox_dir: Path) -> None:
    marker = sandbox_dir / ".wiseway-sandbox.json"
    details = _lstat(marker, "sandbox marker")
    if not stat.S_ISREG(details.st_mode) or details.st_size > 1024 * 1024:
        _fail("Sandbox marker must be a regular file no larger than 1 MiB.")
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail(f"Cannot read sandbox marker: {error}")
    if (
        not isinstance(payload, dict)
        or payload.get("product") != "Wise Way"
        or payload.get("synthetic") is not True
    ):
        _fail("Sandbox marker does not describe Wise Way synthetic data.")
    if payload.get("bootstrap_complete") is not True:
        _fail("Sandbox marker reports incomplete bootstrap.")


def _manifest_bytes(entries: list[dict[str, Any]], directories: list[str]) -> bytes:
    payload = json.dumps(
        {"format": FORMAT, "directories": directories, "files": entries},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(payload) > MAX_MANIFEST_BYTES:
        _fail("Manifest is too large.")
    return payload


def _write_manifest(target: Path, content: bytes) -> None:
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(target, 0o600)


def create_snapshot(data_dir: str | Path, sandbox_dir: str | Path, destination: str | Path) -> Path:
    """Create a verified cold snapshot into a strictly new destination."""
    data = _require_directory(Path(data_dir), "data directory")
    sandbox = _require_directory(Path(sandbox_dir), "sandbox directory")
    if data == sandbox or _is_within(data, sandbox) or _is_within(sandbox, data):
        _fail("Data and sandbox directories must be separate.")
    with _archive_indexer_lock(data):
        _validate_database(data)
        _validate_marker(sandbox)
        data_files, data_directories = _scan_tree(data, "data")
        sandbox_files, sandbox_directories = _scan_tree(sandbox, "sandbox")
        if (
            len(data_files) + len(data_directories) + len(sandbox_files) + len(sandbox_directories)
            > MAX_NODES
        ):
            _fail(f"Snapshot contains more than {MAX_NODES} filesystem nodes.")
        target = _new_destination(Path(destination), (data, sandbox))
        try:
            data_target = target / "data"
            sandbox_target = target / "sandbox"
            _private_directory(data_target)
            _private_directory(sandbox_target)
            entries = _copy_tree(data_files, data_target, "data", data_directories) + _copy_tree(
                sandbox_files, sandbox_target, "sandbox", sandbox_directories
            )
            entries.sort(key=lambda entry: entry["path"])
            _validate_database(data_target)
            _validate_marker(sandbox_target)
            _write_manifest(
                target / "manifest.json",
                _manifest_bytes(entries, sorted(data_directories + sandbox_directories)),
            )
            _fsync_directory(target)
            return target
        except BaseException:
            _remove_created_tree(target)
            raise


def _valid_manifest_path(path: Any, *, allow_root: bool) -> str | None:
    if not isinstance(path, str):
        return None
    pure = Path(path)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != path:
        return None
    if path in ("data", "sandbox"):
        return path if allow_root else None
    if len(pure.parts) < 2 or not (path.startswith("data/") or path.startswith("sandbox/")):
        return None
    return path


def _load_manifest(snapshot: Path) -> tuple[bytes, list[dict[str, Any]], list[str]]:
    manifest_path = snapshot / "manifest.json"
    details = _lstat(manifest_path, "manifest")
    if not stat.S_ISREG(details.st_mode) or details.st_size > MAX_MANIFEST_BYTES:
        _fail("Manifest must be a regular file no larger than 16 MiB.")
    try:
        descriptor = os.open(manifest_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            raw = os.read(descriptor, MAX_MANIFEST_BYTES + 1)
        finally:
            os.close(descriptor)
        if len(raw) > MAX_MANIFEST_BYTES:
            _fail("Manifest must be no larger than 16 MiB.")
        parsed = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail(f"Cannot read manifest: {error}")
    if (
        not isinstance(parsed, dict)
        or parsed.get("format") != FORMAT
        or not isinstance(parsed.get("files"), list)
        or not isinstance(parsed.get("directories"), list)
    ):
        _fail("Invalid manifest.")
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in parsed["files"]:
        if not isinstance(entry, dict):
            _fail("Invalid manifest entry.")
        path, digest, size = entry.get("path"), entry.get("sha256"), entry.get("size_bytes")
        if (
            _valid_manifest_path(path, allow_root=False) is None
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or path in seen
        ):
            _fail("Invalid manifest entry.")
        seen.add(path)
        entries.append({"path": path, "sha256": digest, "size_bytes": size})
        if len(entries) > MAX_FILES:
            _fail(f"Manifest contains more than {MAX_FILES} files.")
    directories: list[str] = []
    for directory in parsed["directories"]:
        if _valid_manifest_path(directory, allow_root=True) is None or directory in seen:
            _fail("Invalid manifest directory.")
        seen.add(directory)
        directories.append(directory)
    if len(entries) + len(directories) > MAX_NODES or {"data", "sandbox"} - set(directories):
        _fail("Invalid manifest directory set.")
    return raw, entries, directories


def _validate_snapshot(
    snapshot: Path,
) -> tuple[
    bytes, list[dict[str, Any]], list[str], list[dict[str, Any]], list[str], list[dict[str, Any]], list[str]
]:
    root_entries = {entry.name for entry in os.scandir(snapshot)}
    if root_entries != {"data", "sandbox", "manifest.json"}:
        _fail("Snapshot contains unexpected top-level entries.")
    data = _require_directory(snapshot / "data", "snapshot data directory")
    sandbox = _require_directory(snapshot / "sandbox", "snapshot sandbox directory")
    raw_manifest, manifest, directories = _load_manifest(snapshot)
    data_files, data_directories = _scan_tree(data, "data")
    sandbox_files, sandbox_directories = _scan_tree(sandbox, "sandbox")
    actual = data_files + sandbox_files
    declared = {entry["path"]: entry for entry in manifest}
    if set(declared) != {entry["path"] for entry in actual}:
        _fail("Snapshot files do not exactly match the manifest.")
    if set(directories) != set(data_directories + sandbox_directories):
        _fail("Snapshot directories do not exactly match the manifest.")
    for entry in actual:
        digest, size = _hash_file(entry["source"], entry["fingerprint"])
        if digest != declared[entry["path"]]["sha256"] or size != declared[entry["path"]]["size_bytes"]:
            _fail(f"Snapshot hash mismatch: {entry['path']}")
    _validate_database(data)
    _validate_marker(sandbox)
    return (
        raw_manifest,
        manifest,
        directories,
        data_files,
        data_directories,
        sandbox_files,
        sandbox_directories,
    )


def restore_snapshot(snapshot_dir: str | Path, destination: str | Path) -> Path:
    """Verify a snapshot fully, then restore it into a strictly new directory."""
    snapshot = _require_directory(Path(snapshot_dir), "snapshot directory")
    raw_manifest, manifest, directories, data_files, data_directories, sandbox_files, sandbox_directories = (
        _validate_snapshot(snapshot)
    )
    target = _new_destination(Path(destination), (snapshot,))
    try:
        data_target = target / "data"
        sandbox_target = target / "sandbox"
        _private_directory(data_target)
        _private_directory(sandbox_target)
        copied = _copy_tree(data_files, data_target, "data", data_directories) + _copy_tree(
            sandbox_files, sandbox_target, "sandbox", sandbox_directories
        )
        copied.sort(key=lambda entry: entry["path"])
        if {entry["path"]: entry for entry in copied} != {entry["path"]: entry for entry in manifest}:
            _fail("Snapshot changed while restoring.")
        _validate_database(data_target)
        _validate_marker(sandbox_target)
        _write_manifest(target / "manifest.json", raw_manifest)
        _fsync_directory(target)
        return target
    except BaseException:
        _remove_created_tree(target)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--data-dir", required=True)
    create.add_argument("--sandbox-dir", required=True)
    create.add_argument("--destination", required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--snapshot", required=True)
    restore.add_argument("--destination", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            result = create_snapshot(args.data_dir, args.sandbox_dir, args.destination)
        else:
            result = restore_snapshot(args.snapshot, args.destination)
    except SnapshotError as error:
        print(f"snapshot: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"destination": str(result)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
