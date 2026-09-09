#!/usr/bin/env python3
"""Reproducible local TCP concurrency check for the Wise Way demo.

The command creates its own temporary database and synthetic filesystem.  It
never opens an existing ``.wiseway`` directory and removes all generated data
when it exits.  It deliberately provisions 50 persisted sessions through the
same authentication service used by the API, with distinct synthetic client
addresses: the public login endpoint rate-limits a single address to ten
attempts per minute, so using that endpoint for every virtual client would
measure the rate limiter rather than concurrent authenticated traffic.

Run from the repository root:

    uv run python backend/benchmarks/stress.py

This is a local, bounded regression check.  Its figures describe the machine
and corpus printed in its JSON output; they are not a production capacity
claim.
"""

from __future__ import annotations

import concurrent.futures
import json
import math
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import httpx2  # noqa: E402

from wiseway.audit import emit  # noqa: E402
from wiseway.auth import Auth  # noqa: E402
from wiseway.common import Settings  # noqa: E402
from wiseway.indexer import Indexer  # noqa: E402
from wiseway.seed import initialize  # noqa: E402
from wiseway.services import Context  # noqa: E402


CORPUS_FILES = 3_200
CLIENTS = 50
REQUESTS_PER_CLIENT = 5
TIMEOUT_SECONDS = 10


def percentile(samples: list[float], ratio: float) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples)
    return round(ordered[max(0, math.ceil(len(ordered) * ratio) - 1)], 3)


def rss_kib(pid: int) -> int | None:
    """Read resident memory through the OS utility available on macOS/Linux."""
    try:
        result = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, timeout=2, check=True
        )
        value = result.stdout.strip()
        return int(value) if value else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


@contextmanager
def process(command: list[str], environment: dict[str, str], log_path: Path):
    with log_path.open("w+", encoding="utf-8") as log:
        child = subprocess.Popen(command, env=environment, stdout=log, stderr=log)
        try:
            yield child
        finally:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)


def wait_for_server(url: str, child: subprocess.Popen[bytes], log_path: Path) -> None:
    deadline = time.monotonic() + 20
    with httpx2.Client(base_url=url, timeout=1, trust_env=False) as client:
        while True:
            if child.poll() is not None:
                raise RuntimeError("server exited: " + log_path.read_text(encoding="utf-8"))
            try:
                if client.get("/api/v1/health").status_code == 200:
                    return
            except httpx2.HTTPError:
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError("server did not become ready: " + log_path.read_text(encoding="utf-8"))
            time.sleep(0.05)


def add_corpus(settings: Settings) -> None:
    for number in range(CORPUS_FILES):
        if number % 2:
            relative = f"Archive/Atlas/Orion_2031/Reports/stress-atlas-{number:04d}.pdf"
        else:
            relative = f"Archive/Nova/Polaris_2030/North/Data/stress-nova-{number:04d}.xlsx"
        (settings.sandbox_dir / relative).write_bytes(b"x")


def prepare(settings: Settings) -> tuple[list[str], str]:
    """Index the corpus, seed a non-trivial audit log and create distinct sessions."""
    initialize(settings, password="synthetic-stress-password")
    add_corpus(settings)
    context = Context(settings)
    try:
        Indexer(context).scan()
        auth = Auth(context.store, settings)
        with context.store.transaction() as tx:
            actor = tx.require("user", "user-worker-atlas")["actor"]
            for number in range(1_000):
                emit(
                    tx,
                    actor,
                    "BATCH_ACCEPTED",
                    f"stress-seed-{number}",
                    now=settings.clock(),
                    company_id="company-atlas",
                )
        tokens = [
            auth.login(
                {"login": "worker-atlas", "password": "synthetic-stress-password"},
                f"stress-login-{number}",
                f"198.18.0.{number + 1}",
            )[1]
            for number in range(CLIENTS)
        ]
        return tokens, actor["user_id"]
    finally:
        context.close()


def payloads(actor_id: str) -> list[tuple[str, dict[str, Any]]]:
    audit = {
        "company_id": "company-atlas",
        "from": "2020-01-01T00:00:00Z",
        "to": "2099-01-01T00:00:00Z",
        "actor_id": actor_id,
        "action": None,
        "result": None,
        "query_text": "",
        "cursor": None,
        "limit": 100,
    }
    queue = {
        "company_id": "company-atlas",
        "filters": {"statuses": [], "query_text": ""},
        "cursor": None,
        "limit": 100,
    }

    def search(request_state_id: str, query: str) -> dict[str, Any]:
        return {
            "request_state_id": request_state_id,
            "root_id": "archive-root",
            "schema_set_version": "schema-demo-1",
            "selected_marker_ids": [],
            "query_text": query,
            "sort": {"field": "RELEVANCE", "direction": "DESC"},
            "facet_prefix": "",
        }

    return [
        ("typical_search", search("stress-typical-a", "stress atlas")),
        ("broad_search", search("stress-broad", "stress")),
        ("queue_query", queue),
        ("audit_query", audit),
        ("typical_search", search("stress-typical-b", "stress nova")),
    ]


