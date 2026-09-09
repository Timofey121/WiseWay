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
        "stress-atlas-0000",
        "stress-nova-0001",
        "stress-atlas-0002",
    ]
    assert [body["query_text"] for body in second_searches] == [
        "stress-atlas-0006",
        "stress-nova-0007",
        "stress-atlas-0008",
    ]
    assert all(body["request_state_id"].startswith("stress-") for body in first_searches + second_searches)
    assert all(body["actor_id"] == "actor-one" for operation, body in first if operation == "audit_query")
    assert all(body["actor_id"] == "actor-two" for operation, body in second if operation == "audit_query")
