"""Hand-authored search expectations derived from contracts/semantics.md."""

import json
from pathlib import Path

import pytest

from wiseway.search import DEMO_SCHEMAS, build_item, search


ROOT = {
    "root_id": "golden-root",
    "label": "Golden archive",
    "display_prefix": "DEMO:/Golden",
    "schema_set_version": "schema-demo-1",
    "index_generation": "golden-generation",
    "indexed_at": "2026-01-01T00:00:00Z",
}


def golden():
    return json.loads((Path(__file__).parent / "fixtures" / "search_golden.json").read_text(encoding="utf-8"))


def build_items(corpus):
    return {
        entry["id"]: build_item(
            ROOT["root_id"],
            ROOT["display_prefix"],
            entry["path"],
            0,
            "2026-01-01T00:00:00Z",
            DEMO_SCHEMAS[ROOT["schema_set_version"]],
            entry["id"],
        )
        for entry in corpus["items"]
    }


def request(case, items):
    selected = []
    if "marker_source" in case:
        selected = [
            items[case["marker_source"]]["markers"][index]["marker_id"] for index in case["marker_indexes"]
        ]
    return {
        "request_state_id": "golden-" + case["id"].replace("_", "-"),
        "root_id": ROOT["root_id"],
        "schema_set_version": ROOT["schema_set_version"],
        "selected_marker_ids": selected,
        "query_text": case.get("query", ""),
        "sort": case.get("sort", {"field": "RELEVANCE", "direction": "DESC"}),
        "facet_prefix": "",
    }


@pytest.mark.parametrize("case", golden()["cases"], ids=lambda case: case["id"])
def test_search_golden_corpus(case):
    items = build_items(golden())
    selected = [items[item_id] for item_id in case["items"]]
    for query in case.get("queries") or [case["query"]]:
        response = search(ROOT, selected, {**request(case, items), "query_text": query})
        assert [item["item_id"] for item in response["items"]] == case["expected_ids"]


@pytest.mark.parametrize("case", golden()["cases"], ids=lambda case: case["id"])
def test_search_golden_corpus_through_api(client, case):
    from test_api import login

    login(client)
    items = build_items(golden())
    selected = [items[item_id] for item_id in case["items"]]
    with client.app.state.ctx.store.transaction() as tx:
        tx.put("root", ROOT["root_id"], {**ROOT, "_searchable": True})
        tx.put("index", ROOT["root_id"], {"root": ROOT, "items": selected})
    for query in case.get("queries") or [case["query"]]:
        body = {**request(case, items), "query_text": query}
        response = client.post("/api/v1/search", json=body)
        assert response.status_code == 200, response.text
        assert response.json()["request_state_id"] == body["request_state_id"]
        assert [item["item_id"] for item in response.json()["items"]] == case["expected_ids"]
