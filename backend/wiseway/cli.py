"""Local administration and process entry points for the synthetic demo."""

import argparse
import getpass
import json
import signal
import sys
from threading import Event

from .common import Settings


def main(argv=None):
    parser = argparse.ArgumentParser(prog="wiseway")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-demo", help="Create synthetic data and local accounts")
    init.add_argument("--password-stdin", action="store_true")
    serve = commands.add_parser("serve", help="Run the HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    commands.add_parser("worker", help="Run indexing and durable file jobs")
    commands.add_parser("tick", help="Run one worker/index observation")
    commands.add_parser("status", help="Show outstanding recovery and index progress")
    commands.add_parser("doctor", help="Check local database, filesystem, and worker state")
    backup = commands.add_parser("backup", help="Create a new integrity-checked SQLite backup")
    backup.add_argument("destination")
    restore_check = commands.add_parser(
        "restore-check", help="Copy a backup into a new database and verify its integrity"
    )
    restore_check.add_argument("backup")
    restore_check.add_argument("destination")
    recover = commands.add_parser("recover", help="Reconcile one attempt using observed file identity")
    recover.add_argument("attempt_id")
    from .accounts import register_commands

    register_commands(commands)
    args = parser.parse_args(argv)
    settings = Settings()
    if args.command == "init-demo":
        from .seed import initialize

        password = (
            sys.stdin.readline().rstrip("\n")
            if args.password_stdin
            else getpass.getpass("Password for the three synthetic accounts: ")
        )
        if len(password) < 12:
            parser.error("Use at least 12 characters")
        initialize(settings, password=password)
        print("Synthetic demo initialized: worker-atlas, worker-nova, admin.")
        return
    if args.command == "serve":
        if not settings.secure_cookie and args.host not in {"localhost", "127.0.0.1", "::1"}:
            parser.error(
                "Insecure HTTP serving is limited to a loopback host; enable secure cookies for HTTPS"
            )
        if settings.trusted_proxy_headers and args.host not in {"localhost", "127.0.0.1", "::1"}:
            parser.error("Trusted proxy headers require a loopback API binding")
        import uvicorn

        uvicorn.run(
            "wiseway.app:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            access_log=False,
            proxy_headers=settings.trusted_proxy_headers,
            forwarded_allow_ips="127.0.0.1,::1" if settings.trusted_proxy_headers else None,
        )
        return
    if args.command == "backup":
        from .operations import OperationError, backup_database

        try:
            print(json.dumps(backup_database(settings, args.destination), ensure_ascii=False, indent=2))
        except OperationError as error:
            parser.error(str(error))
        return
    if args.command == "restore-check":
        from .operations import OperationError, verify_restore

        try:
            print(
                json.dumps(
                    verify_restore(settings, args.backup, args.destination), ensure_ascii=False, indent=2
                )
            )
        except OperationError as error:
            parser.error(str(error))
        return
    from .services import Context

    ctx = Context(settings)
    stop_requested = Event()
    previous_signal_handlers = {}

    def request_stop(_signum, _frame):
        # A worker may be between its durable SQLite and filesystem steps.
        # Let that step complete, then stop before beginning another one.
        stop_requested.set()

    if args.command == "worker":
        for signal_name in (signal.SIGINT, signal.SIGTERM):
            previous_signal_handlers[signal_name] = signal.signal(signal_name, request_stop)
    try:
        from .accounts import execute as execute_account_command

        if execute_account_command(args, ctx, parser):
            return
        if args.command in ("worker", "tick"):
            from .indexer import Indexer
            from .maintenance import Maintenance
            from .quarantine import QuarantineService
            from .worker import Worker

            worker, indexer = Worker(ctx), Indexer(ctx)
            while not stop_requested.is_set():
                worker.run_once()
                if stop_requested.is_set():
                    break
                QuarantineService(ctx).reconcile()
                if stop_requested.is_set():
                    break
                indexer.scan()
                if stop_requested.is_set():
                    break
                Maintenance(ctx).run_once()
                if stop_requested.is_set():
                    break
                from .operations import record_worker_heartbeat

                record_worker_heartbeat(ctx)
                if args.command == "tick":
                    break
                stop_requested.wait(settings.readiness_seconds)
        elif args.command == "status":
            from .operations import operator_status

            print(json.dumps(operator_status(ctx), ensure_ascii=False, indent=2))
        elif args.command == "doctor":
            from .operations import doctor

            result = doctor(ctx)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if not result["ready"]:
                raise SystemExit(1)
        elif args.command == "recover":
            from .worker import Worker

            if not Worker(ctx).recover(args.attempt_id):
                print("Placement remains unproven; no file action was repeated.", file=sys.stderr)
                raise SystemExit(2)
            print("Observed file identity reconciled.")
    except KeyboardInterrupt:
        pass
    finally:
        for signal_name, previous_handler in previous_signal_handlers.items():
            signal.signal(signal_name, previous_handler)
        ctx.close()


if __name__ == "__main__":
    main()
