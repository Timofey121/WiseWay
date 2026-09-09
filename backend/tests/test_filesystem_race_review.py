from __future__ import annotations

import os

import pytest

from wiseway.common import Settings
from wiseway.filesystem import PostRenameChanged, SafeFilesystem
from wiseway.storage import Store
from wiseway.worker import Worker


class _WorkerContext:
    def __init__(self, root) -> None:
        self.settings = Settings(data_dir=root / "state", sandbox_dir=root / "sandbox")
        self.store = Store(self.settings.database)
        self.fs = SafeFilesystem(self.settings.sandbox_dir)
        self.bases = {"incoming-root": "incoming", "archive-root": "archive", "quarantine-root": "quarantine"}

    def close(self) -> None:
        self.fs.close()

    def location(self, tx, root_id, relative_path):
        return _location(root_id, relative_path)

    def physical(self, tx, location):
        return f"{self.bases[location['root_id']]}/{location['relative_path']}"

    def exists(self, tx, location):
        return self.fs.exists(self.physical(tx, location))


def _location(root_id: str, relative_path: str) -> dict:
    return {
        "root_id": root_id,
        "relative_path": relative_path,
        "display_path": f"DEMO:/{root_id}/{relative_path}",
    }


def _worker_context(tmp_path):
    root = tmp_path / "worker"
    for directory in ("incoming/team", "archive/team", "quarantine/team"):
        (root / "sandbox" / directory).mkdir(parents=True)
    context = _WorkerContext(root)
    source = root / "sandbox/incoming/team/report.txt"
    source.write_bytes(b"trusted payload")
    expected = context.fs.stat("incoming/team/report.txt")
    source_location = _location("incoming-root", "team/report.txt")
    target = _location("archive-root", "team/report.txt")
    item = {
        "item_id": "item-1",
        "item_revision": 1,
        "company_id": "company-1",
        "filename": "report.txt",
        "source": source_location,
        "status": "PROCESSING",
        "selectable": False,
        "_fingerprint": expected,
    }
    attempt = {
        "attempt_id": "attempt-1",
        "batch_id": "batch-1",
        "company_id": "company-1",
        "actor": {"user_id": "user-1", "login": "worker", "display_name": "Worker", "role": "WORKER"},
        "request_id": "request-1",
        "item": item,
        "plan": {
            "predicted_state": "WILL_MOVE",
            "reason_code": None,
            "target": target,
            "selected_rule": None,
        },
        "outcome": {
            "attempt_id": "attempt-1",
            "item_id": "item-1",
            "item_revision": 1,
            "state": "PENDING",
            "reason_code": None,
            "source": source_location,
            "planned_target": target,
            "actual_location": None,
            "matched_rule": None,
            "started_at": None,
            "finished_at": None,
        },
        "phase": "QUEUED",
        "intent_target": None,
        "intended_state": None,
        "intended_reason": None,
    }
    with context.store.transaction() as tx:
        tx.put("company", "company-1", {"company_id": "company-1", "_folder": "team"})
        tx.put("queue", "item-1", item)
        tx.put("attempt", "attempt-1", attempt)
        tx.put("claim", "item-1", {"attempt_id": "attempt-1", "batch_id": "batch-1"})
    return context, source, target


def _assert_recovery(context, target) -> None:
    with context.store.transaction(write=False) as tx:
        attempt = tx.require("attempt", "attempt-1")
        assert attempt["phase"] == "RECOVERY_REQUIRED"
        assert attempt["outcome"]["state"] == "RECOVERY_REQUIRED"
        assert attempt["intent_target"] == target
        assert tx.list("quarantine") == []


def test_post_rename_ambiguity_never_quarantines_a_restored_source(tmp_path, monkeypatch) -> None:
    context, source, target = _worker_context(tmp_path)
    original_rename = context.fs.rename_no_replace
    calls = 0

    def move_restore_and_report_ambiguity(source_path, target_path, expected):
        nonlocal calls
        calls += 1
        if calls > 1:
            return original_rename(source_path, target_path, expected)
        original_rename(source_path, target_path, expected)
        os.link(context.settings.sandbox_dir / target_path, context.settings.sandbox_dir / source_path)
        raise PostRenameChanged("simulated post-rename ambiguity")

    monkeypatch.setattr(context.fs, "rename_no_replace", move_restore_and_report_ambiguity)
    try:
        assert Worker(context).run_once() == 1
        _assert_recovery(context, target)
        assert source.read_bytes() == b"trusted payload"
    finally:
        context.close()


