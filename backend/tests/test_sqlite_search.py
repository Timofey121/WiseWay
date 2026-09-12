import pytest
import sqlite3

from test_search import ROOT as SCALE_ROOT
from test_search import request as scale_request
from test_search_scale_review import _corpus, _selection
from test_search_golden import ROOT, build_items, golden, request
from wiseway.common import ApiError
from wiseway.search import _parse_query, facet, search
from wiseway.sqlite_search import (
    SqlSearchIndex,
    activate_generation,
    add_items,
    create_generation,
    delete_generation,
    finish,
    _generation_token,
)
from wiseway.storage import Store


class _FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _force_progress(connection):
    """Run enough VM instructions to deterministically call a 1k progress hook."""
    return connection.execute(
        "WITH RECURSIVE counter(value) AS (VALUES(1) UNION ALL "
        "SELECT value + 1 FROM counter WHERE value < 10000) SELECT sum(value) FROM counter"
    ).fetchone()[0]


def _index(tmp_path, rows, root=ROOT):
    store = Store(tmp_path / "search.sqlite3")
    generation = "sql-golden-generation"
    with store.transaction() as tx:
        create_generation(tx, root, generation)
        assert add_items(tx, generation, iter(rows)) == len(rows)
        finish(tx, generation)
    return store, generation


@pytest.mark.parametrize("case", golden()["cases"], ids=lambda case: case["id"])
def test_sqlite_index_preserves_golden_search_and_facet(tmp_path, case):
    items = build_items(golden())
    rows = [items[item_id] for item_id in case["items"]]
    store, generation = _index(tmp_path, rows)
    for query in case.get("queries") or [case["query"]]:
        body = {**request(case, items), "query_text": query}
        with store.transaction(write=False) as tx:
            actual = SqlSearchIndex(tx, generation).search(ROOT, body)
            actual_facet = SqlSearchIndex(tx, generation).facet(
                ROOT, {key: value for key, value in body.items() if key != "sort"}
            )
        expected = search(ROOT, rows, body)
        expected_facet = facet(ROOT, rows, {key: value for key, value in body.items() if key != "sort"})
        assert actual == expected
        assert actual_facet == expected_facet


def test_sqlite_index_preserves_unicode_casefold_punctuation_and_natural_order(tmp_path):
    from wiseway.search import DEMO_SCHEMAS, build_item

    paths = [
        "Archive/Atlas/Orion_2031/Reports/Straße_A!B_02.txt",
        "Archive/Atlas/Orion_2031/Reports/strasse_A!B_2.txt",
        "Archive/Atlas/Orion_2031/Reports/A!B_10.txt",
    ]
    rows = [
        build_item(
            ROOT["root_id"],
            ROOT["display_prefix"],
            path,
            1,
            ROOT["indexed_at"],
            DEMO_SCHEMAS["schema-demo-1"],
            str(n),
        )
        for n, path in enumerate(paths)
    ]
    store, generation = _index(tmp_path, rows)
    for text, ordering in (
        ("STRASSE", {"field": "RELEVANCE", "direction": "DESC"}),
        ("A!B", {"field": "NAME", "direction": "ASC"}),
    ):
        body = {
            "request_state_id": "unicode",
            "root_id": ROOT["root_id"],
            "schema_set_version": ROOT["schema_set_version"],
            "selected_marker_ids": [],
            "query_text": text,
            "sort": ordering,
            "facet_prefix": "",
        }
        with store.transaction(write=False) as tx:
            actual = SqlSearchIndex(tx, generation).search(ROOT, body)
        assert actual == search(ROOT, rows, body)


def test_sqlite_index_preserves_unicode_decimal_natural_order_and_empty_facet_prefix(tmp_path):
    from wiseway.search import DEMO_SCHEMAS, build_item

    rows = [
        build_item(
            ROOT["root_id"],
            ROOT["display_prefix"],
            f"Archive/Atlas/Orion_2031/Reports/Report_{number}.txt",
            1,
            ROOT["indexed_at"],
            DEMO_SCHEMAS["schema-demo-1"],
            str(index),
        )
        for index, number in enumerate(("١٠", "٢", "02"))
    ]
    store, generation = _index(tmp_path, rows)
    body = {
        "request_state_id": "decimal",
        "root_id": ROOT["root_id"],
        "schema_set_version": ROOT["schema_set_version"],
        "selected_marker_ids": [],
        "query_text": "report",
        "sort": {"field": "NAME", "direction": "ASC"},
        "facet_prefix": "does-not-exist",
    }
    with store.transaction(write=False) as tx:
        actual = SqlSearchIndex(tx, generation).search(ROOT, body)
    assert actual == search(ROOT, rows, body)


