"""Unit checks for the deterministic stress-benchmark workload construction."""

from __future__ import annotations

import importlib.util
from pathlib import Path


BENCHMARK = Path(__file__).parents[1] / "benchmarks" / "stress.py"
SPEC = importlib.util.spec_from_file_location("wiseway_stress_benchmark", BENCHMARK)
assert SPEC and SPEC.loader
stress = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stress)


def test_cli_defaults_preserve_the_original_single_account_single_round_workload():
    options = stress.parse_arguments([])

    assert options.accounts == 1
    assert options.rounds == 1
    assert options.varied_queries is False


def test_default_payloads_remain_the_original_five_request_mix():
    requests = stress.payloads("actor-one")

    assert [operation for operation, _ in requests] == [
        "typical_search",
        "broad_search",
        "queue_query",
        "audit_query",
        "typical_search",
    ]
    searches = [body for operation, body in requests if operation.endswith("search")]
    assert [(body["request_state_id"], body["query_text"]) for body in searches] == [
        ("stress-typical-a", "stress atlas"),
        ("stress-broad", "stress"),
        ("stress-typical-b", "stress nova"),
    ]


def test_varied_payloads_use_distinct_exact_corpus_tokens_and_request_state_ids():
    first = stress.payloads("actor-one", client_number=0, round_number=0, varied_queries=True)
    second = stress.payloads("actor-two", client_number=1, round_number=0, varied_queries=True)

    first_searches = [body for operation, body in first if operation.endswith("search")]
    second_searches = [body for operation, body in second if operation.endswith("search")]
    request_ids = [body["request_state_id"] for body in first_searches + second_searches]
    assert len(request_ids) == len(set(request_ids))
    assert [body["query_text"] for body in first_searches] == [
        '"stress-atlas-0001"',
        "stress",
        '"stress-nova-0000"',
    ]
    assert [body["query_text"] for body in second_searches] == [
        '"stress-atlas-0003"',
        "stress",
        '"stress-nova-0002"',
    ]
    assert all(body["request_state_id"].startswith("stress-") for body in first_searches + second_searches)
    assert all(body["actor_id"] == "actor-one" for operation, body in first if operation == "audit_query")
    assert all(body["actor_id"] == "actor-two" for operation, body in second if operation == "audit_query")


def test_varied_queries_hit_real_files_and_keep_broad_search_broad(client):
    from test_api import login
    from wiseway.indexer import Indexer

    context = client.app.state.ctx
    stress.add_corpus(context.settings)
    Indexer(context).scan()
    login(client)
    for client_number, round_number in ((0, 0), (49, 9), (15, 20), (49, 70)):
        for operation, request in stress.payloads(
            "actor", client_number=client_number, round_number=round_number, varied_queries=True
        ):
            if not operation.endswith("search"):
                continue
            response = client.post("/api/v1/search", json=request)
            assert response.status_code == 200
            result = response.json()
            assert result["total"] == (stress.CORPUS_FILES if operation == "broad_search" else 1)
            if operation == "typical_search":
                assert Path(result["items"][0]["filename"]).stem == request["query_text"].strip('"')


def test_benchmark_rejects_consistent_but_incorrect_zero_result():
    request = stress.payloads("actor")[0][1]
    body = {
        "items": [],
        "total": 0,
        "returned_count": 0,
        "limited": False,
        "request_state_id": request["request_state_id"],
    }
    assert stress.response_error("typical_search", body, request=request)
