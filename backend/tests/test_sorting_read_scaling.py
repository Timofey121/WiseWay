"""Regression coverage for bounded sorting read paths."""

from collections import Counter

from wiseway.common import public, utc
from wiseway.sorting import SortingService, queue_generation, queue_items, queue_snapshot
from wiseway.storage import UnitOfWork


def _actor(tx):
    return public(tx.require("user", "user-worker-atlas")["actor"])


def _outcome(batch_number, attempt_number, state):
    done = state in {"SORTED", "MANUAL_REVIEW"}
    timestamp = "2026-01-01T00:00:00.000000Z" if done else None
    return {
        "attempt_id": f"attempt-{batch_number:03}-{attempt_number:03}",
        "item_id": f"item-{batch_number:03}-{attempt_number:03}",
        "item_revision": 1,
        "state": state,
        "reason_code": None,
        "source": {
            "root_id": "root-demo",
            "relative_path": "Incoming/file.pdf",
            "display_path": "DEMO:/Incoming/file.pdf",
        },
        "planned_target": None,
        "actual_location": None,
        "matched_rule": None,
        "started_at": timestamp,
        "finished_at": timestamp,
    }


def test_list_batches_groups_attempts_once_and_preserves_summaries(configured, monkeypatch):
    """Listing B batches must read the A attempt rows once, not B times."""
    from wiseway.services import Context

    ctx = Context(configured)
    try:
        with ctx.store.transaction() as tx:
            company_id = tx.list("company")[0]["company_id"]
            actor = _actor(tx)
            for batch_number in range(20):
                batch_id = f"batch-scaling-{batch_number:03}"
                selected_count = 30
                tx.insert(
                    "batch",
                    batch_id,
                    {
                        "batch_id": batch_id,
                        "company_id": company_id,
                        "actor": actor,
                        "selection_id": f"selection-{batch_number}",
                        "preview_id": None,
                        "rule_set": {"rule_set_id": "rules", "revision": 1},
                        "created_at": utc(1_700_000_000 + batch_number),
                        "selected_count": selected_count,
                    },
                )
                for attempt_number in range(selected_count):
                    if batch_number == 2:
                        state = "RECOVERY_REQUIRED" if attempt_number == 0 else "PENDING"
                    elif batch_number == 3:
                        state = "PENDING"
                    else:
                        state = "SORTED" if attempt_number % 3 else "MANUAL_REVIEW"
                    outcome = _outcome(batch_number, attempt_number, state)
                    tx.insert(
                        "attempt",
                        outcome["attempt_id"],
                        {"attempt_id": outcome["attempt_id"], "batch_id": batch_id, "outcome": outcome},
                    )

            service = SortingService(ctx)
            expected = [ctx.batch(tx, f"batch-scaling-{number:03}") for number in range(20)]
            calls = Counter()
            attempt_queries = []
            original_list = UnitOfWork.list

            def counted_list(unit, kind):
                calls[kind] += 1
                return original_list(unit, kind)

            monkeypatch.setattr(UnitOfWork, "list", counted_list)
            tx.connection.set_trace_callback(attempt_queries.append)
            status, payload = service.handle(
                "listSortingBatches",
                tx,
                actor,
                {"company_id": company_id, "cursor": None, "limit": 100},
                None,
                "request-scaling",
            )
            tx.connection.set_trace_callback(None)

        assert status == 200
        assert calls["batch"] == 1
        assert calls["attempt"] == 0
        assert sum("FROM objects WHERE kind='attempt'" in statement for statement in attempt_queries) == 1
        keys = (
            "batch_id",
            "company_id",
            "actor",
            "status",
            "created_at",
            "finished_at",
            "selected_count",
            "completed_count",
            "counts",
        )
        expected_items = [
            {key: value[key] for key in keys}
            for value in sorted(
                expected, key=lambda value: (value["created_at"], value["batch_id"]), reverse=True
            )
        ]
        assert payload["items"] == expected_items
    finally:
        ctx.close()


def test_queue_query_reuses_one_snapshot_for_items_counters_and_generation(configured, monkeypatch):
    from wiseway.services import Context

    ctx = Context(configured)
    try:
        with ctx.store.transaction() as tx:
            company_id = tx.list("company")[0]["company_id"]
            actor = _actor(tx)
            filters = {"statuses": [], "query_text": ""}
            expected_items = [public(item) for item in queue_items(tx, company_id, filters)]
            expected_generation = queue_generation(tx, company_id)
            calls = Counter()
            original_list = UnitOfWork.list

            def counted_list(unit, kind):
                calls[kind] += 1
                return original_list(unit, kind)

            monkeypatch.setattr(UnitOfWork, "list", counted_list)
            statements = []
            tx.connection.set_trace_callback(statements.append)
            status, payload = SortingService(ctx).handle(
                "querySortingQueue",
                tx,
                actor,
                {},
                {"company_id": company_id, "filters": filters, "cursor": None, "limit": 100},
                "request-queue-scaling",
            )
            tx.connection.set_trace_callback(None)

        assert status == 200
        assert calls["queue"] == 0
        queue_reads = [
            statement for statement in statements if "FROM objects" in statement and "queue" in statement
        ]
        assert len(queue_reads) == 1
        assert payload["items"] == expected_items
        assert payload["queue_generation"] == expected_generation
        assert payload["matching_count"] == len(expected_items)
        assert payload["eligible_count"] == sum(item["selectable"] for item in expected_items)
    finally:
        ctx.close()


