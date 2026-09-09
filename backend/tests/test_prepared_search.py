import pytest

from test_search_golden import ROOT, build_items, golden, request
from wiseway.search import facet, search
from wiseway.search_index import SearchIndex


@pytest.mark.parametrize("case", golden()["cases"], ids=lambda case: case["id"])
def test_prepared_index_preserves_independent_golden_order(case):
    items = build_items(golden())
    rows = [items[item_id] for item_id in case["items"]]
    prepared = SearchIndex(rows)
    for query in case.get("queries") or [case["query"]]:
        body = {**request(case, items), "query_text": query}
        result = search(ROOT, rows, body, prepared=prepared)
        assert [row["item_id"] for row in result["items"]] == case["expected_ids"]
        # The independent fixture covers ID/order; compare the remaining wire
        # fields to keep both execution paths on the same API semantics.
        assert result == search(ROOT, rows, body)
        facet_body = {key: value for key, value in body.items() if key != "sort"}
        assert facet(ROOT, rows, facet_body, prepared=prepared) == facet(ROOT, rows, facet_body)


def test_prepared_snapshot_is_bound_to_its_items_and_handles_idle_zero_and_invalid_chain():
    from wiseway.common import ApiError
    from test_search import item, request as basic_request

    rows = [item("one", "Archive/Atlas/Orion_2031/Reports/One.pdf")]
    prepared = SearchIndex(rows)
    for query in ("", "absent", "one"):
        body = {**basic_request(query), "root_id": ROOT["root_id"]}
        assert search(ROOT, rows, body, prepared=prepared) == search(ROOT, rows, body)
    with pytest.raises(ApiError, match="маркер"):
        search(ROOT, rows, {**body, "selected_marker_ids": ["unknown"]}, prepared=prepared)
    with pytest.raises(ValueError):
        search(ROOT, list(rows), body, prepared=prepared)