def test_sqlite_modified_at_sort_matches_fractional_utc_oracle_and_keeps_path_ties(tmp_path):
    from wiseway.search import DEMO_SCHEMAS, build_item

    rows = []
    for item_id, filename, modified_at in (
        ("whole-b", "b.txt", "2026-01-01T00:00:00.000000Z"),
        ("fraction", "c.txt", "2026-01-01T00:00:00.001Z"),
        ("whole-a", "a.txt", "2026-01-01T00:00:00Z"),
    ):
        rows.append(
            build_item(
                ROOT["root_id"],
                ROOT["display_prefix"],
                f"Archive/Atlas/Orion_2031/Reports/{filename}",
                1,
                modified_at,
                DEMO_SCHEMAS[ROOT["schema_set_version"]],
                item_id,
            )
        )
    store, generation = _index(tmp_path, rows)
    for direction, expected in (
        ("ASC", ["whole-a", "whole-b", "fraction"]),
        ("DESC", ["fraction", "whole-a", "whole-b"]),
    ):
        body = {
            "request_state_id": "fractional-utc",
            "root_id": ROOT["root_id"],
            "schema_set_version": ROOT["schema_set_version"],
            "selected_marker_ids": [],
            "query_text": "txt",
            "sort": {"field": "MODIFIED_AT", "direction": direction},
            "facet_prefix": "",
        }
        with store.transaction(write=False) as tx:
            actual = SqlSearchIndex(tx, generation).search(ROOT, body)
        assert actual == search(ROOT, rows, body)
        assert [item["item_id"] for item in actual["items"]] == expected


def test_generation_activation_and_contentless_fts_cleanup(tmp_path):
    items = build_items(golden())
    first, second = "sql-first", "sql-second"
    store = Store(tmp_path / "search.sqlite3")
    with store.transaction() as tx:
        create_generation(tx, ROOT, first)
        add_items(tx, first, [items["a-main"]])
        finish(tx, first)
        activate_generation(tx, first)
        create_generation(tx, ROOT, second)
        add_items(tx, second, [items["nova"]])
        finish(tx, second)
        assert delete_generation(tx, second, batch_size=1) is False
        assert delete_generation(tx, second, batch_size=1) is True
    with store.transaction(write=False) as tx:
        assert (
            tx.connection.execute(
                "SELECT COUNT(*) FROM search_fts WHERE search_fts MATCH ?",
                (f"generation : {_generation_token(first)}",),
            ).fetchone()[0]
            == 1
        )
        assert (
            tx.connection.execute(
                "SELECT COUNT(*) FROM search_fts WHERE search_fts MATCH ?",
                (f"generation : {_generation_token(second)}",),
            ).fetchone()[0]
            == 0
        )
        assert (
            tx.connection.execute(
                "SELECT state FROM search_generations WHERE generation_id=?", (first,)
            ).fetchone()[0]
            == "ACTIVE"
        )
        assert (
            tx.connection.execute(
                "SELECT 1 FROM search_generations WHERE generation_id=?", (second,)
            ).fetchone()
            is None
        )


def test_sqlite_index_matches_randomized_oracle_for_all_top_k_orders_and_prefixes(tmp_path):
    rows = _corpus()
    store, generation = _index(tmp_path, rows, SCALE_ROOT)
    selections = ([], _selection(rows, "Atlas"), _selection(rows, "Nova"))
    queries = ("report", "док", "case", "10", '"orion 2031"', '"документ 2"', "atlas report")
    orderings = [
        {"field": field, "direction": direction}
        for field in ("PATH", "NAME", "SIZE", "MODIFIED_AT")
        for direction in ("ASC", "DESC")
    ] + [{"field": "RELEVANCE", "direction": "DESC"}]
    for limit in (1, 7, 47):
        for selected in selections:
            for query in queries:
                for ordering in orderings:
                    body = scale_request(query, selected, sort=ordering, facet_prefix="r")
                    with store.transaction(write=False) as tx:
                        indexed = SqlSearchIndex(tx, generation).search(SCALE_ROOT, body, limit=limit)
                        indexed_facet = SqlSearchIndex(tx, generation).facet(
                            SCALE_ROOT, {key: value for key, value in body.items() if key != "sort"}
                        )
                    assert indexed == search(SCALE_ROOT, rows, body, limit=limit)
                    assert indexed_facet == facet(
                        SCALE_ROOT, rows, {key: value for key, value in body.items() if key != "sort"}
                    )


