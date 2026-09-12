"""A real TCP API, durable accepted job, and independently restarted worker."""

import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from uuid import uuid4

import httpx2


@contextmanager
def server(env, log_path):
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    with log_path.open("w+") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "wiseway", "serve", "--port", str(port)],
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            with httpx2.Client(base_url=url, timeout=3, trust_env=False) as client:
                deadline = time.monotonic() + 15
                while True:
                    assert process.poll() is None, log_path.read_text()
                    try:
                        if client.get("/api/v1/health").status_code == 200:
                            break
                    except httpx2.ConnectError:
                        pass
                    assert time.monotonic() < deadline, log_path.read_text()
                    time.sleep(0.05)
                yield client
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_accepted_batch_survives_logout_api_restart_and_worker_restart(configured, tmp_path):
    env = {
        **os.environ,
        "WISEWAY_DATA_DIR": str(configured.data_dir),
        "WISEWAY_SANDBOX_DIR": str(configured.sandbox_dir),
    }
    # Readiness is an independent observation; avoid slowing the suite by waiting five seconds.
    from wiseway.storage import Store

    with Store(configured.database).transaction() as tx:
        for item in tx.list("queue"):
            item["_observed_at"] = configured.clock() - 6
            tx.put("queue", item["item_id"], item)

    def tick():
        result = subprocess.run(
            [sys.executable, "-m", "wiseway", "tick"],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stderr

    def login(client, name):
        response = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://localhost:8000"},
            json={"login": name, "password": "synthetic-test-password"},
        )
        assert response.status_code == 200, response.text
        return {"Origin": "http://localhost:8000", "X-CSRF-Token": response.json()["csrf_token"]}

    tick()
    with server(env, tmp_path / "first-server.log") as client:
        headers = login(client, "worker-atlas")
        company = client.get("/api/v1/companies").json()["items"][0]["company_id"]
        response = client.post(
            "/api/v1/sorting/queue/query",
            json={
                "company_id": company,
                "filters": {"statuses": ["READY"], "query_text": ""},
                "cursor": None,
                "limit": 100,
            },
        )
        assert response.status_code == 200, response.text
        item = response.json()["items"][0]
        source = configured.sandbox_dir / "Incoming" / "Atlas" / item["source"]["relative_path"]
        original = source.read_bytes()
        response = client.post(
            "/api/v1/sorting/selections",
            headers=headers,
            json={
                "company_id": company,
                "mode": "EXPLICIT",
                "items": [{"item_id": item["item_id"], "item_revision": item["item_revision"]}],
            },
        )
        assert response.status_code == 201, response.text
        body = {"execution_mode": "DIRECT", "selection_id": response.json()["selection_id"]}
        key = str(uuid4())
        response = client.post(
            "/api/v1/sorting/batches",
            headers={**headers, "Idempotency-Key": key},
            json=body,
        )
        assert response.status_code == 202, response.text
        accepted = response.json()
        assert accepted["status"] == "ACCEPTED" and source.exists()
        assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    # Both processes from acceptance are gone. A new process finishes the persisted intent.
    tick()
    tick()
    with server(env, tmp_path / "second-server.log") as client:
        login(client, "worker-nova")
        response = client.get("/api/v1/sorting/batches/" + accepted["batch_id"])
        assert response.status_code == 200, response.text
        finished = response.json()
        assert finished["completed_count"] == 1
        assert finished["actor"]["login"] == "worker-atlas"
        outcome = finished["outcomes"][0]
        assert outcome["state"] == "MANUAL_REVIEW"
        destination = configured.sandbox_dir / "ManualReview" / outcome["actual_location"]["relative_path"]
        assert not source.exists() and destination.read_bytes() == original
        headers = login(client, "worker-atlas")
        repeated = client.post(
            "/api/v1/sorting/batches",
            headers={**headers, "Idempotency-Key": key},
            json=body,
        )
        assert repeated.status_code == 202 and repeated.json() == accepted
        events = client.post(
            "/api/v1/audit/query",
            json={
                "company_id": company,
                "from": "2020-01-01T00:00:00Z",
                "to": "2099-01-01T00:00:00Z",
                "actor_id": None,
                "action": None,
                "result": None,
                "query_text": "",
                "cursor": None,
                "limit": 100,
            },
        ).json()["items"]
        actions = [event["action"] for event in events if event["batch_id"] == accepted["batch_id"]]
        assert sorted(actions) == ["BATCH_ACCEPTED", "FILE_ATTEMPT_FINISHED", "FILE_ATTEMPT_STARTED"]
