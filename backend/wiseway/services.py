"""Shared transactional application context and immutable pagination."""

from pathlib import PurePosixPath
from collections import OrderedDict
import json
from threading import Lock

from .common import ApiError, digest, public, utc
from .filesystem import SafeFilesystem
from .rules import plan_rows
from .storage import Store

PAGE_CURSOR_SECONDS = 86400
MAX_PAGE_SNAPSHOTS_PER_USER = 64
MAX_PAGE_SNAPSHOT_BYTES = 8 * 1024 * 1024
MAX_PAGE_SNAPSHOT_TOTAL_BYTES_PER_USER = 32 * 1024 * 1024
MAX_AUDIT_CACHE_EVENTS = 10_000
MAX_AUDIT_CACHE_BYTES = 8 * 1024 * 1024
MAX_INDEX_CACHE_BYTES = 32 * 1024 * 1024


def _snapshot_bytes(payload):
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())


def _delete_expired_pages(tx, now):
    tx.connection.execute(
        "DELETE FROM objects "
        "WHERE kind IN ('cursor', 'page_snapshot') "
        "AND COALESCE(CAST(json_extract(body, '$.expires') AS REAL), 0) <= ?",
        (now,),
    )


def _check_page_quota(tx, owner, payload_bytes):
    count, total_bytes = tx.connection.execute(
        "SELECT COUNT(*), COALESCE(SUM(CAST(json_extract(body, '$.payload_bytes') AS INTEGER)), 0) "
        "FROM objects WHERE kind='page_snapshot' AND json_extract(body, '$.owner')=?",
        (owner,),
    ).fetchone()
    if (
        payload_bytes > MAX_PAGE_SNAPSHOT_BYTES
        or count >= MAX_PAGE_SNAPSHOTS_PER_USER
        or total_bytes + payload_bytes > MAX_PAGE_SNAPSHOT_TOTAL_BYTES_PER_USER
    ):
        raise ApiError("RATE_LIMITED", "Превышен лимит активных снимков страниц.", 429, retryable=True)


