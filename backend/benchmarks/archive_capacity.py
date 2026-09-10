#!/usr/bin/env python3
"""Resumable OpenSearch capacity benchmark for synthetic archive metadata.

The benchmark never creates payload files.  It writes one bounded, immutable
NDJSON manifest at a time, imports it through ``ArchiveImporter``, checkpoints
the published generation, and only then removes that owned manifest.  A stopped
or crashed run therefore resumes the exact same full/delta source safely.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import time
import uuid
from threading import Event
from typing import Callable

from wiseway.archive_import import ArchiveImporter
from wiseway.common import Settings
from wiseway.seed import initialize
from wiseway.services import Context

from million import PASSWORD, ROOT_ID, peak_rss_mib, query
from archive_corpus import get_corpus, query_diverse


FORMAT = "wise-way-capacity-v2"


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + f".tmp-{uuid.uuid4().hex}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, sort_keys=True, indent=2)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


@contextmanager
def _capacity_lock(directory: Path):
    import fcntl

    path = directory / ".capacity.lock"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Another capacity benchmark process is running") from error
        yield
    finally:
        os.close(descriptor)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _regular(path: Path, label: str) -> None:
    try:
        info = path.lstat()
    except OSError as error:
        raise ValueError(f"Capacity benchmark {label} is unavailable") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError(f"Capacity benchmark {label} must be a regular non-symlink file")


class _GuardedStop:
    def __init__(self, supplied: Event, guard: Callable[[], None]):
        self.supplied, self.guard = supplied, guard

    def is_set(self) -> bool:
        self.guard()
        return self.supplied.is_set()


class CapacityRun:
    """Own one marker directory and extend its deterministic corpus in chunks."""

    def __init__(
        self,
        directory: Path,
        ctx,
        engine,
        *,
        chunk_records: int = 1_000_000,
        corpus: str = "baseline",
        shards: int = 8,
        batch_size: int = 1000,
        min_free_bytes: int = 20 * 1024**3,
        free_bytes: Callable[[Path], int] | None = None,
    ):
        if not 1 <= chunk_records <= 1_000_000:
            raise ValueError("chunk_records must be 1..1000000")
        if not 1 <= shards <= 128 or not 1 <= batch_size <= 5000:
            raise ValueError("shards must be 1..128 and batch_size must be 1..5000")
        if min_free_bytes < 0:
            raise ValueError("min_free_bytes must be non-negative")
        self.directory = directory.absolute()
        self.ctx, self.engine = ctx, engine
        self.corpus = get_corpus(corpus)
        self.chunk_records, self.shards, self.batch_size = chunk_records, shards, batch_size
        self.min_free_bytes = min_free_bytes
        self.free_bytes = free_bytes or (lambda path: shutil.disk_usage(path).free)
        self.marker = self.directory / ".wiseway-capacity.json"
        self.progress_file = self.directory / "progress.json"
        self.chunks = self.directory / "chunks"
        self._last_engine_check = 0.0
        self._prepare()

    @property
    def configuration(self) -> dict:
        return {
            "format": FORMAT,
            "corpus": self.corpus.name,
            "root_id": ROOT_ID,
            "chunk_records": self.chunk_records,
            "shards": self.shards,
            "batch_size": self.batch_size,
        }

    @classmethod
    def prepare_directory(
        cls,
        directory: Path,
        chunk_records: int,
        corpus: str = "baseline",
        shards: int = 8,
        batch_size: int = 1000,
    ) -> None:
        """Create or validate only the benchmark ownership marker."""
        if not 1 <= chunk_records <= 1_000_000:
            raise ValueError("chunk_records must be 1..1000000")
        if not 1 <= shards <= 128 or not 1 <= batch_size <= 5000:
            raise ValueError("shards must be 1..128 and batch_size must be 1..5000")
        directory = directory.absolute()
        marker = directory / ".wiseway-capacity.json"
        configuration = {
            "format": FORMAT,
            "corpus": get_corpus(corpus).name,
            "root_id": ROOT_ID,
            "chunk_records": chunk_records,
            "shards": shards,
            "batch_size": batch_size,
        }
        if directory.is_symlink():
            raise ValueError("Capacity benchmark directory must not be a symlink")
        if directory.exists():
            if not marker.is_file():
                raise ValueError("Refusing an existing directory without a Wise Way capacity marker")
            _regular(marker, "marker")
            try:
                saved = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise ValueError("Invalid Wise Way capacity marker") from error
            if saved != configuration:
                raise ValueError("Capacity benchmark configuration mismatch")
            return
        directory.mkdir(parents=True)
        _atomic_json(marker, configuration)
        (directory / "chunks").mkdir()
        _atomic_json(
            directory / "progress.json",
            {
                "format": FORMAT,
                "corpus": get_corpus(corpus).name,
                "root_id": ROOT_ID,
                "completed_records": 0,
                "chunks_completed": 0,
                "index": None,
                "generation": None,
                "pending_chunk": None,
                "updated_at": time.time(),
            },
        )

    def _prepare(self) -> None:
        self.prepare_directory(
            self.directory, self.chunk_records, self.corpus.name, self.shards, self.batch_size
        )
        _regular(self.marker, "marker")
        _regular(self.progress_file, "progress")
        if self.chunks.is_symlink() or not self.chunks.is_dir():
            raise ValueError("Capacity benchmark chunks directory must not be a symlink")

    def status(self) -> dict:
        _regular(self.progress_file, "progress")
        try:
            progress = json.loads(self.progress_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RuntimeError("Capacity benchmark progress is unreadable") from error
        if progress.get("format") != FORMAT or progress.get("corpus") != self.corpus.name:
            raise RuntimeError("Capacity benchmark progress does not match its marker")
        if progress.get("root_id") != ROOT_ID or type(progress.get("completed_records")) is not int:
            raise RuntimeError("Capacity benchmark progress is malformed")
        return progress

    def _chunk_path(self, start: int, end: int) -> Path:
        return self.chunks / f"{start:012d}-{end:012d}.ndjson"

    def _source_guard(self, estimated_bytes: int = 0) -> None:
        available = self.free_bytes(self.directory)
        if available < self.min_free_bytes + estimated_bytes:
            raise RuntimeError("Capacity benchmark stopped: source filesystem free space is below its guard")

    def _engine_guard(self) -> None:
        # Importer asks ``stop.is_set`` for every batch.  Poll the remote file
        # system only periodically so a million-row chunk does not make a
        # thousand monitoring requests.
        if time.monotonic() - self._last_engine_check < 30:
            return
        self._last_engine_check = time.monotonic()
        request = getattr(self.engine, "request", None)
        if request is None:
            return
        stats = request("GET", "/_nodes/stats/fs", None)
        if not isinstance(stats, dict) or not isinstance(stats.get("nodes"), dict) or not stats["nodes"]:
            raise RuntimeError("Capacity benchmark stopped: search engine filesystem stats are incomplete")
        available = [
            value
            for node in stats.get("nodes", {}).values()
            for value in [node.get("fs", {}).get("total", {}).get("available_in_bytes")]
            if isinstance(value, int)
        ]
        if len(available) != len(stats["nodes"]):
            raise RuntimeError("Capacity benchmark stopped: search engine filesystem stats are incomplete")
        if min(available) < self.min_free_bytes:
            raise RuntimeError("Capacity benchmark stopped: search engine free space is below its guard")

    def _guard(self) -> None:
        self._source_guard()
        self._engine_guard()

    def _manifest(self, start: int, end: int, stop: Event | None = None) -> Path:
        path = self._chunk_path(start, end)
        if path.exists():
            _regular(path, "manifest")
            return path
        # A conservative source-only reservation bounds each temporary manifest.
        self._source_guard((end - start) * 512)
        temporary = path.with_suffix(path.suffix + ".pending")
        if temporary.exists():
            _regular(temporary, "pending manifest")
            temporary.unlink()
        try:
            with temporary.open("xb") as output:
                for number in range(start, end):
                    if number % 10_000 == 0:
                        self._guard()
                        if stop is not None and stop.is_set():
                            raise InterruptedError("Capacity manifest generation stopped")
                    output.write(_json_bytes(self.corpus.row(number)))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            _fsync_directory(self.chunks)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return path

    def _remove_acknowledged(self, completed: int) -> None:
        for path in self.chunks.glob("*.ndjson"):
            _regular(path, "manifest")
            try:
                start, end = (int(part) for part in path.stem.split("-", 1))
            except ValueError:
                continue
            if end <= completed:
                path.unlink()

    def _checkpoint(self, progress: dict, result: dict, end: int) -> dict:
        start = progress["completed_records"]
        if result.get("records") != end - start:
            raise RuntimeError("Capacity importer published an unexpected record count")
        saved = {
            **progress,
            "completed_records": end,
            "chunks_completed": progress["chunks_completed"] + 1,
            "index": result["index"],
            "generation": result["generation"],
            "pending_chunk": None,
            "updated_at": time.time(),
        }
        _atomic_json(self.progress_file, saved)
        self._remove_acknowledged(end)
        return saved

    def _pending(self, progress: dict, start: int, end: int) -> dict:
        """Expose a durable heartbeat before a potentially long import."""
        saved = {
            **progress,
            "pending_chunk": {"start": start, "end": end},
            "updated_at": time.time(),
        }
        _atomic_json(self.progress_file, saved)
        return saved

    def build(self, records: int, *, stop: Event | None = None) -> dict:
        if not 1 <= records <= 400_000_000:
            raise ValueError("records must be 1..400000000")
        stop = stop or Event()
        with _capacity_lock(self.directory):
            return self._build_locked(records, stop)

    def _build_locked(self, records: int, stop: Event) -> dict:
        progress = self.status()
        completed = progress["completed_records"]
        count_before = completed
        if not isinstance(completed, int) or completed < 0 or completed > records:
            raise ValueError("records target is below saved benchmark progress")
        self._install_schema(completed)
        self._remove_acknowledged(completed)
        importer = ArchiveImporter(self.ctx, self.engine, batch_size=self.batch_size, shards=self.shards)
        progress = self._maintain_generation(importer, progress)
        started = time.perf_counter()
        try:
            while completed < records:
                self._guard()
                pending = progress.get("pending_chunk")
                if pending is not None:
                    if (
                        not isinstance(pending, dict)
                        or pending.get("start") != completed
                        or type(pending.get("end")) is not int
                        or not completed < pending["end"] <= completed + self.chunk_records
                    ):
                        raise RuntimeError("Capacity benchmark pending chunk is malformed")
                    end = pending["end"]
                    if records < end:
                        raise ValueError("records target is below the pending immutable chunk")
                else:
                    end = min(records, completed + self.chunk_records)
                source = self._manifest(completed, end, stop)
                mode = "full" if completed == 0 else "delta"
                if pending is None:
                    progress = self._pending(progress, completed, end)
                result = importer.run(
                    ROOT_ID,
                    source,
                    mode=mode,
                    base_generation=progress["generation"] if mode == "delta" else None,
                    stop=_GuardedStop(stop, self._guard),
                )
                progress = self._checkpoint(progress, result, end)
                completed = end
                elapsed = time.perf_counter() - started
                print(
                    json.dumps(
                        {
                            "status": "BUILDING",
                            "completed_records": completed,
                            "target_records": records,
                            "seconds_this_invocation": round(elapsed, 3),
                            "records_per_second": round((completed - count_before) / elapsed)
                            if elapsed
                            else None,
                        }
                    ),
                    flush=True,
                )
        except Exception as error:
            _atomic_json(
                self.directory / "capacity-result.json",
                {
                    "status": "INCOMPLETE",
                    "completed_records": completed,
                    "target_records": records,
                    "pending_chunk": self.status().get("pending_chunk"),
                    "error": type(error).__name__,
                },
            )
            raise
        report = {
            **progress,
            "seconds_this_run": round(time.perf_counter() - started, 3),
            "peak_client_rss_mib": peak_rss_mib(),
        }
        _atomic_json(
            self.directory / "build-result.json",
            {
                "status": "COMPLETE",
                "count_before": count_before,
                "count_after": completed,
                "target_records": records,
                "seconds_this_invocation": report["seconds_this_run"],
                "report": report,
            },
        )
        return report

    def _maintain_generation(self, importer: ArchiveImporter, progress: dict) -> dict:
        """Renew a lost PIT before a new delta and checkpoint its new base."""
        if not progress["completed_records"] or progress.get("pending_chunk") is not None:
            return progress
        # Unit-test engines deliberately implement only the import boundary.
        # A real OpenSearch client always exposes request(), so its malformed
        # maintenance response remains fail-closed below.
        if not callable(getattr(self.engine, "request", None)):
            return progress
        try:
            importer.maintain()
        except Exception as error:
            raise RuntimeError(
                "Restore the published search snapshot before continuing this capacity run"
            ) from error
        with self.ctx.store.transaction(write=False) as tx:
            current = tx.get("index", ROOT_ID, {})
        root = current.get("root", {})
        generation, index = root.get("index_generation"), current.get("_index_name")
        if (
            current.get("_storage") != "opensearch"
            or not isinstance(generation, str)
            or not isinstance(index, str)
        ):
            raise RuntimeError("Published search generation is unavailable for the capacity benchmark")
        if index != progress.get("index"):
            raise RuntimeError("Published physical index changed outside the capacity benchmark")
        if generation == progress.get("generation"):
            return progress
        saved = {**progress, "generation": generation, "index": index, "updated_at": time.time()}
        _atomic_json(self.progress_file, saved)
        return saved

    def maintain_before_query(self) -> dict:
        importer = ArchiveImporter(self.ctx, self.engine, batch_size=self.batch_size, shards=self.shards)
        return self._maintain_generation(importer, self.status())

    def _install_schema(self, completed: int) -> None:
        """Install a capacity-only private schema before the first import."""
        if self.corpus.schema is None:
            return
        with self.ctx.store.transaction() as tx:
            root = tx.require("root", ROOT_ID)
            if completed:
                if root.get("schema_set_version") != self.corpus.schema["schema_set_version"]:
                    raise ValueError("Diverse corpus schema changed after its first import")
                return
            root["schema_set_version"] = self.corpus.schema["schema_set_version"]
            root["_schema"] = self.corpus.schema
            tx.put("root", ROOT_ID, root)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--records", type=int, default=200_000_000)
    parser.add_argument("--chunk-records", type=int, default=1_000_000)
    parser.add_argument("--corpus", choices=("baseline", "diverse"), default="baseline")
    parser.add_argument("--shards", type=int, default=8)
    parser.add_argument("--batch-size", type=int, choices=(1000, 5000), default=1000)
    parser.add_argument("--min-free-gib", type=float, default=20)
    parser.add_argument("--phase", choices=("build", "query", "all", "status"), default="all")
    parser.add_argument("--clients", type=int, default=50)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.records <= 400_000_000:
        parser.error("records must be 1..400000000")
    if not 1 <= args.chunk_records <= 1_000_000:
        parser.error("chunk-records must be 1..1000000")
    if not 1 <= args.shards <= 128:
        parser.error("shards must be 1..128")
    if args.min_free_gib < 0:
        parser.error("min-free-gib must be non-negative")
    if args.phase != "status" and not os.getenv("WISEWAY_SEARCH_URL"):
        parser.error("Set WISEWAY_SEARCH_URL to an isolated test engine")
    return args


def run_query_phase(data: Path, report: dict, action) -> dict:
    """Persist a terminal failure when the public query workload raises."""
    try:
        return {**report, "query": action()}
    except Exception as error:
        _atomic_json(
            data / "capacity-result.json",
            {
                **report,
                "status": "FAILED",
                "error": type(error).__name__,
                "query": {"passed": False, "error": type(error).__name__},
            },
        )
        raise SystemExit(1) from error


def run_query_measurement(data: Path, run: CapacityRun, report: dict, action) -> dict:
    """Serialize PIT renewal and its workload with capacity writes."""
    with _capacity_lock(data):
        progress = run.maintain_before_query()
        if progress.get("pending_chunk") is not None:
            raise RuntimeError("Complete the pending capacity chunk before running query measurements")
        result = run_query_phase(data, {**report, **progress}, lambda: action(progress))
        _atomic_json(data / "capacity-result.json", result)
        return result


def main() -> None:
    args = _args()
    data = args.data_dir.absolute()
    if args.phase == "status":
        # Status has no search-engine or sandbox side effects.
        marker = data / ".wiseway-capacity.json"
        if not marker.is_file():
            raise SystemExit("Capacity benchmark marker is missing")
        print((data / "progress.json").read_text(encoding="utf-8"))
        return
    # Claim the benchmark directory before the synthetic bootstrap creates its
    # state/sandbox children; arbitrary existing directories are still refused.
    CapacityRun.prepare_directory(data, args.chunk_records, args.corpus, args.shards, args.batch_size)
    settings = Settings(data_dir=data / "state", sandbox_dir=data / "sandbox")
    initialize(settings, password=PASSWORD)
    ctx = Context(settings)
    try:
        run = CapacityRun(
            data,
            ctx,
            ctx.search_engine(),
            chunk_records=args.chunk_records,
            corpus=args.corpus,
            shards=args.shards,
            batch_size=args.batch_size,
            min_free_bytes=int(args.min_free_gib * 1024**3),
        )
        interrupted = Event()
        previous = {name: signal.getsignal(name) for name in (signal.SIGINT, signal.SIGTERM)}
        for name in previous:
            signal.signal(name, lambda *_: interrupted.set())
        try:
            report = (
                run.build(args.records, stop=interrupted) if args.phase in {"build", "all"} else run.status()
            )
        finally:
            for name, handler in previous.items():
                signal.signal(name, handler)
        if args.phase in {"query", "all"}:
            if args.corpus == "baseline":
                report = run_query_measurement(
                    data,
                    run,
                    report,
                    lambda progress: query(
                        data, progress["completed_records"], args.repeats, args.clients, 250
                    ),
                )
            else:
                report = run_query_measurement(
                    data,
                    run,
                    report,
                    lambda progress: query_diverse(
                        settings, progress["completed_records"], args.repeats, args.clients, 250
                    ),
                )
        else:
            _atomic_json(data / "capacity-result.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report.get("query", {}).get("passed") is False:
            raise SystemExit(1)
    finally:
        ctx.close()


if __name__ == "__main__":
    main()
