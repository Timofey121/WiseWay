#!/usr/bin/env python3
"""Measure metadata search separately from filesystem scanning and HTTP overhead."""

import argparse
import cProfile
import json
import math
import os
from pathlib import Path
import platform
import resource
import sys
import tempfile
import time


sys.path.insert(0, os.environ.get("WISEWAY_BENCHMARK_BACKEND", str(Path(__file__).resolve().parents[1])))

from wiseway.search import DEMO_SCHEMAS, build_item, search  # noqa: E402
from wiseway.search_index import SearchIndex  # noqa: E402


ROOT = {
    "root_id": "scale-root",
    "schema_set_version": "schema-demo-1",
    "index_generation": "scale-generation",
    "indexed_at": "2026-01-01T00:00:00Z",
}


def run(count, repeats):
    started = time.perf_counter()
    rows = [
        build_item(
            ROOT["root_id"],
            "DEMO:/Scale",
            f"Archive/Atlas/Orion_2031/Reports/paper-{number:08d}.pdf",
            number % 17,
            "2026-01-01T00:00:00Z",
            DEMO_SCHEMAS["schema-demo-1"],
            f"scale-{number}",
        )
        for number in range(count)
    ]
    build_items_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    prepared = SearchIndex(rows)
    prepare_ms = (time.perf_counter() - started) * 1000
    cases = {}
    for name, query, field, expected in (
        ("rare", f"{count - 1:08d}", "RELEVANCE", 1),
        ("absent", "nonexistent", "RELEVANCE", 0),
        ("broad", "paper", "RELEVANCE", count),
        ("broad_size", "paper", "SIZE", count),
        ("idle", "", "PATH", None),
    ):
        elapsed = []
        for number in range(repeats + 1):
            body = {
                "request_state_id": f"scale-{number}",
                "root_id": ROOT["root_id"],
                "schema_set_version": ROOT["schema_set_version"],
                "selected_marker_ids": [],
                "query_text": query,
                "sort": {"field": field, "direction": "DESC"},
                "facet_prefix": "",
            }
            started = time.perf_counter()
            result = search(ROOT, rows, body, prepared=prepared)
            duration = (time.perf_counter() - started) * 1000
            assert result["total"] == expected, (name, result["total"], expected)
            assert result["returned_count"] == (min(100, expected) if expected else 0)
            if name == "rare":
                assert result["items"][0]["item_id"] == f"scale-{count - 1}"
            if name == "broad":
                assert [row["item_id"] for row in result["items"]] == [
                    f"scale-{offset}" for offset in range(min(100, count))
                ]
            if number:
                elapsed.append(duration)
        elapsed.sort()
        cases[name] = {
            "p50_ms": round(elapsed[math.ceil(repeats * 0.5) - 1], 3),
            "p95_ms": round(elapsed[math.ceil(repeats * 0.95) - 1], 3),
        }
    return {
        "records": count,
        "repeats": repeats,
        "build_items_ms": round(build_items_ms, 3),
        "prepare_ms": round(prepare_ms, 3),
        "search": cases,
    }


def run_api(count, repeats):
    from fastapi.testclient import TestClient

    from wiseway.app import create_app
    from wiseway.common import Settings
    from wiseway.seed import initialize
    from wiseway.services import Context

    with tempfile.TemporaryDirectory(prefix="wiseway-api-scale-") as temporary:
        base = Path(temporary)
        settings = Settings(data_dir=base / "state", sandbox_dir=base / "sandbox")
        initialize(settings, password="synthetic-test-password")
        ctx = Context(settings)
        try:
            with ctx.store.transaction() as tx:
                document = tx.require("index", "archive-root")
                document["items"] = [
                    build_item(
                        "archive-root",
                        "DEMO:/Scale",
                        f"Archive/Atlas/Orion_2031/Reports/paper-{number:08d}.pdf",
                        number,
                        "2026-01-01T00:00:00Z",
                        DEMO_SCHEMAS["schema-demo-1"],
                        f"scale-{number}",
                    )
                    for number in range(count)
                ]
                encoded_mib = len(json.dumps(document).encode()) / 1024**2
                tx.put("index", "archive-root", document)
            del document
        finally:
            ctx.close()
        cases = {}
        with TestClient(create_app(settings), base_url="http://localhost:8000") as client:
            login = client.post(
                "/api/v1/auth/login",
                headers={"Origin": "http://localhost:8000"},
                json={"login": "worker-atlas", "password": "synthetic-test-password"},
            )
            assert login.status_code == 200
            for name, query, expected in (("rare", f"{count - 1:08d}", 1), ("broad", "paper", count)):
                samples = []
                cold_ms = None
                for number in range(repeats + 1):
                    body = {
                        "request_state_id": f"api-scale-{number}",
                        "root_id": "archive-root",
                        "schema_set_version": "schema-demo-1",
                        "selected_marker_ids": [],
                        "query_text": query,
                        "sort": {"field": "RELEVANCE", "direction": "DESC"},
                        "facet_prefix": "",
                    }
                    started = time.perf_counter()
                    response = client.post("/api/v1/search", json=body)
                    elapsed = (time.perf_counter() - started) * 1000
                    assert response.status_code == 200, response.text
                    result = response.json()
                    assert result["total"] == expected
                    if name == "rare":
                        assert result["items"][0]["item_id"] == f"scale-{count - 1}"
                    else:
                        assert [row["item_id"] for row in result["items"]] == [
                            f"scale-{offset}" for offset in range(min(count, 100))
                        ]
                    if number:
                        samples.append(elapsed)
                    else:
                        cold_ms = elapsed
                samples.sort()
                cases[name] = {
                    "first_ms": round(cold_ms, 3),
                    "p50_ms": round(samples[math.ceil(repeats * 0.5) - 1], 3),
                    "p95_ms": round(samples[math.ceil(repeats * 0.95) - 1], 3),
                }
        return {"records": count, "index_json_mib": round(encoded_mib, 2), "search": cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=int, nargs="+", default=[10_000, 100_000])
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--profile", type=Path)
    parser.add_argument(
        "--api", action="store_true", help="Measure real ASGI/SQLite reads of synthetic metadata"
    )
    args = parser.parse_args()
    if min(args.records) < 1 or args.repeats < 1:
        parser.error("records and repeats must be positive")
    profile = cProfile.Profile() if args.profile else None
    if profile:
        profile.enable()
    results = [(run_api if args.api else run)(count, args.repeats) for count in args.records]
    if profile:
        profile.disable()
        profile.dump_stats(args.profile)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(
        json.dumps(
            {
                "scope": (
                    "ASGI/SQLite synthetic metadata; excludes filesystem scan and real TCP"
                    if args.api
                    else "prepared metadata algorithm; excludes database, HTTP and filesystem scanning"
                ),
                "runtime": {"python": platform.python_version(), "platform": platform.platform()},
                "peak_rss_mib": round(peak / (1024**2 if sys.platform == "darwin" else 1024), 2),
                "results": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
