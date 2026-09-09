"""HTTP and transaction boundaries for persistent archive generations."""

import pytest

from wiseway.app import dispatch
from wiseway.common import public
from wiseway.search import build_item
from wiseway.services import Context
from wiseway.sqlite_search import add_items, create_generation, finish


def publish(ctx, generation, names):
    with ctx.store.transaction() as tx:
        configured_root = tx.require("root", "archive-root")
        root = {
            **public(configured_root),
            "index_generation": generation,
            "indexed_at": "2026-01-01T00:00:00Z",
        }
        create_generation(tx, root, generation)
        rows = [
            build_item(
                root["root_id"],
                root["display_prefix"],
                "Archive/Atlas/Orion_2031/Reports/" + name,
                1,
                root["indexed_at"],
                configured_root["_schema"],
                name.replace(".", "-"),
            )
            for name in names
        ]
        add_items(tx, generation, rows)
        finish(tx, generation)
        tx.put(
            "index",
            root["root_id"],
            {"root": root, "items": [], "_storage": "sqlite", "_generation": generation},
        )
    return root


def body(root, text="paper"):
    return {
        "request_state_id": "persistent-request",
        "root_id": root["root_id"],
        "schema_set_version": root["schema_set_version"],
        "selected_marker_ids": [],
        "query_text": text,
        "sort": {"field": "RELEVANCE", "direction": "DESC"},
        "facet_prefix": "",
    }


def test_http_reads_persistent_index_after_reopen(configured, client):
    ctx = Context(configured)
    try:
        root = publish(ctx, "persistent-api", ["paper-10.pdf", "paper-2.pdf", "other.pdf"])
    finally:
        ctx.close()
    login = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://localhost:8000"},
        json={"login": "worker-atlas", "password": "synthetic-test-password"},
    )
    assert login.status_code == 200
    response = client.post("/api/v1/search", json=body(root))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 2
    assert [row["item_id"] for row in payload["items"]] == ["paper-2-pdf", "paper-10-pdf"]
    assert payload["next_facet"]["options"][0]["count"] == 2
    assert payload["index_generation"] == "persistent-api"


def test_persistent_search_reader_keeps_generation_across_publication(configured):
    ctx = Context(configured)
    try:
        root = publish(ctx, "old-persistent", ["paper-old.pdf"])
        with ctx.store.transaction(write=False) as old:
            status, first = dispatch(ctx, old, "searchFiles", {}, {}, body(root), "before")
            assert status == 200
            new_root = publish(ctx, "new-persistent", ["paper-new.pdf", "paper-next.pdf"])
            with ctx.store.transaction(write=False) as new:
                _, current = dispatch(ctx, new, "searchFiles", {}, {}, body(new_root), "new")
            _, previous = dispatch(ctx, old, "searchFiles", {}, {}, body(root), "old")
        assert first == previous
        assert [row["item_id"] for row in previous["items"]] == ["paper-old-pdf"]
        assert current["total"] == 2
        assert current["index_generation"] == "new-persistent"
    finally:
        ctx.close()


def test_missing_persistent_generation_fails_without_empty_success(configured):
    from wiseway.common import ApiError

    ctx = Context(configured)
    try:
        root = publish(ctx, "broken-persistent", ["paper.pdf"])
        with ctx.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE search_generations SET state='BUILDING' WHERE generation_id=?", ("broken-persistent",)
            )
        with ctx.store.transaction(write=False) as tx, pytest.raises(ApiError) as caught:
            dispatch(ctx, tx, "searchFiles", {}, {}, body(root), "invalid-generation")
        assert (caught.value.code, caught.value.status) == ("SEARCH_UNAVAILABLE", 503)
    finally:
        ctx.close()