def test_empty_batch_list_does_not_scan_attempt_history(configured, monkeypatch):
    from wiseway.services import Context

    ctx = Context(configured)
    try:
        with ctx.store.transaction() as tx:
            company_id = tx.list("company")[0]["company_id"]
            actor = _actor(tx)
            calls = Counter()
            original_list = UnitOfWork.list

            def counted_list(unit, kind):
                calls[kind] += 1
                return original_list(unit, kind)

            monkeypatch.setattr(UnitOfWork, "list", counted_list)
            status, payload = SortingService(ctx).handle(
                "listSortingBatches",
                tx,
                actor,
                {"company_id": company_id, "cursor": None, "limit": 100},
                None,
                "request-empty-scaling",
            )

        assert status == 200
        assert payload["items"] == []
        assert calls["batch"] == 1
        assert calls["attempt"] == 0
    finally:
        ctx.close()


def test_queue_snapshot_reads_only_the_requested_company_without_unit_list(configured, monkeypatch):
    """A queue read must not decode another company's rows before filtering."""
    from wiseway.services import Context

    ctx = Context(configured)
    try:
        with ctx.store.transaction() as tx:
            company_id = tx.list("company")[0]["company_id"]
            source = tx.list("queue")[0]
            other = {**source, "item_id": "queue-unrelated-scaling", "company_id": "other-company"}
            tx.insert("queue", other["item_id"], other)
            original_list = UnitOfWork.list

            def forbidden_list(unit, kind):
                if kind == "queue":
                    raise AssertionError("queue snapshot must filter in SQLite before JSON decoding")
                return original_list(unit, kind)

            statements = []
            monkeypatch.setattr(UnitOfWork, "list", forbidden_list)
            tx.connection.set_trace_callback(statements.append)
            snapshot = queue_snapshot(tx, company_id)
            tx.connection.set_trace_callback(None)

        assert snapshot
        assert all(row["company_id"] == company_id for row in snapshot)
        queue_reads = [
            statement for statement in statements if "FROM objects" in statement and "queue" in statement
        ]
        assert len(queue_reads) == 1
    finally:
        ctx.close()


def test_batch_reads_attempts_by_batch_without_unit_list(configured, monkeypatch):
    from wiseway.services import Context

    ctx = Context(configured)
    try:
        with ctx.store.transaction() as tx:
            company_id = tx.list("company")[0]["company_id"]
            actor = _actor(tx)
            batch_id = "batch-single-read"
            tx.insert(
                "batch",
                batch_id,
                {
                    "batch_id": batch_id,
                    "company_id": company_id,
                    "actor": actor,
                    "selection_id": "selection-single-read",
                    "preview_id": None,
                    "rule_set": {"rule_set_id": "rules", "revision": 1},
                    "created_at": utc(1_700_000_000),
                    "selected_count": 1,
                },
            )
            outcome = _outcome(99, 1, "SORTED")
            tx.insert(
                "attempt",
                outcome["attempt_id"],
                {"attempt_id": outcome["attempt_id"], "batch_id": batch_id, "outcome": outcome},
            )
            original_list = UnitOfWork.list

            def forbidden_list(unit, kind):
                if kind == "attempt":
                    raise AssertionError("single batch must filter attempts in SQLite")
                return original_list(unit, kind)

            statements = []
            monkeypatch.setattr(UnitOfWork, "list", forbidden_list)
            tx.connection.set_trace_callback(statements.append)
            result = ctx.batch(tx, batch_id)
            tx.connection.set_trace_callback(None)

        assert result["batch_id"] == batch_id
        attempt_reads = [
            statement for statement in statements if "FROM objects" in statement and "attempt" in statement
        ]
        assert len(attempt_reads) == 1
    finally:
        ctx.close()


def test_sorting_read_queries_use_partial_lookup_indexes(configured):
    from wiseway.services import Context

    ctx = Context(configured)
    try:
        with ctx.store.transaction(write=False) as tx:
            queue_plan = tx.connection.execute(
                "EXPLAIN QUERY PLAN SELECT body FROM objects INDEXED BY queue_company_order "
                "WHERE kind='queue' AND json_extract(body, '$.company_id')=? ORDER BY id",
                ("company-atlas",),
            ).fetchall()
            attempt_plan = tx.connection.execute(
                "EXPLAIN QUERY PLAN SELECT body FROM objects "
                "WHERE kind='attempt' AND json_extract(body, '$.batch_id') IN (?)",
                ("batch-any",),
            ).fetchall()

        assert any("queue_company_order" in row[-1] for row in queue_plan)
        assert any("attempt_batch_lookup" in row[-1] for row in attempt_plan)
    finally:
        ctx.close()
