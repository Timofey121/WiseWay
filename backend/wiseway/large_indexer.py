"""Bounded-memory staging scanner for archives larger than the demo index.

This module deliberately does not select itself from the regular worker yet.
It records a complete, unpublished generation in SQLite, then delegates the
search-record publication to ``sqlite_search``.  A filesystem enumeration has
no crash-stable cursor, therefore an interrupted staging run is discarded on
the next attempt rather than risking silently missed files.
"""

from __future__ import annotations

import hashlib
import json
from itertools import islice
from typing import Any, Iterator

from .common import digest, public, uid, utc
from .filesystem import ScanLimits
from .indexer import IDENTITY_PROFILE_VERSION, _strip_base, _technical_name
from .search import build_item


LARGE_SCAN_LIMITS = ScanLimits(
    max_entries=1_100_000,
    max_depth=64,
    max_path_bytes=512 * 1024 * 1024,
    max_seconds=3600.0,
)
_WRITE_BATCH_SIZE = 1_000
_BUILD_BATCH_SIZE = 500


class _StopRequested(Exception):
    pass


def _chunks(rows: Iterator[tuple], size: int) -> Iterator[list[tuple]]:
    while batch := list(islice(rows, size)):
        yield batch


class LargeIndexer:
    """Build an unpublished SQLite-backed index generation for one root."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    @staticmethod
    def _configuration(root: dict[str, Any]) -> dict[str, Any]:
        """Every field that affects staged paths or published public values."""
        return {
            "root_id": root["root_id"],
            "label": root["label"],
            "display_prefix": root["display_prefix"],
            "base": root["_base"],
            "searchable": root.get("_searchable"),
            "schema_set_version": root["schema_set_version"],
            "schema": root["_schema"],
            "prefixes": root.get("_scan_prefixes", [""]),
            "identity_profile": IDENTITY_PROFILE_VERSION,
        }

    def scan(self, root: dict[str, Any], *, stop=None) -> bool:
        """Stage, build and atomically publish one complete root observation.

        The caller owns the process-wide indexer lock.  The previously
        published index remains available if scanning or building fails.
        """
        if stop is not None and stop.is_set():
            return False
        config = self._configuration(root)
        config_digest = digest(config)
        run_id = None
        try:
            run_id = self._begin(root, config_digest, stop)
            count = self._stage(root, run_id, stop)
            self._check_stop(stop)
            fingerprint = self._fingerprint(run_id, config, stop)
            if self._unchanged(root, fingerprint):
                self._complete_unchanged(root, run_id, count, config_digest, stop)
                return True
            self._assign_ids(root, run_id, stop)
            generation = "generation-" + digest([root["root_id"], fingerprint])[:24]
            self._build_generation(root, run_id, generation, stop)
            self._check_stop(stop)
            self._publish(root, run_id, generation, fingerprint, count, config_digest)
            try:
                self._discard_superseded(root["root_id"], run_id, stop)
            except Exception:
                # Publication is already durable.  Cleanup is deliberately a
                # best-effort maintenance concern and must not relabel a new,
                # active generation as failed.
                pass
            return True
        except _StopRequested:
            if run_id is not None:
                self._stopped(root, run_id)
            return False
        except Exception:
            if run_id is not None:
                self._fail(root, run_id)
            return False

    @staticmethod
    def _check_stop(stop) -> None:
        if stop is not None and stop.is_set():
            raise _StopRequested()

    def _begin(self, root: dict[str, Any], config_digest: str, stop=None) -> str:
        run_id = uid("large-index-run")
        self._discard_incomplete(root["root_id"], stop)
        self._check_stop(stop)
        with self.ctx.store.transaction() as tx:
            # A filesystem traversal cannot be resumed from a durable cursor:
            # directory order is not stable across a process crash.  Discard
            # only unpublished work; published generations are not touched.
            tx.connection.execute(
                "INSERT INTO large_scan_runs(run_id, root_id, state, config_digest, created_at) VALUES(?,?,?,?,?)",
                (run_id, root["root_id"], "SCANNING", config_digest, self.ctx.settings.clock()),
            )
            tx.put(
                "index_progress",
                root["root_id"],
                {
                    "root_id": root["root_id"],
                    "status": "SCANNING",
                    "count": 0,
                    "checkpoint": None,
                    "estimated_remaining_seconds": None,
                    "_run_id": run_id,
                },
            )
        return run_id

    def _stage(self, root: dict[str, Any], run_id: str, stop) -> int:
        def rows():
            for prefix in root.get("_scan_prefixes", [""]):
                physical = "/".join(part for part in (root["_base"], prefix) if part)
                for path, meta in self.ctx.fs.iter_files(physical, limits=LARGE_SCAN_LIMITS):
                    self._check_stop(stop)
                    relative = _strip_base(path, root["_base"])
                    if not _technical_name(relative):
                        yield relative, meta["dev"], meta["ino"], meta["size"], meta["mtime_ns"]

        count = 0
        for batch in _chunks(rows(), _WRITE_BATCH_SIZE):
            self._check_stop(stop)
            count += len(batch)
            with self.ctx.store.transaction() as tx:
                tx.connection.executemany(
                    "INSERT INTO large_scan_entries(run_id,path,dev,ino,size,mtime_ns) VALUES(?,?,?,?,?,?)",
                    [(run_id, *row) for row in batch],
                )
                tx.connection.execute(
                    "UPDATE large_scan_runs SET entry_count=? WHERE run_id=?", (count, run_id)
                )
                progress = tx.get("index_progress", root["root_id"], {})
                if progress.get("_run_id") != run_id:
                    raise RuntimeError("large scan ownership changed")
                progress.update(count=count, checkpoint=batch[-1][0])
                tx.put("index_progress", root["root_id"], progress)
        return count

    def _fingerprint(self, run_id: str, config: dict[str, Any], stop) -> str:
        # This is intentionally streaming.  Its format is private to large
        # generations; a legacy JSON index is rebuilt once on migration.
        checksum = hashlib.sha256()
        checksum.update(
            json.dumps(config, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        )
        with self.ctx.store.transaction(write=False) as tx:
            rows = tx.connection.execute(
                "SELECT path,dev,ino,size,mtime_ns FROM large_scan_entries WHERE run_id=? ORDER BY path",
                (run_id,),
            )
            for row in rows:
                self._check_stop(stop)
                checksum.update(b"\x1e")
                checksum.update(json.dumps(tuple(row), ensure_ascii=False, separators=(",", ":")).encode())
        return checksum.hexdigest()

    def _unchanged(self, root: dict[str, Any], fingerprint: str) -> bool:
        with self.ctx.store.transaction(write=False) as tx:
            previous = tx.get("index", root["root_id"])
        return bool(
            previous
            and previous.get("_storage") == "sqlite"
            and previous.get("_fingerprint_digest") == fingerprint
        )

    def _complete_unchanged(
        self, root: dict[str, Any], run_id: str, count: int, config_digest: str, stop
    ) -> None:
        self._check_stop(stop)
        now = self.ctx.settings.clock()
        with self.ctx.store.transaction() as tx:
            previous = tx.require("index", root["root_id"])
            current_root = tx.require("root", root["root_id"])
            progress = tx.get("index_progress", root["root_id"], {})
            if (
                digest(self._configuration(current_root)) != config_digest
                or progress.get("_run_id") != run_id
            ):
                raise RuntimeError("large scan configuration changed before publication")
            previous["freshness"] = {
                "indexed_at": previous["root"]["indexed_at"],
                "last_successful_sync_at": utc(now),
                "status": "CURRENT",
            }
            tx.put("index", root["root_id"], previous)
            tx.put(
                "index_progress",
                root["root_id"],
                {"root_id": root["root_id"], "status": "COMPLETE", "count": count, "checkpoint": None},
            )
        self._discard_run(run_id, stop)

    def _assign_ids(self, root: dict[str, Any], run_id: str, stop) -> None:
        """Keep exact paths and unambiguous renames without materializing maps."""
        prior_run = None
        legacy_ids: set[str] = set()
        with self.ctx.store.transaction(write=False) as tx:
            previous = tx.get("index", root["root_id"])
            prior_run = (
                previous.get("_scan_run_id") if previous and previous.get("_storage") == "sqlite" else None
            )
        if isinstance(prior_run, str):
            last_path = ""
            while True:
                self._check_stop(stop)
                with self.ctx.store.transaction(write=False) as tx:
                    paths = tx.connection.execute(
                        "SELECT path FROM large_scan_entries WHERE run_id=? AND path>? ORDER BY path LIMIT ?",
                        (run_id, last_path, _WRITE_BATCH_SIZE),
                    ).fetchall()
                if not paths:
                    break
                with self.ctx.store.transaction() as tx:
                    for (path,) in paths:
                        tx.connection.execute(
                            "UPDATE large_scan_entries AS current SET item_id=("
                            "SELECT prior.item_id FROM large_scan_entries AS prior "
                            "WHERE prior.run_id=? AND prior.path=current.path "
                            "AND prior.dev=current.dev AND prior.ino=current.ino) "
                            "WHERE current.run_id=? AND current.path=?",
                            (prior_run, run_id, path),
                        )
                    for (path,) in paths:
                        tx.connection.execute(
                            "UPDATE large_scan_entries AS current SET item_id=("
                            "SELECT prior.item_id FROM large_scan_entries AS prior "
                            "WHERE prior.run_id=? AND prior.dev=current.dev AND prior.ino=current.ino "
                            "AND NOT EXISTS (SELECT 1 FROM large_scan_entries AS same_path "
                            "WHERE same_path.run_id=current.run_id AND same_path.path=prior.path) "
                            "AND (SELECT COUNT(*) FROM large_scan_entries AS now_count "
                            "WHERE now_count.run_id=current.run_id AND now_count.dev=current.dev AND now_count.ino=current.ino)=1 "
                            "AND (SELECT COUNT(*) FROM large_scan_entries AS old_count "
                            "WHERE old_count.run_id=? AND old_count.dev=current.dev AND old_count.ino=current.ino "
                            "AND NOT EXISTS (SELECT 1 FROM large_scan_entries AS same_now "
                            "WHERE same_now.run_id=current.run_id AND same_now.path=old_count.path))=1"
                            ") WHERE current.run_id=? AND current.path=? AND current.item_id IS NULL",
                            (prior_run, prior_run, run_id, path),
                        )
                last_path = paths[-1][0]
        elif previous and isinstance(previous.get("_entry_ids"), dict):
            with self.ctx.store.transaction() as tx:
                legacy = previous["_entry_ids"]
                if len(legacy) <= 10_000:
                    missing_by_inode: dict[tuple[int, int], list[tuple[str, str]]] = {}
                    for path, entry in legacy.items():
                        if isinstance(entry, dict) and isinstance(entry.get("item_id"), str):
                            item_id, dev, ino = entry["item_id"], entry.get("dev"), entry.get("ino")
                            legacy_ids.add(item_id)
                            tx.connection.execute(
                                "UPDATE large_scan_entries SET item_id=? WHERE run_id=? AND path=? AND dev=? AND ino=? "
                                "AND item_id IS NULL",
                                (item_id, run_id, path, dev, ino),
                            )
                            if isinstance(dev, int) and isinstance(ino, int):
                                exists = tx.connection.execute(
                                    "SELECT 1 FROM large_scan_entries WHERE run_id=? AND path=?",
                                    (run_id, path),
                                ).fetchone()
                                if not exists:
                                    missing_by_inode.setdefault((dev, ino), []).append((path, item_id))
                    for (dev, ino), candidates in missing_by_inode.items():
                        if len(candidates) != 1:
                            continue
                        current = tx.connection.execute(
                            "SELECT path FROM large_scan_entries WHERE run_id=? AND dev=? AND ino=? AND item_id IS NULL LIMIT 2",
                            (run_id, dev, ino),
                        ).fetchall()
                        if len(current) == 1:
                            tx.connection.execute(
                                "UPDATE large_scan_entries SET item_id=? WHERE run_id=? AND path=?",
                                (candidates[0][1], run_id, current[0][0]),
                            )
        # New IDs are assigned in bounded batches.  Hard-linked directory
        # entries deliberately receive different deterministic IDs; an inode
        # alone is not an entry identity.
        last_path = ""
        while True:
            self._check_stop(stop)
            with self.ctx.store.transaction(write=False) as tx:
                rows = tx.connection.execute(
                    "SELECT current.path,current.dev,current.ino,("
                    "SELECT COUNT(*) FROM large_scan_entries AS same_inode "
                    "WHERE same_inode.run_id=current.run_id AND same_inode.dev=current.dev AND same_inode.ino=current.ino"
                    ") FROM large_scan_entries AS current "
                    "WHERE current.run_id=? AND current.item_id IS NULL AND current.path>? ORDER BY current.path LIMIT ?",
                    (run_id, last_path, _WRITE_BATCH_SIZE),
                ).fetchall()
            if not rows:
                return
            candidates = []
            for path, dev, ino, inode_count in rows:
                self._check_stop(stop)
                item_id = f"file-{root['root_id']}-{dev}-{ino}"
                if inode_count > 1:
                    item_id += "-" + digest(path)[:20]
                candidates.append((path, item_id))
            used_ids = set(legacy_ids)
            with self.ctx.store.transaction(write=False) as tx:
                for start in range(0, len(candidates), 400):
                    chunk = [item_id for _, item_id in candidates[start : start + 400]]
                    marks = ",".join("?" for _ in chunk)
                    for checked_run in (run_id, prior_run):
                        if not isinstance(checked_run, str):
                            continue
                        used_ids.update(
                            row[0]
                            for row in tx.connection.execute(
                                f"SELECT item_id FROM large_scan_entries WHERE run_id=? AND item_id IN ({marks})",
                                (checked_run, *chunk),
                            )
                        )
            updates = []
            for path, item_id in candidates:
                if item_id in used_ids:
                    item_id += "-" + digest(path)[:20]
                updates.append((item_id, run_id, path))
            with self.ctx.store.transaction() as tx:
                tx.connection.executemany(
                    "UPDATE large_scan_entries SET item_id=? WHERE run_id=? AND path=?", updates
                )
            last_path = rows[-1][0]

    def _build_generation(self, root: dict[str, Any], run_id: str, generation: str, stop) -> None:
        from . import sqlite_search

        with self.ctx.store.transaction() as tx:
            sqlite_search.create_generation(tx, root, generation)
            tx.connection.execute(
                "UPDATE large_scan_runs SET generation=? WHERE run_id=?", (generation, run_id)
            )
        last_path = ""
        while True:
            self._check_stop(stop)
            with self.ctx.store.transaction(write=False) as tx:
                rows = tx.connection.execute(
                    "SELECT path,size,mtime_ns,item_id FROM large_scan_entries "
                    "WHERE run_id=? AND path>? ORDER BY path LIMIT ?",
                    (run_id, last_path, _BUILD_BATCH_SIZE),
                ).fetchall()
            if not rows:
                break
            items = [
                build_item(
                    root["root_id"],
                    root["display_prefix"],
                    path,
                    size,
                    utc(mtime_ns / 1e9),
                    root["_schema"],
                    item_id,
                )
                for path, size, mtime_ns, item_id in rows
            ]
            with self.ctx.store.transaction() as tx:
                self._check_stop(stop)
                sqlite_search.add_items(tx, generation, items)
            last_path = rows[-1][0]
        with self.ctx.store.transaction() as tx:
            sqlite_search.finish(tx, generation)
            tx.connection.execute(
                "UPDATE large_scan_runs SET state='BUILT', generation=? WHERE run_id=?", (generation, run_id)
            )

    def _publish(self, root, run_id, generation, fingerprint, count, config_digest=None) -> None:
        from . import sqlite_search

        now = self.ctx.settings.clock()
        with self.ctx.store.transaction() as tx:
            current_root = tx.require("root", root["root_id"])
            current_config = self._configuration(current_root)
            progress = tx.get("index_progress", root["root_id"], {})
            if (config_digest is not None and digest(current_config) != config_digest) or progress.get(
                "_run_id"
            ) != run_id:
                raise RuntimeError("large scan configuration changed before publication")
            sqlite_search.activate_generation(tx, generation)
            public_root = public(current_root)
            public_root["index_generation"] = generation
            public_root["indexed_at"] = utc(now)
            tx.put(
                "index",
                root["root_id"],
                {
                    "root": public_root,
                    "items": [],
                    "_storage": "sqlite",
                    "_generation": generation,
                    "_scan_run_id": run_id,
                    "_fingerprint_digest": fingerprint,
                    "freshness": {
                        "indexed_at": utc(now),
                        "last_successful_sync_at": utc(now),
                        "status": "CURRENT",
                    },
                },
            )
            tx.connection.execute(
                "UPDATE large_scan_runs SET state='PUBLISHED', fingerprint_digest=?, completed_at=? WHERE run_id=?",
                (fingerprint, now, run_id),
            )
            tx.put(
                "index_progress",
                root["root_id"],
                {"root_id": root["root_id"], "status": "COMPLETE", "count": count, "checkpoint": None},
            )

    def _discard_incomplete(self, root_id: str, stop=None) -> None:
        with self.ctx.store.transaction(write=False) as tx:
            rows = tx.connection.execute(
                "SELECT run_id FROM large_scan_runs WHERE root_id=? AND state!='PUBLISHED'", (root_id,)
            ).fetchall()
        for (run_id,) in rows:
            self._check_stop(stop)
            self._discard_run(run_id, stop)

    def _discard_superseded(self, root_id: str, keep_run_id: str, stop=None) -> None:
        with self.ctx.store.transaction(write=False) as tx:
            rows = tx.connection.execute(
                "SELECT run_id FROM large_scan_runs WHERE root_id=? AND state='PUBLISHED' AND run_id!=?",
                (root_id, keep_run_id),
            ).fetchall()
        for (run_id,) in rows:
            self._check_stop(stop)
            self._discard_run(run_id, stop)

    def _discard_run(self, run_id: str, stop=None) -> None:
        from . import sqlite_search

        while True:
            self._check_stop(stop)
            with self.ctx.store.transaction() as tx:
                row = tx.connection.execute(
                    "SELECT generation FROM large_scan_runs WHERE run_id=?", (run_id,)
                ).fetchone()
                if row is None:
                    return
                generation = row[0]
                if generation and not sqlite_search.delete_generation(tx, generation, batch_size=1000):
                    continue
                paths = tx.connection.execute(
                    "SELECT path FROM large_scan_entries WHERE run_id=? LIMIT 1000", (run_id,)
                ).fetchall()
                if paths:
                    tx.connection.executemany(
                        "DELETE FROM large_scan_entries WHERE run_id=? AND path=?",
                        [(run_id, path) for (path,) in paths],
                    )
                    continue
                tx.connection.execute("DELETE FROM large_scan_runs WHERE run_id=?", (run_id,))
                return

    def _fail(self, root: dict[str, Any], run_id: str) -> None:
        with self.ctx.store.transaction() as tx:
            tx.connection.execute("UPDATE large_scan_runs SET state='FAILED' WHERE run_id=?", (run_id,))
            progress = tx.get("index_progress", root["root_id"], {})
            progress.update(status="FAILED", estimated_remaining_seconds=None)
            tx.put("index_progress", root["root_id"], progress)
            previous = tx.get("index", root["root_id"])
            if previous:
                previous["freshness"] = {
                    "indexed_at": previous["root"]["indexed_at"],
                    "last_successful_sync_at": previous["freshness"]["last_successful_sync_at"],
                    "status": "STALE",
                }
                tx.put("index", root["root_id"], previous)

    def _stopped(self, root: dict[str, Any], run_id: str) -> None:
        """Leave unpublished staging for bounded cleanup by the next run."""
        with self.ctx.store.transaction() as tx:
            progress = tx.get("index_progress", root["root_id"], {})
            if progress.get("_run_id") == run_id:
                progress.update(status="STOPPED", estimated_remaining_seconds=None)
                tx.put("index_progress", root["root_id"], progress)
