import random

import pytest

from test_search import ROOT, item, request
from wiseway.search import facet, search
from wiseway.search_index import SearchIndex


def corpus(count=301):
    rows = [
        item(f"item-{number}", f"Archive/Atlas/Orion_2031/Reports/Документ-{number % 31}-{number}.pdf")
        for number in range(count)
    ]
    for number, row in enumerate(rows):
        row["size_bytes"] = number % 7
        row["modified_at"] = f"2026-01-{number % 9 + 1:02d}T00:00:00Z"
    random.Random(42).shuffle(rows)
    return rows


@pytest.mark.parametrize(
    "field,direction",
    [(field, direction) for field in ("PATH", "NAME", "MODIFIED_AT", "SIZE") for direction in ("ASC", "DESC")]
    + [("RELEVANCE", "DESC")],
)
@pytest.mark.parametrize("limit", [1, 7, 100])
def test_prepared_top_k_preserves_complete_order_counts_and_facets(field, direction, limit):
    rows = corpus()
    prepared = SearchIndex(rows)
    body = request("док", sort={"field": field, "direction": direction})
    expected = search(ROOT, rows, body, limit=limit)
    assert search(ROOT, rows, body, limit=limit, prepared=prepared) == expected
    assert search(ROOT, rows, body, limit=limit, prepared=prepared) == expected


@pytest.mark.parametrize("query", ["999999", "nonexistent", '"rare 999999"', ""])
def test_selective_or_idle_prepared_query_does_not_enumerate_the_root(query):
    rows = corpus()
    rows.append(item("rare", "Archive/Atlas/Orion_2031/Reports/rare-999999.pdf"))
    prepared = SearchIndex(rows)
    body = request(query)
    expected = search(ROOT, rows, body)

    class NoIteration(list):
        def __iter__(self):
            raise AssertionError("A selective or idle query scanned the whole root")

    prepared._chains[()] = NoIteration(prepared._chains[()])
    assert search(ROOT, rows, body, prepared=prepared) == expected
    if not query:
        assert facet(ROOT, rows, body, prepared=prepared) == facet(ROOT, rows, body)


def test_warm_broad_query_reuses_natural_order(monkeypatch):
    import wiseway.search as search_module

    rows = corpus()
    prepared = SearchIndex(rows)
    body = request("док")
    expected = search(ROOT, rows, body, prepared=prepared)
    calls = []
    original = search_module._path_tie

    def count(row):
        calls.append(row["item_id"])
        return original(row)

    monkeypatch.setattr(search_module, "_path_tie", count)
    assert search(ROOT, rows, body, prepared=prepared) == expected
    assert len(calls) <= len(expected["items"])
