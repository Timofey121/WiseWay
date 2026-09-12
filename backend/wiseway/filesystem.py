"""Fail-closed primitives for the synthetic Wise Way filesystem sandbox.

Callers use only POSIX-relative paths.  This adapter deliberately exposes no
copy/delete operation: a sorting move must be a same-filesystem, no-replace
rename or fail before changing a file.
"""

from __future__ import annotations

import ctypes
import errno
import os
import stat as stat_module
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final


class FilesystemError(RuntimeError):
    """Base error for a refused or failed sandbox operation."""


class InvalidPath(FilesystemError):
    pass


class NotRegularFile(FilesystemError):
    pass


class SourceChanged(FilesystemError):
    pass


class PostRenameChanged(FilesystemError):
    """A native rename returned, but its target cannot prove source identity.

    Callers must treat this as an ambiguous post-move outcome, rather than a
    pre-move source change that can safely be skipped or retried.
    """


class TargetExists(FilesystemError):
    pass


class UnsupportedFilesystem(FilesystemError):
    pass


class ScanLimitExceeded(FilesystemError):
    """The tree cannot be completely observed within the demo scan budget."""


@dataclass(frozen=True)
class ScanLimits:
    max_entries: int = 10_000
    max_depth: int = 64
    max_path_bytes: int = 8 * 1024 * 1024
    max_seconds: float = 30.0


@dataclass
class _ScanBudget:
    limits: ScanLimits
    deadline: float
    entries: int = 0
    path_bytes: int = 0

    def observe(self, path: str, depth: int) -> None:
        self.entries += 1
        self.path_bytes += len(os.fsencode(path))
        if (
            self.entries > self.limits.max_entries
            or depth > self.limits.max_depth
            or self.path_bytes > self.limits.max_path_bytes
            or time.monotonic() >= self.deadline
        ):
            raise ScanLimitExceeded("filesystem scan budget exceeded")


_DIRECTORY_FLAGS: Final[int] = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
_FILE_FLAGS: Final[int] = os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC
_NOFOLLOW: Final[int] = getattr(os, "O_NOFOLLOW", 0)
_DARWIN_RENAME_EXCL: Final[int] = 0x00000004
_LINUX_RENAME_NOREPLACE: Final[int] = 0x00000001