def test_sqlite_index_handles_nul_token_and_natural_key_without_changing_oracle(tmp_path):
    from wiseway.search import DEMO_SCHEMAS, build_item

    rows = [
        build_item(
            SCALE_ROOT["root_id"],
            SCALE_ROOT["display_prefix"],
            "Archive/Atlas/Orion_2031/Reports/a\x00b-2.txt",
            1,
            SCALE_ROOT["indexed_at"],
            DEMO_SCHEMAS[SCALE_ROOT["schema_set_version"]],
            "nul-2",
        ),
        build_item(
            SCALE_ROOT["root_id"],
            SCALE_ROOT["display_prefix"],
            "Archive/Atlas/Orion_2031/Reports/a\x00b-10.txt",
            1,
            SCALE_ROOT["indexed_at"],
            DEMO_SCHEMAS[SCALE_ROOT["schema_set_version"]],
            "nul-10",
        ),
    ]
    store, generation = _index(tmp_path, rows, SCALE_ROOT)
    body = scale_request("a\x00b", sort={"field": "NAME", "direction": "ASC"})
    with store.transaction(write=False) as tx:
        indexed = SqlSearchIndex(tx, generation).search(SCALE_ROOT, body)
    assert indexed == search(SCALE_ROOT, rows, body)


def test_sqlite_index_handles_contract_length_prefix_and_punctuation_phrase(tmp_path):
    from wiseway.search import DEMO_SCHEMAS, build_item

    long = "x" * 512
    rows = [
        build_item(
            SCALE_ROOT["root_id"],
            SCALE_ROOT["display_prefix"],
            f"Archive/Atlas/Orion_2031/Reports/{long}.txt",
            1,
            SCALE_ROOT["indexed_at"],
            DEMO_SCHEMAS[SCALE_ROOT["schema_set_version"]],
            "long",
        ),
        build_item(
            SCALE_ROOT["root_id"],
            SCALE_ROOT["display_prefix"],
            "Archive/Atlas/Orion_2031/Reports/A!B_٢٠٣١.txt",
            1,
            SCALE_ROOT["indexed_at"],
            DEMO_SCHEMAS[SCALE_ROOT["schema_set_version"]],
            "punctuation",
        ),
    ]
    store, generation = _index(tmp_path, rows, SCALE_ROOT)
    for query in (long[:511], long, '"A!B ٢٠٣١"'):
        body = scale_request(query, sort={"field": "RELEVANCE", "direction": "DESC"})
        with store.transaction(write=False) as tx:
            indexed = SqlSearchIndex(tx, generation).search(SCALE_ROOT, body)
        assert indexed == search(SCALE_ROOT, rows, body)


def test_sqlite_index_materializes_one_candidate_set_and_always_cleans_temp_table(tmp_path, monkeypatch):
    rows = _corpus()
    store, generation = _index(tmp_path, rows, SCALE_ROOT)
    body = scale_request("report", sort={"field": "NAME", "direction": "ASC"})
    with store.transaction(write=False) as tx:
        index = SqlSearchIndex(tx, generation)
        original, calls = index._candidates, []

        def counted(*args):
            calls.append(args)
            return original(*args)

        monkeypatch.setattr(index, "_candidates", counted)
        assert index.search(SCALE_ROOT, body) == search(SCALE_ROOT, rows, body)
        assert len(calls) == 1
        facet_body = {key: value for key, value in body.items() if key != "sort"}
        assert index.facet(SCALE_ROOT, facet_body) == facet(SCALE_ROOT, rows, facet_body)
        assert (
            tx.connection.execute(
                "SELECT 1 FROM sqlite_temp_master WHERE type='table' AND name='wiseway_search_candidates'"
            ).fetchone()
            is None
        )
        with pytest.raises(ApiError):
            index.search(SCALE_ROOT, {**body, "sort": {"field": "unknown", "direction": "ASC"}})
        assert (
            tx.connection.execute(
                "SELECT 1 FROM sqlite_temp_master WHERE type='table' AND name='wiseway_search_candidates'"
            ).fetchone()
            is None
        )


def test_sqlite_candidate_temp_writes_do_not_block_main_writer(tmp_path):
    rows = _corpus()
    store, generation = _index(tmp_path, rows, SCALE_ROOT)
    with store.transaction(write=False) as reader:
        SqlSearchIndex(reader, generation).search(
            SCALE_ROOT, scale_request("report", sort={"field": "RELEVANCE", "direction": "DESC"})
        )
        with store.transaction() as writer:
            writer.put("temp-search-regression", "writer", {"ok": True})
    with store.transaction(write=False) as tx:
        assert tx.require("temp-search-regression", "writer") == {"ok": True}


