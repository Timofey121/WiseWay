"""Regression checks for process-facing operational health behavior."""

import os
import signal
import sqlite3
import subprocess
import sys
import time

import pytest

from wiseway.common import Settings
from wiseway.seed import initialize


@pytest.mark.parametrize(
    ("kwargs", "status", "code"),
    [
        ({"headers": {"Host": "untrusted.example"}}, 403, "FORBIDDEN"),
        ({"params": {"unknown": "value"}}, 422, "VALIDATION_ERROR"),
        ({"json": {"unexpected": True}}, 422, "VALIDATION_ERROR"),
    ],
)
def test_health_rejects_bad_host_and_input_without_an_internal_error(client, kwargs, status, code):
    response = client.request("GET", "/api/v1/health", **kwargs)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    assert response.headers["cache-control"] == "no-store"


def _environment(settings):
    return {
        **os.environ,
        "WISEWAY_DATA_DIR": str(settings.data_dir),
        "WISEWAY_SANDBOX_DIR": str(settings.sandbox_dir),
    }


def test_doctor_uses_nonzero_exit_when_not_ready_and_zero_after_worker_cycle(tmp_path):
    settings = Settings(data_dir=tmp_path / "state", sandbox_dir=tmp_path / "sandbox")
    initialize(settings, password="synthetic-test-password")
    environment = _environment(settings)

    unhealthy = subprocess.run(
        [sys.executable, "-m", "wiseway", "doctor"],
        env=environment,
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert unhealthy.returncode == 1
    assert '"ready": false' in unhealthy.stdout
    assert "worker_heartbeat_missing" in unhealthy.stdout

    tick = subprocess.run(
        [sys.executable, "-m", "wiseway", "tick"],
        env=environment,
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert tick.returncode == 0, tick.stderr

    healthy = subprocess.run(
        [sys.executable, "-m", "wiseway", "doctor"],
        env=environment,
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert healthy.returncode == 0, healthy.stderr
    assert '"ready": true' in healthy.stdout


def test_worker_sigterm_exits_cleanly_between_durable_cycles(tmp_path):
    settings = Settings(data_dir=tmp_path / "state", sandbox_dir=tmp_path / "sandbox")
    initialize(settings, password="synthetic-test-password")
    worker = subprocess.Popen(
        [sys.executable, "-m", "wiseway", "worker"],
        env=_environment(settings),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while True:
            with sqlite3.connect(settings.database) as connection:
                heartbeat = connection.execute(
                    "SELECT body FROM objects WHERE kind='operator_state' AND id='worker'"
                ).fetchone()
            if heartbeat:
                break
            assert worker.poll() is None, "worker exited before its first cycle"
            assert time.monotonic() < deadline, "worker did not finish its first cycle"
            time.sleep(0.02)
        worker.send_signal(signal.SIGTERM)
        stdout, stderr = worker.communicate(timeout=10)
    except BaseException:
        worker.kill()
        worker.communicate(timeout=5)
        raise
    assert worker.returncode == 0, stdout + stderr
