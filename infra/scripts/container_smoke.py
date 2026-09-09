"""Exercise the production Compose stack with isolated synthetic data and TLS."""

import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, HTTPCookieProcessor, ProxyHandler, Request, build_opener
from uuid import uuid4


def run(args, *, environment=None, input=None, timeout=180):
    result = subprocess.run(
        args, env=environment, input=input, text=True, capture_output=True, timeout=timeout
    )
    if result.returncode:
        raise RuntimeError(f"Command failed: {args[0:3]}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def main(image):
    repository = Path(__file__).resolve().parents[2]
    task = Path(tempfile.mkdtemp(prefix="wiseway-container-")).resolve()
    lock_descriptor, lock_path = tempfile.mkstemp(prefix="wiseway-smoke-ops-")
    os.close(lock_descriptor)
    project = "wiseway-smoke-" + secrets.token_hex(6)
    with socket.socket() as port_probe:
        port_probe.bind(("127.0.0.1", 0))
        port = port_probe.getsockname()[1]
    origin = f"https://localhost:{port}"
    environment = {
        **os.environ,
        "COMPOSE_PROJECT_NAME": project,
        "WISEWAY_IMAGE": image,
        "WISEWAY_ORIGINS": origin,
        "WISEWAY_STATE_PATH": str(task / "state"),
        "WISEWAY_SANDBOX_PATH": str(task / "sandbox"),
        "WISEWAY_BACKUP_PATH": str(task / "backups"),
        "WISEWAY_TLS_PATH": str(task / "tls"),
        "WISEWAY_BIND_ADDRESS": "127.0.0.1",
        "WISEWAY_HTTPS_PORT": str(port),
    }
    compose = ["docker", "compose", "--env-file", "/dev/null", "-f", str(repository / "compose.yaml")]

    def dc(*args, input=None, timeout=180):
        return run([*compose, *args], environment=environment, input=input, timeout=timeout)

    ops = [
        sys.executable,
        str(repository / "infra/scripts/compose_ops.py"),
        "--env-file",
        "/dev/null",
        "--lock-file",
        lock_path,
    ]

    def owner(uid, gid):
        # Only the private temporary directory allocated above is mounted writable.
        return run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--user",
                "0:0",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--cap-add",
                "CHOWN",
                "--cap-add",
                "DAC_OVERRIDE",
                "--cap-add",
                "FOWNER",
                "--mount",
                f"type=bind,src={task},dst=/work",
                "--entrypoint",
                "python",
                image,
                "-c",
                "import os,sys; uid,gid=map(int,sys.argv[1:]); "
                "paths=['/work']+[os.path.join(p,n) for p,ds,fs in os.walk('/work') for n in ds+fs]; "
                "[(os.chown(p,uid,gid,follow_symlinks=False)) for p in paths]",
                str(uid),
                str(gid),
            ]
        )

    try:
        for name in ("state", "sandbox", "backups", "tls"):
            (task / name).mkdir(mode=0o700)
        run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost",
                "-keyout",
                str(task / "tls/privkey.pem"),
                "-out",
                str(task / "tls/fullchain.pem"),
            ]
        )
        context = ssl.create_default_context(cafile=str(task / "tls/fullchain.pem"))
        owner(10001, 10001)
        dc("config", "--quiet")
        password = secrets.token_urlsafe(32)
        dc("run", "--rm", "-T", "--no-deps", "cli", "init-demo", "--password-stdin", input=password + "\n")
        dc("up", "-d", "--wait", "--wait-timeout", "150", "api", "worker", timeout=210)

        cookies = http.cookiejar.CookieJar()
        browser = build_opener(ProxyHandler({}), HTTPSHandler(context=context), HTTPCookieProcessor(cookies))

        def api(path, body=None, headers=None, expected=200):
            request = Request(origin + "/api/v1" + path, headers=headers or {})
            if body is not None:
                request.data = json.dumps(body).encode()
                request.add_header("Content-Type", "application/json")
            try:
                response = browser.open(request, timeout=15)
            except HTTPError as error:
                response = error
            with response:
                raw = response.read()
                assert response.status == expected, (path, response.status, raw)
                assert response.headers["Cache-Control"] == "no-store"
                assert response.headers["X-Request-ID"]
                return json.loads(raw) if raw else None

        assert api("/health") == {"status": "ok"}
        session = api("/auth/login", {"login": "worker-atlas", "password": password}, {"Origin": origin})
        assert all(cookie.secure and cookie.has_nonstandard_attr("HttpOnly") for cookie in cookies)
        assert list(cookies)
        headers = {"Origin": origin, "X-CSRF-Token": session["csrf_token"], "Idempotency-Key": str(uuid4())}
        assert api("/session")["actor"]["role"] == "WORKER"
        root = api("/roots")["items"][0]
        search = api(
            "/search",
            {
                "request_state_id": "container-smoke",
                "root_id": root["root_id"],
                "schema_set_version": root["schema_set_version"],
                "selected_marker_ids": [],
                "query_text": "atlas",
                "sort": {"field": "RELEVANCE", "direction": "DESC"},
                "facet_prefix": "",
            },
        )
        assert search["total"] > 0
        company = "company-atlas"
        dictionary = api(
            f"/companies/{company}/dictionaries",
            {"name": "Container persistence", "description": ""},
            headers,
            201,
        )
        denied = api(
            f"/companies/{company}/dictionaries",
            {"name": "Must not exist", "description": ""},
            {**headers, "Origin": "https://untrusted.example"},
            403,
        )
        assert denied["error"]["code"] == "FORBIDDEN"

        deadline = time.monotonic() + 25
        while True:
            queue = api(
                "/sorting/queue/query",
                {
                    "company_id": company,
                    "filters": {"statuses": ["READY"], "query_text": ""},
                    "cursor": None,
                    "limit": 100,
                },
            )
            if queue["items"]:
                break
            assert time.monotonic() < deadline, "Incoming item did not become READY"
            time.sleep(1)
        item = queue["items"][0]
        selection = api(
            "/sorting/selections",
            {
                "company_id": company,
                "mode": "EXPLICIT",
                "items": [{"item_id": item["item_id"], "item_revision": item["item_revision"]}],
            },
            headers,
            201,
        )
        batch = api(
            "/sorting/batches",
            {"execution_mode": "DIRECT", "selection_id": selection["selection_id"]},
            headers,
            202,
        )
        deadline = time.monotonic() + 25
        while True:
            finished = api(f"/sorting/batches/{batch['batch_id']}")
            if finished["status"] in {"COMPLETED", "COMPLETED_WITH_ISSUES"}:
                break
            assert time.monotonic() < deadline, (
                "File batch did not complete",
                finished,
                dc("run", "--rm", "-T", "--no-deps", "cli", "status"),
            )
            time.sleep(1)
        assert finished["outcomes"][0]["state"] == "MANUAL_REVIEW"
        assert finished["status"] == "COMPLETED_WITH_ISSUES"
        original_dictionary = api(f"/dictionaries/{dictionary['dictionary_id']}")
        dc("restart", "api", "worker")
        dc("up", "-d", "--wait", "--wait-timeout", "150", "api", "worker", timeout=210)
        assert api(f"/dictionaries/{dictionary['dictionary_id']}") == original_dictionary

        run([*ops, "check"], environment=environment)
        run([*ops, "snapshot", "snapshot"], environment=environment)
        refused = subprocess.run(
            [*ops, "snapshot", "snapshot"], env=environment, text=True, capture_output=True, timeout=210
        )
        assert refused.returncode != 0 and "does not already exist" in refused.stderr
        # A failed copy must resume the previously running application too.
        assert api(f"/dictionaries/{dictionary['dictionary_id']}") == original_dictionary
        dc("stop", "api", "worker")
        run([*ops, "restore", "snapshot", "restored"], environment=environment)
        environment["WISEWAY_STATE_PATH"] = str(task / "backups/restored/data")
        environment["WISEWAY_SANDBOX_PATH"] = str(task / "backups/restored/sandbox")
        dc("up", "-d", "--force-recreate", "--wait", "--wait-timeout", "150", "api", "worker", timeout=210)
        assert api(f"/dictionaries/{dictionary['dictionary_id']}") == original_dictionary
        assert api(f"/sorting/batches/{batch['batch_id']}")["outcomes"] == finished["outcomes"]
        assert json.loads(dc("run", "--rm", "-T", "--no-deps", "cli", "doctor"))["ready"] is True
        for service in ("api", "worker", "gateway"):
            details = json.loads(run(["docker", "inspect", dc("ps", "-q", service).strip()]))[0]
            assert details["Config"]["User"] == "10001:10001"
            assert details["HostConfig"]["ReadonlyRootfs"] is True
            assert details["HostConfig"]["Privileged"] is False
            assert "ALL" in details["HostConfig"]["CapDrop"]
        print(
            json.dumps(
                {
                    "tls": True,
                    "login": True,
                    "csrf_origin": True,
                    "search": True,
                    "native_file_batch": True,
                    "restart_persistence": True,
                    "full_snapshot_restore": True,
                    "failed_backup_resumes_services": True,
                    "nonroot_readonly": True,
                }
            )
        )
    except (AssertionError, OSError, RuntimeError, URLError, subprocess.TimeoutExpired):
        print(dc("logs", "--no-color", "--tail", "60"), file=sys.stderr)
        raise
    finally:
        try:
            dc("down", "--remove-orphans", timeout=180)
        finally:
            owner(os.getuid(), os.getgid())
            shutil.rmtree(task)
            os.unlink(lock_path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: container_smoke.py IMAGE")
    main(sys.argv[1])
