"""Maximum supported batch under competing workers and concurrent API reads."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
from threading import Barrier
import time

from test_bulk_acceptance import _add_files, _all_matching, _headers, _login, _scan_ready
from test_bulk_acceptance import bulk_client as bulk_client
from wiseway.worker import Worker


def test_thousand_file_batch_with_competing_workers_preserves_every_file_and_audit(bulk_client):
    client, settings, now = bulk_client
    csrf = _login(client)
    _add_files(settings, 0, 1000)
    _scan_ready(client, now)
    selected = _all_matching(client, csrf, 1000)
    assert selected.status_code == 201, selected.text
    accepted = client.post(
        "/api/v1/sorting/batches",
        headers=_headers(csrf),
        json={"execution_mode": "DIRECT", "selection_id": selected.json()["selection_id"]},
    )
    assert accepted.status_code == 202, accepted.text
    batch_id = accepted.json()["batch_id"]
    assert accepted.json()["selected_count"] == 1000

    barrier = Barrier(2)
    environment = {
        **os.environ,
        "WISEWAY_DATA_DIR": str(settings.data_dir),
        "WISEWAY_SANDBOX_DIR": str(settings.sandbox_dir),
    }
    child_code = """
import sys
from wiseway.common import Settings
from wiseway.services import Context
from wiseway.worker import Worker
ctx = Context(Settings(clock=lambda: float(sys.argv[1])))
try:
    print(Worker(ctx).run_once())
finally:
    ctx.close()
"""

    def run():
        barrier.wait(timeout=10)
        child = subprocess.run(
            [sys.executable, "-c", child_code, str(now[0])],
            env=environment,
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert child.returncode == 0, child.stderr
        return int(child.stdout.strip())

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        deadline = time.monotonic() + 130
        while True:
            response = client.get(f"/api/v1/sorting/batches/{batch_id}")
            assert response.status_code == 200, response.text
            current = response.json()
            assert current["selected_count"] == 1000
            assert 0 <= current["completed_count"] <= 1000
            if all(future.done() for future in futures):
                break
            assert time.monotonic() < deadline, "workers exceeded the bounded runtime"
            time.sleep(settings.app_config()["batch_poll_interval_ms"] / 1000)
        assert sorted(future.result(timeout=5) for future in futures) == [0, 1000]

    response = client.get(f"/api/v1/sorting/batches/{batch_id}")
    assert response.status_code == 200, response.text
    batch = response.json()
    assert batch["completed_count"] == batch["selected_count"] == 1000
    outcomes = list(batch["outcomes"])
    cursor = batch["next_cursor"]
    while cursor:
        response = client.get(f"/api/v1/sorting/batches/{batch_id}", params={"cursor": cursor, "limit": 100})
        assert response.status_code == 200, response.text
        outcomes.extend(response.json()["outcomes"])
        cursor = response.json()["next_cursor"]
    assert len(outcomes) == len({outcome["item_id"] for outcome in outcomes}) == 1000
    assert {outcome["state"] for outcome in outcomes} == {"MANUAL_REVIEW"}
    assert list((settings.sandbox_dir / "Incoming/Atlas").iterdir()) == []
    for number in range(1000):
        assert (
            settings.sandbox_dir / "ManualReview/Atlas" / f"bulk-{number:04}.pdf"
        ).read_bytes() == f"bulk {number}".encode()
    with client.app.state.ctx.store.transaction(write=False) as tx:
        events = [event for event in tx.events() if event["batch_id"] == batch_id]
        assert Counter(event["action"] for event in events) == {
            "BATCH_ACCEPTED": 1,
            "FILE_ATTEMPT_STARTED": 1000,
            "FILE_ATTEMPT_FINISHED": 1000,
        }
        assert {event["actor"]["user_id"] for event in events} == {batch["actor"]["user_id"]}
        assert tx.list("claim") == []
    assert Worker(client.app.state.ctx).run_once() == 0
