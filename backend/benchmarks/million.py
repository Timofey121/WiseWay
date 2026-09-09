#!/usr/bin/env python3
"""Build and query a durable one-million-record SQLite search generation.

The corpus contains logical metadata only.  It does not create a terabyte of
payload files, does not scan a live filesystem, and never opens ``.wiseway``.
It exercises the product's seed, SQLite generation storage and ASGI endpoint.

Examples:

    uv run python backend/benchmarks/million.py
    uv run python backend/benchmarks/million.py --records 10000 --repeats 3
    uv run python backend/benchmarks/million.py --data-dir /tmp/wise-way-million

With ``--data-dir``, the generated synthetic database is retained so that a
query-only repeat can measure a fresh process:

    uv run python backend/benchmarks/million.py --phase query --data-dir /tmp/wise-way-million
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import platform
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterator


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

from wiseway.app import create_app  # noqa: E402
from wiseway.common import Settings, public, utc  # noqa: E402
from wiseway.search import DEMO_SCHEMAS, build_item  # noqa: E402
from wiseway.seed import initialize  # noqa: E402
from wiseway.services import Context  # noqa: E402


ROOT_ID = "archive-root"
GENERATION = "million-benchmark-v1"
PASSWORD = "synthetic-million-benchmark-password"
CHUNK_SIZE = 1_000


def percentile(samples: list[float], ratio: float) -> float:
    ordered = sorted(samples)
    return round(ordered[max(0, math.ceil(len(ordered) * ratio) - 1)], 3)


def peak_rss_mib() -> float:
    # ru_maxrss is bytes on macOS and KiB on Linux.
    scale = 1024**2 if sys.platform == "darwin" else 1024
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / scale, 2)


def item_path(number: int) -> str:
    """Two valid schema paths, with numeric and Unicode filename cases."""
    if number % 2 == 0:
        return f"Archive/Atlas/Orion_2031/Reports/документ-{number:07d}.pdf"
    return f"Archive/Nova/Polaris_2030/North/Data/документ-{number:07d}.xlsx"


def item_rows(count: int) -> Iterator[dict[str, Any]]:
    schema = DEMO_SCHEMAS["schema-demo-1"]
    for number in range(count):
        yield build_item(
            ROOT_ID,
            "DEMO:/Million",
            item_path(number),
            900_000 + number % 200_001,
            "2026-01-01T00:00:00Z",
            schema,
            f"million-{number:07d}",
        )


def chunks(rows: Iterator[dict[str, Any]], size: int = CHUNK_SIZE) -> Iterator[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def marker_ids() -> dict[str, str]:
    """Derive marker IDs through product code instead of copying its hash rule."""
    sample = next(item_rows(1))
    return {marker["raw_value"]: marker["marker_id"] for marker in sample["markers"] if marker["raw_value"]}


def build(data_dir: Path, count: int) -> dict[str, Any]:
    """Persist an index generation in chunks; no generated list spans the corpus."""
    settings = Settings(data_dir=data_dir / "state", sandbox_dir=data_dir / "sandbox")
    initialize(settings, password=PASSWORD)
    started = time.perf_counter()
    context = Context(settings)
    try:
        # This module is introduced with the persistent-search implementation.
        # Keep this import local so --help remains available before installation.
        from wiseway.sqlite_search import add_items, create_generation, finish  # noqa: PLC0415

        with context.store.transaction() as tx:
            configured_root = tx.require("root", ROOT_ID)
            root = {**public(configured_root), "index_generation": GENERATION, "indexed_at": utc(0)}
            create_generation(tx, root, GENERATION)
        inserted = 0
        for batch in chunks(item_rows(count)):
            with context.store.transaction() as tx:
                add_items(tx, GENERATION, batch)
            inserted += len(batch)
            if inserted % 100_000 == 0 or inserted == count:
                print(f"indexed {inserted:,}/{count:,} metadata rows", file=sys.stderr, flush=True)
        with context.store.transaction() as tx:
            finish(tx, GENERATION)
            from wiseway.sqlite_search import activate_generation  # noqa: PLC0415

            activate_generation(tx, GENERATION)
            active_root = tx.require("root", ROOT_ID)
            active_root["index_generation"] = GENERATION
            active_root["indexed_at"] = utc(0)
            root = public(active_root)
            tx.put("root", ROOT_ID, active_root)
            tx.put(
                "index",
                ROOT_ID,
                {
                    "root": root,
                    "items": [],
                    "_storage": "sqlite",
                    "_generation": GENERATION,
                    "freshness": {
                        "indexed_at": root["indexed_at"],
                        "last_successful_sync_at": root["indexed_at"],
                        "status": "CURRENT",
                    },
                },
            )
    finally:
        context.close()
    database = settings.database
    bytes_on_disk = sum(
        path.stat().st_size
        for path in (database, database.with_name(database.name + "-wal"))
        if path.exists()
    )
    return {
        "records": inserted,
        "build_seconds": round(time.perf_counter() - started, 3),
        "database_bytes": bytes_on_disk,
        "peak_rss_mib": peak_rss_mib(),
    }


def request_body(query: str, *, selected: list[str] | None = None, state: str = "million") -> dict[str, Any]:
    return {
        "request_state_id": state,
        "root_id": ROOT_ID,
        "schema_set_version": "schema-demo-1",
        "selected_marker_ids": selected or [],
        "query_text": query,
        "sort": {"field": "RELEVANCE", "direction": "DESC"},
        "facet_prefix": "",
    }


def expected_atlas_ids(count: int, limit: int = 100) -> list[str]:
    """First page after filtering to Atlas (the even-numbered rows)."""
    return [f"million-{number:07d}" for number in range(0, min(count, 2 * limit), 2)]


def expected_broad_ids(count: int, limit: int = 100) -> list[str]:
    """Path tie-break: all Atlas rows precede all Nova rows on a broad search."""
    atlas = expected_atlas_ids(count, limit)
    remaining = limit - len(atlas)
    nova = [f"million-{number:07d}" for number in range(1, min(count, 1 + 2 * remaining), 2)]
    return atlas + nova


def burst_case(number: int, count: int) -> tuple[str, dict[str, Any], int, list[str]]:
    """One broad request per 50 requests; the rest are selective or empty."""
    if number % 50 == 49:
        return "broad", request_body("документ", state=f"burst-{number}"), count, expected_broad_ids(count)
    if number % 2:
        item_id = f"million-{count - 1:07d}"
        return "rare", request_body(f"{count - 1:07d}", state=f"burst-{number}"), 1, [item_id]
    return "absent", request_body("не-существует", state=f"burst-{number}"), 0, []


def asgi_burst(
    settings: Settings, count: int, clients: int, requests: int, *, broad_only=False
) -> dict[str, Any]:
    """Concurrent ASGI requests over one authenticated synthetic account.

    This intentionally shares one TestClient/application and one session so
    the API request limiter and SQLite database are shared. It excludes TCP,
    browser work and login throughput.
    """
    samples: dict[str, list[float]] = {"rare": [], "absent": [], "broad": []}
    failures: list[dict[str, Any]] = []

    with TestClient(create_app(settings), base_url="http://localhost:8000") as client:
        login = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://localhost:8000"},
            json={"login": "worker-atlas", "password": PASSWORD},
        )
        if login.status_code != 200:
            raise RuntimeError(f"burst login failed: {login.status_code} {login.text}")
        token = client.cookies.get("wiseway_session")
        if not token:
            raise RuntimeError("burst login did not issue a session cookie")

        def one(number: int) -> tuple[str, float, dict[str, Any] | None]:
            name, body, expected_total, expected_ids = (
                ("broad", request_body("документ", state=f"burst-{number}"), count, expected_broad_ids(count))
                if broad_only
                else burst_case(number, count)
            )
            started = time.perf_counter()
            try:
                response = client.post(
                    "/api/v1/search",
                    json=body,
                    cookies={"wiseway_session": token},
                )
                elapsed = (time.perf_counter() - started) * 1000
                if response.status_code != 200:
                    return name, elapsed, {"request": number, "reason": f"HTTP {response.status_code}"}
                payload = response.json()
                actual_ids = [item["item_id"] for item in payload.get("items", [])]
                if (
                    payload.get("total") != expected_total
                    or actual_ids != expected_ids[: min(100, expected_total)]
                ):
                    return (
                        name,
                        elapsed,
                        {
                            "request": number,
                            "reason": "unexpected result",
                            "total": payload.get("total"),
                        },
                    )
                return name, elapsed, None
            except Exception as error:  # benchmark must report client-side failures too
                elapsed = (time.perf_counter() - started) * 1000
                return name, elapsed, {"request": number, "reason": type(error).__name__}

        with concurrent.futures.ThreadPoolExecutor(max_workers=clients) as pool:
            for name, elapsed, failure in pool.map(one, range(requests)):
                samples[name].append(elapsed)
                if failure is not None:
                    failures.append(failure)

    return {
        "clients": clients,
        "accounts": 1,
        "requests": requests,
        "transport": "ASGI; excludes TCP and login throughput",
        "mix": "all broad" if broad_only else "49 rare/absent requests per 1 broad request",
        "passed": not failures,
        "error_count": len(failures),
        "errors": failures[:10],
        "error_details_truncated": len(failures) > 10,
        "timing_ms": {
            name: {
                "requests": len(values),
                "p50": percentile(values, 0.5) if values else None,
                "p95": percentile(values, 0.95) if values else None,
            }
            for name, values in samples.items()
        },
    }


def query(data_dir: Path, count: int, repeats: int, clients: int, requests: int) -> dict[str, Any]:
    """Measure the public HTTP route in a new process and assert closed-form data."""
    settings = Settings(data_dir=data_dir / "state", sandbox_dir=data_dir / "sandbox")
    markers = marker_ids()
    atlas_chain = [markers["Archive"], markers["Atlas"]]
    atlas_total = (count + 1) // 2
    cases = (
        ("rare", request_body(f"{count - 1:07d}"), 1, [f"million-{count - 1:07d}"]),
        ("absent", request_body("не-существует"), 0, []),
        # Relevance ties are broken by logical path: Atlas comes before Nova.
        ("broad", request_body("документ"), count, expected_broad_ids(count)),
        ("and", request_body("atlas документ"), atlas_total, expected_atlas_ids(count)),
        ("phrase", request_body('"orion 2031"'), atlas_total, expected_atlas_ids(count)),
        (
            "selected_marker",
            request_body("документ", selected=atlas_chain),
            atlas_total,
            expected_atlas_ids(count),
        ),
    )
    timings: dict[str, dict[str, float]] = {}
    with TestClient(create_app(settings), base_url="http://localhost:8000") as client:
        login = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://localhost:8000"},
            json={"login": "worker-atlas", "password": PASSWORD},
        )
        assert login.status_code == 200, login.text
        roots = client.get("/api/v1/roots")
        assert roots.status_code == 200, roots.text
        archive = next(item for item in roots.json()["items"] if item["root_id"] == ROOT_ID)
        assert not any(key.startswith("_") for key in archive), archive
        # One real IDLE response also protects the no-query path from scanning all rows.
        idle_body = request_body("", state="idle")
        idle_body["sort"] = {"field": "PATH", "direction": "ASC"}
        idle = client.post("/api/v1/search", json=idle_body)
        assert idle.status_code == 200 and idle.json()["mode"] == "IDLE" and idle.json()["total"] is None
        for name, body, total, first_ids in cases:
            samples: list[float] = []
            first_ms = 0.0
            for attempt in range(repeats + 1):
                started = time.perf_counter()
                response = client.post(
                    "/api/v1/search",
                    json={**body, "request_state_id": f"{name.replace('_', '-')}-{attempt}"},
                )
                elapsed = (time.perf_counter() - started) * 1000
                assert response.status_code == 200, (name, response.text)
                result = response.json()
                assert result["total"] == total, (name, result["total"], total)
                assert [item["item_id"] for item in result["items"]] == first_ids[: min(100, total)], name
                if attempt == 0:
                    first_ms = elapsed
                else:
                    samples.append(elapsed)
            timings[name] = {
                "cold_ms": round(first_ms, 3),
                "p50_ms": percentile(samples, 0.5),
                "p95_ms": percentile(samples, 0.95),
            }
            print(f"measured {name}: {timings[name]}", file=sys.stderr, flush=True)
        facet_body = request_body("", selected=[markers["Archive"]], state="facet")
        facet_body.pop("sort")
        facet = client.post(
            "/api/v1/search/facet",
            json=facet_body,
        )
        assert facet.status_code == 200, facet.text
        options = {item["display_value"]: item["count"] for item in facet.json()["facet"]["options"]}
        assert options == {"Atlas": atlas_total, "Nova": count // 2}, options
    result: dict[str, Any] = {
        "records": count,
        "repeats": repeats,
        "search": timings,
    }
    if clients > 1:
        result["asgi_burst"] = asgi_burst(settings, count, clients, requests)
    result["peak_rss_mib"] = peak_rss_mib()
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=int, default=1_000_000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument(
        "--clients", type=int, default=1, help="ASGI burst clients; >1 enables the optional burst"
    )
    parser.add_argument(
        "--requests", type=int, default=250, help="total ASGI burst requests when --clients > 1"
    )
    parser.add_argument("--data-dir", type=Path, help="retain or reuse this synthetic benchmark directory")
    parser.add_argument("--phase", choices=("all", "build", "query"), default="all")
    args = parser.parse_args()
    if args.records < 100:
        parser.error("--records must be at least 100")
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if not 1 <= args.clients <= 50:
        parser.error("--clients must be between 1 and 50")
    if args.requests < 1:
        parser.error("--requests must be positive")
    if args.clients > 1 and args.requests < args.clients:
        parser.error("--requests must be at least --clients for an ASGI burst")
    return args


def main() -> None:
    args = parse_args()
    with (
        tempfile.TemporaryDirectory(prefix="wiseway-million-")
        if args.data_dir is None
        else _null_context(args.data_dir) as raw
    ):
        data_dir = Path(raw).absolute()
        data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        result: dict[str, Any] = {
            "scope": "Synthetic logical metadata, durable SQLite search and ASGI; excludes payload I/O and TCP.",
            "runtime": {"python": platform.python_version(), "platform": platform.platform()},
            "data_dir": str(data_dir),
        }
        if args.phase in {"all", "build"}:
            result["build"] = build(data_dir, args.records)
            print(json.dumps({"build": result["build"]}), file=sys.stderr, flush=True)
        child_failed = False
        if args.phase == "query":
            result["query"] = query(data_dir, args.records, args.repeats, args.clients, args.requests)
        elif args.phase == "all":
            child = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--phase",
                    "query",
                    "--records",
                    str(args.records),
                    "--repeats",
                    str(args.repeats),
                    "--clients",
                    str(args.clients),
                    "--requests",
                    str(args.requests),
                    "--data-dir",
                    str(data_dir),
                ],
                stdout=subprocess.PIPE,
                text=True,
                check=False,
            )
            try:
                result["query"] = json.loads(child.stdout)["query"]
            except (KeyError, TypeError, ValueError) as error:
                print(
                    f"query process exited with code {child.returncode} without a valid JSON report: {error}",
                    file=sys.stderr,
                )
                print(json.dumps(result, ensure_ascii=False, indent=2))
                raise SystemExit(1) from None
            child_failed = child.returncode != 0
            if child_failed:
                print(
                    f"query process reported failure with exit code {child.returncode}; preserving its JSON report",
                    file=sys.stderr,
                )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if child_failed or result.get("query", {}).get("asgi_burst", {}).get("passed") is False:
            raise SystemExit(1)


class _null_context:
    def __init__(self, value: Path):
        self.value = value

    def __enter__(self) -> Path:
        return self.value

    def __exit__(self, *_: object) -> None:
        return None


if __name__ == "__main__":
    main()
