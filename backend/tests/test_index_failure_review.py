def test_incoming_scan_failure_is_exposed_in_progress(configured, monkeypatch):
    from wiseway.indexer import Indexer

    from wiseway.services import Context

    ctx = Context(configured)
    real_walk = ctx.fs.walk

    def fail_incoming(relative):
        if relative == "Incoming/Atlas":
            raise PermissionError("synthetic denied directory")
        return real_walk(relative)

    monkeypatch.setattr(ctx.fs, "walk", fail_incoming)
    try:
        Indexer(ctx).scan()
        with ctx.store.transaction(write=False) as tx:
            progress = tx.require("index_progress", "incoming-incoming-atlas")
        assert progress["root_id"] == "incoming-atlas"
        assert progress["status"] == "FAILED"
    finally:
        ctx.close()


def test_unchanged_index_scan_reuses_items_and_refreshes_freshness(configured, monkeypatch):
    from wiseway import indexer as module
    from wiseway.services import Context

    ctx = Context(configured)
    try:
        module.Indexer(ctx).scan()
        with ctx.store.transaction() as tx:
            before = tx.require("index", "archive-root")
            before["freshness"]["status"] = "STALE"
            tx.put("index", "archive-root", before)

        def unexpected_rebuild(*args, **kwargs):
            raise AssertionError("Unchanged metadata must reuse the published generation")

        monkeypatch.setattr(module, "build_item", unexpected_rebuild)
        module.Indexer(ctx).scan()
        with ctx.store.transaction(write=False) as tx:
            after = tx.require("index", "archive-root")
        assert after["freshness"]["status"] == "CURRENT"
        assert after["items"] == before["items"]
        assert after["root"]["index_generation"] == before["root"]["index_generation"]
    finally:
        ctx.close()
