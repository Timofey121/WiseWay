"""Independent equivalence checks for the prepared search snapshot.

These cases intentionally compare the indexed implementation to the original
per-item evaluator, including boundary ties that a top-k selection can expose.
"""

from concurrent.futures import ThreadPoolExecutor
import random

import pytest

from test_search import ROOT, item, request
from wiseway.common import ApiError
from wiseway.search import facet, search
from wiseway.search_index import SearchIndex


def _corpus():
    rows = []
    for number in range(137):
        company = "Atlas" if number % 2 else "Nova"
        project = "Orion_2031" if company == "Atlas" else "Polaris_2030"
        tail = (
            f"{company}/{project}/Reports"
            if company == "Atlas"
            else f"{company}/{project}/{'North' if number % 3 else 'South'}/Reports"
        )
        name = (
            f"Документ {number % 13} Case-{number % 11}.pdf"
            if number % 4
            else f"Report {number % 13} Кейс-{number % 11}.pdf"
        )
        row = item(f"row-{number:03d}", f"Archive/{tail}/{name}")
        # Deliberately create ties in both non-natural primary sort fields.
        row["size_bytes"] = number % 5
        row["modified_at"] = f"2026-02-{number % 3 + 1:02d}T00:00:00Z"
        rows.append(row)
    random.Random(739).shuffle(rows)
    return rows


def _selection(rows, company):
    for row in rows:
        marker_values = [marker["raw_value"] for marker in row["markers"]]
        if marker_values[:2] == ["Archive", company]:
            return [marker["marker_id"] for marker in row["markers"][:2]]
    raise AssertionError("test corpus lacks requested marker chain")


@pytest.mark.parametrize("limit", [1, 2, 7, 47])
def test_prepared_search_matches_legacy_across_mixed_queries_sorts_and_ties(limit):
    rows = _corpus()
    prepared = SearchIndex(rows)
    selections = ([], _selection(rows, "Atlas"), _selection(rows, "Nova"))
    queries = ("report", "док", "case", "10", '"orion 2031"', '"документ 2"', "atlas report")
    orderings = [
        {"field": field, "direction": direction}
        for field in ("PATH", "NAME", "SIZE", "MODIFIED_AT")
        for direction in ("ASC", "DESC")
    ] + [{"field": "RELEVANCE", "direction": "DESC"}]

    for selected in selections:
        for query in queries:
            for ordering in orderings:
                body = request(query, selected, sort=ordering, facet_prefix="r")
                assert search(ROOT, rows, body, limit=limit, prepared=prepared) == search(
                    ROOT, rows, body, limit=limit
                )
                facet_body = {key: value for key, value in body.items() if key != "sort"}
                assert facet(ROOT, rows, facet_body, prepared=prepared) == facet(ROOT, rows, facet_body)


def test_prepared_search_matches_legacy_errors_and_is_safe_for_concurrent_reads():
    rows = _corpus()
    prepared = SearchIndex(rows)
    requests = [
        request("report", sort={"field": "SIZE", "direction": "DESC"}),
        request('"документ 2"', _selection(rows, "Atlas")),
        request("10", _selection(rows, "Nova"), sort={"field": "NAME", "direction": "ASC"}),
    ]
    expected = [search(ROOT, rows, body) for body in requests]

    def read(number):
        return search(ROOT, rows, requests[number % len(requests)], prepared=prepared)

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(read, range(64))) == [expected[number % len(expected)] for number in range(64)]

    invalid = request("report", ["unknown-marker"])
    for indexed in (False, True):
        with pytest.raises(ApiError) as caught:
            search(ROOT, rows, invalid, prepared=prepared if indexed else None)
        assert (caught.value.code, caught.value.status) == ("INVALID_MARKER_SELECTION", 422)
