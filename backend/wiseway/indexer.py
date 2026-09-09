"""Metadata-only index and incoming-file readiness reconciliation."""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from typing import Any

from .common import digest, public, uid, utc
from .search import build_item


CHECKPOINT_INTERVAL = 100
IDENTITY_PROFILE_VERSION = "directory-entry-v2"


def _inode(meta: dict[str, int]) -> tuple[int, int]:
    return meta["dev"], meta["ino"]


def _entry_ids(
    root_id: str,
    found: list[tuple[str, dict[str, int]]],
    previous: dict[str, Any] | None,
    staged_items: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Assign one stable ID per directory entry, retaining unambiguous renames."""
    old = (previous or {}).get("_entry_ids", {})
    current_paths = {path for path, _ in found}
    current_inode_counts = Counter(_inode(meta) for _, meta in found)
    old_by_inode: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    old_ids = set()
    for old_path, entry in old.items():
        if old_path not in current_paths:
            old_by_inode[_inode(entry)].append(entry)
        old_ids.add(entry["item_id"])
    assigned: set[str] = set()
    result: dict[str, str] = {}
    for path, item in zip((path for path, _ in found), staged_items or []):
        result[path] = item["item_id"]
        assigned.add(item["item_id"])
    for path, meta in found[len(result) :]:
        exact = old.get(path)
        if exact and _inode(exact) == _inode(meta) and exact["item_id"] not in assigned:
            item_id = exact["item_id"]
        else:
            candidates = [entry for entry in old_by_inode[_inode(meta)] if entry["item_id"] not in assigned]
            if current_inode_counts[_inode(meta)] == 1 and len(candidates) == 1:
                item_id = candidates[0]["item_id"]
            else:
                item_id = f"file-{root_id}-{meta['dev']}-{meta['ino']}"
                if item_id in assigned or item_id in old_ids:
                    item_id = uid("file")
        result[path] = item_id
        assigned.add(item_id)
    return result


def _strip_base(path: str, base: str) -> str:
    return path[len(base) + 1 :] if base and path.startswith(base + "/") else path


def _technical_name(path: str) -> bool:
    return path.rsplit("/", 1)[-1] in {".DS_Store", "Thumbs.db"}


def _temporary_name(path: str) -> bool:
    return path.casefold().endswith((".part", ".tmp", ".crdownload"))


class Indexer:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    def scan(self) -> None:
        with self.ctx.store.transaction() as tx:
            roots = tx.list("root")
        for root in roots:
            if root.get("_searchable"):
                self._scan_search_root(root)
            if root.get("_incoming_company"):
                self._scan_incoming_root(root)

    def _walk(self, root: dict[str, Any]) -> list[tuple[str, dict[str, int]]]:
        found: list[tuple[str, dict[str, int]]] = []
        for prefix in root.get("_scan_prefixes", [""]):
            physical = "/".join(part for part in (root["_base"], prefix) if part)
            for path, meta in self.ctx.fs.walk(physical):
                found.append((_strip_base(path, root["_base"]), meta))
        return sorted(found)

    def _scan_search_root(self, root: dict[str, Any]) -> None:
        now = self.ctx.settings.clock()
        started = time.monotonic()
        config = {
            "schema_set_version": root["schema_set_version"],
            "schema": root["_schema"],
            "prefixes": root.get("_scan_prefixes", [""]),
            "identity_profile": IDENTITY_PROFILE_VERSION,
        }
        config_digest = digest(config)
        with self.ctx.store.transaction() as tx:
            saved = tx.get("index_progress", root["root_id"], {})
            can_resume = (
                saved.get("status") in {"SCANNING", "FAILED"} and saved.get("_config_digest") == config_digest
            )
            staged_found = saved.get("_found", []) if can_resume else []
            staged_items = saved.get("_items", []) if can_resume else []
            tx.put(
                "index_progress",
                root["root_id"],
                {
                    "root_id": root["root_id"],
                    "status": "SCANNING",
                    "count": len(staged_items),
                    "checkpoint": staged_found[-1][0] if staged_found else None,
                    "estimated_remaining_seconds": None,
                    "_config_digest": config_digest,
                    "_found": staged_found,
                    "_items": staged_items,
                },
            )
        try:
            found = [(path, meta) for path, meta in self._walk(root) if not _technical_name(path)]
            fingerprint = digest({"files": found, **config})
            with self.ctx.store.transaction() as tx:
                previous = tx.get("index", root["root_id"])
                if previous and previous.get("_fingerprint_digest") == fingerprint:
                    previous["freshness"] = {
                        "indexed_at": previous["root"]["indexed_at"],
                        "last_successful_sync_at": utc(now),
                        "status": "CURRENT",
                    }
                    tx.put("index", root["root_id"], previous)
                    tx.put(
                        "index_progress",
                        root["root_id"],
                        {
                            "root_id": root["root_id"],
                            "status": "COMPLETE",
                            "count": len(previous["items"]),
                            "checkpoint": None,
                        },
                    )
                    return
            verified_prefix = [[path, meta] for path, meta in found[: len(staged_found)]]
            if verified_prefix != staged_found or len(staged_found) != len(staged_items):
                staged_found, staged_items = [], []
            entry_ids = _entry_ids(root["root_id"], found, previous, staged_items)
            items = list(staged_items)
            for count, (path, meta) in enumerate(found[len(items) :], start=len(items) + 1):
                items.append(
                    build_item(
                        root["root_id"],
                        root["display_prefix"],
                        path,
                        meta["size"],
                        utc(meta["mtime_ns"] / 1e9),
                        root["_schema"],
                        entry_ids[path],
                    )
                )
                if count % CHECKPOINT_INTERVAL == 0 or count == len(found):
                    self._checkpoint(root, config_digest, found, items, count, started)
        except Exception:
            with self.ctx.store.transaction() as tx:
                progress = tx.get("index_progress", root["root_id"], {})
                # Keep the verified checkpoint for the next scan, but expose
                # that this scan stopped instead of reporting active progress.
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
            return
        with self.ctx.store.transaction() as tx:
            previous = tx.get("index", root["root_id"])
            if previous and previous.get("_fingerprint_digest") == fingerprint:
                previous["freshness"] = {
                    "indexed_at": previous["root"]["indexed_at"],
                    "last_successful_sync_at": utc(now),
                    "status": "CURRENT",
                }
                tx.put("index", root["root_id"], previous)
                tx.put(
                    "index_progress",
                    root["root_id"],
                    {
                        "root_id": root["root_id"],
                        "status": "COMPLETE",
                        "count": len(items),
                        "checkpoint": None,
                    },
                )
                return
            public_root = public(root)
            public_root["index_generation"] = "generation-" + digest([root["root_id"], fingerprint])[:24]
            public_root["indexed_at"] = utc(now)
            tx.put(
                "index",
                root["root_id"],
                {
                    "root": public_root,
                    "items": items,
                    "_entry_ids": {
                        path: {"item_id": entry_ids[path], "dev": meta["dev"], "ino": meta["ino"]}
                        for path, meta in found
                    },
                    "_fingerprint_digest": fingerprint,
                    "freshness": {
                        "indexed_at": utc(now),
                        "last_successful_sync_at": utc(now),
                        "status": "CURRENT",
                    },
                },
            )
            tx.put(
                "index_progress",
                root["root_id"],
                {"root_id": root["root_id"], "status": "COMPLETE", "count": len(items), "checkpoint": None},
            )

    def _checkpoint(self, root, config_digest, found, items, count, started) -> None:
        elapsed = time.monotonic() - started
        remaining = None if elapsed <= 0 else max(0, round((len(found) - count) * elapsed / count, 3))
        with self.ctx.store.transaction() as tx:
            tx.put(
                "index_progress",
                root["root_id"],
                {
                    "root_id": root["root_id"],
                    "status": "SCANNING",
                    "count": count,
                    "checkpoint": found[count - 1][0],
                    "estimated_remaining_seconds": remaining,
                    "_config_digest": config_digest,
                    "_found": found[:count],
                    "_items": items,
                },
            )

    def _scan_incoming_root(self, root: dict[str, Any]) -> None:
        now = self.ctx.settings.clock()
        try:
            found = [
                (_strip_base(path, root["_base"]), meta) for path, meta in self.ctx.fs.walk(root["_base"])
            ]
        except Exception:
            self._incoming_progress(root, "FAILED")
            return
        seen: set[str] = set()
        with self.ctx.store.transaction() as tx:
            existing = [item for item in tx.list("queue") if item["incoming_source_id"] == root["root_id"]]
            found_paths = {relative for relative, _ in found}
            found_inode_counts = Counter(_inode(meta) for _, meta in found)
            existing_by_path = {item["source"]["relative_path"]: item for item in existing}
            existing_by_inode: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
            existing_ids = set()
            for item in existing:
                if item["source"]["relative_path"] not in found_paths:
                    existing_by_inode[_inode(item["_fingerprint"])].append(item)
                existing_ids.add(item["item_id"])
            assigned: set[str] = set()
            for relative, meta in found:
                previous = existing_by_path.get(relative)
                if previous is not None and previous["item_id"] in assigned:
                    previous = None
                if previous is None:
                    candidates = [
                        item for item in existing_by_inode[_inode(meta)] if item["item_id"] not in assigned
                    ]
                    previous = (
                        candidates[0]
                        if found_inode_counts[_inode(meta)] == 1 and len(candidates) == 1
                        else None
                    )
                if previous is not None:
                    item_id = previous["item_id"]
                else:
                    item_id = f"queue-{root['root_id']}-{meta['dev']}-{meta['ino']}"
                    if item_id in assigned or item_id in existing_ids:
                        item_id = uid("queue")
                seen.add(item_id)
                assigned.add(item_id)
                source = {
                    "root_id": root["root_id"],
                    "relative_path": relative,
                    "display_path": root["display_prefix"].rstrip("/") + "/" + relative,
                }
                if previous is None:
                    value = {
                        "item_id": item_id,
                        "item_revision": 1,
                        "company_id": root["_incoming_company"],
                        "incoming_source_id": root["root_id"],
                        "source_name": root["label"],
                        "source": source,
                        "filename": relative.split("/")[-1],
                        "size_bytes": meta["size"],
                        "modified_at": utc(meta["mtime_ns"] / 1e9),
                        "status": "WAITING_READY",
                        "reason_code": None,
                        "selectable": False,
                        "active_attempt_id": None,
                        "_fingerprint": meta,
                        "_observed_at": now,
                    }
                elif previous["status"] in {"PROCESSING", "RECOVERY_REQUIRED"} or previous.get(
                    "active_attempt_id"
                ):
                    value = previous
                elif (
                    previous.get("_fingerprint") == meta
                    and previous["source"]["relative_path"] == relative
                    and previous["status"] != "MISSING"
                ):
                    value = previous
                    value.update(
                        {
                            "source": source,
                            "filename": relative.split("/")[-1],
                            "size_bytes": meta["size"],
                            "modified_at": utc(meta["mtime_ns"] / 1e9),
                        }
                    )
                    if _temporary_name(relative):
                        value.update({"status": "WAITING_READY", "reason_code": None, "selectable": False})
                    elif (
                        value["status"] in {"DISCOVERED", "WAITING_READY"}
                        and now - value.get("_observed_at", now) >= self.ctx.settings.readiness_seconds
                    ):
                        value.update({"status": "READY", "reason_code": None, "selectable": True})
                else:
                    value = {
                        **previous,
                        "item_revision": previous["item_revision"] + 1,
                        "source": source,
                        "filename": relative.split("/")[-1],
                        "size_bytes": meta["size"],
                        "modified_at": utc(meta["mtime_ns"] / 1e9),
                        "status": "WAITING_READY",
                        "reason_code": None,
                        "selectable": False,
                        "_fingerprint": meta,
                        "_observed_at": now,
                        "_departed": False,
                    }
                tx.put("queue", item_id, value)
            for prior in existing:
                if (
                    prior["item_id"] not in seen
                    and not prior.get("_departed")
                    and prior["status"]
                    not in {"SORTED", "MANUAL_REVIEW", "QUARANTINED", "PROCESSING", "RECOVERY_REQUIRED"}
                ):
                    if prior["status"] != "MISSING":
                        prior.update(
                            {
                                "item_revision": prior["item_revision"] + 1,
                                "status": "MISSING",
                                "reason_code": "SOURCE_MISSING",
                                "selectable": False,
                            }
                        )
                    tx.put("queue", prior["item_id"], prior)
        self._incoming_progress(root, "COMPLETE", len(found))

    def _incoming_progress(self, root: dict[str, Any], status: str, count: int | None = None) -> None:
        with self.ctx.store.transaction() as tx:
            tx.put(
                "index_progress",
                f"incoming-{root['root_id']}",
                {
                    "root_id": root["root_id"],
                    "status": status,
                    "count": count,
                    "checkpoint": None,
                    "source_kind": "INCOMING",
                },
            )