def test_sqlite_idle_facets_use_marker_indexes_without_reading_item_rows(tmp_path):
    rows = _corpus()
    store, generation = _index(tmp_path, rows, SCALE_ROOT)
    idle = scale_request("", sort={"field": "PATH", "direction": "ASC"})
    selected = scale_request("", _selection(rows, "Atlas"), sort={"field": "PATH", "direction": "ASC"})
    with store.transaction(write=False) as tx:
        reads = []

        def observe(action, first, second, *_):
            if action == sqlite3.SQLITE_READ:
                reads.append((first, second))
            return sqlite3.SQLITE_OK

        tx.connection.set_authorizer(observe)
        try:
            index = SqlSearchIndex(tx, generation)
            assert index.search(SCALE_ROOT, idle) == search(SCALE_ROOT, rows, idle)
            facet_body = {key: value for key, value in selected.items() if key != "sort"}
            assert index.facet(SCALE_ROOT, facet_body) == facet(SCALE_ROOT, rows, facet_body)
        finally:
            tx.connection.set_authorizer(None)
        assert not any(table == "search_items" for table, _ in reads)


def test_sqlite_index_accepts_more_than_sqlite_join_limit_of_unique_query_terms(tmp_path):
    rows = _corpus()
    store, generation = _index(tmp_path, rows, SCALE_ROOT)
    # 80 unique CJK letter tokens fit comfortably inside the public 512-char
    # limit. The legacy evaluator returns an empty result rather than imposing
    # a hidden clause-count limit.
    query = " ".join(chr(0x4E00 + offset) for offset in range(80))
    assert len(query) < 512
    body = scale_request(query, sort={"field": "RELEVANCE", "direction": "DESC"})
    with store.transaction(write=False) as tx:
        indexed = SqlSearchIndex(tx, generation).search(SCALE_ROOT, body)
    assert indexed == search(SCALE_ROOT, rows, body)


def test_prefix_postings_exclude_same_column_exact_hits_without_changing_scores(tmp_path):
    from wiseway.search import DEMO_SCHEMAS, build_item
    from wiseway.sqlite_search import _encoded_token

    rows = [
        build_item(
            SCALE_ROOT["root_id"],
            SCALE_ROOT["display_prefix"],
            "Archive/Atlas/Orion_2031/Reports/foo-foobar.txt",
            1,
            SCALE_ROOT["indexed_at"],
            DEMO_SCHEMAS[SCALE_ROOT["schema_set_version"]],
            "same-column",
        ),
        build_item(
            SCALE_ROOT["root_id"],
            SCALE_ROOT["display_prefix"],
            "Archive/Atlas/Orion_2031/Reports/foobar.txt",
            1,
            SCALE_ROOT["indexed_at"],
            DEMO_SCHEMAS[SCALE_ROOT["schema_set_version"]],
            "prefix-only",
        ),
    ]
    store, generation = _index(tmp_path, rows, SCALE_ROOT)
    body = scale_request("foo", sort={"field": "RELEVANCE", "direction": "DESC"})
    with store.transaction(write=False) as tx:
        index = SqlSearchIndex(tx, generation)
        _, matches = index._term_cte("term", "foo")
        indexed = index.search(SCALE_ROOT, body)
    assert any(
        isinstance(match, str) and f"{_encoded_token('foo')}* NOT {_encoded_token('foo')}" in match
        for match in matches
    )
    assert indexed == search(SCALE_ROOT, rows, body)


def test_sqlite_top_k_temp_snapshot_keeps_only_ids_and_scores_then_fetches_bounded_bodies(tmp_path):
    rows = _corpus()
    store, generation = _index(tmp_path, rows, SCALE_ROOT)
    body = scale_request("report", sort={"field": "NAME", "direction": "ASC"})
    with store.transaction(write=False) as tx:
        index = SqlSearchIndex(tx, generation)
        with index._materialized_candidates(_parse_query("report"), []) as table:
            columns = [
                row[1] for row in tx.connection.execute("PRAGMA temp.table_info('wiseway_search_candidates')")
            ]
            top_ids = index._top_ids(table, body["sort"], 7)
            assert columns == ["row_id", "score"]
            assert len(top_ids) == 7
        assert [row["item_id"] for row in index._read_bodies(top_ids)] == [
            row["item_id"] for row in search(SCALE_ROOT, rows, body, limit=7)["items"]
        ]


