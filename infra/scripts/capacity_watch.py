#!/usr/bin/env python3
"""Stop the labelled capacity test before it exhausts the host filesystem."""

import argparse
import json
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time


def _inspect(name, run):
    response = run(["docker", "inspect", name], check=True, capture_output=True, text=True, timeout=15)
    rows = json.loads(response.stdout)
    if len(rows) != 1 or rows[0].get("Config", {}).get("Labels", {}).get("com.wiseway.capacity") != "true":
        raise ValueError("Refusing a container without the Wise Way capacity label")
    return rows[0]


def monitor(
    client, search, path, *, min_free_bytes, interval=10, stop=None, run=subprocess.run, free_bytes=None
):
    if min_free_bytes <= 0 or interval <= 0:
        raise ValueError("Disk reserve and polling interval must be positive")
    stop = stop if stop is not None else threading.Event()
    free_bytes = free_bytes or (lambda directory: shutil.disk_usage(directory).free)
    # Validate both first; immutable container IDs prevent a name replacement
    # from making the watcher stop another workload.
    client_info, search_info = _inspect(client, run), _inspect(search, run)
    client_id, search_id = client_info["Id"], search_info["Id"]

    def inspect_running(identity):
        try:
            return _inspect(identity, run)
        except subprocess.TimeoutExpired:
            # Docker Desktop may stall briefly while the host is under load.
            # Retry one read, with a fresh independent host-space check first.
            # Repeated failure, a stop signal or low space still stops the test.
            available = free_bytes(path)
            print(json.dumps({"inspect_timeout": identity, "host_free_bytes": available}), flush=True)
            if available < min_free_bytes or stop.is_set():
                raise
            return _inspect(identity, run)

    client_finished = False
    code = 1
    try:
        while True:
            available = free_bytes(path)
            print(json.dumps({"time": time.time(), "host_free_bytes": available}), flush=True)
            if available < min_free_bytes:
                print(json.dumps({"stopped": "host_disk_reserve"}), flush=True)
                code = 78
                break
            if stop.is_set():
                code = 130
                break
            if not client_info["State"]["Running"]:
                client_finished = True
                code = int(client_info["State"]["ExitCode"])
                break
            if not search_info["State"]["Running"]:
                raise RuntimeError("Capacity search engine stopped before its client")
            stop.wait(interval)
            client_info, search_info = inspect_running(client_id), inspect_running(search_id)
    finally:
        # Quiesce merges as well as imports. Retained volumes/checkpoints are
        # never deleted. Stop search even if stopping the client fails.
        try:
            if not client_finished:
                run(["docker", "stop", "--time", "60", client_id], check=True, timeout=75)
        finally:
            run(["docker", "stop", "--time", "30", search_id], check=True, timeout=45)
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", required=True)
    parser.add_argument("--search", required=True)
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--min-free-gib", type=float, default=40)
    parser.add_argument("--interval", type=float, default=10)
    args = parser.parse_args()
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    return monitor(
        args.client,
        args.search,
        args.path,
        min_free_bytes=int(args.min_free_gib * 1024**3),
        interval=args.interval,
        stop=stop,
    )


if __name__ == "__main__":
    raise SystemExit(main())
