"""Metadata-only index and incoming-file readiness reconciliation."""

from __future__ import annotations

import time
from typing import Any

from .common import digest, public, utc
from .search import build_item


CHECKPOINT_INTERVAL = 100


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
        }
        config_digest = digest(config)
        with self.ctx.store.transaction() as tx:
            saved = tx.get("index_progress", root["root_id"], {})
            can_resume = saved.get("status") == "SCANNING" and saved.get("_config_digest") == config_digest
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
            verified_prefix = [[path, meta] for path, meta in found[: len(staged_found)]]
            if verified_prefix != staged_found or len(staged_found) != len(staged_items):
                staged_found, staged_items = [], []
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
                        f"file-{root['root_id']}-{meta['dev']}-{meta['ino']}",
                    )
                )
                if count % CHECKPOINT_INTERVAL == 0 or count == len(found):
                    self._checkpoint(root, config_digest, found, items, count, started)
        except Exception:
            with self.ctx.store.transaction() as tx:
                previous = tx.get("index", root["root_id"])
                if previous:
                    previous["freshness"] = {
                        "indexed_at": previous["root"]["indexed_at"],
                        "last_successful_sync_at": previous["root"]["indexed_at"],
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
            return
        seen: set[str] = set()
        with self.ctx.store.transaction() as tx:
            existing = [item for item in tx.list("queue") if item["incoming_source_id"] == root["root_id"]]
            for relative, meta in found:
                item_id = f"queue-{root['root_id']}-{meta['dev']}-{meta['ino']}"
                previous = tx.get("queue", item_id)
                if previous is None:
                    previous = next(
                        (
                            item
                            for item in existing
                            if item["status"] == "MISSING" and item["source"]["relative_path"] == relative
                        ),
                        None,
                    )
                    if previous is not None:
                        item_id = previous["item_id"]
                seen.add(item_id)
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
