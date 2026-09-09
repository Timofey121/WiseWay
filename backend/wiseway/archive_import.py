"""Streaming immutable manifests and ordered deltas; no per-file SQLite catalog."""

from contextlib import closing, nullcontext
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import stat
from threading import Event

from .common import digest, public, timestamp, uid, utc
from .indexer import _index_lock
from .opensearch import document
from .search import build_item

MAX_LINE = 256 * 1024
VERSION_RANGE = 1_000_000_000


def _configuration(root):
    return {key: root[key] for key in ("root_id", "display_prefix", "schema_set_version", "_schema")}


def _signature(handle):
    info = os.fstat(handle.fileno())
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Manifest must be a regular immutable file")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _record(value, root, mode):
    if not isinstance(value, dict) or value.get("op") not in {"upsert", "delete"}:
        raise ValueError("Manifest requires upsert/delete records")
    identity = value.get("item_id")
    if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,96}", identity):
        raise ValueError("Invalid item_id")
    if value["op"] == "delete":
        if mode != "delta" or set(value) != {"op", "item_id"}:
            raise ValueError("Deletes are allowed only in delta manifests")
        return {"id": identity, "deleted": True}
    if set(value) != {"op", "item_id", "relative_path", "size_bytes", "modified_at"}:
        raise ValueError("Invalid upsert fields")
    path, size, modified = value["relative_path"], value["size_bytes"], value["modified_at"]
    if (
        not isinstance(path, str)
        or not path
        or path.startswith("/")
        or "\\" in path
        or ":" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or any(ord(c) < 32 or ord(c) == 127 for c in path)
        or len(path.encode()) > 4096
    ):
        raise ValueError("Invalid relative_path")
    if type(size) is not int or not 0 <= size <= 9007199254740991:
        raise ValueError("Invalid file size")
    if not isinstance(modified, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", modified
    ):
        raise ValueError("modified_at must be UTC")
    timestamp(modified)
    return document(
        build_item(root["root_id"], root["display_prefix"], path, size, modified, root["_schema"], identity)
    )


