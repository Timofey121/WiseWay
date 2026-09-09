"""Local administration and process entry points for the synthetic demo."""

import argparse
import getpass
import json
import sys
import time

from .common import Settings, uid


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
    recover = commands.add_parser("recover", help="Reconcile one attempt using observed file identity")
    recover.add_argument("attempt_id")
    block = commands.add_parser("block-user", help="Block a local account and revoke sessions")
    block.add_argument("login")
    block.add_argument("--actor", required=True, help="Existing local ADMIN login for audit attribution")
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
        import uvicorn

        uvicorn.run(
            "wiseway.app:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            access_log=False,
            proxy_headers=False,
        )
        return
    from .services import Context

    ctx = Context(settings)
    try:
        if args.command in ("worker", "tick"):
            from .indexer import Indexer
            from .maintenance import Maintenance
            from .quarantine import QuarantineService
            from .worker import Worker

            worker, indexer = Worker(ctx), Indexer(ctx)
            while True:
                worker.run_once()
                QuarantineService(ctx).reconcile()
                indexer.scan()
                Maintenance(ctx).run_once()
                if args.command == "tick":
                    break
                time.sleep(settings.readiness_seconds)
        elif args.command == "status":
            with ctx.store.transaction(write=False) as tx:
                print(
                    json.dumps(
                        {
                            "index": tx.list("index_progress"),
                            "attempts": [
                                {"attempt_id": a["attempt_id"], "phase": a["phase"]}
                                for a in tx.list("attempt")
                                if a["phase"] == "RECOVERY_REQUIRED"
                            ],
                            "returns": [
                                {"operation_id": o["operation_id"], "phase": o["phase"]}
                                for o in tx.list("return")
                                if o["phase"] in ("INTENT", "RECOVERY_REQUIRED")
                            ],
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
        elif args.command == "recover":
            from .worker import Worker

            if not Worker(ctx).recover(args.attempt_id):
                print("Placement remains unproven; no file action was repeated.", file=sys.stderr)
                raise SystemExit(2)
            print("Observed file identity reconciled.")
        elif args.command == "block-user":
            from .audit import emit

            with ctx.store.transaction() as tx:
                users = tx.list("user")
                administrator = next(
                    (
                        u
                        for u in users
                        if u["actor"]["login"] == args.actor
                        and u["actor"]["role"] == "ADMIN"
                        and not u["blocked"]
                    ),
                    None,
                )
                target = next((u for u in users if u["actor"]["login"] == args.login), None)
                if not administrator or not target:
                    parser.error("An active administrator and existing target account are required")
                target["blocked"] = True
                tx.put("user", target["actor"]["user_id"], target)
                # Authentication checks the current account state on every request.
                emit(
                    tx,
                    administrator["actor"],
                    "ACCOUNT_BLOCKED",
                    uid("request"),
                    now=settings.clock(),
                    comment="Blocked account: " + target["actor"]["login"],
                )
            print("Account blocked; its sessions no longer authorize requests.")
    except KeyboardInterrupt:
        pass
    finally:
        ctx.close()


if __name__ == "__main__":
    main()
