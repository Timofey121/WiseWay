#!/usr/bin/env python3
"""Measure one synthetic metadata index rebuild without using application data.

Run from the repository root.  Set ``WISEWAY_BENCHMARK_BACKEND`` to compare a
different backend checkout while keeping this reproducible harness unchanged.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import time


BACKEND = Path(os.environ.get("WISEWAY_BENCHMARK_BACKEND", Path(__file__).resolve().parents[1]))
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from wiseway.common import Settings  # noqa: E402
from wiseway.indexer import Indexer  # noqa: E402
from wiseway.seed import initialize  # noqa: E402
from wiseway.services import Context  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=9_500, help="synthetic archive files to add")
    options = parser.parse_args()
    if options.files < 1:
        parser.error("--files must be positive")

    with tempfile.TemporaryDirectory(prefix="wiseway-indexer-benchmark-") as temporary:
        base = Path(temporary)
        settings = Settings(data_dir=base / "state", sandbox_dir=base / "sandbox")
        initialize(settings, password="synthetic-benchmark-password")
        directory = settings.sandbox_dir / "Archive" / "zzzz-indexer-benchmark"
        directory.mkdir()
        for number in range(options.files):
            (directory / f"file-{number:08d}.pdf").touch()
        context = Context(settings)
        try:
            started = time.perf_counter()
            Indexer(context).scan()
            elapsed = time.perf_counter() - started
            with context.store.transaction(write=False) as tx:
                indexed = len(tx.require("index", "archive-root")["items"])
        finally:
            context.close()

    print(
        json.dumps(
            {
                "scope": "single local rebuild; includes filesystem walk, metadata parsing and SQLite writes",
                "ordinary_files_added": options.files,
                "archive_indexed_items": indexed,
                "elapsed_seconds": round(elapsed, 3),
                "runtime": {"python": platform.python_version(), "platform": platform.platform()},
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
