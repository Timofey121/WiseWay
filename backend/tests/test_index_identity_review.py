import os
from dataclasses import replace

from wiseway.common import digest, timestamp
from wiseway.indexer import Indexer, _technical_name
from wiseway.services import Context
from wiseway.worker import Worker


def _scan_until_ready(ctx):
    with ctx.store.transaction() as tx:
        for item in tx.list("queue"):
            item["_observed_at"] = ctx.settings.clock() - ctx.settings.readiness_seconds - 1
            tx.put("queue", item["item_id"], item)
    Indexer(ctx).scan()


def test_failed_scan_preserves_last_successful_sync_time(configured, monkeypatch):
    now = [1_700_000_000.0]
    settings = replace(configured, clock=lambda: now[0])
    context = Context(settings)
    try:
        indexer = Indexer(context)
        now[0] += 10
        indexer.scan()
        with context.store.transaction(write=False) as tx:
            before = tx.require("index", "archive-root")["freshness"]["last_successful_sync_at"]

        original_walk = context.fs.walk
        monkeypatch.setattr(
            context.fs,
            "walk",
            lambda path: (
                (_ for _ in ()).throw(OSError("forced failure")) if path == "Archive" else original_walk(path)
            ),
        )
        now[0] += 10
        indexer.scan()
        with context.store.transaction(write=False) as tx:
            after = tx.require("index", "archive-root")["freshness"]
            progress = tx.require("index_progress", "archive-root")

        assert after["status"] == "STALE"
        assert timestamp(after["last_successful_sync_at"]) == timestamp(before)
        assert progress["status"] == "FAILED"
    finally:
        context.close()


def test_hardlinked_incoming_names_are_distinct_ready_queue_items(configured):
    first = configured.sandbox_dir / "Incoming/Atlas/hardlink-first.pdf"
    second = configured.sandbox_dir / "Incoming/Atlas/hardlink-second.pdf"
    first.write_bytes(b"same inode")
    os.link(first, second)

    context = Context(configured)
    try:
        Indexer(context).scan()
        _scan_until_ready(context)
        with context.store.transaction(write=False) as tx:
            items = [
                item
                for item in tx.list("queue")
                if item["source"]["relative_path"] in {first.name, second.name}
            ]
        assert len(items) == 2
        assert {item["status"] for item in items} == {"READY"}
        assert len({item["item_id"] for item in items}) == 2
    finally:
        context.close()


def test_search_index_keeps_distinct_hardlink_ids_stable_across_unchanged_scans(configured):
    first = configured.sandbox_dir / "Archive/Atlas/Orion_2031/Reports/search-first.pdf"
    second = configured.sandbox_dir / "Archive/Atlas/Orion_2031/Reports/search-second.pdf"
    first.write_bytes(b"same inode")
    os.link(first, second)

    context = Context(configured)
    try:
        indexer = Indexer(context)
        indexer.scan()
        with context.store.transaction(write=False) as tx:
            first_index = tx.require("index", "archive-root")
            first_ids = {
                item["location"]["relative_path"]: item["item_id"]
                for item in first_index["items"]
                if item["location"]["relative_path"].endswith((first.name, second.name))
            }
        indexer.scan()
        with context.store.transaction(write=False) as tx:
            second_index = tx.require("index", "archive-root")
            second_ids = {
                item["location"]["relative_path"]: item["item_id"]
                for item in second_index["items"]
                if item["location"]["relative_path"].endswith((first.name, second.name))
            }

        assert len(first_ids) == 2
        assert len(set(first_ids.values())) == 2
        assert second_ids == first_ids
    finally:
        context.close()


def test_identity_profile_rebuilds_a_legacy_duplicate_hardlink_index(configured):
    first = configured.sandbox_dir / "Archive/Atlas/Orion_2031/Reports/legacy-first.pdf"
    second = configured.sandbox_dir / "Archive/Atlas/Orion_2031/Reports/legacy-second.pdf"
    first.write_bytes(b"same inode")
    os.link(first, second)

    context = Context(configured)
    try:
        indexer = Indexer(context)
        indexer.scan()
        with context.store.transaction() as tx:
            legacy = tx.require("index", "archive-root")
            legacy["_entry_ids"] = {}
            root = tx.require("root", "archive-root")
            files = [(path, meta) for path, meta in indexer._walk(root) if not _technical_name(path)]
            legacy["_fingerprint_digest"] = digest(
                {
                    "files": files,
                    "schema_set_version": root["schema_set_version"],
                    "schema": root["_schema"],
                    "prefixes": root.get("_scan_prefixes", [""]),
                }
            )
            legacy["root"]["index_generation"] = "generation-legacy"
            tx.put("index", "archive-root", legacy)

        indexer.scan()
        with context.store.transaction(write=False) as tx:
            upgraded = tx.require("index", "archive-root")
            items = [
                item
                for item in upgraded["items"]
                if item["location"]["relative_path"].endswith((first.name, second.name))
            ]
        assert upgraded["root"]["index_generation"] != "generation-legacy"
        assert len({item["item_id"] for item in items}) == 2
    finally:
        context.close()


def test_hardlinked_items_can_be_moved_independently(configured):
    first = configured.sandbox_dir / "Incoming/Atlas/move-first.pdf"
    second = configured.sandbox_dir / "Incoming/Atlas/move-second.pdf"
    first.write_bytes(b"same inode")
    os.link(first, second)

    context = Context(configured)
    try:
        Indexer(context).scan()
        _scan_until_ready(context)
        with context.store.transaction() as tx:
            items = sorted(
                [
                    item
                    for item in tx.list("queue")
                    if item["source"]["relative_path"] in {first.name, second.name}
                ],
                key=lambda item: item["filename"],
            )
            for number, item in enumerate(items):
                target = context.location(
                    tx, "archive-root", f"Archive/Atlas/Orion_2031/Reports/moved-{number}.pdf"
                )
                attempt_id = f"hardlink-attempt-{number}"
                tx.put(
                    "attempt",
                    attempt_id,
                    {
                        "attempt_id": attempt_id,
                        "batch_id": "hardlink-batch",
                        "company_id": item["company_id"],
                        "actor": {
                            "user_id": "user-worker-atlas",
                            "login": "worker-atlas",
                            "display_name": "Atlas worker",
                            "role": "WORKER",
                        },
                        "request_id": attempt_id,
                        "item": item,
                        "plan": {
                            "predicted_state": "WILL_MOVE",
                            "reason_code": None,
                            "target": target,
                            "selected_rule": None,
                        },
                        "outcome": {
                            "attempt_id": attempt_id,
                            "item_id": item["item_id"],
                            "item_revision": item["item_revision"],
                            "state": "PENDING",
                            "reason_code": None,
                            "source": item["source"],
                            "planned_target": target,
                            "actual_location": None,
                            "matched_rule": None,
                            "started_at": None,
                            "finished_at": None,
                        },
                        "phase": "QUEUED",
                        "intent_target": None,
                        "intended_state": None,
                        "intended_reason": None,
                    },
                )
                tx.put("claim", item["item_id"], {"attempt_id": attempt_id, "batch_id": "hardlink-batch"})
                item.update(status="PROCESSING", selectable=False, active_attempt_id=attempt_id)
                tx.put("queue", item["item_id"], item)

        assert Worker(context).run_once() == 2
        with context.store.transaction(write=False) as tx:
            outcomes = [tx.require("attempt", f"hardlink-attempt-{number}")["outcome"] for number in range(2)]
        assert [outcome["state"] for outcome in outcomes] == ["SORTED", "SORTED"]
    finally:
        context.close()
