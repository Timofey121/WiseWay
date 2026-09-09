from wiseway.services import Context


def test_index_cache_tracks_transaction_snapshot_updates_and_deletion(configured):
    ctx = Context(configured)
    try:
        with ctx.store.transaction(write=False) as old:
            before = ctx.read_index(old, "archive-root")
            with ctx.store.transaction() as writer:
                updated = writer.require("index", "archive-root")
                updated["freshness"]["status"] = "STALE"
                updated["items"] = []
                writer.put("index", "archive-root", updated)
            with ctx.store.transaction(write=False) as current:
                changed = ctx.read_index(current, "archive-root")
                assert changed["items"] == []
                assert changed["freshness"]["status"] == "STALE"
            assert ctx.read_index(old, "archive-root") == before
        with ctx.store.transaction() as writer:
            writer.delete("index", "archive-root")
        with ctx.store.transaction(write=False) as current:
            assert ctx.read_index(current, "archive-root") is None
    finally:
        ctx.close()


def test_cached_index_avoids_body_read_but_tracks_sql_updates_and_recreation(configured):
    ctx = Context(configured)
    try:
        with ctx.store.transaction(write=False) as tx:
            original = ctx.read_index(tx, "archive-root")
        queries = []
        with ctx.store.transaction(write=False) as tx:
            tx.connection.set_trace_callback(queries.append)
            assert ctx.read_index(tx, "archive-root") is original
        assert not any("SELECT body FROM objects" in sql for sql in queries)
        with ctx.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE objects SET body=json_set(body, '$.freshness.status', 'STALE') "
                "WHERE kind='index' AND id='archive-root'"
            )
        with ctx.store.transaction(write=False) as tx:
            assert ctx.read_index(tx, "archive-root")["freshness"]["status"] == "STALE"
        with ctx.store.transaction() as tx:
            tx.delete("index", "archive-root")
            replacement = {**original, "items": []}
            tx.put("index", "archive-root", replacement)
        with ctx.store.transaction(write=False) as tx:
            assert ctx.read_index(tx, "archive-root")["items"] == []
    finally:
        ctx.close()
