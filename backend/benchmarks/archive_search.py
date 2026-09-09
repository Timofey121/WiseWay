#!/usr/bin/env python3
"""Synthetic OpenSearch metadata benchmark, using the same million-query oracle."""

import argparse
import json
import os
from pathlib import Path
import time

from million import PASSWORD, ROOT_ID, asgi_burst, item_path, peak_rss_mib, query
from wiseway.archive_import import ArchiveImporter
from wiseway.common import Settings
from wiseway.seed import initialize
from wiseway.services import Context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--records", type=int, default=1_000_000)
    parser.add_argument("--shards", type=int, default=2)
    parser.add_argument("--phase", choices=("build", "query", "all"), default="all")
    parser.add_argument(
        "--broad-only",
        action="store_true",
        help="50 concurrent broad queries instead of the normal mixed workload",
    )
    parser.add_argument("--clients", type=int, default=50)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if not 10 <= args.records <= 400_000_000:
        parser.error("records must be 10..400000000")
    if not os.getenv("WISEWAY_SEARCH_URL"):
        parser.error("Set WISEWAY_SEARCH_URL to an isolated test engine")
    data = args.data_dir.absolute()
    settings = Settings(data_dir=data / "state", sandbox_dir=data / "sandbox")
    report = {
        "records": args.records,
        "shards": args.shards,
        "engine": "OpenSearch",
        "payload_files": False,
        "response_cache_bytes": settings.search_cache_bytes,
    }
    if args.phase != "query":
        # Refuse an existing state directory rather than overwrite a real deployment.
        data.mkdir(parents=True, exist_ok=False)
        initialize(settings, password=PASSWORD)
        manifest = data / "initial.ndjson"
        with manifest.open("x") as output:
            for number in range(args.records):
                output.write(
                    json.dumps(
                        {
                            "op": "upsert",
                            "item_id": f"million-{number:07d}",
                            "relative_path": item_path(number),
                            "size_bytes": 900_000 + number % 200_001,
                            "modified_at": "2026-01-01T00:00:00Z",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        ctx = Context(settings)
        try:
            start = time.perf_counter()
            result = ArchiveImporter(ctx, ctx.search_engine(), shards=args.shards).run(ROOT_ID, manifest)
            elapsed = time.perf_counter() - start
            stats = ctx.search_engine().request("GET", f"/{result['index']}/_stats/store,docs")
            report["build"] = {
                **result,
                "seconds": round(elapsed, 3),
                "records_per_second": round(args.records / elapsed),
                "primary_store_bytes": stats["_all"]["primaries"]["store"]["size_in_bytes"],
                "peak_client_rss_mib": peak_rss_mib(),
            }
        finally:
            ctx.close()
        (data / "build-result.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)
    if args.phase != "build":
        report["query"] = (
            asgi_burst(settings, args.records, args.clients, 50, broad_only=True)
            if args.broad_only
            else query(data, args.records, args.repeats, args.clients, 250)
        )
        (data / "query-result.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2), flush=True)
        measured = report["query"]
        if measured.get("asgi_burst", measured).get("passed") is False:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
