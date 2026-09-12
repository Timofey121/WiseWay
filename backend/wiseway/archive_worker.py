"""Separate archive indexing process; file readiness stays on the regular worker."""

from threading import Event

from .common import utc
from .indexer import _index_lock
from .large_indexer import LargeIndexer


def run(ctx, *, interval=0, stop=None):
    stop = stop if stop is not None else Event()
    with _index_lock(ctx, "archive-indexer.lock") as held:
        if not held:
            raise RuntimeError("Another archive indexer is running")
        while not stop.is_set():
            # Switching the root while a legacy scan publishes could replace
            # the completed SQL generation with an obsolete JSON snapshot.
            with _index_lock(ctx) as transition_held:
                if not transition_held:
                    if not interval:
                        raise RuntimeError("File indexer is busy; retry archive indexing")
                    stop.wait(1)
                    continue
                with ctx.store.transaction() as tx:
                    roots = [
                        root
                        for root in tx.list("root")
                        if root.get("_searchable") and root.get("_index_storage") != "opensearch"
                    ]
                    for root in roots:
                        root["_index_storage"] = "sqlite"
                        tx.put("root", root["root_id"], root)
            completed = True
            for root in roots:
                if stop.is_set():
                    completed = False
                    break
                if not LargeIndexer(ctx).scan(root, stop=stop):
                    completed = False
                    break
            with ctx.store.transaction() as tx:
                failed = any(
                    tx.get("index_progress", root["root_id"], {}).get("status") == "FAILED" for root in roots
                )
                if completed and not failed:
                    tx.put(
                        "operator_state",
                        "archive_indexer",
                        {"last_completed_at": utc(ctx.settings.clock())},
                    )
            if not interval:
                return completed and not failed
            stop.wait(interval)
    return True
