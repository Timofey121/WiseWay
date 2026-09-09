from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from wiseway.search import DEMO_SCHEMAS, build_item, search

BACKEND = Path(__file__).parents[1]


def test_adversarial_glob_failure_finishes_within_two_seconds() -> None:
    script = """
from wiseway.rules import match_rule

rule = {"mask": "*a" * 20 + "b", "match_field": "BASENAME"}
print(match_rule(rule, "a" * 40))
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=BACKEND,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=2)
        completed = True
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        completed = False

    assert completed, "matching an adversarial glob timed out"
    assert process.returncode == 0, stderr
    assert stdout.strip() == "False"


def test_search_sorts_superscript_filename_without_numeric_conversion_error() -> None:
    root = {
        "root_id": "root-demo-1",
        "display_prefix": "DEMO:/SandboxRoot",
        "schema_set_version": "schema-demo-1",
        "index_generation": "generation-1",
        "indexed_at": "2026-01-01T00:00:00Z",
    }
    value = build_item(
        root["root_id"],
        root["display_prefix"],
        "Archive/Atlas/Orion_2031/Reports/²",
        0,
        root["indexed_at"],
        DEMO_SCHEMAS[root["schema_set_version"]],
        "item-1",
    )
    request = {
        "request_state_id": "state-1",
        "root_id": root["root_id"],
        "schema_set_version": root["schema_set_version"],
        "selected_marker_ids": [],
        "query_text": "²",
        "sort": {"field": "NAME", "direction": "ASC"},
        "facet_prefix": "",
    }

    assert search(root, [value], request)["total"] == 1
