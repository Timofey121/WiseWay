"""Bounded cleanup of data whose expiry is already part of the service contract."""

import json


class Maintenance:
    def __init__(self, ctx):
        self.ctx = ctx

    def run_once(self):
        now = self.ctx.settings.clock()
        with self.ctx.store.transaction() as tx:

            def count(kind):
                return tx.connection.execute("SELECT COUNT(*) FROM objects WHERE kind=?", (kind,)).fetchone()[
                    0
                ]

            before = {kind: count(kind) for kind in ("cursor", "page_snapshot", "session", "login_rate")}

            def records(kind):
                return [
                    (key, json.loads(body))
                    for key, body in tx.connection.execute(
                        "SELECT id, body FROM objects WHERE kind=?", (kind,)
                    )
                ]

            tx.connection.execute(
                "DELETE FROM objects "
                "WHERE kind IN ('cursor', 'page_snapshot') "
                "AND COALESCE(CAST(json_extract(body, '$.expires') AS REAL), 0) <= ?",
                (now,),
            )
            for key, session in records("session"):
                if (
                    min(
                        session["created"] + self.ctx.settings.absolute_session_seconds,
                        session["touched"] + self.ctx.settings.idle_session_seconds,
                    )
                    <= now
                ):
                    tx.delete("session", key)
            for key, attempts in records("login_rate"):
                kept = [attempt for attempt in attempts if now - attempt < 60]
                if kept:
                    tx.put("login_rate", key, kept)
                else:
                    tx.delete("login_rate", key)
            return {kind: before[kind] - count(kind) for kind in before}