class Context:
    def __init__(self, settings):
        self.settings = settings
        marker = settings.sandbox_dir / ".wiseway-sandbox.json"
        try:
            marker_payload = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            marker_payload = None
        if (
            not isinstance(marker_payload, dict)
            or marker_payload.get("product") != "Wise Way"
            or marker_payload.get("synthetic") is not True
            or not settings.database.is_file()
        ):
            raise RuntimeError("Initialize the synthetic sandbox before starting Wise Way")
        self.store = Store(settings.database)
        with self.store.transaction(write=False) as tx:
            bootstrap = tx.get("bootstrap", "seed-v1")
            if not isinstance(bootstrap, dict) or bootstrap.get("complete") is not True:
                raise RuntimeError("Initialize the synthetic sandbox before starting Wise Way")
        self._index_cache = OrderedDict()
        self._index_cache_sizes = {}
        self._prepared_indexes = OrderedDict()
        self._index_cache_lock = Lock()
        from .search_cache import SearchCache

        self.search_cache = SearchCache(max_bytes=settings.search_cache_bytes)
        self._search_engine = None
        self._search_engine_lock = Lock()
        self._audit_cache = None
        self._audit_cache_lock = Lock()
        self.fs = SafeFilesystem(settings.sandbox_dir)
        if not self.fs.probe():
            self.fs.close()
            raise RuntimeError("Atomic no-replace rename is required")

    def close(self):
        self.fs.close()
        if self._search_engine is not None:
            self._search_engine.close()

    def search_engine(self):
        from .opensearch import OpenSearch, unavailable

        with self._search_engine_lock:
            if self._search_engine is None:
                if not self.settings.search_url:
                    raise unavailable()
                self._search_engine = OpenSearch(
                    self.settings.search_url,
                    ca_file=self.settings.search_ca_file,
                    credentials_file=self.settings.search_credentials_file,
                    allow_http=self.settings.search_allow_http,
                )
            return self._search_engine

    def prepared_search(self, index):
        from .search_index import SearchIndex

        items = index["items"]
        if len(items) > 10_000:
            return None
        key = index["root"]["root_id"]
        with self._index_cache_lock:
            prepared = self._prepared_indexes.get(key)
            if prepared is None or prepared.items is not items:
                prepared = SearchIndex(items)
                self._prepared_indexes[key] = prepared
            self._prepared_indexes.move_to_end(key)
            while len(self._prepared_indexes) > 4:
                self._prepared_indexes.popitem(last=False)
            return prepared

    def read_index(self, tx, root_id):
        """Read-only published rows; a transactional revision binds the cached document.

        Callers must not mutate these rows. Four documents share one 32 MiB
        encoded-data budget; a larger root can use otherwise unused capacity.
        """
        revision = tx.connection.execute(
            "SELECT revision FROM index_revisions WHERE root_id=?", (root_id,)
        ).fetchone()
        with self._index_cache_lock:
            saved = self._index_cache.get(root_id)
            if saved is not None and saved[0] == revision:
                self._index_cache.move_to_end(root_id)
                return saved[1]
            row = tx.connection.execute(
                "SELECT body FROM objects WHERE kind='index' AND id=?", (root_id,)
            ).fetchone()
            if row is None:
                self._index_cache.pop(root_id, None)
                self._index_cache_sizes.pop(root_id, None)
                self._prepared_indexes.pop(root_id, None)
                return None
            encoded = row[0]
            value = json.loads(encoded)
            size = len(encoded.encode("utf-8"))
            if size > MAX_INDEX_CACHE_BYTES:
                self._index_cache.pop(root_id, None)
                self._index_cache_sizes.pop(root_id, None)
                self._prepared_indexes.pop(root_id, None)
                return value
            # Freshness-only publications can retain the prepared token index.
            if saved is not None and saved[1]["items"] == value["items"]:
                value["items"] = saved[1]["items"]
            saved = (revision, value)
            self._index_cache[root_id] = saved
            self._index_cache_sizes[root_id] = size
            self._index_cache.move_to_end(root_id)
            while len(self._index_cache) > 4 or sum(self._index_cache_sizes.values()) > MAX_INDEX_CACHE_BYTES:
                evicted, _ = self._index_cache.popitem(last=False)
                self._index_cache_sizes.pop(evicted)
                self._prepared_indexes.pop(evicted, None)
            return saved[1]

    def read_audit(self, tx):
        """Return this transaction's immutable audit snapshot, caching bounded revisions.

        Audit rows are append-only, so the maximum sequence number identifies a
        complete snapshot.  An older reader must still receive its own snapshot;
        it must not replace a cache built by a newer transaction.
        """
        revision = tx.connection.execute("SELECT MAX(seq) FROM audit").fetchone()[0]
        with self._audit_cache_lock:
            cached = self._audit_cache
            if cached is not None and cached[0] == revision:
                return cached[1]
            count, encoded_bytes = tx.connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(LENGTH(CAST(body AS BLOB))), 0) FROM audit"
            ).fetchone()
            events = tx.events()
            if count > MAX_AUDIT_CACHE_EVENTS or encoded_bytes > MAX_AUDIT_CACHE_BYTES:
                return events
            if cached is None or cached[0] is None or (revision is not None and cached[0] <= revision):
                self._audit_cache = (revision, events)
            return events

    def location(self, tx, root_id, relative):
        root = tx.get("root", root_id)
        if root is None:
            raise ApiError("INVALID_TARGET", "Неизвестный логический корень.", 422)
        path = PurePosixPath(relative)
        if (
            not relative
            or "\\" in relative
            or relative.startswith("/")
            or any(p in ("", ".", "..") for p in relative.split("/"))
        ):
            raise ApiError("PATH_OUTSIDE_ROOT", "Путь должен находиться внутри корня.", 422)
        return {
            "root_id": root_id,
            "relative_path": str(path),
            "display_path": root["display_prefix"].rstrip("/") + "/" + str(path),
        }

    def physical(self, tx, location):
        checked = self.location(tx, location["root_id"], location["relative_path"])
        root = tx.require("root", checked["root_id"])
        return "/".join(p for p in (root["_base"], checked["relative_path"]) if p)

    def exists(self, tx, location):
        return self.fs.exists(self.physical(tx, location))

    def targets(self, tx, company_id):
        company = tx.require("company", company_id)
        result = []
        for target in company["_targets"]:
            loc = self.location(tx, target["root_id"], target["relative_directory"])
            if self.fs.is_directory(self.physical(tx, loc)):
                result.append({**target, "display_path": loc["display_path"]})
        return sorted(result, key=lambda value: (value["display_path"].casefold(), value["display_path"]))

    def ready_items(self, tx, company_id):
        return [
            public(q)
            for q in tx.list("queue")
            if q["company_id"] == company_id and q["status"] == "READY" and q["selectable"]
        ]

    def plan(self, tx, items, rules, company_id):
        company = tx.require("company", company_id)

        def source_info(location):
            meta = self.fs.stat(self.physical(tx, location))
            return (
                None
                if meta is None
                else {
                    "filename": location["relative_path"].split("/")[-1],
                    "location": location,
                    "size_bytes": meta["size"],
                    "modified_at": utc(meta["mtime_ns"] / 1e9),
                }
            )

        return plan_rows(
            items,
            rules,
            {"root_id": "manual-root", "relative_directory": company["_folder"]},
            lambda loc: self.exists(tx, loc),
            location=lambda root_id, relative: self.location(tx, root_id, relative),
            source_info=source_info,
        )

    def page(self, tx, scope, actor, query, payload, field="items", cursor=None, limit=100):
        if cursor is None and len(payload[field]) <= limit:
            return {**payload, field: payload[field][:limit], "next_cursor": None}
        if not tx.write:
            # The payload belongs to the caller's consistent read snapshot.
            # Persist only pagination metadata in a separate, short write unit.
            with self.store.transaction() as writer:
                return self.page(writer, scope, actor, query, payload, field, cursor, limit)
        filters = {k: v for k, v in query.items() if k not in ("cursor", "limit")}
        signature = digest(filters)
        offset = 0
        now = self.settings.clock()
        expires = now + PAGE_CURSOR_SECONDS
        snapshot = None
        if cursor:
            saved = tx.get("cursor", cursor)
            if (
                saved is None
                or saved["scope"] != scope
                or saved["owner"] != actor["user_id"]
                or saved["query"] != signature
                or saved["expires"] <= now
            ):
                raise ApiError("VALIDATION_ERROR", "Недействительный курсор страницы.", 422)
            offset, expires = saved["offset"], saved["expires"]
            if "payload" in saved:  # Cursor created before compact snapshots were introduced.
                snapshot_id = "page-snapshot-legacy-" + digest(cursor)[:32]
                snapshot = tx.get("page_snapshot", snapshot_id)
                if snapshot is None:
                    payload = saved["payload"]
            else:
                snapshot = tx.get("page_snapshot", saved.get("snapshot_id"))
                if (
                    snapshot is None
                    or snapshot["scope"] != scope
                    or snapshot["owner"] != actor["user_id"]
                    or snapshot["query"] != signature
                    or snapshot["expires"] <= now
                ):
                    raise ApiError("VALIDATION_ERROR", "Недействительный курсор страницы.", 422)
            if snapshot is not None:
                payload = snapshot["payload"]
        else:
            _delete_expired_pages(tx, now)
            snapshot_id = "page-snapshot-" + digest([scope, actor["user_id"], signature, field, payload])
            snapshot = tx.get("page_snapshot", snapshot_id)
            if snapshot is not None:
                expires = snapshot["expires"]
        result = {**payload, field: payload[field][offset : offset + limit], "next_cursor": None}
        if offset + limit < len(payload[field]):
            if snapshot is None:
                payload_bytes = _snapshot_bytes(payload)
                _check_page_quota(tx, actor["user_id"], payload_bytes)
                snapshot = {
                    "snapshot_id": ("page-snapshot-legacy-" + digest(cursor)[:32] if cursor else snapshot_id),
                    "scope": scope,
                    "owner": actor["user_id"],
                    "query": signature,
                    "payload": payload,
                    "payload_bytes": payload_bytes,
                    "expires": expires,
                }
                tx.put("page_snapshot", snapshot["snapshot_id"], snapshot)
            next_offset = offset + limit
            key = (
                "cursor-"
                + digest([scope, actor["user_id"], signature, snapshot["snapshot_id"], next_offset, expires])[
                    :32
                ]
            )
            tx.put(
                "cursor",
                key,
                {
                    "cursor_id": key,
                    "scope": scope,
                    "owner": actor["user_id"],
                    "query": signature,
                    "snapshot_id": snapshot["snapshot_id"],
                    "offset": next_offset,
                    "expires": expires,
                },
            )
            result["next_cursor"] = key
        return result

    def reserve_audit_snapshot(self, actor, signature, cutoff_seq, newest_event_id):
        """Persist compact immutable audit pagination metadata in a short write unit."""
        now = self.settings.clock()
        expires = now + PAGE_CURSOR_SECONDS
        with self.store.transaction() as tx:
            _delete_expired_pages(tx, now)
            row = tx.connection.execute(
                "SELECT body FROM objects WHERE kind='page_snapshot' "
                "AND json_extract(body, '$.kind')='audit-seq' "
                "AND json_extract(body, '$.owner')=? "
                "AND json_extract(body, '$.query')=? "
                "AND CAST(json_extract(body, '$.cutoff_seq') AS INTEGER)=? "
                "AND CAST(json_extract(body, '$.expires') AS REAL)>? LIMIT 1",
                (actor["user_id"], signature, cutoff_seq, now),
            ).fetchone()
            if row is not None:
                saved = json.loads(row[0])
                return saved
            snapshot_id = (
                "audit-page-snapshot-" + digest([actor["user_id"], signature, cutoff_seq, expires])[:32]
            )
            metadata = {
                "snapshot_id": snapshot_id,
                "kind": "audit-seq",
                "owner": actor["user_id"],
                "query": signature,
                "cutoff_seq": cutoff_seq,
                "newest_event_id": newest_event_id,
                "expires": expires,
            }
            metadata["payload_bytes"] = _snapshot_bytes(metadata)
            _check_page_quota(tx, actor["user_id"], metadata["payload_bytes"])
            tx.put("page_snapshot", snapshot_id, metadata)
            return metadata

    def create_audit_cursor(self, actor, signature, snapshot, occurred_at, event_id):
        """Bind one keyset position to the compact immutable audit snapshot."""
        now = self.settings.clock()
        key = (
            "cursor-"
            + digest(
                [
                    "queryAuditEvents",
                    actor["user_id"],
                    signature,
                    snapshot["snapshot_id"],
                    occurred_at,
                    event_id,
                ]
            )[:32]
        )
        with self.store.transaction() as tx:
            saved = tx.get("page_snapshot", snapshot["snapshot_id"])
            if (
                saved is None
                or saved.get("kind") != "audit-seq"
                or saved.get("owner") != actor["user_id"]
                or saved.get("query") != signature
                or saved.get("expires", 0) <= now
            ):
                raise ApiError("VALIDATION_ERROR", "Недействительный курсор страницы.", 422)
            tx.put(
                "cursor",
                key,
                {
                    "cursor_id": key,
                    "scope": "queryAuditEvents",
                    "owner": actor["user_id"],
                    "query": signature,
                    "snapshot_id": saved["snapshot_id"],
                    "expires": saved["expires"],
                    "audit_keyset": True,
                    "occurred_at": occurred_at,
                    "event_id": event_id,
                },
            )
        return key

    def batch_attempts(self, tx, batch_ids):
        """Group all attempt rows once for a batch-list snapshot."""
        grouped = {batch_id: [] for batch_id in batch_ids}
        batch_ids = tuple(grouped)
        if not batch_ids:
            return grouped
        # SQLite accepts a bounded number of bind variables. Chunk the batch
        # identifiers so a long retained history does not turn one API read
        # into a Python decode of every attempt from every company.
        for offset in range(0, len(batch_ids), 900):
            chunk = batch_ids[offset : offset + 900]
            placeholders = ",".join("?" for _ in chunk)
            rows = tx.connection.execute(
                "SELECT body FROM objects WHERE kind='attempt' "
                f"AND json_extract(body, '$.batch_id') IN ({placeholders})",
                chunk,
            )
            for (body,) in rows:
                attempt = json.loads(body)
                grouped[attempt["batch_id"]].append(attempt)
        return grouped

    def batch(self, tx, batch_id, *, attempts=None):
        batch = public(tx.require("batch", batch_id))
        if attempts is None:
            attempts = self.batch_attempts(tx, {batch_id})[batch_id]
        outcomes = [a["outcome"] for a in attempts]
        outcomes.sort(key=lambda o: o["attempt_id"])
        counts = {
            key: 0
            for key in (
                "sorted",
                "manual_review",
                "requires_decision",
                "quarantined",
                "skipped",
                "recovery_required",
            )
        }
        for outcome in outcomes:
            if outcome["state"].lower() in counts:
                counts[outcome["state"].lower()] += 1
        completed = sum(counts[k] for k in counts if k != "recovery_required")
        started = [o["started_at"] for o in outcomes if o["started_at"]]
        finished = [o["finished_at"] for o in outcomes if o["finished_at"]]
        if completed == batch["selected_count"]:
            status = "COMPLETED" if counts["sorted"] == completed else "COMPLETED_WITH_ISSUES"
        elif counts["recovery_required"]:
            status = "RECOVERY_REQUIRED"
        elif started:
            status = "RUNNING"
        else:
            status = "ACCEPTED"
        return {
            **batch,
            "outcomes": outcomes,
            "counts": counts,
            "completed_count": completed,
            "started_at": min(started) if started else None,
            "finished_at": max(finished) if completed == batch["selected_count"] and finished else None,
            "status": status,
            "next_cursor": None,
        }

    def idempotent(self, tx, operation, actor, key, body, action):
        record_id = digest([actor["user_id"], operation, key])
        previous = tx.get("idempotency", record_id)
        if previous:
            if previous["body"] != digest(body):
                raise ApiError("IDEMPOTENCY_KEY_REUSED", "Ключ уже использован с другим запросом.", 409)
            if "error" in previous:
                e = previous["error"]
                raise ApiError(e["code"], e["message"], e["status"], operation_id=e["operation_id"])
            return previous["status"], previous["result"]
        status, result = action()
        tx.insert("idempotency", record_id, {"body": digest(body), "status": status, "result": result})
        return status, result