class SafeFilesystem:
    """A descriptor-anchored filesystem view rooted at one configured directory."""

    def __init__(self, sandbox: Path, *, scan_limits: ScanLimits | None = None) -> None:
        # ``resolve`` would silently accept a configured symlink.  Keep the
        # configured object itself and let O_NOFOLLOW reject such a root.
        self.sandbox = Path(os.path.abspath(sandbox))
        self.scan_limits = scan_limits or ScanLimits()
        if not self.sandbox.is_dir():
            raise NotADirectoryError(self.sandbox)
        self._root_fd = os.open(self.sandbox, _DIRECTORY_FLAGS | _NOFOLLOW)
        root_stat = os.fstat(self._root_fd)
        if not stat_module.S_ISDIR(root_stat.st_mode):
            self.close()
            raise NotADirectoryError(self.sandbox)

    def close(self) -> None:
        if getattr(self, "_root_fd", None) is not None:
            os.close(self._root_fd)
            self._root_fd = None

    def __enter__(self) -> "SafeFilesystem":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def probe(self) -> bool:
        """Whether this process can provide the required atomic no-replace move."""
        libc = ctypes.CDLL(None)
        if sys.platform == "darwin":
            return hasattr(libc, "renameatx_np")
        if sys.platform.startswith("linux"):
            return hasattr(libc, "renameat2")
        return False

    def stat(self, relative: str) -> dict[str, int] | None:
        """Return identity metadata for a regular non-link file, else ``None``."""
        try:
            parent_fd, leaf = self._open_parent(relative)
        except FileNotFoundError:
            return None
        try:
            try:
                descriptor = os.open(leaf, _FILE_FLAGS | _NOFOLLOW, dir_fd=parent_fd)
            except (FileNotFoundError, OSError) as error:
                if isinstance(error, OSError) and error.errno not in (
                    errno.ENOENT,
                    errno.ELOOP,
                    errno.EISDIR,
                ):
                    raise
                return None
            try:
                item_stat = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            if not stat_module.S_ISREG(item_stat.st_mode):
                return None
            return self._identity(item_stat)
        finally:
            os.close(parent_fd)

    def exists(self, relative: str) -> bool:
        """Return whether any non-followed directory entry occupies ``relative``.

        This intentionally differs from :meth:`stat`: a directory, symlink or
        special file occupies a target name and must prevent a no-replace move.
        """
        try:
            parent_fd, leaf = self._open_parent(relative)
        except FileNotFoundError:
            return False
        try:
            try:
                os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                return False
            return True
        finally:
            os.close(parent_fd)

    def is_directory(self, relative: str) -> bool:
        """Return true only for an existing non-link directory inside the sandbox."""
        try:
            parts = self._parts(relative, allow_empty=True)
            descriptor = self._open_directory(parts)
        except (FileNotFoundError, NotADirectoryError, OSError):
            return False
        else:
            os.close(descriptor)
            return True

    def walk(self, relative_dir: str) -> list[tuple[str, dict[str, int]]]:
        """Recursively list regular files without reading file content or following links."""
        parts = self._parts(relative_dir, allow_empty=True)
        start_fd = self._open_directory(parts)
        prefix = "/".join(parts)
        found: list[tuple[str, dict[str, int]]] = []
        budget = _ScanBudget(self.scan_limits, time.monotonic() + self.scan_limits.max_seconds)
        try:
            self._walk_fd(start_fd, prefix, found, budget, 0)
        finally:
            os.close(start_fd)
        return sorted(found)

    def iter_files(
        self, relative_dir: str, *, limits: ScanLimits | None = None
    ) -> Iterator[tuple[str, dict[str, int]]]:
        """Yield regular files below a directory without accumulating the tree.

        The yielded order is the filesystem's directory-entry order.  Callers
        that need a stable global order must arrange it in durable storage;
        sorting here would defeat the bounded-memory property.  As with
        :meth:`walk`, links are never followed and every observed directory
        entry consumes the configured resource budget.
        """
        parts = self._parts(relative_dir, allow_empty=True)
        start_fd = self._open_directory(parts)
        prefix = "/".join(parts)
        budget = _ScanBudget(
            limits or self.scan_limits, time.monotonic() + (limits or self.scan_limits).max_seconds
        )
        try:
            yield from self._iter_files_fd(start_fd, prefix, budget, 0)
        finally:
            os.close(start_fd)

    def rename_no_replace(self, source: str, target: str, expected: dict[str, int]) -> None:
        """Atomically rename a verified regular file, refusing an occupied target."""
        if not self.probe():
            raise UnsupportedFilesystem("atomic no-replace rename is unavailable on this platform")
        source_parent, source_leaf = self._open_parent(source)
        try:
            target_parent, target_leaf = self._open_parent(target)
            try:
                source_stat = self._lstat_regular(source_parent, source_leaf)
                self._require_identity(source_stat, expected)
                # This is deliberately the last check before the native atomic operation.
                source_stat = self._lstat_regular(source_parent, source_leaf)
                self._require_identity(source_stat, expected)
                self._rename_exclusive(source_parent, source_leaf, target_parent, target_leaf)
                self._verify_and_fsync_after_rename(target_parent, target_leaf, source_parent, expected)
            finally:
                os.close(target_parent)
        finally:
            os.close(source_parent)

    def _walk_fd(self, directory_fd, prefix, found, budget, depth) -> None:
        # Iterate directory entries before sorting the bounded result. listdir
        # would allocate the entire directory before we could enforce a limit.
        with os.scandir(directory_fd) as entries:
            for entry in entries:
                path = f"{prefix}/{entry.name}" if prefix else entry.name
                budget.observe(path, depth)
                try:
                    item_stat = os.stat(entry.name, dir_fd=directory_fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue  # concurrent removal: a later reconciliation discovers the result
                if stat_module.S_ISREG(item_stat.st_mode):
                    found.append((path, self._identity(item_stat)))
                elif stat_module.S_ISDIR(item_stat.st_mode):
                    if depth >= budget.limits.max_depth:
                        raise ScanLimitExceeded("filesystem scan depth exceeded")
                    # An unreadable/replaced child makes the complete scan fail.
                    child_fd = os.open(entry.name, _DIRECTORY_FLAGS | _NOFOLLOW, dir_fd=directory_fd)
                    try:
                        self._walk_fd(child_fd, path, found, budget, depth + 1)
                    finally:
                        os.close(child_fd)
                # Links and special files are ignored, but still consume budget.

    def _iter_files_fd(self, directory_fd, prefix, budget, depth) -> Iterator[tuple[str, dict[str, int]]]:
        """Descriptor-owned streaming counterpart to :meth:`_walk_fd`."""
        # Keep scandir's lifetime separate from the caller-owned descriptor.
        # CPython currently leaves an integer fd passed to scandir open, while
        # another implementation may close it; always close our duplicate and
        # tolerate the latter behavior.
        scan_fd = os.dup(directory_fd)
        try:
            with os.scandir(scan_fd) as entries:
                for entry in entries:
                    path = f"{prefix}/{entry.name}" if prefix else entry.name
                    budget.observe(path, depth)
                    try:
                        item_stat = os.stat(entry.name, dir_fd=directory_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    if stat_module.S_ISREG(item_stat.st_mode):
                        yield path, self._identity(item_stat)
                    elif stat_module.S_ISDIR(item_stat.st_mode):
                        if depth >= budget.limits.max_depth:
                            raise ScanLimitExceeded("filesystem scan depth exceeded")
                        child_fd = os.open(entry.name, _DIRECTORY_FLAGS | _NOFOLLOW, dir_fd=directory_fd)
                        try:
                            yield from self._iter_files_fd(child_fd, path, budget, depth + 1)
                        finally:
                            os.close(child_fd)
        finally:
            try:
                os.close(scan_fd)
            except OSError as error:
                if error.errno != errno.EBADF:
                    raise

    def _open_parent(self, relative: str) -> tuple[int, str]:
        parts = self._parts(relative)
        return self._open_directory(parts[:-1]), parts[-1]

    def _open_directory(self, parts: list[str]) -> int:
        root_fd = self._require_open()
        descriptor = os.dup(root_fd)
        try:
            for component in parts:
                next_descriptor = os.open(component, _DIRECTORY_FLAGS | _NOFOLLOW, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_descriptor
            if not stat_module.S_ISDIR(os.fstat(descriptor).st_mode):
                raise NotADirectoryError("/".join(parts))
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def _parts(self, relative: str, *, allow_empty: bool = False) -> list[str]:
        if not isinstance(relative, str) or "\\" in relative or "\x00" in relative:
            raise InvalidPath("path must be a POSIX relative path")
        if relative == "" and allow_empty:
            return []
        if relative == "" or relative.startswith("/") or relative.endswith("/"):
            raise InvalidPath("path must name an object below the sandbox")
        parts = relative.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise InvalidPath("path traversal is not allowed")
        return parts

    def _lstat_regular(self, parent_fd: int, leaf: str) -> os.stat_result:
        try:
            item_stat = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            raise SourceChanged("source disappeared") from None
        if not stat_module.S_ISREG(item_stat.st_mode):
            raise NotRegularFile("source must be a regular non-link file")
        return item_stat

    @staticmethod
    def _identity(item_stat: os.stat_result) -> dict[str, int]:
        return {
            "dev": item_stat.st_dev,
            "ino": item_stat.st_ino,
            "size": item_stat.st_size,
            "mtime_ns": item_stat.st_mtime_ns,
        }

    def _require_identity(self, item_stat: os.stat_result, expected: dict[str, int]) -> None:
        if not isinstance(expected, dict) or self._identity(item_stat) != expected:
            raise SourceChanged("source identity changed since planning")

    def _verify_and_fsync_after_rename(
        self, target_parent_fd: int, target: str, source_parent_fd: int, expected: dict[str, int]
    ) -> None:
        """Verify the moved descriptor, then flush it and both directories."""
        try:
            file_fd = os.open(target, _FILE_FLAGS | _NOFOLLOW, dir_fd=target_parent_fd)
        except OSError as error:
            if error.errno in (errno.ENOENT, errno.ELOOP):
                raise PostRenameChanged("target changed after native rename") from None
            raise
        try:
            item_stat = os.fstat(file_fd)
            if not stat_module.S_ISREG(item_stat.st_mode) or self._identity(item_stat) != expected:
                raise PostRenameChanged("target identity changed after native rename")
            os.fsync(file_fd)
        finally:
            os.close(file_fd)
        for descriptor in {target_parent_fd, source_parent_fd}:
            try:
                os.fsync(descriptor)
            except OSError as error:
                if error.errno not in (errno.EINVAL, errno.ENOTSUP):
                    raise

    @staticmethod
    def _rename_exclusive(source_fd: int, source: str, target_fd: int, target: str) -> None:
        libc = ctypes.CDLL(None, use_errno=True)
        if sys.platform == "darwin":
            native_rename = libc.renameatx_np
            flags = _DARWIN_RENAME_EXCL
        elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
            native_rename = libc.renameat2
            flags = _LINUX_RENAME_NOREPLACE
        else:
            raise UnsupportedFilesystem("atomic no-replace rename is unavailable on this platform")
        native_rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        native_rename.restype = ctypes.c_int
        result = native_rename(source_fd, os.fsencode(source), target_fd, os.fsencode(target), flags)
        if result == 0:
            return
        error_number = ctypes.get_errno()
        if error_number == errno.EEXIST:
            raise TargetExists("target already exists")
        if error_number in (errno.ENOENT, errno.ELOOP):
            raise SourceChanged("source changed before move")
        raise OSError(error_number, os.strerror(error_number))

    def _require_open(self) -> int:
        if self._root_fd is None:
            raise FilesystemError("filesystem adapter is closed")
        return self._root_fd
