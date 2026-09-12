import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def load_watch():
    path = Path(__file__).parents[2] / "infra/scripts/capacity_watch.py"
    spec = importlib.util.spec_from_file_location("capacity_watch", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def docker_boundary(*, label="true", exit_code=None):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[1] == "inspect":
            identity = command[-1]
            data = {
                "Id": identity + "-immutable",
                "Config": {"Labels": {"com.wiseway.capacity": label}},
                "State": {"Running": exit_code is None, "ExitCode": exit_code or 0},
            }
            return SimpleNamespace(stdout=json.dumps([data]), returncode=0)
        return SimpleNamespace(stdout="", returncode=0)

    return run, calls


def test_disk_guard_stops_only_verified_benchmark_containers(tmp_path):
    watch = load_watch()
    run, calls = docker_boundary()
    code = watch.monitor("client", "search", tmp_path, min_free_bytes=100, run=run, free_bytes=lambda _: 99)
    assert code == 78
    stops = [call[-1] for call in calls if call[1] == "stop"]
    assert stops == ["client-immutable", "search-immutable"]


def test_watcher_refuses_unlabelled_container_without_stopping_anything(tmp_path):
    watch = load_watch()
    run, calls = docker_boundary(label="false")
    with pytest.raises(ValueError, match="capacity"):
        watch.monitor("client", "search", tmp_path, min_free_bytes=100, run=run, free_bytes=lambda _: 99)
    assert not any(call[1] == "stop" for call in calls)


def test_watcher_preserves_failed_client_exit_code(tmp_path):
    watch = load_watch()
    run, calls = docker_boundary(exit_code=7)
    code = watch.monitor("client", "search", tmp_path, min_free_bytes=100, run=run, free_bytes=lambda _: 1000)
    assert code == 7
    assert [call[-1] for call in calls if call[1] == "stop"] == ["search-immutable"]


def test_watcher_retries_one_transient_inspect_timeout_and_rechecks_disk(tmp_path):
    import subprocess

    watch = load_watch()
    calls, disks = [], []
    timed_out = False

    def run(command, **kwargs):
        nonlocal timed_out
        calls.append(command)
        if command[1] == "inspect":
            identity = command[-1]
            if identity == "client-immutable" and not timed_out:
                timed_out = True
                raise subprocess.TimeoutExpired(command, 15)
            body = {
                "Id": identity if identity.endswith("-immutable") else identity + "-immutable",
                "Config": {"Labels": {"com.wiseway.capacity": "true"}},
                "State": {"Running": identity != "client-immutable", "ExitCode": 0},
            }
            return SimpleNamespace(stdout=json.dumps([body]))
        return SimpleNamespace(returncode=0)

    stop = SimpleNamespace(is_set=lambda: False, wait=lambda _: None)
    result = watch.monitor(
        "client",
        "search",
        tmp_path,
        min_free_bytes=100,
        run=run,
        free_bytes=lambda _: disks.append(True) or 1000,
        stop=stop,
    )
    assert result == 0
    assert len(disks) >= 3  # First check, timeout retry, final client exit.
    assert [call[-1] for call in calls if call[1] == "stop"] == ["search-immutable"]


@pytest.mark.parametrize("low_space", [False, True])
def test_watcher_still_stops_after_repeated_timeout_or_low_retry_space(tmp_path, low_space):
    import subprocess

    watch = load_watch()
    original, calls = docker_boundary()
    failures = []

    def run(command, **kwargs):
        if command[1:] == ["inspect", "client-immutable"]:
            failures.append(command)
            raise subprocess.TimeoutExpired(command, 15)
        return original(command, **kwargs)

    stop = SimpleNamespace(is_set=lambda: False, wait=lambda _: None)
    with pytest.raises(subprocess.TimeoutExpired):
        watch.monitor(
            "client",
            "search",
            tmp_path,
            min_free_bytes=100,
            run=run,
            free_bytes=lambda _: 99 if low_space and failures else 1000,
            stop=stop,
        )
    assert len(failures) == (1 if low_space else 2)
    assert [call[-1] for call in calls if call[1] == "stop"] == ["client-immutable", "search-immutable"]
