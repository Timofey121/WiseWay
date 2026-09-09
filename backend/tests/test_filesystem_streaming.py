from __future__ import annotations

import os

import pytest

from wiseway.filesystem import SafeFilesystem, ScanLimitExceeded, ScanLimits


def _record_opened_directory(monkeypatch, fs):
    opened = []
    original = fs._open_directory

    def record(parts):
        descriptor = original(parts)
        opened.append(descriptor)
        return descriptor

    monkeypatch.setattr(fs, "_open_directory", record)
    return opened


def _record_duplicates(monkeypatch):
    duplicates = []
    original = os.dup

    def record(descriptor):
        duplicate = original(descriptor)
        duplicates.append(duplicate)
        return duplicate

    monkeypatch.setattr("wiseway.filesystem.os.dup", record)
    return duplicates


def test_streaming_iterator_yields_before_scanning_entire_directory(tmp_path, monkeypatch):
    for number in range(100):
        (tmp_path / f"file-{number:03d}.txt").write_text("x")
    with SafeFilesystem(tmp_path) as fs:
        calls = 0
        original_stat = os.stat

        def count_stat(*args, **kwargs):
            nonlocal calls
            if kwargs.get("dir_fd") is not None:
                calls += 1
            return original_stat(*args, **kwargs)

        monkeypatch.setattr("wiseway.filesystem.os.stat", count_stat)
        iterator = fs.iter_files("")
        path, identity = next(iterator)
        iterator.close()

    assert path.startswith("file-")
    assert identity["size"] == 1
    assert calls == 1


def test_streaming_iterator_close_releases_open_start_descriptor(tmp_path, monkeypatch):
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "file.txt").write_text("x")
    with SafeFilesystem(tmp_path) as fs:
        opened = _record_opened_directory(monkeypatch, fs)
        duplicates = _record_duplicates(monkeypatch)
        iterator = fs.iter_files("")
        next(iterator)
        iterator.close()

        with pytest.raises(OSError):
            os.fstat(opened[0])
        for descriptor in duplicates:
            with pytest.raises(OSError):
                os.fstat(descriptor)


def test_streaming_iterator_error_releases_open_start_descriptor(tmp_path, monkeypatch):
    (tmp_path / "file.txt").write_text("x")
    with SafeFilesystem(tmp_path, scan_limits=ScanLimits(max_entries=0)) as fs:
        opened = _record_opened_directory(monkeypatch, fs)
        duplicates = _record_duplicates(monkeypatch)
        with pytest.raises(ScanLimitExceeded):
            next(fs.iter_files(""))

        with pytest.raises(OSError):
            os.fstat(opened[0])
        for descriptor in duplicates:
            with pytest.raises(OSError):
                os.fstat(descriptor)


def test_streaming_iterator_keeps_walk_nonfollow_semantics(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "regular.txt").write_text("x")
    (tmp_path / "nested" / "deep.txt").write_text("xx")
    os.symlink("regular.txt", tmp_path / "file-link.txt")
    os.symlink("nested", tmp_path / "directory-link")

    with SafeFilesystem(tmp_path) as fs:
        rows = list(fs.iter_files(""))

    assert {path for path, _ in rows} == {"regular.txt", "nested/deep.txt"}