class ArchiveImporter:
    def __init__(self, ctx, engine, *, batch_size=1000, shards=8):
        if not 1 <= batch_size <= 5000:
            raise ValueError("Import batch size must be 1..5000")
        self.ctx, self.engine, self.batch_size, self.shards = ctx, engine, batch_size, shards
        self.database = ctx.settings.data_dir / "archive-import.sqlite3"

    def _journal(self):
        db = sqlite3.connect(self.database, timeout=5)
        os.chmod(self.database, 0o600)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("""CREATE TABLE IF NOT EXISTS imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT, root_id TEXT NOT NULL, source_hash TEXT NOT NULL,
            mode TEXT NOT NULL, config_hash TEXT NOT NULL, base TEXT, index_name TEXT NOT NULL,
            generation TEXT NOT NULL, byte_offset INTEGER NOT NULL DEFAULT 0,
            records INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'BUILDING', result TEXT,
            CHECK(state IN ('BUILDING','PUBLISHED','ABORTED')))""")
        db.execute("""CREATE TABLE IF NOT EXISTS retired_pits (
            pit TEXT PRIMARY KEY, retire_at REAL NOT NULL)""")
        db.execute("CREATE INDEX IF NOT EXISTS imports_root_state ON imports(root_id,state)")
        db.execute("CREATE INDEX IF NOT EXISTS imports_source ON imports(root_id,source_hash,mode,base)")
        db.execute("CREATE INDEX IF NOT EXISTS imports_index_state ON imports(index_name,state)")
        db.commit()
        return db

    def run(self, root_id, source, *, mode="full", base_generation=None, stop=None, _lock_held=False):
        if mode not in {"full", "delta"} or mode == "delta" and not base_generation:
            raise ValueError("Delta import requires its base generation")
        stop = stop if stop is not None else Event()
        with nullcontext(True) if _lock_held else _index_lock(self.ctx, "archive-indexer.lock") as held:
            if not held:
                raise RuntimeError("Another archive importer/indexer is running")
            descriptor = os.open(Path(source).absolute(), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as handle, closing(self._journal()) as db:
                signature = _signature(handle)
                source_hash = hashlib.sha256()
                while chunk := handle.read(4 * 1024 * 1024):
                    if stop.is_set():
                        raise InterruptedError("Import stopped before checkpoint allocation")
                    source_hash.update(chunk)
                if _signature(handle) != signature:
                    raise ValueError("Manifest changed while hashing")
                handle.seek(0)
                root, job = self._claim(db, root_id, source_hash.hexdigest(), mode, base_generation)
                if job["state"] == "PUBLISHED":
                    return json.loads(job["result"])
                # A crash after SQLite publication but before journal commit is
                # completed without reapplying or republishing an older snapshot.
                with self.ctx.store.transaction(write=False) as tx:
                    saved = tx.get("index", root_id, {})
                if saved.get("_import_generation") == job["generation"]:
                    return self._finish(db, job)
                self.engine.ensure(job["index_name"], shards=self.shards, config_hash=job["config_hash"])
                handle.seek(job["byte_offset"])
                count = job["records"]
                while True:
                    if stop.is_set():
                        raise InterruptedError("Import stopped at a durable checkpoint")
                    records, encoded_size = [], 0
                    for _ in range(self.batch_size):
                        line = handle.readline(MAX_LINE + 1)
                        if not line:
                            break
                        if len(line) > MAX_LINE:
                            raise ValueError("Manifest record exceeds line limit")
                        count += 1
                        if count >= VERSION_RANGE or job["id"] >= (2**63 // VERSION_RANGE) - 1:
                            raise ValueError("Import revision range exhausted")
                        doc = _record(json.loads(line), root, mode)
                        records.append((doc, job["id"] * VERSION_RANGE + count))
                        encoded_size += len(json.dumps(doc, ensure_ascii=False).encode()) + 1024
                        if encoded_size >= 4 * 1024 * 1024:
                            break
                    if not records:
                        break
                    if _signature(handle) != signature:
                        raise ValueError("Manifest changed during import")
                    self.engine.bulk(job["index_name"], records)
                    with db:
                        db.execute(
                            "UPDATE imports SET byte_offset=?,records=? WHERE id=?",
                            (handle.tell(), count, job["id"]),
                        )
                    with self.ctx.store.transaction() as tx:
                        tx.put(
                            "index_progress",
                            root_id,
                            {
                                "root_id": root_id,
                                "status": "SCANNING",
                                "count": count,
                                "checkpoint": str(handle.tell()),
                            },
                        )
                if _signature(handle) != signature:
                    raise ValueError("Manifest changed before publication")
                pit = self.engine.publish(job["index_name"])
                now = self.ctx.settings.clock()
                with self.ctx.store.transaction() as tx:
                    current_root = tx.require("root", root_id)
                    if digest(_configuration(current_root)) != job["config_hash"]:
                        raise ValueError("Root configuration changed during import")
                    old = tx.get("index", root_id, {})
                    if mode == "delta" and old.get("root", {}).get("index_generation") != base_generation:
                        raise ValueError("Delta base changed before publication")
                    if old.get("_pit_id"):
                        # Commit retirement before the pointer swap; a crash can
                        # only leak a PIT until its keep_alive expires.
                        with db:
                            db.execute(
                                "INSERT OR REPLACE INTO retired_pits VALUES (?,?)",
                                (old["_pit_id"], now + 120),
                            )
                    published = {
                        **public(current_root),
                        "index_generation": job["generation"],
                        "indexed_at": utc(now),
                    }
                    tx.put(
                        "index",
                        root_id,
                        {
                            "root": published,
                            "items": [],
                            "_storage": "opensearch",
                            "_index_name": job["index_name"],
                            "_pit_id": pit,
                            "_schema": current_root["_schema"],
                            "_import_generation": job["generation"],
                        },
                    )
                    tx.put(
                        "index_progress",
                        root_id,
                        {"root_id": root_id, "status": "COMPLETE", "count": count, "checkpoint": None},
                    )
                with self.ctx.store.transaction() as tx:
                    tx.put("operator_state", "search", {"last_completed_at": utc(now)})
                result = self._finish(db, job)
                self._cleanup(db)
                return result

    def _claim(self, db, root_id, source_hash, mode, base):
        with _index_lock(self.ctx) as held:
            if not held:
                raise RuntimeError("File indexer is busy; retry import")
            with self.ctx.store.transaction() as tx:
                root = tx.require("root", root_id)
                if not root.get("_searchable"):
                    raise ValueError("Root is not searchable")
                config_hash = digest(_configuration(root))
                existing = db.execute(
                    "SELECT * FROM imports WHERE root_id=? AND source_hash=? AND mode=? AND base IS ? AND state!='ABORTED' ORDER BY id DESC LIMIT 1",
                    (root_id, source_hash, mode, base),
                ).fetchone()
                if existing and existing["state"] != "ABORTED":
                    if existing["config_hash"] != config_hash:
                        raise ValueError("Root configuration changed; create a new full manifest")
                    root["_index_storage"] = "opensearch"
                    tx.put("root", root_id, root)
                    return root, existing
                pending = db.execute(
                    "SELECT 1 FROM imports WHERE root_id=? AND state='BUILDING'", (root_id,)
                ).fetchone()
                if pending:
                    raise ValueError("Resume the unfinished immutable manifest before another import")
                old = tx.get("index", root_id, {})
                if mode == "delta" and (
                    old.get("_storage") != "opensearch" or old["root"]["index_generation"] != base
                ):
                    raise ValueError("Delta base is not the current OpenSearch generation")
                if (
                    mode == "delta"
                    and db.execute(
                        "SELECT 1 FROM imports WHERE index_name=? AND state='ABORTED' LIMIT 1",
                        (old["_index_name"],),
                    ).fetchone()
                ):
                    raise ValueError("An aborted delta requires a new full import")
                name = old["_index_name"] if mode == "delta" else "wiseway-archive-" + uid("build")
                generation = uid("search")
                with db:
                    cursor = db.execute(
                        "INSERT INTO imports(root_id,source_hash,mode,config_hash,base,index_name,generation) VALUES (?,?,?,?,?,?,?)",
                        (root_id, source_hash, mode, config_hash, base, name, generation),
                    )
                root["_index_storage"] = "opensearch"
                tx.put("root", root_id, root)
                return root, db.execute("SELECT * FROM imports WHERE id=?", (cursor.lastrowid,)).fetchone()

    def abort(self, root_id):
        """Retain the last published PIT; an aborted mutable index needs rebuilding."""
        with _index_lock(self.ctx, "archive-indexer.lock") as held:
            if not held:
                raise RuntimeError("Stop the active importer before aborting")
            with closing(self._journal()) as db, db:
                cursor = db.execute(
                    "UPDATE imports SET state='ABORTED' WHERE root_id=? AND state='BUILDING'", (root_id,)
                )
                if cursor.rowcount:
                    with self.ctx.store.transaction() as tx:
                        tx.delete("search_outbox_batch", root_id)
                return {"aborted": cursor.rowcount, "requires_full_import": bool(cursor.rowcount)}

    def maintain(self):
        """Renew published snapshots, recovering lost PITs only from complete indexes."""
        from .common import ApiError
        from .opensearch import _complete

        with _index_lock(self.ctx, "archive-indexer.lock") as held:
            if not held:
                return {"busy": True}
            with closing(self._journal()) as db:
                with self.ctx.store.transaction(write=False) as tx:
                    indexes = tx.list("index")
                renewed = 0
                for manifest in indexes:
                    if manifest.get("_storage") != "opensearch":
                        continue
                    try:
                        response = self.engine.request(
                            "POST",
                            "/_search?allow_partial_search_results=false",
                            {
                                "pit": {"id": manifest["_pit_id"], "keep_alive": "24h"},
                                "size": 0,
                                "query": {"match_none": {}},
                                "track_total_hits": False,
                            },
                        )
                        _complete(response)
                    except ApiError:
                        dirty = db.execute(
                            "SELECT 1 FROM imports WHERE index_name=? AND state IN ('BUILDING','ABORTED') LIMIT 1",
                            (manifest["_index_name"],),
                        ).fetchone()
                        if dirty:
                            raise RuntimeError(
                                "Complete the pending import or rebuild before restoring a lost snapshot"
                            )
                        pit = self.engine.publish(manifest["_index_name"])
                        with self.ctx.store.transaction() as tx:
                            current = tx.require("index", manifest["root"]["root_id"])
                            if current.get("_pit_id") != manifest["_pit_id"]:
                                raise RuntimeError("Published snapshot changed during maintenance")
                            current["_pit_id"] = pit
                            current["root"]["index_generation"] = uid("search")
                            tx.put("index", current["root"]["root_id"], current)
                    renewed += 1
                self._cleanup(db)
                with self.ctx.store.transaction() as tx:
                    tx.put("operator_state", "search", {"last_completed_at": utc(self.ctx.settings.clock())})
                return {"renewed": renewed}

    def _finish(self, db, job):
        count = db.execute("SELECT records FROM imports WHERE id=?", (job["id"],)).fetchone()[0]
        result = {"index": job["index_name"], "generation": job["generation"], "records": count}
        with db:
            db.execute(
                "UPDATE imports SET state='PUBLISHED',result=? WHERE id=?", (json.dumps(result), job["id"])
            )
        return result

    def _cleanup(self, db):
        with self.ctx.store.transaction(write=False) as tx:
            active = {
                row[0]
                for row in tx.connection.execute(
                    "SELECT json_extract(body,'$._pit_id') FROM objects WHERE kind='index'"
                )
            }
        for pit, _ in db.execute(
            "SELECT pit,retire_at FROM retired_pits WHERE retire_at<=? LIMIT 100",
            (self.ctx.settings.clock(),),
        ):
            if pit not in active:
                self.engine.close_pit(pit)
                with db:
                    db.execute("DELETE FROM retired_pits WHERE pit=?", (pit,))
