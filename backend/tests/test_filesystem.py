from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path

from wiseway.filesystem import (
    InvalidPath,
    NotRegularFile,
    SafeFilesystem,
    SourceChanged,
    TargetExists,
)


class SafeFilesystemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "incoming").mkdir()
        (self.root / "archive").mkdir()
        self.fs = SafeFilesystem(self.root)

    def tearDown(self) -> None:
        self.fs.close()
        self.temp.cleanup()

    def write(self, relative: str, content: bytes = b"payload") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_stat_returns_identity_for_regular_file_only(self) -> None:
        self.write("incoming/report.pdf", b"abc")

        identity = self.fs.stat("incoming/report.pdf")

        self.assertEqual(identity["size"], 3)
        self.assertEqual(set(identity), {"dev", "ino", "size", "mtime_ns"})
        self.assertIsNone(self.fs.stat("incoming/missing.pdf"))
        self.assertIsNone(self.fs.stat("incoming"))

    def test_rejects_traversal_absolute_paths_and_links(self) -> None:
        self.write("incoming/report.pdf")
        os.symlink("report.pdf", self.root / "incoming" / "linked.pdf")
        for invalid in ("../incoming/report.pdf", "/incoming/report.pdf", "incoming//report.pdf"):
            with self.assertRaises(InvalidPath):
                self.fs.stat(invalid)
        self.assertIsNone(self.fs.stat("incoming/linked.pdf"))
        with self.assertRaises(NotRegularFile):
            self.fs.rename_no_replace("incoming/linked.pdf", "archive/x.pdf", {})

    def test_walk_recursively_returns_regular_file_metadata_and_skips_links(self) -> None:
        self.write("incoming/a.pdf", b"a")
        self.write("incoming/nested/b.pdf", b"bb")
        os.symlink(self.root / "incoming" / "nested", self.root / "incoming" / "link-dir")

        files = self.fs.walk("incoming")

        self.assertEqual([path for path, _ in files], ["incoming/a.pdf", "incoming/nested/b.pdf"])
        self.assertEqual(files[1][1]["size"], 2)

    def test_rename_is_atomic_no_replace_and_preserves_contents(self) -> None:
        self.write("incoming/report.pdf", b"source")
        expected = self.fs.stat("incoming/report.pdf")

        self.fs.rename_no_replace("incoming/report.pdf", "archive/report.pdf", expected)

        self.assertFalse((self.root / "incoming/report.pdf").exists())
        self.assertEqual((self.root / "archive/report.pdf").read_bytes(), b"source")

    def test_existing_target_is_never_overwritten(self) -> None:
        self.write("incoming/report.pdf", b"source")
        self.write("archive/report.pdf", b"existing")
        expected = self.fs.stat("incoming/report.pdf")

        with self.assertRaises(TargetExists):
            self.fs.rename_no_replace("incoming/report.pdf", "archive/report.pdf", expected)

        self.assertEqual((self.root / "incoming/report.pdf").read_bytes(), b"source")
        self.assertEqual((self.root / "archive/report.pdf").read_bytes(), b"existing")

    def test_exists_treats_symlinks_and_directories_as_occupied(self) -> None:
        (self.root / "archive" / "folder").mkdir()
        os.symlink("folder", self.root / "archive" / "link")

        self.assertTrue(self.fs.exists("archive/folder"))
        self.assertTrue(self.fs.exists("archive/link"))
        self.assertFalse(self.fs.exists("archive/missing"))

    def test_changed_source_is_rejected_before_move(self) -> None:
        self.write("incoming/report.pdf", b"old")
        expected = self.fs.stat("incoming/report.pdf")
        self.write("incoming/report.pdf", b"replacement")

        with self.assertRaises(SourceChanged):
            self.fs.rename_no_replace("incoming/report.pdf", "archive/report.pdf", expected)

        self.assertTrue((self.root / "incoming/report.pdf").exists())

    def test_never_creates_a_missing_target_directory(self) -> None:
        self.write("incoming/report.pdf", b"source")
        expected = self.fs.stat("incoming/report.pdf")

        with self.assertRaises(FileNotFoundError):
            self.fs.rename_no_replace("incoming/report.pdf", "not-created/report.pdf", expected)

        self.assertTrue((self.root / "incoming/report.pdf").exists())
        self.assertFalse((self.root / "not-created").exists())

    def test_competing_moves_of_one_source_have_one_winner(self) -> None:
        self.write("incoming/report.pdf", b"source")
        expected = self.fs.stat("incoming/report.pdf")
        barrier = threading.Barrier(2)
        outcomes: list[object] = []

        def move(target: str) -> None:
            barrier.wait()
            try:
                self.fs.rename_no_replace("incoming/report.pdf", target, expected)
                outcomes.append("moved")
            except Exception as error:  # the specific loser depends on syscall timing
                outcomes.append(type(error))

        first = threading.Thread(target=move, args=("archive/one.pdf",))
        second = threading.Thread(target=move, args=("archive/two.pdf",))
        first.start()
        second.start()
        first.join()
        second.join()

        self.assertEqual(outcomes.count("moved"), 1)
        self.assertEqual(
            sum(path.exists() for path in (self.root / "archive/one.pdf", self.root / "archive/two.pdf")), 1
        )


if __name__ == "__main__":
    unittest.main()
