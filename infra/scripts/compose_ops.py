"""Coordinate health checks and offline snapshots for one Compose installation."""

import argparse
import fcntl
import os
from pathlib import Path
import re
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    repository = Path(__file__).resolve().parents[2]
    parser.add_argument("--env-file", default=str(repository / ".env"))
    parser.add_argument("--lock-file", default=str(repository / ".wiseway-ops.lock"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    create = commands.add_parser("snapshot")
    create.add_argument("name")
    restore = commands.add_parser("restore")
    restore.add_argument("name")
    restore.add_argument("destination")
    args = parser.parse_args()
    for name in (getattr(args, "name", None), getattr(args, "destination", None)):
        if name is not None and (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", name) or name in {".", ".."}
        ):
            parser.error("Snapshot names must be simple directory names of at most 100 characters")
    compose = ["docker", "compose", "--env-file", args.env_file, "-f", str(repository / "compose.yaml")]

    def dc(*command, capture=False):
        return subprocess.run([*compose, *command], check=True, text=True, capture_output=capture)

    descriptor = os.open(args.lock_file, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("Another operation is running for this installation")
        dc("config", "--quiet")
        running = set(dc("ps", "--services", "--status", "running", capture=True).stdout.split())
        active = running & {"api", "worker"}
        if args.command == "check":
            if not {"api", "worker", "gateway"} <= running:
                parser.error("API, worker and gateway must all be running")
            dc("exec", "-T", "api", "python", "/usr/local/lib/wiseway/healthcheck.py", "api")
            dc("exec", "-T", "worker", "python", "/usr/local/lib/wiseway/healthcheck.py", "worker")
        elif args.command == "snapshot":
            # Remember exactly what was running; never unexpectedly start a stopped service.
            try:
                dc("stop", "api", "worker")
                dc(
                    "run",
                    "--rm",
                    "-T",
                    "--no-deps",
                    "--entrypoint",
                    "python",
                    "cli",
                    "/usr/local/lib/wiseway/snapshot.py",
                    "create",
                    "--data-dir",
                    "/var/lib/wiseway/state",
                    "--sandbox-dir",
                    "/srv/wiseway/sandbox",
                    "--destination",
                    "/backups/" + args.name,
                )
            finally:
                if active:
                    dc("up", "-d", "--wait", "--wait-timeout", "150", *sorted(active))
        elif args.command == "restore":
            if active:
                parser.error("Stop API and worker before restoring; existing data will remain untouched")
            dc(
                "run",
                "--rm",
                "-T",
                "--no-deps",
                "--entrypoint",
                "python",
                "cli",
                "/usr/local/lib/wiseway/snapshot.py",
                "restore",
                "--snapshot",
                "/backups/" + args.name,
                "--destination",
                "/backups/" + args.destination,
            )
            print(
                "Restored into new backup subdirectories. Select their data/ and sandbox/ paths before starting."
            )
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    main()
