#!/usr/bin/env python3
"""Measure audit and batch services against isolated, persisted synthetic history."""

import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time


sys.path.insert(0, os.environ.get("WISEWAY_BENCHMARK_BACKEND", str(Path(__file__).resolve().parents[1])))

from wiseway.app import dispatch  # noqa: E402
from wiseway.audit import emit  # noqa: E402
from wiseway.common import ApiError, Settings  # noqa: E402
from wiseway.seed import initialize  # noqa: E402
from wiseway.services import Context  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-events", type=int, default=50_000)
    parser.add_argument("--batches", type=int, default=200)
    parser.add_argument("--attempts", type=int, default=50)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if min(args.audit_events, args.batches, args.attempts, args.repeats) < 1:
        parser.error("All counts must be positive")
    results = {}
    with tempfile.TemporaryDirectory(prefix="wiseway-read-paths-") as temporary:
        base = Path(temporary)
        settings = Settings(data_dir=base / "state", sandbox_dir=base / "sandbox")
        initialize(settings, password="synthetic-test-password")
        ctx = Context(settings)
        try:
            with ctx.store.transaction() as tx:
                actor = tx.require("user", "user-worker-atlas")["actor"]
                for number in range(args.audit_events):
                    emit(tx, actor, "DRAFT_SAVED", f"benchmark-event-{number}", now=1_800_000_000 + number)
                for batch_number in range(args.batches):
                    batch_id = f"benchmark-batch-{batch_number:06d}"
                    tx.put(
                        "batch",
                        batch_id,
                        {
                            "batch_id": batch_id,
                            "company_id": "company-atlas",
                            "actor": actor,
                            "selected_count": args.attempts,
                            "created_at": "2026-01-01T00:00:00Z",
                        },
                    )
                    for number in range(args.attempts):
                        attempt_id = f"{batch_id}-attempt-{number:06d}"
                        tx.put(
                            "attempt",
                            attempt_id,
                            {
                                "batch_id": batch_id,
                                "outcome": {
                                    "attempt_id": attempt_id,
                                    "state": "SORTED",
                                    "started_at": "2026-01-01T00:00:00Z",
                                    "finished_at": "2026-01-01T00:00:00Z",
                                },
                            },
                        )
            query = {
                "from": "2020-01-01T00:00:00Z",
                "to": "2099-01-01T00:00:00Z",
                "company_id": None,
                "action": None,
                "result": None,
                "actor_id": None,
                "query_text": "",
                "cursor": None,
                "limit": 100,
            }
            for name, params, body in (
                ("queryAuditEvents", {}, query),
                ("getAuditUpdates", {"after_event_id": None}, None),
                ("listAuditActors", {"prefix": "", "cursor": None, "limit": 100}, None),
                ("listSortingBatches", {"company_id": "company-atlas", "cursor": None, "limit": 100}, None),
            ):
                durations, error = [], None
                for _ in range(args.repeats):
                    started = time.perf_counter()
                    try:
                        with ctx.store.transaction(write=False) as tx:
                            status, result = dispatch(ctx, tx, name, actor, params, body, "benchmark-read")
                        assert status == 200
                        if name == "queryAuditEvents":
                            assert len(result["items"]) == min(100, args.audit_events)
                        elif name == "getAuditUpdates":
                            assert result["has_new_events"] is True
                        elif name == "listAuditActors":
                            assert actor in result["items"]
                        else:
                            assert len(result["items"]) == min(100, args.batches)
                            assert all(row["completed_count"] == args.attempts for row in result["items"])
                    except ApiError as failure:
                        if name != "queryAuditEvents" or failure.code != "RATE_LIMITED":
                            raise
                        error = failure.code
                    durations.append((time.perf_counter() - started) * 1000)
                results[name] = {"p50_ms": round(statistics.median(durations), 3), "error": error}
        finally:
            ctx.close()
    print(
        json.dumps(
            {
                "scope": "SQLite application services; excludes HTTP/wire validation and dataset preparation",
                "corpus": vars(args),
                "results": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
