from dataclasses import replace

import pytest

from wiseway.filesystem import SafeFilesystem, ScanLimitExceeded, ScanLimits
from wiseway.indexer import Indexer
from wiseway.services import Context


def test_scan_counts_directories_and_ignored_entries_before_accumulating(tmp_path):
    for number in range(4):
        (tmp_path / str(number)).mkdir()
    with SafeFilesystem(tmp_path, scan_limits=ScanLimits(max_entries=3)) as fs:
        with pytest.raises(ScanLimitExceeded):
            fs.walk("")
    with SafeFilesystem(tmp_path, scan_limits=ScanLimits(max_entries=4)) as fs:
        assert fs.walk("") == []


@pytest.mark.parametrize("boundary", ["depth", "path_bytes", "time"])
def test_scan_fails_at_resource_boundary(tmp_path, monkeypatch, boundary):
    (tmp_path / "one" / "two").mkdir(parents=True)
    (tmp_path / "one" / "two" / "file.txt").write_bytes(b"payload")
    limits = ScanLimits()
    if boundary == "depth":
        limits = replace(limits, max_depth=1)
    elif boundary == "path_bytes":
        limits = replace(limits, max_path_bytes=3)
    else:
        ticks = iter([0.0, 31.0])
        monkeypatch.setattr("wiseway.filesystem.time.monotonic", lambda: next(ticks))
    with SafeFilesystem(tmp_path, scan_limits=limits) as fs:
        with pytest.raises(ScanLimitExceeded):
            fs.walk("")
    assert (tmp_path / "one" / "two" / "file.txt").read_bytes() == b"payload"


def test_over_budget_scan_keeps_last_complete_index_and_queue(configured):
    with_context = Context(configured)
    try:
        Indexer(with_context).scan()
        with with_context.store.transaction(write=False) as tx:
            old_index = tx.require("index", "archive-root")
            old_queue = tx.list("queue")
        archive = configured.sandbox_dir / "Archive"
        incoming = configured.sandbox_dir / "Incoming" / "Atlas"
        for number in range(4):
            (archive / f"extra-{number}.txt").write_text("archive")
            (incoming / f"extra-{number}.txt").write_text("incoming")
        with_context.fs.scan_limits = ScanLimits(max_entries=3)
        Indexer(with_context).scan()
        with with_context.store.transaction(write=False) as tx:
            current = tx.require("index", "archive-root")
            assert current["items"] == old_index["items"]
            assert current["root"] == old_index["root"]
            assert current["freshness"]["status"] == "STALE"
            assert tx.list("queue") == old_queue
            assert tx.require("index_progress", "incoming-incoming-atlas")["status"] == "FAILED"
        assert all((incoming / f"extra-{number}.txt").exists() for number in range(4))
    finally:
        with_context.close()
