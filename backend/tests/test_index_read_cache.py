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
