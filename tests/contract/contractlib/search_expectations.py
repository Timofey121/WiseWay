"""LT-03.1b literal search/facet/auth/error expectations over the LT-03.1a corpus.

``fixtures/synthetic/search_expectations.json`` stores the finite, hand-authored
oracle data:

* ``search_scenarios`` - a ``SearchRequest`` plus the *literal* ordered result
  ``item_ids``, ``total``, ``returned_count``, ``result_limit``, ``limited`` and
  the next ``Facet`` options (marker id + exact count);
* ``facet_scenarios`` - a ``FacetRequest`` plus the literal ``Facet`` options;
* ``auth_scenarios`` / ``error_scenarios`` - exact HTTP status + ``error.code``
  pairs and their literal ``ErrorResponse`` payloads;
* ``race_scenarios`` - scripted ``request_state_id`` last-write-wins sequences;
* ``lifecycle_scenarios`` - create/change/rename/move/delete index expectations;
* ``format_samples`` - Q-042 UI formatting literals (bytes/date/display path).

This module is a *materializer*, not a search implementation.  Given the literal
``item_ids`` it looks up the already-materialized ``SearchItem`` payloads from
the corpus and assembles a schema-shaped response.  It never computes result
membership, ranking, facet counts or totals: every count and every id below is
data.  ``reason`` on each scenario is the manual trace that lets a reviewer
verify membership/order against the corpus.

A documented preparation command regenerates the committed public examples:

    python tests/contract/contractlib/search_expectations.py --write-examples
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # package import (tests, verify_contract.py)
    from . import synthetic
    from .expectations import EXPECTED_OPERATIONS, HTTP_ERROR_CODES
    from .loading import load_contract, resolve_pointer
except ImportError:  # pragma: no cover - documented direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from contractlib import synthetic  # type: ignore
    from contractlib.expectations import EXPECTED_OPERATIONS, HTTP_ERROR_CODES  # type: ignore
    from contractlib.loading import load_contract, resolve_pointer  # type: ignore

EXPECTATIONS_RELATIVE = Path("fixtures") / "synthetic" / "search_expectations.json"
SEARCH_SCHEMA = "#/components/schemas/SearchResponse"
FACET_SCHEMA = "#/components/schemas/FacetResponse"
ERROR_SCHEMA = "#/components/schemas/ErrorResponse"
SEARCH_ITEM = "#/components/schemas/SearchItem"
KNOWN_Q = [f"Q-{index:03d}" for index in range(1, 15)] + ["Q-042", "Q-043"]
KNOWN_OPERATIONS = set(EXPECTED_OPERATIONS.values())
KNOWN_ERROR_CODES = {code for codes in HTTP_ERROR_CODES.values() for code in codes}
DATE_PATTERN = re.compile(r"^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}$")

# (example id, kind, scenario id, canonical schema, output file, description).
EXAMPLE_BINDINGS: List[Dict[str, str]] = [
    {
        "id": "search-idle-atlas",
        "kind": "search",
        "scenario_id": "SRCH-Q004-IDLE-ATLAS",
        "schema": SEARCH_SCHEMA,
        "file": "contracts/examples/search/search-idle-atlas.json",
        "description": "IDLE SearchResponse for root-demo-atlas with the first level-section facet.",
    },
    {
        "id": "search-results-n10-limited",
        "kind": "search",
        "scenario_id": "SRCH-Q013-N10",
        "schema": SEARCH_SCHEMA,
        "file": "contracts/examples/search/search-results-n10-limited.json",
        "description": "RESULTS SearchResponse with total=13 > result_limit=10 and limited=true.",
    },
    {
        "id": "search-results-met-ranking",
        "kind": "search",
        "scenario_id": "SRCH-Q009-RANKING",
        "schema": SEARCH_SCHEMA,
        "file": "contracts/examples/search/search-results-met-ranking.json",
        "description": "RELEVANCE DESC result for token met with the manual score order 10/5/2.",
    },
    {
        "id": "search-results-and-markers",
        "kind": "search",
        "scenario_id": "SRCH-Q007-MARKER-AND",
        "schema": SEARCH_SCHEMA,
        "file": "contracts/examples/search/search-results-and-markers.json",
        "description": "RESULTS SearchResponse for a marker chain AND text; terminal next_facet=null.",
    },
    {
        "id": "facet-nova-orion-north",
        "kind": "facet",
        "scenario_id": "FACET-Q006-NOVA-ORION-NORTH",
        "schema": FACET_SCHEMA,
        "file": "contracts/examples/search/facet-nova-orion-north.json",
        "description": "FacetResponse reopening level-category under Archive/Nova/Orion_2031/North.",
    },
    {
        "id": "error-unauthenticated",
        "kind": "error",
        "scenario_id": "AUTH-Q001-UNAUTHENTICATED",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-unauthenticated.json",
        "description": "401 UNAUTHENTICATED for a protected operation without a session.",
    },
    {
        "id": "error-login-failed",
        "kind": "error",
        "scenario_id": "AUTH-Q001-LOGIN-FAILED",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-login-failed.json",
        "description": "401 LOGIN_FAILED for a wrong login/password.",
    },
    {
        "id": "error-search-unavailable",
        "kind": "error",
        "scenario_id": "AUTH-Q003-SEARCH-503",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-search-unavailable.json",
        "description": "503 SEARCH_UNAVAILABLE; the previous result is stale, never a false success.",
    },
    {
        "id": "error-internal-error",
        "kind": "error",
        "scenario_id": "AUTH-Q003-INTERNAL-500",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-internal-error.json",
        "description": "500 INTERNAL_ERROR without technical details, request_id for triage.",
    },
    {
        "id": "error-invalid-query",
        "kind": "error",
        "scenario_id": "SRCH-Q010-INVALID-QUOTE",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-invalid-query.json",
        "description": "400 INVALID_QUERY for an unclosed quote.",
    },
    {
        "id": "error-validation-error",
        "kind": "error",
        "scenario_id": "SRCH-Q010-LENGTH",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-validation-error.json",
        "description": "422 VALIDATION_ERROR with a safe field_errors entry for an over-long query.",
    },
    {
        "id": "error-invalid-marker-selection",
        "kind": "error",
        "scenario_id": "SRCH-Q010-INVALID-MARKER",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-invalid-marker-selection.json",
        "description": "422 INVALID_MARKER_SELECTION for a stale marker chain.",
    },
    {
        "id": "error-schema-version-changed",
        "kind": "error",
        "scenario_id": "SRCH-Q010-SCHEMA-CHANGED",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-schema-version-changed.json",
        "description": "409 SCHEMA_VERSION_CHANGED after a schema generation change.",
    },
    {
        "id": "error-root-not-ready",
        "kind": "error",
        "scenario_id": "SRCH-Q010-ROOT-NOT-READY",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-root-not-ready.json",
        "description": "409 ROOT_NOT_READY for an unpublished search root.",
    },
    {
        "id": "error-csrf-failed",
        "kind": "error",
        "scenario_id": "CONTRACT-Q043-CSRF",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-csrf-failed.json",
        "description": "403 CSRF_FAILED for an invalid X-CSRF-Token.",
    },
    {
        "id": "error-forbidden",
        "kind": "error",
        "scenario_id": "CONTRACT-Q043-FORBIDDEN",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-forbidden.json",
        "description": "403 FORBIDDEN for a disallowed action.",
    },
    {
        "id": "error-rate-limited",
        "kind": "error",
        "scenario_id": "CONTRACT-Q043-RATE-LIMITED",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-rate-limited.json",
        "description": "429 RATE_LIMITED, retryable=true; the client honors Retry-After.",
    },
]


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

def expectations_path(root: Optional[Path] = None) -> Path:
    return (root or synthetic.repo_root()) / EXPECTATIONS_RELATIVE


def load_expectations(root: Optional[Path] = None) -> Dict[str, Any]:
    return synthetic.load_json(expectations_path(root))


def build_context(root: Optional[Path] = None) -> Dict[str, Any]:
    """Load the corpus, the canonical contract and the lookup tables."""
    base = Path(root) if root is not None else synthetic.repo_root()
    manifest = synthetic.load_manifest(synthetic.manifest_path(base))
    corpus = synthetic.load_corpus(manifest, base)
    materialized = synthetic.materialize(corpus)
    contract = base / "contracts" / "openapi" / "wiseway-v1.yaml"
    return {
        "base": base,
        "manifest": manifest,
        "corpus": corpus,
        "document": load_contract(contract),
        "inventory": {item["item_id"]: item for item in materialized["files"]},
        "catalog": synthetic.marker_index(corpus),
        "lifecycle": synthetic.materialize_lifecycle(corpus),
    }


def allowed_error_codes(document: Dict[str, Any], operation_id: str, status: int) -> set:
    """The ``error.code`` values the canonical response schema declares.

    The check is per-operation (the response actually referenced by the
    operation), not the global HTTP/code table: ``searchFiles`` 403 declares
    only ``FORBIDDEN`` while the mutation 403 declares ``FORBIDDEN`` and
    ``CSRF_FAILED``.
    """
    for (method, path), candidate in EXPECTED_OPERATIONS.items():
        if candidate != operation_id:
            continue
        responses = document.get("paths", {}).get(path, {}).get(method, {}).get("responses", {})
        response = responses.get(str(status))
        if response is None:
            return set()
        if isinstance(response, dict) and set(response.keys()) == {"$ref"}:
            response = resolve_pointer(document, response["$ref"])
        schema = (
            ((response.get("content") or {}).get("application/json") or {}).get("schema")
        )
        return _schema_error_codes(document, schema)
    return set()


def _schema_error_codes(document: Dict[str, Any], schema: Any) -> set:
    codes: set = set()

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if set(node.keys()) == {"$ref"}:
            visit(resolve_pointer(document, node["$ref"]))
            return
        properties = node.get("properties")
        if isinstance(properties, dict):
            error = properties.get("error")
            if isinstance(error, dict) and set(error.keys()) == {"$ref"}:
                error = resolve_pointer(document, error["$ref"])
            code = ((error or {}).get("properties") or {}).get("code")
            if isinstance(code, dict) and isinstance(code.get("enum"), list):
                codes.update(code["enum"])
        for key in ("allOf", "anyOf", "oneOf"):
            for child in node.get(key, []) or []:
                visit(child)

    visit(schema)
    return codes


# --------------------------------------------------------------------------- #
# Materialization from literal ids (no search / ranking / facet computation)
# --------------------------------------------------------------------------- #

def _marker(catalog: Dict[str, Dict[str, Any]], marker_id: str) -> Dict[str, Any]:
    return synthetic.marker_payload(catalog[marker_id])


def _facet(
    catalog: Dict[str, Dict[str, Any]], literal: Dict[str, Any]
) -> Dict[str, Any]:
    options = []
    for option in literal["options"]:
        payload = _marker(catalog, option["marker_id"])
        payload["count"] = option["count"]
        options.append(payload)
    return {
        "level_id": literal["level_id"],
        "level_name": literal["level_name"],
        "options": options,
    }


def materialize_search_response(
    expectations: Dict[str, Any], scenario: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    request = scenario["request"]
    expected = scenario["expected"]
    constants = expectations["constants"]
    root = request["root_id"]
    root_constants = constants["roots"][root]
    next_facet = expected["next_facet"]
    profile = scenario.get("freshness_profile", "CURRENT")
    return {
        "request_state_id": request["request_state_id"],
        "mode": expected["mode"],
        "root_id": root,
        "schema_set_version": root_constants["schema_set_version"],
        "index_generation": root_constants["index_generation"],
        "ranking_profile_version": constants["ranking_profile_version"],
        "applied_query_text": expected["applied_query_text"],
        "selected_markers": [
            _marker(context["catalog"], marker_id)
            for marker_id in request["selected_marker_ids"]
        ],
        "total": expected["total"],
        "returned_count": expected["returned_count"],
        "result_limit": expected["result_limit"],
        "limited": expected["limited"],
        "items": [context["inventory"][item_id] for item_id in expected["item_ids"]],
        "next_facet": None if next_facet is None else _facet(context["catalog"], next_facet),
        "freshness": constants["freshness_profiles"][profile],
    }


def materialize_facet_response(
    expectations: Dict[str, Any], scenario: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    request = scenario["request"]
    expected = scenario["expected"]
    constants = expectations["constants"]
    root = request["root_id"]
    root_constants = constants["roots"][root]
    facet = None
    if expected["facet_level_id"] is not None:
        level_id = expected["facet_level_id"]
        options = []
        for option in expected["options"]:
            payload = _marker(context["catalog"], option["marker_id"])
            payload["count"] = option["count"]
            options.append(payload)
        facet = {
            "level_id": level_id,
            "level_name": constants["level_names"][level_id],
            "options": options,
        }
    return {
        "request_state_id": request["request_state_id"],
        "root_id": root,
        "schema_set_version": root_constants["schema_set_version"],
        "index_generation": root_constants["index_generation"],
        "facet": facet,
    }


def materialize_error_response(scenario: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "error": {
            "code": scenario["code"],
            "message": scenario["message"],
            "request_id": scenario["request_id"],
            "operation_id": scenario["operation_id"],
            "retryable": scenario["retryable"],
            "field_errors": scenario.get("field_errors", []),
        }
    }


# --------------------------------------------------------------------------- #
# Validation (structural / consistency only; never re-derives membership)
# --------------------------------------------------------------------------- #

def _normalized_query(query: str) -> str:
    return " ".join(query.split())


def _chain_valid(selected: List[str], catalog: Dict[str, Dict[str, Any]]) -> bool:
    previous: Optional[Dict[str, Any]] = None
    for marker_id in selected:
        entry = catalog.get(marker_id)
        if entry is None:
            return False
        expected_parents: List[Dict[str, Any]] = []
        if previous is not None:
            expected_parents = previous["parents"] + [
                {"level_id": previous["level_id"], "raw_value": previous["raw_value"]}
            ]
        if entry["parents"] != expected_parents:
            return False
        previous = entry
    return True


def _option_errors(
    label: str,
    level_id: str,
    options: List[Dict[str, Any]],
    catalog: Dict[str, Dict[str, Any]],
) -> List[str]:
    errors: List[str] = []
    seen = set()
    previous_unrecognized = False
    for option in options:
        marker_id = option.get("marker_id")
        entry = catalog.get(marker_id)
        if entry is None:
            errors.append(f"{label}: facet option references unknown marker {marker_id!r}")
            continue
        if entry["level_id"] != level_id:
            errors.append(
                f"{label}: facet option {marker_id!r} level {entry['level_id']!r} "
                f"does not match facet level {level_id!r}"
            )
        count = option.get("count")
        if not isinstance(count, int) or count < 1:
            errors.append(f"{label}: facet option {marker_id!r} count must be >= 1")
        if marker_id in seen:
            errors.append(f"{label}: duplicate facet option {marker_id!r}")
        seen.add(marker_id)
        if entry["kind"] == "UNRECOGNIZED":
            previous_unrecognized = True
        elif previous_unrecognized:
            errors.append(f"{label}: UNRECOGNIZED option {marker_id!r} is not last")
    return errors


def search_scenario_errors(
    scenario: Dict[str, Any], context: Dict[str, Any], constants: Dict[str, Any]
) -> List[str]:
    label = scenario.get("scenario_id", "search")
    errors: List[str] = []
    request = scenario.get("request") or {}
    expected = scenario.get("expected") or {}
    catalog = context["catalog"]
    inventory = context["inventory"]
    root = request.get("root_id")
    if root not in constants["roots"]:
        errors.append(f"{label}: unknown root_id {root!r}")
        return errors
    selected = request.get("selected_marker_ids", [])
    if not _chain_valid(selected, catalog):
        errors.append(f"{label}: selected_marker_ids is not a valid continuous chain")

    item_ids = expected.get("item_ids", [])
    if len(item_ids) != len(set(item_ids)):
        errors.append(f"{label}: item_ids are not unique")
    for item_id in item_ids:
        item = inventory.get(item_id)
        if item is None:
            errors.append(f"{label}: unknown item_id {item_id!r}")
            continue
        if item["location"]["root_id"] != root:
            errors.append(f"{label}: item {item_id!r} belongs to another root")
        for marker in item.get("markers", []):
            if marker.get("kind") != "VALUE":
                errors.append(
                    f"{label}: item {item_id!r} carries non-VALUE marker "
                    f"{marker.get('marker_id')!r}; SearchItem.markers must be "
                    f"recognized VALUE parents only"
                )

    returned = expected.get("returned_count")
    limit = expected.get("result_limit")
    if not isinstance(limit, int) or limit < 1:
        errors.append(f"{label}: result_limit must be a positive integer")
    if returned != len(item_ids):
        errors.append(
            f"{label}: returned_count {returned!r} != len(item_ids) {len(item_ids)}"
        )
    mode = expected.get("mode")
    total = expected.get("total")
    limited = expected.get("limited")
    if mode == "IDLE":
        if total is not None:
            errors.append(f"{label}: IDLE total must be null")
        if item_ids:
            errors.append(f"{label}: IDLE must not return items")
        if limited is not False:
            errors.append(f"{label}: IDLE limited must be false")
        if expected.get("applied_query_text") != "":
            errors.append(f"{label}: IDLE applied_query_text must be empty")
        if selected:
            errors.append(f"{label}: IDLE must not select markers")
        if _normalized_query(request.get("query_text", "")) != "":
            errors.append(f"{label}: IDLE must not carry query text")
    elif mode == "RESULTS":
        if not isinstance(total, int) or total < 0:
            errors.append(f"{label}: RESULTS total must be a non-negative integer")
        else:
            if len(item_ids) > total:
                errors.append(f"{label}: returned items exceed total")
            if limited is not (total > limit):
                errors.append(f"{label}: limited must equal (total > result_limit)")
            if returned != min(total, limit):
                errors.append(
                    f"{label}: returned_count must equal min(total, result_limit)"
                )
            if not limited and total != len(item_ids):
                errors.append(f"{label}: unlimited RESULTS must return all matches")
        if expected.get("applied_query_text") != _normalized_query(
            request.get("query_text", "")
        ):
            errors.append(f"{label}: applied_query_text is not the normalized query")
    else:
        errors.append(f"{label}: unknown mode {mode!r}")

    next_facet = expected.get("next_facet")
    if next_facet is not None:
        level_id = next_facet.get("level_id")
        levels = context["corpus"]["schema"]["roots"][root]["levels"]
        if level_id not in levels:
            errors.append(f"{label}: next_facet level {level_id!r} is not in the root schema")
        errors.extend(_option_errors(f"{label}.next_facet", level_id, next_facet.get("options", []), catalog))

    scores = scenario.get("scores")
    if scores is not None:
        if set(scores) != set(item_ids):
            errors.append(f"{label}: scores keys do not match item_ids")
        if request.get("sort", {}).get("field") == "RELEVANCE":
            values = [scores.get(item_id) for item_id in item_ids]
            if any(
                left is None or right is None or left < right
                for left, right in zip(values, values[1:])
            ):
                errors.append(f"{label}: RELEVANCE order is not non-increasing by score")
    return errors


def facet_scenario_errors(
    scenario: Dict[str, Any], context: Dict[str, Any], constants: Dict[str, Any]
) -> List[str]:
    label = scenario.get("scenario_id", "facet")
    errors: List[str] = []
    request = scenario.get("request") or {}
    expected = scenario.get("expected") or {}
    catalog = context["catalog"]
    root = request.get("root_id")
    if root not in constants["roots"]:
        errors.append(f"{label}: unknown root_id {root!r}")
        return errors
    selected = request.get("selected_marker_ids", [])
    if not _chain_valid(selected, catalog):
        errors.append(f"{label}: selected_marker_ids is not a valid continuous chain")
    levels = context["corpus"]["schema"]["roots"][root]["levels"]
    index = len(selected)
    if expected.get("facet_level_id") is None:
        if expected.get("options"):
            errors.append(f"{label}: null facet must not carry options")
        if index < len(levels):
            errors.append(f"{label}: null facet at non-terminal level {levels[index]!r}")
    else:
        level_id = expected["facet_level_id"]
        if index >= len(levels) or levels[index] != level_id:
            errors.append(
                f"{label}: facet level {level_id!r} is not the next level after the parents"
            )
        errors.extend(_option_errors(label, level_id, expected.get("options", []), catalog))
        errors.extend(
            _unrecognized_source_errors(
                label, expected.get("options", []), expected.get("unrecognized_sources", []),
                context,
            )
        )
    return errors


def _unrecognized_source_errors(
    label: str,
    options: List[Dict[str, Any]],
    sources: List[Dict[str, Any]],
    context: Dict[str, Any],
) -> List[str]:
    """Literal association: a catalog UNRECOGNIZED option -> its first issue file."""
    errors: List[str] = []
    catalog = context["catalog"]
    inventory = context["inventory"]
    unrecognized_options = {
        option["marker_id"]
        for option in options
        if catalog.get(option.get("marker_id"), {}).get("kind") == "UNRECOGNIZED"
    }
    sourced_markers: set = set()
    for source in sources:
        marker_id = source.get("marker_id")
        item_id = source.get("item_id")
        sourced_markers.add(marker_id)
        if marker_id not in unrecognized_options:
            errors.append(
                f"{label}: unrecognized source {marker_id!r} is not an UNRECOGNIZED option"
            )
        entry = catalog.get(marker_id)
        if entry is None or entry.get("kind") != "UNRECOGNIZED":
            errors.append(f"{label}: unrecognized source {marker_id!r} is not a catalog terminal")
            continue
        if source.get("issue_level_id") != entry["level_id"]:
            errors.append(
                f"{label}: unrecognized source {marker_id!r} issue_level_id does not "
                f"match the catalog terminal level"
            )
        item = inventory.get(item_id)
        if item is None:
            errors.append(f"{label}: unrecognized source references unknown item {item_id!r}")
            continue
        if item.get("structure_status") != "UNRECOGNIZED":
            errors.append(f"{label}: source item {item_id!r} is not UNRECOGNIZED")
        issue = item.get("structure_issue") or {}
        if issue.get("code") != source.get("issue_code"):
            errors.append(f"{label}: source item {item_id!r} issue code mismatch")
        if issue.get("level_id") != source.get("issue_level_id"):
            errors.append(f"{label}: source item {item_id!r} first-issue level mismatch")
    for marker_id in unrecognized_options - sourced_markers:
        errors.append(
            f"{label}: UNRECOGNIZED option {marker_id!r} has no literal first-issue source"
        )
    return errors


def _sort_profile_errors(profile: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    """Finite stand-alone tie comparator table (not physical inventory)."""
    label = profile.get("scenario_id", "sort_profile")
    errors: List[str] = []
    if profile.get("kind") != "tie_profile" or not profile.get("standalone"):
        errors.append(f"{label}: sort profile must be an explicit stand-alone tie_profile")
    inputs = profile.get("inputs", [])
    ids = [entry.get("item_id") for entry in inputs]
    if len(ids) < 2 or len(ids) != len(set(ids)):
        errors.append(f"{label}: tie profile needs at least two unique logical item ids")
    keys = set()
    for entry in inputs:
        location = entry.get("location") or {}
        for key in ("root_id", "relative_path", "display_path"):
            if not location.get(key):
                errors.append(f"{label}: logical item {entry.get('item_id')!r} is missing {key!r}")
        if not entry.get("filename"):
            errors.append(f"{label}: logical item {entry.get('item_id')!r} is missing filename")
        keys.add(
            (location.get("display_path"), location.get("relative_path"), entry.get("filename"))
        )
    if len(keys) != 1:
        errors.append(f"{label}: tie profile inputs must share one display sort key")
    expected = profile.get("expected_item_ids", [])
    if sorted(ids) != expected:
        errors.append(
            f"{label}: expected_item_ids must be the input ids ordered by item_id ASC"
        )
    return errors


def _scenario_q_errors(scenario: Dict[str, Any], known_scenarios: set) -> List[str]:
    label = scenario.get("scenario_id", "scenario")
    errors: List[str] = []
    if label in known_scenarios:
        errors.append(f"duplicate scenario_id {label!r}")
    known_scenarios.add(label)
    if not scenario.get("q_ids"):
        errors.append(f"{label}: q_ids must not be empty")
    for q in scenario.get("q_ids", []):
        if q not in KNOWN_Q:
            errors.append(f"{label}: unknown Q id {q!r}")
    if not scenario.get("parameters"):
        errors.append(f"{label}: parameters must not be empty")
    if not scenario.get("reason"):
        errors.append(f"{label}: reason (manual trace) must not be empty")
    return errors


def expectation_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    """Every structural/consistency violation of the LT-03.1b oracle data."""
    errors: List[str] = []
    constants = expectations["constants"]
    manifest = context["manifest"]
    examples = {entry["id"] for entry in manifest.get("examples", [])}
    corpus_version = context["corpus"]["version"]
    if expectations.get("corpus_version") != corpus_version:
        errors.append(
            f"expectations corpus_version {expectations.get('corpus_version')!r} "
            f"does not match corpus {corpus_version!r}"
        )

    known_scenarios: set = set()
    for scenario in expectations.get("search_scenarios", []):
        errors.extend(_scenario_q_errors(scenario, known_scenarios))
        errors.extend(search_scenario_errors(scenario, context, constants))
    for scenario in expectations.get("facet_scenarios", []):
        errors.extend(_scenario_q_errors(scenario, known_scenarios))
        errors.extend(facet_scenario_errors(scenario, context, constants))

    for scenario in expectations.get("auth_scenarios", []):
        errors.extend(_scenario_q_errors(scenario, known_scenarios))
        if scenario.get("operation") not in KNOWN_OPERATIONS:
            errors.append(f"{scenario['scenario_id']}: unknown operationId")
        if scenario.get("status") not in (200, 204):
            errors.append(f"{scenario['scenario_id']}: success status must be 200/204")
        ids = []
        if scenario.get("response_example_id"):
            ids.append(scenario["response_example_id"])
        ids.extend(scenario.get("response_example_ids", []))
        if not ids and scenario.get("status") != 204:
            errors.append(f"{scenario['scenario_id']}: success scenario needs an example id")
        for example_id in ids:
            if example_id not in examples:
                errors.append(
                    f"{scenario['scenario_id']}: unknown response example {example_id!r}"
                )

    for scenario in expectations.get("error_scenarios", []):
        errors.extend(_scenario_q_errors(scenario, known_scenarios))
        label = scenario["scenario_id"]
        if scenario.get("operation") not in KNOWN_OPERATIONS:
            errors.append(f"{label}: unknown operationId")
        status = scenario.get("status")
        code = scenario.get("code")
        allowed = allowed_error_codes(context["document"], scenario.get("operation"), status)
        if code not in KNOWN_ERROR_CODES:
            errors.append(f"{label}: unknown error code {code!r}")
        elif code not in allowed:
            errors.append(
                f"{label}: code {code!r} is not declared by operation "
                f"{scenario.get('operation')!r} for HTTP {status}"
            )
        if not scenario.get("request_id"):
            errors.append(f"{label}: request_id must not be empty")
        if scenario.get("operation_id") is not None and not scenario.get("operation_id"):
            errors.append(f"{label}: operation_id must be null or non-empty")
        if not isinstance(scenario.get("retryable"), bool):
            errors.append(f"{label}: retryable must be boolean")
        if not scenario.get("precondition"):
            errors.append(f"{label}: precondition must not be empty")
        if "request_headers" in scenario and not isinstance(scenario["request_headers"], dict):
            errors.append(f"{label}: request_headers must be an object when present")

    for scenario in expectations.get("race_scenarios", []):
        errors.extend(_scenario_q_errors(scenario, known_scenarios))
        label = scenario["scenario_id"]
        sends = scenario.get("sends", [])
        ids = [send.get("request_state_id") for send in sends]
        if len(ids) != len(set(ids)):
            errors.append(f"{label}: request_state_id values must be unique")
        if scenario.get("accepted") not in ids:
            errors.append(f"{label}: accepted request_state_id is not one of the sends")
        for stale in scenario.get("stale_ignored", []):
            if stale not in ids:
                errors.append(f"{label}: stale_ignored {stale!r} is not one of the sends")
            if stale == scenario.get("accepted"):
                errors.append(f"{label}: accepted id is also marked stale")
        if not scenario.get("dedup_key"):
            errors.append(f"{label}: dedup_key must not be empty")

    for scenario in expectations.get("lifecycle_scenarios", []):
        errors.extend(_scenario_q_errors(scenario, known_scenarios))
        label = scenario["scenario_id"]
        stage = scenario.get("stage")
        if stage not in synthetic.REQUIRED_LIFECYCLE_STAGES:
            errors.append(f"{label}: unknown lifecycle stage {stage!r}")
            continue
        state = context["lifecycle"].get(stage)
        if state is None:
            errors.append(f"{label}: lifecycle stage {stage!r} is missing")
            continue
        if scenario.get("item_id") != state["item_id"]:
            errors.append(f"{label}: item_id does not match the lifecycle fixture")
        before_id = state["before"]["item_id"] if state["before"] else None
        after_id = state["after"]["item_id"] if state["after"] else None
        for item_id in scenario.get("before_match_item_ids", []):
            if item_id != before_id:
                errors.append(f"{label}: before_match_item_ids references a non-before item")
        for item_id in scenario.get("after_match_item_ids", []):
            if item_id != after_id:
                errors.append(f"{label}: after_match_item_ids references a non-after item")
        if stage == "rename":
            before_path = scenario.get("before_path", "")
            after_path = scenario.get("after_path", "")
            if scenario.get("removed_token") not in before_path:
                errors.append(f"{label}: removed_token is not in the before path")
            if scenario.get("added_token") not in after_path:
                errors.append(f"{label}: added_token is not in the after path")
            if before_path == after_path:
                errors.append(f"{label}: rename paths must differ")

    for scenario in expectations.get("format_samples", []):
        errors.extend(_scenario_q_errors(scenario, known_scenarios))
        label = scenario["scenario_id"]
        kind = scenario.get("kind")
        cases = scenario.get("cases", [])
        if not cases:
            errors.append(f"{label}: cases must not be empty")
        if kind == "size":
            for case in cases:
                if not isinstance(case.get("bytes"), int) or case["bytes"] < 0:
                    errors.append(f"{label}: invalid byte value")
                if not case.get("expected"):
                    errors.append(f"{label}: missing expected size string")
        elif kind == "date":
            for case in cases:
                if not str(case.get("instant", "")).endswith("Z"):
                    errors.append(f"{label}: instant must be UTC with Z")
                if not DATE_PATTERN.match(case.get("expected", "")):
                    errors.append(f"{label}: expected date must be DD.MM.YYYY HH:MM")
        elif kind == "display_path":
            for case in cases:
                item = context["inventory"].get(case.get("item_id"))
                if item is None:
                    errors.append(f"{label}: unknown item_id")
                elif case.get("expected_display_path") != item["location"]["display_path"]:
                    errors.append(f"{label}: display_path does not match the corpus item")
        else:
            errors.append(f"{label}: unknown format kind {kind!r}")

    for profile in expectations.get("sort_profiles", []):
        errors.extend(_scenario_q_errors(profile, known_scenarios))
        errors.extend(_sort_profile_errors(profile, context))

    # Coverage: every required Q is mapped to existing scenario ids and the
    # mapping agrees with each scenario's own q_ids.
    coverage = expectations.get("coverage") or {}
    for q in KNOWN_Q:
        if not coverage.get(q):
            errors.append(f"coverage: {q} has no scenario ids")
    for q, scenario_ids in coverage.items():
        if q not in KNOWN_Q:
            errors.append(f"coverage: unknown Q id {q!r}")
        for scenario_id in scenario_ids:
            if scenario_id not in known_scenarios:
                errors.append(f"coverage: {q} references unknown scenario {scenario_id!r}")
    for scenario in (
        expectations.get("search_scenarios", [])
        + expectations.get("facet_scenarios", [])
        + expectations.get("auth_scenarios", [])
        + expectations.get("error_scenarios", [])
        + expectations.get("race_scenarios", [])
        + expectations.get("lifecycle_scenarios", [])
        + expectations.get("format_samples", [])
        + expectations.get("sort_profiles", [])
    ):
        for q in scenario.get("q_ids", []):
            if scenario["scenario_id"] not in coverage.get(q, []):
                errors.append(
                    f"coverage: {q} does not list scenario {scenario['scenario_id']!r}"
                )
    return errors


# --------------------------------------------------------------------------- #
# Generated public examples (documented preparation path)
# --------------------------------------------------------------------------- #

def generated_examples(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    searches = {s["scenario_id"]: s for s in expectations["search_scenarios"]}
    facets = {s["scenario_id"]: s for s in expectations["facet_scenarios"]}
    errors = {s["scenario_id"]: s for s in expectations["error_scenarios"]}
    output: Dict[str, Any] = {}
    for binding in EXAMPLE_BINDINGS:
        kind = binding["kind"]
        if kind == "search":
            output[binding["file"]] = materialize_search_response(
                expectations, searches[binding["scenario_id"]], context
            )
        elif kind == "facet":
            output[binding["file"]] = materialize_facet_response(
                expectations, facets[binding["scenario_id"]], context
            )
        elif kind == "error":
            output[binding["file"]] = materialize_error_response(
                errors[binding["scenario_id"]]
            )
        else:  # pragma: no cover - guarded by the static binding table
            raise ValueError(f"unknown example kind {kind!r}")
    return output


def write_examples(root: Optional[Path] = None) -> List[str]:
    base = Path(root) if root is not None else synthetic.repo_root()
    expectations = load_expectations(base)
    context = build_context(base)
    written = []
    for relative, payload in generated_examples(expectations, context).items():
        target = base / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        written.append(relative)
    return written


def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="LT-03.1b search expectation materializer/preparer."
    )
    parser.add_argument("--write-examples", action="store_true")
    args = parser.parse_args(argv)

    base = synthetic.repo_root()
    expectations = load_expectations(base)
    context = build_context(base)
    errors = expectation_errors(expectations, context)
    if errors:
        for message in errors:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1
    if args.write_examples:
        for relative in write_examples(base):
            print(f"wrote {relative}")
    print(
        f"expectations {expectations['fixture_set']} v{expectations['version']}: "
        f"{len(expectations['search_scenarios'])} search, "
        f"{len(expectations['facet_scenarios'])} facet, "
        f"{len(expectations['error_scenarios'])} error, "
        f"{len(expectations['race_scenarios'])} race, "
        f"{len(expectations['format_samples'])} format scenario(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
