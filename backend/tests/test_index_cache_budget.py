import json

from wiseway.services import Context


def test_one_larger_index_reuses_the_existing_total_cache_budget(configured):
    ctx = Context(configured)
    try:
        with ctx.store.transaction() as tx:
            document = tx.require("index", "archive-root")
            sample = document["items"][0]
            document["items"] = [{**sample, "item_id": f"large-{number}"} for number in range(8_000)]
            size = len(json.dumps(document, ensure_ascii=False).encode())
            assert 8 * 1024**2 < size < 32 * 1024**2
            tx.put("index", "archive-root", document)
        with ctx.store.transaction(write=False) as tx:
            first = ctx.read_index(tx, "archive-root")
        queries = []
        with ctx.store.transaction(write=False) as tx:
            tx.connection.set_trace_callback(queries.append)
            second = ctx.read_index(tx, "archive-root")
        assert second is first
        assert not any("SELECT body FROM objects" in sql for sql in queries)
    finally:
        ctx.close()


def test_shared_cache_budget_evicts_documents_and_their_prepared_indexes(configured, monkeypatch):
    import wiseway.services as services

    ctx = Context(configured)
    try:
        with ctx.store.transaction() as tx:
            document = tx.require("index", "archive-root")
            size = len(json.dumps(document, ensure_ascii=False).encode())
            monkeypatch.setattr(services, "MAX_INDEX_CACHE_BYTES", size * 2 + 100, raising=False)
            for number in range(3):
                tx.put(
                    "index",
                    f"budget-{number}",
                    {**document, "root": {**document["root"], "root_id": f"budget-{number}"}},
                )
        for number in range(3):
            with ctx.store.transaction(write=False) as tx:
                read = ctx.read_index(tx, f"budget-{number}")
            ctx.prepared_search(read)
        assert "budget-0" not in ctx._index_cache
        assert "budget-0" not in ctx._prepared_indexes
        with ctx.store.transaction(write=False) as tx:
            queries = []
            tx.connection.set_trace_callback(queries.append)
            assert ctx.read_index(tx, "budget-0")["items"] == document["items"]
        assert any("SELECT body FROM objects" in sql for sql in queries)
    finally:
        ctx.close()