@pytest.mark.parametrize("entrypoint", ("search", "facet"))
def test_sqlite_deadline_interrupts_both_public_entrypoints_and_cleans_up(tmp_path, monkeypatch, entrypoint):
    rows = _corpus()
    store, generation = _index(tmp_path, rows, SCALE_ROOT)
    clock = _FakeClock()
    body = scale_request("report", sort={"field": "NAME", "direction": "ASC"})
    with store.transaction(write=False) as tx:
        index = SqlSearchIndex(tx, generation, clock=clock)
        method_name = "_top_ids" if entrypoint == "search" else "_facet_table"

        def expire(*args, **kwargs):
            clock.now = 31.0
            _force_progress(tx.connection)

        monkeypatch.setattr(index, method_name, expire)
        call = index.search if entrypoint == "search" else index.facet
        payload = (
            body if entrypoint == "search" else {key: value for key, value in body.items() if key != "sort"}
        )
        with pytest.raises(ApiError) as caught:
            call(SCALE_ROOT, payload)
        assert (caught.value.code, caught.value.status, caught.value.retryable) == (
            "SEARCH_UNAVAILABLE",
            503,
            True,
        )
        assert (
            tx.connection.execute(
                "SELECT 1 FROM sqlite_temp_master WHERE type='table' AND name='wiseway_search_candidates'"
            ).fetchone()
            is None
        )
        assert _force_progress(tx.connection) == 50005000


def test_sqlite_deadline_is_removed_after_success_and_api_or_sql_errors(tmp_path, monkeypatch):
    rows = _corpus()
    store, generation = _index(tmp_path, rows, SCALE_ROOT)
    clock = _FakeClock()
    body = scale_request("report", sort={"field": "NAME", "direction": "ASC"})
    with store.transaction(write=False) as tx:
        index = SqlSearchIndex(tx, generation, clock=clock)
        assert index.search(SCALE_ROOT, body) == search(SCALE_ROOT, rows, body)
        clock.now = 31.0
        assert _force_progress(tx.connection) == 50005000

        clock.now = 0.0
        facet_body = {key: value for key, value in body.items() if key != "sort"}
        assert index.facet(SCALE_ROOT, facet_body) == facet(SCALE_ROOT, rows, facet_body)
        clock.now = 31.0
        assert _force_progress(tx.connection) == 50005000

        clock.now = 0.0
        with pytest.raises(ApiError):
            index.search(SCALE_ROOT, {**body, "sort": {"field": "unknown", "direction": "ASC"}})
        clock.now = 31.0
        assert _force_progress(tx.connection) == 50005000

        clock.now = 0.0
        with pytest.raises(ApiError):
            index.facet(SCALE_ROOT, {**facet_body, "selected_marker_ids": ["missing"]})
        clock.now = 31.0
        assert _force_progress(tx.connection) == 50005000

        clock.now = 0.0

        def broken(*args, **kwargs):
            raise sqlite3.OperationalError("forced sqlite failure")

        monkeypatch.setattr(index, "_top_ids", broken)
        with pytest.raises(sqlite3.OperationalError, match="forced sqlite failure"):
            index.search(SCALE_ROOT, body)
        assert (
            tx.connection.execute(
                "SELECT 1 FROM sqlite_temp_master WHERE type='table' AND name='wiseway_search_candidates'"
            ).fetchone()
            is None
        )
        clock.now = 31.0
        assert _force_progress(tx.connection) == 50005000


def test_rare_facet_plan_starts_with_materialized_candidates_then_marker_primary_keys(tmp_path):
    rows = _corpus()
    store, generation = _index(tmp_path, rows, SCALE_ROOT)
    with store.transaction(write=False) as tx:
        index = SqlSearchIndex(tx, generation)
        with index._materialized_candidates(_parse_query("136"), []) as table:
            plan = tx.connection.execute(
                "EXPLAIN QUERY PLAN SELECT m.marker_json,COUNT(*) FROM "
                + table
                + " c CROSS JOIN search_item_markers im "
                "ON im.generation_id=? AND im.row_id=c.row_id AND im.depth=? "
                "CROSS JOIN search_markers m ON m.generation_id=im.generation_id AND m.marker_id=im.marker_id "
                "GROUP BY m.marker_id",
                (generation, 0),
            ).fetchall()
    details = [row[3] for row in plan]
    assert details[:3] == [
        "SCAN c",
        "SEARCH im USING PRIMARY KEY (generation_id=? AND row_id=? AND depth=?)",
        "SEARCH m USING PRIMARY KEY (generation_id=? AND marker_id=?)",
    ]