def test_worker_symlink_race_preserves_intent_and_requires_recovery(tmp_path, monkeypatch) -> None:
    context, source, target = _worker_context(tmp_path)
    external = tmp_path / "external.txt"
    external.write_bytes(b"external payload")
    original_rename = context.fs._rename_exclusive

    def substitute_source(source_fd, source_name, target_fd, target_name):
        source.rename(context.settings.sandbox_dir / "incoming/team/displaced.txt")
        os.symlink(external, source)
        return original_rename(source_fd, source_name, target_fd, target_name)

    monkeypatch.setattr(context.fs, "_rename_exclusive", substitute_source)
    try:
        assert Worker(context).run_once() == 1
        _assert_recovery(context, target)
        assert external.read_bytes() == b"external payload"
        assert (context.settings.sandbox_dir / "archive/team/report.txt").is_symlink()
    finally:
        context.close()


def test_source_symlink_substitution_after_final_check_requires_recovery(tmp_path, monkeypatch) -> None:
    sandbox = tmp_path / "sandbox"
    incoming = sandbox / "incoming"
    archive = sandbox / "archive"
    external = tmp_path / "external.txt"
    incoming.mkdir(parents=True)
    archive.mkdir()
    source = incoming / "report.txt"
    source.write_bytes(b"trusted payload")
    external.write_bytes(b"external payload")

    with SafeFilesystem(sandbox) as filesystem:
        expected = filesystem.stat("incoming/report.txt")
        original_rename = filesystem._rename_exclusive

        def substitute_source(source_fd, source_name, target_fd, target_name):
            source.rename(sandbox / "displaced.txt")
            os.symlink(external, source)
            return original_rename(source_fd, source_name, target_fd, target_name)

        monkeypatch.setattr(filesystem, "_rename_exclusive", substitute_source)
        with pytest.raises(PostRenameChanged):
            filesystem.rename_no_replace("incoming/report.txt", "archive/report.txt", expected)

    assert external.read_bytes() == b"external payload"
    assert (archive / "report.txt").is_symlink()


def test_regular_source_substitution_after_final_check_requires_recovery(tmp_path, monkeypatch) -> None:
    sandbox = tmp_path / "sandbox"
    incoming = sandbox / "incoming"
    archive = sandbox / "archive"
    external = tmp_path / "external.txt"
    incoming.mkdir(parents=True)
    archive.mkdir()
    source = incoming / "report.txt"
    source.write_bytes(b"trusted payload")
    external.write_bytes(b"external payload")

    with SafeFilesystem(sandbox) as filesystem:
        expected = filesystem.stat("incoming/report.txt")
        original_rename = filesystem._rename_exclusive

        def substitute_source(source_fd, source_name, target_fd, target_name):
            source.rename(sandbox / "displaced.txt")
            source.write_bytes(b"replacement payload")
            return original_rename(source_fd, source_name, target_fd, target_name)

        monkeypatch.setattr(filesystem, "_rename_exclusive", substitute_source)
        with pytest.raises(PostRenameChanged):
            filesystem.rename_no_replace("incoming/report.txt", "archive/report.txt", expected)

    assert external.read_bytes() == b"external payload"
    assert (archive / "report.txt").read_bytes() == b"replacement payload"


def test_parent_symlink_substitution_before_rename_keeps_move_inside_open_directory(
    tmp_path, monkeypatch
) -> None:
    sandbox = tmp_path / "sandbox"
    incoming = sandbox / "incoming"
    archive = sandbox / "archive"
    external = tmp_path / "external"
    incoming.mkdir(parents=True)
    archive.mkdir()
    external.mkdir()
    source = incoming / "report.txt"
    source.write_bytes(b"trusted payload")
    external_target = external / "report.txt"
    external_target.write_bytes(b"external payload")

    with SafeFilesystem(sandbox) as filesystem:
        expected = filesystem.stat("incoming/report.txt")
        original_rename = filesystem._rename_exclusive

        def substitute_parent(source_fd, source_name, target_fd, target_name):
            incoming.rename(sandbox / "incoming-original")
            os.symlink(external, incoming)
            return original_rename(source_fd, source_name, target_fd, target_name)

        monkeypatch.setattr(filesystem, "_rename_exclusive", substitute_parent)
        filesystem.rename_no_replace("incoming/report.txt", "archive/report.txt", expected)

    assert external_target.read_bytes() == b"external payload"
    assert (archive / "report.txt").read_bytes() == b"trusted payload"