def virtual_user(client: httpx2.Client, token: str, actor_id: str) -> list[tuple[str, float, int, str]]:
    results: list[tuple[str, float, int, str]] = []
    for operation, body in payloads(actor_id):
        started = time.perf_counter()
        try:
            response = client.post(
                {
                    "typical_search": "/api/v1/search",
                    "broad_search": "/api/v1/search",
                    "queue_query": "/api/v1/sorting/queue/query",
                    "audit_query": "/api/v1/audit/query",
                }[operation],
                json=body,
                headers={"Cookie": f"wiseway_session={token}"},
            )
            detail = response.text[:160] if response.status_code >= 400 else ""
            results.append((operation, (time.perf_counter() - started) * 1000, response.status_code, detail))
        except httpx2.HTTPError as error:
            results.append((operation, (time.perf_counter() - started) * 1000, 0, type(error).__name__))
    return results


def summarize(
    rows: list[tuple[str, float, int, str]], log: str, elapsed: float, rss: int | None
) -> dict[str, Any]:
    classes: dict[str, dict[str, Any]] = {}
    for operation, milliseconds, status, detail in rows:
        current = classes.setdefault(operation, {"latencies": [], "statuses": {}, "errors": []})
        current["latencies"].append(milliseconds)
        current["statuses"][str(status)] = current["statuses"].get(str(status), 0) + 1
        if status != 200:
            current["errors"].append(detail)
    normalized = {
        name: {
            "requests": len(value["latencies"]),
            "p50_ms": percentile(value["latencies"], 0.50),
            "p95_ms": percentile(value["latencies"], 0.95),
            "p99_ms": percentile(value["latencies"], 0.99),
            "status_counts": value["statuses"],
            "error_samples": value["errors"][:3],
        }
        for name, value in classes.items()
    }
    text = log.casefold()
    return {
        "workload": {
            "ordinary_files_added": CORPUS_FILES,
            "seed_audit_events": 1000,
            "distinct_accounts": 1,
            "clients": CLIENTS,
            "requests_per_client": REQUESTS_PER_CLIENT,
            "total_requests": len(rows),
            "concurrent_worker_index_loop": True,
            "request_warmup": 0,
            "client_initialization": "HTTP clients created before timed traffic to exclude client TLS-context initialization on the shared host.",
            "authentication": "50 persisted sessions issued via Auth with distinct synthetic client addresses; public login rate limiter was not load-tested here.",
        },
        "results": normalized,
        "total_elapsed_ms": round(elapsed * 1000, 3),
        "server_rss_kib_after": rss,
        "observed_server_log_sqlite_busy": "database is locked" in text or "sqlite_busy" in text,
        "observed_server_log_5xx": " 500 " in text or "internal_error" in text,
        "runtime": {"os": platform.platform(), "python": sys.version.split()[0], "cpu_count": os.cpu_count()},
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="wiseway-stress-") as temporary:
        base = Path(temporary)
        settings = Settings(data_dir=base / "state", sandbox_dir=base / "sandbox")
        tokens, actor_id = prepare(settings)
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        environment = {
            **os.environ,
            "WISEWAY_DATA_DIR": str(settings.data_dir),
            "WISEWAY_SANDBOX_DIR": str(settings.sandbox_dir),
        }
        server_log, worker_log = base / "server.log", base / "worker.log"
        with process(
            [sys.executable, "-m", "wiseway", "serve", "--port", str(port)], environment, server_log
        ) as server:
            wait_for_server(url, server, server_log)
            with ExitStack() as stack:
                clients = [
                    stack.enter_context(
                        httpx2.Client(
                            base_url=url,
                            timeout=TIMEOUT_SECONDS,
                            trust_env=False,
                        )
                    )
                    for _ in range(CLIENTS)
                ]
                worker = stack.enter_context(
                    process(
                        [sys.executable, "-m", "wiseway", "worker"],
                        environment,
                        worker_log,
                    )
                )
                started = time.perf_counter()
                with concurrent.futures.ThreadPoolExecutor(max_workers=CLIENTS) as pool:
                    futures = [
                        pool.submit(virtual_user, client, token, actor_id)
                        for client, token in zip(clients, tokens)
                    ]
                    rows = [result for future in futures for result in future.result()]
                elapsed = time.perf_counter() - started
                log = server_log.read_text(encoding="utf-8")
                result = summarize(rows, log, elapsed, rss_kib(server.pid))
                result["checks"] = {
                    "all_requests_succeeded": all(status == 200 for _, _, status, _ in rows),
                    "typical_p95_within_2000ms": result["results"]["typical_search"]["p95_ms"] <= 2000,
                    "broad_p95_within_5000ms": result["results"]["broad_search"]["p95_ms"] <= 5000,
                    "server_and_worker_alive": server.poll() is None and worker.poll() is None,
                }
                print(json.dumps(result, ensure_ascii=False, indent=2))
                if not all(result["checks"].values()):
                    raise SystemExit(1)


if __name__ == "__main__":
    main()
