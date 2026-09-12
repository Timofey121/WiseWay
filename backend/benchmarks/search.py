#!/usr/bin/env python3
"""Reproducible local search benchmark for the synthetic Wise Way corpus.

Run from the repository root with ``python backend/benchmarks/search.py``.
It creates and removes an isolated synthetic sandbox, so it does not use an
existing demo database or files.
"""

from __future__ import annotations

import json
import math
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

from wiseway.app import create_app  # noqa: E402
from wiseway.common import Settings  # noqa: E402
from wiseway.indexer import Indexer  # noqa: E402
from wiseway.seed import initialize  # noqa: E402
from wiseway.services import Context  # noqa: E402


CORPUS_FILES = 3_200
REQUESTS = 40
WARMUP = 5


def percentile(values: list[float], ratio: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * ratio) - 1)]


def cpu_model() -> str:
    linux = Path("/proc/cpuinfo")
    if linux.is_file():
        for line in linux.read_text(errors="replace").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    if platform.system() == "Darwin":
        try:
            return subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"], text=True, stderr=subprocess.DEVNULL
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            pass
    return platform.processor() or platform.machine()


def request(client: TestClient, body: dict) -> dict:
    response = client.post("/api/v1/search", json=body)
    if response.status_code != 200:
        raise RuntimeError(f"search failed: {response.status_code} {response.text}")
    return response.json()


def payload(query: str, markers: list[str], number: int) -> dict:
    return {
        "request_state_id": f"benchmark-request-{number}",
        "root_id": "archive-root",
        "schema_set_version": "schema-demo-1",
        "selected_marker_ids": markers,
        "query_text": query,
        "sort": {"field": "RELEVANCE", "direction": "DESC"},
        "facet_prefix": "",
    }


def samples(client: TestClient, query: str, markers: list[str]) -> tuple[list[float], dict]:
    last = None
    for number in range(WARMUP):
        last = request(client, payload(query, markers, number))
    elapsed: list[float] = []
    for number in range(WARMUP, WARMUP + REQUESTS):
        started = time.perf_counter()
        last = request(client, payload(query, markers, number))
        elapsed.append((time.perf_counter() - started) * 1000)
    return elapsed, last


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="wiseway-search-benchmark-") as temporary:
        base = Path(temporary)
        settings = Settings(data_dir=base / "state", sandbox_dir=base / "sandbox")
        initialize(settings, password="synthetic-test-password")
        for index in range(CORPUS_FILES):
            if index % 2:
                relative = f"Archive/Atlas/Orion_2031/Reports/benchmark-atlas-{index:04d}.pdf"
            else:
                relative = f"Archive/Nova/Polaris_2030/North/Data/benchmark-nova-{index:04d}.xlsx"
            (settings.sandbox_dir / relative).write_bytes(b"x")

        context = Context(settings)
        try:
            started = time.perf_counter()
            Indexer(context).scan()
            index_ms = (time.perf_counter() - started) * 1000
        finally:
            context.close()

        with TestClient(create_app(settings), base_url="http://localhost:8000") as client:
            login = client.post(
                "/api/v1/auth/login",
                headers={"Origin": "http://localhost:8000"},
                json={"login": "worker-atlas", "password": "synthetic-test-password"},
            )
            if login.status_code != 200:
                raise RuntimeError(f"login failed: {login.status_code} {login.text}")

            initial = request(client, payload("benchmark", [], 99_001))
            archive_marker = initial["next_facet"]["options"][0]["marker_id"]
            archive_only = request(client, payload("benchmark", [archive_marker], 99_002))
            atlas_marker = next(
                option["marker_id"]
                for option in archive_only["next_facet"]["options"]
                if option["raw_value"] == "Atlas"
            )
            typical, typical_result = samples(client, "benchmark", [archive_marker, atlas_marker])
            broad, broad_result = samples(client, "bench", [])

        output = {
            "corpus": {"ordinary_files_added": CORPUS_FILES, "seed_companies": ["Atlas", "Nova"]},
            "query_classes": {
                "typical_text_plus_markers": {
                    "query": "benchmark",
                    "markers": 2,
                    "result_total": typical_result["total"],
                    "samples": len(typical),
                    "warmup": WARMUP,
                    "p50_ms": round(percentile(typical, 0.50), 3),
                    "p95_ms": round(percentile(typical, 0.95), 3),
                },
                "broad_text": {
                    "query": "bench",
                    "markers": 0,
                    "result_total": broad_result["total"],
                    "samples": len(broad),
                    "warmup": WARMUP,
                    "p50_ms": round(percentile(broad, 0.50), 3),
                    "p95_ms": round(percentile(broad, 0.95), 3),
                },
            },
            "index": {"scan_ms": round(index_ms, 3), "generation": broad_result["index_generation"]},
            "runtime": {
                "os": platform.platform(),
                "cpu_model": cpu_model(),
                "cpu_count": os.cpu_count(),
                "python": sys.version.split()[0],
                "implementation": platform.python_implementation(),
                "client": "FastAPI TestClient (in-process)",
            },
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
