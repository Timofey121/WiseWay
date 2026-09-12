"""LT-03.3a finite queue / readiness / selection oracle for the WiseWay demo.

``fixtures/synthetic/queue_selections.json`` stores the finite, hand-authored
oracle for the company queue, the readiness observation sequences, the explicit
selection snapshot and the pre-batch ownership/expiry errors that API section 7,
QUEUE-01/02/03/10 and Q-022...026 describe.  It builds on the immutable
``rule_expectations.json`` definitions (the accepted ``rule-set-atlas-published``
identity is preserved for the LT-03.3b preview leaf) and the auth fixture actors.

The module is a *materializer and consistency checker*, not a runtime domain:

* every payload is literal data bound to a canonical OAS schema pointer;
* compact ``{index}`` group ranges only enumerate already-declared members - they
  never filter, rank or select;
* ``matching_count``/``eligible_count``, ``status_counts``, counters, membership,
  readiness transitions and snapshot contents are declared literals that are
  cross-checked against each other.  No matcher, readiness detector, counter or
  selection algorithm is implemented.

A documented preparation command regenerates the committed public examples::

    python tests/contract/contractlib/queue_selections.py --write-examples
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # package import (tests, verify_contract.py)
    from . import rule_expectations, synthetic
    from .expectations import EXPECTED_OPERATIONS
    from .schemas import validate_value
    from .search_expectations import allowed_error_codes
    from .semantic import queue_response_errors, validate_fixture
except ImportError:  # pragma: no cover - documented direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from contractlib import rule_expectations, synthetic  # type: ignore
    from contractlib.expectations import EXPECTED_OPERATIONS  # type: ignore
    from contractlib.schemas import validate_value  # type: ignore
    from contractlib.search_expectations import allowed_error_codes  # type: ignore
    from contractlib.semantic import queue_response_errors, validate_fixture  # type: ignore

EXPECTATIONS_RELATIVE = Path("fixtures") / "synthetic" / "queue_selections.json"

QUEUE_RESPONSE_SCHEMA = "#/components/schemas/QueueResponse"
QUEUE_ITEM_SCHEMA = "#/components/schemas/QueueItem"
SELECTION_REQUEST_SCHEMA = "#/components/schemas/SelectionRequest"
SELECTION_SNAPSHOT_SCHEMA = "#/components/schemas/SelectionSnapshot"
ERROR_SCHEMA = "#/components/schemas/ErrorResponse"

KNOWN_Q = ("Q-022", "Q-023", "Q-024", "Q-025", "Q-026")
KNOWN_OPERATIONS = set(EXPECTED_OPERATIONS.values())

SELECTABLE_STATES = ("READY", "REQUIRES_DECISION")

_INDEX_RE = re.compile(r"\{index(?::0?(\d+)d)?\}")


# --------------------------------------------------------------------------- #
# Loading and group expansion
# --------------------------------------------------------------------------- #

def expectations_path(root: Optional[Path] = None) -> Path:
    return (root or synthetic.repo_root()) / EXPECTATIONS_RELATIVE


def load_expectations(root: Optional[Path] = None) -> Dict[str, Any]:
    return synthetic.load_json(expectations_path(root))


def _format_index(template: str, index: int) -> str:
    def replace(match: "re.Match[str]") -> str:
        width = match.group(1)
        return f"{index:0{int(width)}d}" if width else str(index)

    return _INDEX_RE.sub(replace, template)


def _expand(value: Any) -> Any:
    """Expand the documented ``{"$repeat_items": {...}}`` literal placeholder."""
    if isinstance(value, dict):
        if set(value.keys()) == {"$repeat_items"}:
            spec = value["$repeat_items"]
            return [
                {
                    "item_id": f"{spec['item_prefix']}{index:04d}",
                    "item_revision": spec["item_revision"],
                }
                for index in range(spec["index_start"], spec["index_end"] + 1)
            ]
        return {key: _expand(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_expand(child) for child in value]
    return value


def build_context(
    root: Optional[Path] = None, expectations: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Load the contract, actors and the literal lookup tables."""
    base = Path(root) if root is not None else synthetic.repo_root()
    if expectations is None:
        expectations = load_expectations(base)
    manifest = synthetic.load_manifest(synthetic.manifest_path(base))
    try:
        from .loading import load_contract
    except ImportError:  # pragma: no cover
        from contractlib.loading import load_contract  # type: ignore

    document = load_contract(base / "contracts" / "openapi" / "wiseway-v1.yaml")
    raw_actors = _load_actors(manifest, base)
    actors = {
        alias: raw_actors[user_id]
        for alias, user_id in expectations["actors"].items()
        if user_id in raw_actors
    }
    groups = {
        profile["profile_id"]: {group["group"]: group for group in profile["groups"]}
        for profile in expectations["profiles"]
    }
    profiles = {profile["profile_id"]: profile for profile in expectations["profiles"]}
    queries = {
        profile["profile_id"]: {
            query["query_id"]: query for query in profile["queries"]
        }
        for profile in expectations["profiles"]
    }
    rule_exp = rule_expectations.load_expectations(base)
    reference_rule_set = next(
        (
            rule_set
            for rule_set in rule_exp["rule_sets"]
            if rule_set["rule_set_id"] == expectations["rule_set"]["rule_set_id"]
        ),
        None,
    )
    return {
        "base": base,
        "manifest": manifest,
        "document": document,
        "expectations": expectations,
        "actors": actors,
        "companies": expectations["companies"],
        "rule_set": expectations["rule_set"],
        "reference_rule_set": reference_rule_set,
        "groups": groups,
        "profiles": profiles,
        "queries": queries,
        "scenarios": {
            scenario["scenario_id"]: scenario
            for scenario in expectations["selection_scenarios"]
        },
        "errors": {
            entry["error_id"]: entry for entry in expectations["selection_errors"]
        },
        "ownership": {
            entry["scenario_id"]: entry for entry in expectations["ownership"]
        },
        "sequences": {
            entry["sequence_id"]: entry for entry in expectations["sequences"]
        },
        "readiness": {
            entry["item_id"]: entry for entry in expectations["readiness"]["items"]
        },
    }


def _load_actors(manifest: Dict[str, Any], base: Path) -> Dict[str, Dict[str, Any]]:
    actors: Dict[str, Dict[str, Any]] = {}
    for entry in manifest.get("examples", []):
        if not entry.get("id", "").startswith("auth-actor"):
            continue
        payload = synthetic.load_json(base / entry["file"])
        actors[payload["user_id"]] = payload
    return actors


# --------------------------------------------------------------------------- #
# Materialization (literal ids only, never a selection algorithm)
# --------------------------------------------------------------------------- #

def materialize_members(
    spec: Dict[str, Any], groups: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Expand a compact member spec into explicit ``{item_id, item_revision}``."""
    members: List[Dict[str, Any]] = []
    for reference in spec.get("groups", []):
        group = groups[reference["group"]]
        start = reference.get("index_start", group["index_start"])
        end = reference.get("index_end", group["index_end"])
        for index in range(start, end + 1):
            members.append(
                {
                    "item_id": _format_index(group["id_template"], index),
                    "item_revision": group["item_revision"],
                }
            )
    for explicit in spec.get("explicit", []):
        members.append(
            {"item_id": explicit["item_id"], "item_revision": explicit["item_revision"]}
        )
    return members


def materialize_item(
    group: Dict[str, Any], company: Dict[str, Any], index: int
) -> Dict[str, Any]:
    attempt = group.get("active_attempt_id")
    if attempt is not None:
        attempt = _format_index(attempt, index)
    return {
        "item_id": _format_index(group["id_template"], index),
        "item_revision": group["item_revision"],
        "company_id": company["company_id"],
        "incoming_source_id": company["incoming_source_id"],
        "source_name": group["source_name"],
        "source": {
            "root_id": company["root_id"],
            "relative_path": _format_index(group["relative_path_template"], index),
            "display_path": _format_index(group["display_path_template"], index),
        },
        "filename": _format_index(group["filename_template"], index),
        "size_bytes": group["size_bytes"],
        "modified_at": group["modified_at"],
        "status": group["status"],
        "reason_code": group.get("reason_code"),
        "selectable": group["selectable"],
        "active_attempt_id": attempt,
    }


def materialize_membership(
    profile: Dict[str, Any], context: Dict[str, Any]
) -> List[Dict[str, Any]]:
    company = context["companies"][profile["company"]]
    items: List[Dict[str, Any]] = []
    for group in profile["groups"]:
        for index in range(group["index_start"], group["index_end"] + 1):
            items.append(materialize_item(group, company, index))
    return items


def materialize_queue_response(
    profile: Dict[str, Any], query: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    groups = context["groups"][profile["profile_id"]]
    membership = {
        item["item_id"]: item for item in materialize_membership(profile, context)
    }
    page = materialize_members(query["page_ids"], groups)
    return {
        "queue_generation": profile["queue_generation"],
        "items": [membership[member["item_id"]] for member in page],
        "matching_count": query["matching_count"],
        "eligible_count": query["eligible_count"],
        "counters": dict(profile["counters"]),
        "status_counts": [dict(entry) for entry in profile["status_counts"]],
        "next_cursor": query.get("next_cursor"),
    }


def materialize_selection_request(
    scenario: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    return _expand(copy.deepcopy(scenario["request"]))


def materialize_selection_snapshot(
    scenario: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    return dict(scenario["expected"])


def materialize_selection_members(
    scenario: Dict[str, Any], context: Dict[str, Any]
) -> List[Dict[str, Any]]:
    profile = context["profiles"][scenario["profile_id"]]
    return materialize_members(scenario["members"], context["groups"][profile["profile_id"]])


def materialize_error(entry: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "error": {
            "code": entry["code"],
            "message": entry["message"],
            "request_id": entry["request_id"],
            "operation_id": entry.get("operation_id"),
            "retryable": entry.get("retryable", False),
            "field_errors": entry.get("field_errors", []),
        }
    }


def materialize_invalid_request(entry: Dict[str, Any]) -> Any:
    return _expand(copy.deepcopy(entry["value"]))


# --------------------------------------------------------------------------- #
# Validators (literal cross-checks, no domain algorithm)
# --------------------------------------------------------------------------- #

def _stability_map(
    profile: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, bool]:
    """Explicit per-item source stability declared by the bundle groups.

    Stability is *not* a QueueItem DTO field (the schema is closed), so it is
    carried only by the fixture group metadata and never materialized into the
    payload.  The membership validator must use this declared metadata instead
    of inferring stability from ``status`` alone.
    """
    stability: Dict[str, bool] = {}
    for group in profile["groups"]:
        stable = group.get("stable")
        if not isinstance(stable, bool):
            continue
        for index in range(group["index_start"], group["index_end"] + 1):
            stability[_format_index(group["id_template"], index)] = stable
    return stability


def membership_errors(profile: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = profile["profile_id"]
    for group in profile["groups"]:
        if not isinstance(group.get("stable"), bool):
            errors.append(
                f"{label}: group {group['group']} must declare explicit stable metadata"
            )
    items = materialize_membership(profile, context)
    by_id: Dict[str, Dict[str, Any]] = {}
    for item in items:
        if item["item_id"] in by_id:
            errors.append(f"{label}: duplicate item_id {item['item_id']}")
        by_id[item["item_id"]] = item
    by_status: Dict[str, int] = {}
    for item in by_id.values():
        by_status[item["status"]] = by_status.get(item["status"], 0) + 1
    declared = {entry["status"]: entry["count"] for entry in profile["status_counts"]}
    if len(declared) != len(profile["status_counts"]):
        errors.append(f"{label}: duplicate status in status_counts")
    if declared != by_status:
        errors.append(
            f"{label}: status_counts {declared} != materialized membership {by_status}"
        )
    for state in profile["required_states"]:
        if state not in declared:
            errors.append(f"{label}: required state {state} missing from status_counts")
    stability = _stability_map(profile, context)
    for item in by_id.values():
        expected = (
            item["status"] in SELECTABLE_STATES
            and stability.get(item["item_id"], False)
            and item["active_attempt_id"] is None
        )
        if item["selectable"] != expected:
            errors.append(
                f"{label}: item {item['item_id']} selectable={item['selectable']} "
                f"but status={item['status']} stable={stability.get(item['item_id'])} "
                f"active_attempt_id={item['active_attempt_id']}"
            )
    return errors


def profile_errors(profile: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = list(membership_errors(profile, context))
    label = profile["profile_id"]
    groups = context["groups"][label]
    membership = {
        item["item_id"]: item for item in materialize_membership(profile, context)
    }
    counters = profile["counters"]
    declared = {entry["status"]: entry["count"] for entry in profile["status_counts"]}
    expected_counters = {
        "ready": declared.get("READY", 0),
        "processing": declared.get("PROCESSING", 0),
        "attention": declared.get("REQUIRES_DECISION", 0)
        + declared.get("RECOVERY_REQUIRED", 0),
    }
    if counters != expected_counters:
        errors.append(f"{label}: counters {counters} != {expected_counters}")

    for query in profile["queries"]:
        qlabel = f"{label}/{query['query_id']}"
        matching = materialize_members(query["matching_ids"], groups)
        eligible = materialize_members(query["eligible_ids"], groups)
        page = materialize_members(query["page_ids"], groups)
        matching_ids = [member["item_id"] for member in matching]
        eligible_ids = [member["item_id"] for member in eligible]
        page_ids = [member["item_id"] for member in page]
        if len(matching_ids) != query["matching_count"]:
            errors.append(
                f"{qlabel}: matching_count {query['matching_count']} != declared ids "
                f"{len(matching_ids)}"
            )
        if len(eligible_ids) != query["eligible_count"]:
            errors.append(
                f"{qlabel}: eligible_count {query['eligible_count']} != declared ids "
                f"{len(eligible_ids)}"
            )
        for item_id in matching_ids + page_ids:
            if item_id not in membership:
                errors.append(f"{qlabel}: id {item_id} is not in the company membership")
        matching_set = set(matching_ids)
        if not set(eligible_ids) <= matching_set:
            errors.append(f"{qlabel}: eligible ids are not a subset of matching ids")
        if not set(page_ids) <= matching_set:
            errors.append(f"{qlabel}: page ids are not a subset of matching ids")
        for item_id in eligible_ids:
            item = membership.get(item_id)
            if item is not None and not item["selectable"]:
                errors.append(f"{qlabel}: eligible id {item_id} is not selectable")
        if len(page_ids) > query["limit"]:
            errors.append(f"{qlabel}: page size {len(page_ids)} exceeds limit {query['limit']}")
        if query["matching_count"] > query["limit"] and len(page_ids) != query["limit"]:
            errors.append(
                f"{qlabel}: matching_count {query['matching_count']} > limit "
                f"{query['limit']} but page has {len(page_ids)} items"
            )
        if query["matching_count"] <= query["limit"] and len(page_ids) != query["matching_count"]:
            errors.append(
                f"{qlabel}: matching_count {query['matching_count']} fits the limit but "
                f"page has {len(page_ids)} items"
            )
        statuses = set(query["filters"]["statuses"])
        if "MISSING" not in statuses:
            for item_id in page_ids + matching_ids:
                item = membership.get(item_id)
                if item is not None and item["status"] == "MISSING":
                    errors.append(
                        f"{qlabel}: MISSING id {item_id} present without an explicit "
                        "MISSING filter"
                    )
        if "MISSING" in statuses and not any(
            membership.get(item_id, {}).get("status") == "MISSING"
            for item_id in matching_ids
        ):
            errors.append(f"{qlabel}: explicit MISSING filter has no MISSING members")
    return errors


def selection_errors(scenario: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = scenario["scenario_id"]
    profile = context["profiles"][scenario["profile_id"]]
    company = context["companies"][profile["company"]]
    request = materialize_selection_request(scenario, context)
    snapshot = materialize_selection_snapshot(scenario, context)
    members = materialize_selection_members(scenario, context)
    membership = {
        item["item_id"]: item for item in materialize_membership(profile, context)
    }

    if request["company_id"] != company["company_id"]:
        errors.append(f"{label}: request company {request['company_id']} != profile company")
    if request["mode"] != scenario["mode"]:
        errors.append(f"{label}: request mode {request['mode']} != {scenario['mode']}")
    if snapshot["company_id"] != request["company_id"]:
        errors.append(f"{label}: snapshot company {snapshot['company_id']} != request company")
    if snapshot["selected_count"] != len(members):
        errors.append(
            f"{label}: selected_count {snapshot['selected_count']} != membership {len(members)}"
        )
    member_ids = [member["item_id"] for member in members]
    if len(member_ids) != len(set(member_ids)):
        errors.append(f"{label}: duplicate explicit members")
    for member in members:
        item = membership.get(member["item_id"])
        if item is None:
            errors.append(f"{label}: member {member['item_id']} is not in the queue profile")
            continue
        if item["item_revision"] != member["item_revision"]:
            errors.append(
                f"{label}: member {member['item_id']} revision {member['item_revision']} "
                f"!= queue revision {item['item_revision']}"
            )
        if item["company_id"] != snapshot["company_id"]:
            errors.append(
                f"{label}: member {member['item_id']} belongs to {item['company_id']}"
            )

    if scenario["mode"] == "EXPLICIT":
        request_items = [
            (item["item_id"], item["item_revision"]) for item in request["items"]
        ]
        member_pairs = [(member["item_id"], member["item_revision"]) for member in members]
        if request_items != member_pairs:
            errors.append(f"{label}: EXPLICIT request items != frozen membership")
    else:
        if request["expected_eligible_count"] != snapshot["selected_count"]:
            errors.append(
                f"{label}: expected_eligible_count {request['expected_eligible_count']} "
                f"!= selected_count {snapshot['selected_count']}"
            )
        matching_query = next(
            (
                query
                for query in profile["queries"]
                if query["filters"] == request["filters"]
            ),
            None,
        )
        if matching_query is None:
            errors.append(f"{label}: no declared queue query matches the ALL_MATCHING filter")
        else:
            eligible = materialize_members(
                matching_query["eligible_ids"], context["groups"][profile["profile_id"]]
            )
            eligible_ids = [member["item_id"] for member in eligible]
            if member_ids != eligible_ids:
                errors.append(
                    f"{label}: frozen membership {member_ids} != declared eligible set"
                )
            if request["expected_eligible_count"] != matching_query["eligible_count"]:
                errors.append(
                    f"{label}: expected_eligible_count {request['expected_eligible_count']} "
                    f"!= queue eligible_count {matching_query['eligible_count']}"
                )

    ttl = _ttl_seconds(snapshot["created_at"], snapshot["expires_at"])
    expected_ttl = context["expectations"]["constants"]["snapshot_ttl_seconds"]
    if ttl != expected_ttl:
        errors.append(f"{label}: TTL {ttl}s != declared {expected_ttl}s")

    for off_page in scenario.get("off_page_item_ids", []):
        if off_page not in member_ids:
            errors.append(f"{label}: declared off-page member {off_page} is missing")
    return errors


def readiness_errors(item: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = item["item_id"]
    observations = item["observations"]
    kind = item["change_kind"]
    if len(observations) < 2:
        errors.append(f"{label}: readiness requires at least two observations")
        return errors
    first, second = observations[-2], observations[-1]
    if kind == "stable":
        if first["size_bytes"] != second["size_bytes"] or first["modified_at"] != second["modified_at"]:
            errors.append(f"{label}: READY requires equal size and mtime")
        if any(observation.get("unfinished") for observation in observations):
            errors.append(f"{label}: READY must not carry an unfinished marker")
        if item.get("claim") is not None:
            errors.append(f"{label}: READY must not carry a claim")
        if _seconds_between(first["observed_at"], second["observed_at"]) < 5:
            errors.append(f"{label}: READY requires observations at least 5 seconds apart")
        if item["expected_status"] != "READY":
            errors.append(f"{label}: stable sequence must declare READY")
        if item["expected_content_revision"] != item["content_revision_before"]:
            errors.append(f"{label}: READY must not change the content revision")
    elif kind in ("changed", "renamed"):
        differs = (
            first["size_bytes"] != second["size_bytes"]
            or first["modified_at"] != second["modified_at"]
            or first.get("filename") != second.get("filename")
        )
        if not differs:
            errors.append(f"{label}: {kind} sequence has no observable difference")
        if item["expected_status"] != "WAITING_READY":
            errors.append(f"{label}: {kind} must return to WAITING_READY")
        if item["expected_content_revision"] <= item["content_revision_before"]:
            errors.append(f"{label}: {kind} must advance the content revision")
    elif kind == "unfinished":
        if not any(observation.get("unfinished") for observation in observations):
            errors.append(f"{label}: unfinished sequence has no unfinished marker")
        if item["expected_status"] != "WAITING_READY":
            errors.append(f"{label}: unfinished sequence must stay WAITING_READY")
    elif kind == "claimed":
        if item.get("claim") is None:
            errors.append(f"{label}: claimed sequence requires a claim")
        if item["expected_status"] != "PROCESSING":
            errors.append(f"{label}: claimed sequence must declare PROCESSING")
        if item["expected_content_revision"] != item["content_revision_before"]:
            errors.append(f"{label}: a claim must not change the content revision")
    else:
        errors.append(f"{label}: unknown change_kind {kind!r}")
    return errors


def ownership_errors(entry: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = entry["scenario_id"]
    if entry["operation"] not in KNOWN_OPERATIONS:
        errors.append(f"{label}: unknown operation {entry['operation']}")
    for key in ("owner", "requesting_actor"):
        actor_id = context["actors"].get(entry[key])
        if actor_id is None:
            errors.append(f"{label}: {key} {entry[key]} does not resolve to an auth fixture actor")
    expected = entry["expected"]
    if expected.get("allowed"):
        if entry["owner"] != entry["requesting_actor"]:
            errors.append(f"{label}: allowed preview requires the same user")
        if expected.get("status") != 201:
            errors.append(f"{label}: allowed preview must expect 201")
    else:
        error_entry = context["errors"].get(entry.get("error_id"))
        if error_entry is None:
            errors.append(f"{label}: rejected scenario has no referenced error")
        else:
            if error_entry["status"] != expected.get("status"):
                errors.append(f"{label}: error status != expected status")
            if error_entry["code"] != expected.get("code"):
                errors.append(f"{label}: error code != expected code")
            if error_entry["operation"] != entry["operation"]:
                errors.append(f"{label}: referenced error is not for {entry['operation']}")
    return errors


def sequence_errors(sequence: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = sequence["sequence_id"]
    scenario = context["scenarios"].get(sequence["selection_scenario_id"])
    if scenario is None:
        errors.append(f"{label}: unknown selection scenario")
        return errors
    snapshot = materialize_selection_snapshot(scenario, context)
    member_ids = {
        member["item_id"] for member in materialize_selection_members(scenario, context)
    }
    for step in sequence["steps"]:
        if step["step"] == "assert_unchanged":
            if step.get("expected_selected_count") != snapshot["selected_count"]:
                errors.append(f"{label}: snapshot changed after the event")
        if step["step"] == "late_arrival" and step.get("late_item_id") in member_ids:
            errors.append(f"{label}: late arrival is already part of the frozen snapshot")
        if step["step"] == "filter_switch" and step.get("membership_rebuilt"):
            errors.append(f"{label}: filter switch must not rebuild the frozen membership")
    if "expected_ttl_seconds" in sequence:
        ttl = _ttl_seconds(snapshot["created_at"], snapshot["expires_at"])
        if ttl != sequence["expected_ttl_seconds"]:
            errors.append(f"{label}: TTL {ttl}s != declared {sequence['expected_ttl_seconds']}s")
    return errors


def rule_set_identity_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    ours = expectations["rule_set"]
    reference = context.get("reference_rule_set")
    if reference is None:
        errors.append("accepted rule-set reference is missing from rule_expectations.json")
        return errors
    if ours["rule_set_id"] != reference["rule_set_id"]:
        errors.append("rule_set_id does not match the accepted LT-03.2b RuleSet")
    if ours["company_id"] != reference["company_id"]:
        errors.append("rule_set company_id does not match the accepted LT-03.2b RuleSet")
    if ours["members"] != reference["members"]:
        errors.append("rule_set members do not match the accepted LT-03.2b RuleSet")
    return errors


def coverage_errors(expectations: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    known_ids = set()
    for profile in expectations["profiles"]:
        known_ids.add(profile["profile_id"])
        known_ids.update(query["query_id"] for query in profile["queries"])
    known_ids.update(
        scenario["scenario_id"] for scenario in expectations["selection_scenarios"]
    )
    known_ids.update(entry["error_id"] for entry in expectations["selection_errors"])
    known_ids.update(entry["scenario_id"] for entry in expectations["ownership"])
    known_ids.update(entry["sequence_id"] for entry in expectations["sequences"])
    known_ids.update(entry["item_id"] for entry in expectations["readiness"]["items"])
    coverage = expectations["coverage"]
    for q_id, references in coverage.items():
        if q_id not in KNOWN_Q:
            errors.append(f"coverage references unknown Q id {q_id}")
        for reference in references:
            if reference not in known_ids:
                errors.append(f"coverage {q_id} references unknown id {reference}")
    for q_id in KNOWN_Q:
        if q_id not in coverage:
            errors.append(f"coverage is missing {q_id}")
    return errors


# --------------------------------------------------------------------------- #
# Generic payload links
# --------------------------------------------------------------------------- #

def build_payloads(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    payloads: Dict[str, Any] = {}
    for profile in expectations["profiles"]:
        groups = context["groups"][profile["profile_id"]]
        payloads[f"membership:{profile['profile_id']}"] = materialize_membership(
            profile, context
        )
        for query in profile["queries"]:
            key = f"{profile['profile_id']}:{query['query_id']}"
            payloads[f"queue:{key}"] = materialize_queue_response(profile, query, context)
            payloads[f"query_eligible:{key}"] = materialize_members(
                query["eligible_ids"], groups
            )
            payloads[f"query_eligible_count:{key}"] = query["eligible_count"]
    for scenario in expectations["selection_scenarios"]:
        scenario_id = scenario["scenario_id"]
        payloads[f"request:{scenario_id}"] = materialize_selection_request(
            scenario, context
        )
        payloads[f"snapshot:{scenario_id}"] = materialize_selection_snapshot(
            scenario, context
        )
        payloads[f"members:{scenario_id}"] = materialize_selection_members(
            scenario, context
        )
    for entry in expectations["selection_errors"]:
        payloads[f"error:{entry['error_id']}"] = materialize_error(entry, context)
        payloads[f"error_meta:{entry['error_id']}"] = entry
    for entry in expectations["ownership"]:
        payloads[f"ownership:{entry['scenario_id']}"] = entry
    payloads["rule_set:queue-selections"] = context["rule_set"]
    if context.get("reference_rule_set") is not None:
        payloads["rule_set:rule_expectations"] = context["reference_rule_set"]
    return payloads


def _resolve_path(value: Any, path: List[Any]) -> Any:
    current = value
    for part in path:
        current = current[part]
    return current


def link_errors(
    expectations: Dict[str, Any],
    context: Dict[str, Any],
    payloads: Optional[Dict[str, Any]] = None,
) -> List[str]:
    errors: List[str] = []
    if payloads is None:
        payloads = build_payloads(expectations, context)
    for link in expectations["links"]:
        label = link["link_id"]
        source = _resolve_path(payloads[link["source"]["payload"]], link["source"]["path"])
        target = _resolve_path(payloads[link["target"]["payload"]], link["target"]["path"])
        relation = link["relation"]
        if relation == "equals" and source != target:
            errors.append(f"{label}: {source!r} != {target!r}")
        elif relation == "not_equals" and source == target:
            errors.append(f"{label}: expected different values, both {source!r}")
        elif relation == "length_equals" and len(source) != target:
            errors.append(f"{label}: length {len(source)} != {target}")
        elif relation == "membership_subset":
            source_ids = {member["item_id"] for member in source}
            target_ids = {member["item_id"] for member in target}
            if not source_ids <= target_ids:
                errors.append(f"{label}: {sorted(source_ids - target_ids)} not in target")
        elif relation == "membership_equals":
            source_ids = [member["item_id"] for member in source]
            target_ids = [member["item_id"] for member in target]
            if source_ids != target_ids:
                errors.append(f"{label}: membership {source_ids} != {target_ids}")
        elif relation not in (
            "equals",
            "not_equals",
            "length_equals",
            "membership_subset",
            "membership_equals",
        ):
            errors.append(f"{label}: unknown relation {relation!r}")
    return errors


# --------------------------------------------------------------------------- #
# Schema classification and negative mutations
# --------------------------------------------------------------------------- #

def payload_errors(
    expectations: Dict[str, Any], context: Dict[str, Any], registry
) -> List[str]:
    errors: List[str] = []
    for profile in expectations["profiles"]:
        for query in profile["queries"]:
            label = f"{profile['profile_id']}/{query['query_id']}"
            payload = materialize_queue_response(profile, query, context)
            schema_errors, semantic = validate_fixture(
                registry, QUEUE_RESPONSE_SCHEMA, payload
            )
            errors.extend(f"{label}: {message}" for message in schema_errors + semantic)
            for item in payload["items"]:
                item_errors, item_semantic = validate_fixture(
                    registry, QUEUE_ITEM_SCHEMA, item
                )
                errors.extend(
                    f"{label}/{item['item_id']}: {message}"
                    for message in item_errors + item_semantic
                )
    for scenario in expectations["selection_scenarios"]:
        label = scenario["scenario_id"]
        request = materialize_selection_request(scenario, context)
        schema_errors, semantic = validate_fixture(
            registry, SELECTION_REQUEST_SCHEMA, request
        )
        errors.extend(f"{label}: {message}" for message in schema_errors + semantic)
        snapshot = materialize_selection_snapshot(scenario, context)
        schema_errors, semantic = validate_fixture(
            registry, SELECTION_SNAPSHOT_SCHEMA, snapshot
        )
        errors.extend(f"{label}: {message}" for message in schema_errors + semantic)
    for entry in expectations["selection_errors"]:
        payload = materialize_error(entry, context)
        schema_errors, semantic = validate_fixture(registry, ERROR_SCHEMA, payload)
        errors.extend(f"{entry['error_id']}: {message}" for message in schema_errors + semantic)
    return errors


def schema_rejection_errors(
    expectations: Dict[str, Any], registry
) -> List[str]:
    errors: List[str] = []
    for entry in expectations["invalid_requests"]:
        label = entry["request_id"]
        value = materialize_invalid_request(entry)
        schema_errors = validate_value(registry, entry["schema"], value)
        if entry["schema_rejected"] and not schema_errors:
            errors.append(f"{label}: declared schema rejection but the schema accepted it")
        if not entry["schema_rejected"] and schema_errors:
            errors.append(
                f"{label}: declared schema-valid but the schema rejected it: {schema_errors}"
            )
    return errors


def error_operation_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    """Every error code must belong to the canonical response of its operation."""
    errors: List[str] = []
    document = context["document"]
    for entry in expectations["selection_errors"]:
        codes = allowed_error_codes(document, entry["operation"], entry["status"])
        if not codes:
            errors.append(
                f"{entry['error_id']}: {entry['operation']} does not declare HTTP "
                f"{entry['status']}"
            )
        elif entry["code"] not in codes:
            errors.append(
                f"{entry['error_id']}: code {entry['code']} is not declared by "
                f"{entry['operation']} response {entry['status']}"
            )
    return errors


def _apply_mutation(payload: Any, mutation: Dict[str, Any]) -> None:
    path = list(mutation["path"])
    operation = mutation["operation"]
    if not path:
        raise ValueError("mutation path must not be empty")
    parent = payload
    for part in path[:-1]:
        parent = parent[part]
    last = path[-1]
    if operation == "set":
        parent[last] = copy.deepcopy(mutation["value"])
    elif operation == "remove":
        del parent[last]
    elif operation == "append":
        parent[last].append(copy.deepcopy(mutation["value"]))
    else:  # pragma: no cover - guarded by the static fixture
        raise ValueError(f"unknown mutation operation {operation!r}")


def _base_payload(
    reference: str, expectations: Dict[str, Any], context: Dict[str, Any]
) -> Any:
    kind, _, key = reference.partition(":")
    if kind == "queue":
        profile_id, _, query_id = key.partition(":")
        profile = context["profiles"][profile_id]
        query = context["queries"][profile_id][query_id]
        return materialize_queue_response(profile, query, context)
    if kind == "profile":
        return copy.deepcopy(context["profiles"][key])
    if kind == "scenario":
        return copy.deepcopy(context["scenarios"][key])
    if kind == "readiness":
        return copy.deepcopy(context["readiness"][key])
    if kind == "snapshot":
        return materialize_selection_snapshot(context["scenarios"][key], context)
    raise ValueError(f"unknown mutation base {reference!r}")


def _run_validator(
    validator: str,
    mutated: Any,
    mutation: Dict[str, Any],
    expectations: Dict[str, Any],
    context: Dict[str, Any],
) -> List[str]:
    if validator == "queue_response":
        return queue_response_errors(mutated)
    if validator == "queue_profile":
        return profile_errors(mutated, context)
    if validator == "selection":
        return selection_errors(mutated, context)
    if validator == "readiness":
        return readiness_errors(mutated)
    if validator == "link":
        payloads = build_payloads(expectations, context)
        payloads[mutation["base"]] = mutated
        return link_errors(expectations, context, payloads)
    raise ValueError(f"unknown validator {validator!r}")


def mutation_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    for mutation in expectations["mutations"]:
        label = mutation["mutation_id"]
        base = _base_payload(mutation["base"], expectations, context)
        mutated = copy.deepcopy(base)
        _apply_mutation(mutated, mutation)
        reported = _run_validator(
            mutation["validator"], mutated, mutation, expectations, context
        )
        if not reported:
            errors.append(
                f"{label}: expected the {mutation['validator']} validator to reject the "
                f"mutation ({mutation['reason']}) but it passed"
            )
    return errors


# --------------------------------------------------------------------------- #
# Aggregate expectation check
# --------------------------------------------------------------------------- #

def expectation_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    for profile in expectations["profiles"]:
        errors.extend(profile_errors(profile, context))
    for scenario in expectations["selection_scenarios"]:
        errors.extend(selection_errors(scenario, context))
    for item in expectations["readiness"]["items"]:
        errors.extend(readiness_errors(item))
    for entry in expectations["ownership"]:
        errors.extend(ownership_errors(entry, context))
    for sequence in expectations["sequences"]:
        errors.extend(sequence_errors(sequence, context))
    errors.extend(rule_set_identity_errors(expectations, context))
    errors.extend(link_errors(expectations, context))
    errors.extend(coverage_errors(expectations))
    return errors


# --------------------------------------------------------------------------- #
# Generated public examples (documented preparation path)
# --------------------------------------------------------------------------- #

# (example id, kind, binding, canonical schema, output file, description).
EXAMPLE_BINDINGS: List[Dict[str, str]] = [
    {
        "id": "queue-ready-120-page1",
        "kind": "queue",
        "binding": "QUEUE-Q022-READY-120:Q-Q024-READY-PAGE1",
        "schema": QUEUE_RESPONSE_SCHEMA,
        "file": "contracts/examples/sorting/queue-ready-120-page1.json",
        "description": "Company queue page 1 of 120 READY files; company counters and filtered counts differ.",
    },
    {
        "id": "queue-all-active-120",
        "kind": "queue",
        "binding": "QUEUE-Q022-READY-120:Q-Q022-ALL-ACTIVE",
        "schema": QUEUE_RESPONSE_SCHEMA,
        "file": "contracts/examples/sorting/queue-all-active-120.json",
        "description": "Default active queue (empty statuses) excludes MISSING and still pages 100 of 130 matches.",
    },
    {
        "id": "queue-missing-explicit",
        "kind": "queue",
        "binding": "QUEUE-Q022-READY-120:Q-Q022-MISSING-EXPLICIT",
        "schema": QUEUE_RESPONSE_SCHEMA,
        "file": "contracts/examples/sorting/queue-missing-explicit.json",
        "description": "MISSING appears only under an explicit status filter and is never eligible.",
    },
    {
        "id": "queue-query-text",
        "kind": "queue",
        "binding": "QUEUE-Q022-READY-120:Q-Q022-QUERY-TEXT",
        "schema": QUEUE_RESPONSE_SCHEMA,
        "file": "contracts/examples/sorting/queue-query-text.json",
        "description": "query_text is a literal case-insensitive substring filter over filename/display path.",
    },
    {
        "id": "queue-ready-0",
        "kind": "queue",
        "binding": "QUEUE-Q024-READY-0:Q-Q024-READY-EMPTY",
        "schema": QUEUE_RESPONSE_SCHEMA,
        "file": "contracts/examples/sorting/queue-ready-0.json",
        "description": "Zero READY files: the empty READY page drives the EMPTY_SELECTION case.",
    },
    {
        "id": "queue-all-active-0",
        "kind": "queue",
        "binding": "QUEUE-Q024-READY-0:Q-Q022-ALL-ACTIVE-0",
        "schema": QUEUE_RESPONSE_SCHEMA,
        "file": "contracts/examples/sorting/queue-all-active-0.json",
        "description": "Non-empty company queue with no selectable item.",
    },
    {
        "id": "queue-ready-1001-page1",
        "kind": "queue",
        "binding": "QUEUE-Q024-READY-1001:Q-Q024-READY-LIMIT-PAGE1",
        "schema": QUEUE_RESPONSE_SCHEMA,
        "file": "contracts/examples/sorting/queue-ready-1001-page1.json",
        "description": "1001 eligible READY files: the page is capped at 100 and the batch limit is exceeded.",
    },
    {
        "id": "selection-request-explicit-one",
        "kind": "selection_request",
        "binding": "SEL-Q024-EXPLICIT-ONE",
        "schema": SELECTION_REQUEST_SCHEMA,
        "file": "contracts/examples/sorting/selection-request-explicit-one.json",
        "description": "EXPLICIT selection request for one item with its content revision.",
    },
    {
        "id": "selection-request-explicit-multiple",
        "kind": "selection_request",
        "binding": "SEL-Q024-EXPLICIT-MULTIPLE-OFFPAGE",
        "schema": SELECTION_REQUEST_SCHEMA,
        "file": "contracts/examples/sorting/selection-request-explicit-multiple.json",
        "description": "EXPLICIT selection request for several items, including off-page ids.",
    },
    {
        "id": "selection-request-all-matching-120",
        "kind": "selection_request",
        "binding": "SEL-Q024-ALL-MATCHING-120",
        "schema": SELECTION_REQUEST_SCHEMA,
        "file": "contracts/examples/sorting/selection-request-all-matching-120.json",
        "description": "ALL_MATCHING selection request with expected_eligible_count=120.",
    },
    {
        "id": "selection-snapshot-explicit-one",
        "kind": "selection_snapshot",
        "binding": "SEL-Q024-EXPLICIT-ONE",
        "schema": SELECTION_SNAPSHOT_SCHEMA,
        "file": "contracts/examples/sorting/selection-snapshot-explicit-one.json",
        "description": "Immutable snapshot of one explicit item; the id list stays server-side.",
    },
    {
        "id": "selection-snapshot-explicit-multiple",
        "kind": "selection_snapshot",
        "binding": "SEL-Q024-EXPLICIT-MULTIPLE-OFFPAGE",
        "schema": SELECTION_SNAPSHOT_SCHEMA,
        "file": "contracts/examples/sorting/selection-snapshot-explicit-multiple.json",
        "description": "Immutable snapshot of several explicit items, including off-page ids.",
    },
    {
        "id": "selection-snapshot-all-matching-120",
        "kind": "selection_snapshot",
        "binding": "SEL-Q024-ALL-MATCHING-120",
        "schema": SELECTION_SNAPSHOT_SCHEMA,
        "file": "contracts/examples/sorting/selection-snapshot-all-matching-120.json",
        "description": "Immutable ALL_MATCHING snapshot of all 120 eligible READY files.",
    },
    {
        "id": "error-empty-selection",
        "kind": "error",
        "binding": "SEL-ERR-EMPTY",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-empty-selection.json",
        "description": "422 EMPTY_SELECTION for a filter with zero eligible files.",
    },
    {
        "id": "error-batch-limit-exceeded",
        "kind": "error",
        "binding": "SEL-ERR-LIMIT",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-batch-limit-exceeded.json",
        "description": "422 BATCH_LIMIT_EXCEEDED for 1001 eligible files, without truncation.",
    },
    {
        "id": "error-selection-changed",
        "kind": "error",
        "binding": "SEL-ERR-CHANGED",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-selection-changed.json",
        "description": "409 SELECTION_CHANGED when the shown eligible count differs before creation.",
    },
    {
        "id": "error-selection-forbidden",
        "kind": "error",
        "binding": "SEL-ERR-FORBIDDEN",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-selection-forbidden.json",
        "description": "403 FORBIDDEN when another user uses a snapshot bound to a different user_id.",
    },
    {
        "id": "error-selection-expired-preview",
        "kind": "error",
        "binding": "SEL-ERR-EXPIRED-PREVIEW",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-selection-expired-preview.json",
        "description": "409 SELECTION_EXPIRED on the real preview operation.",
    },
    {
        "id": "error-selection-expired-batch",
        "kind": "error",
        "binding": "SEL-ERR-EXPIRED-BATCH",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-selection-expired-batch.json",
        "description": "409 SELECTION_EXPIRED on the real batch operation.",
    },
    {
        "id": "error-selection-not-found",
        "kind": "error",
        "binding": "SEL-ERR-NOT-FOUND",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-selection-not-found.json",
        "description": "404 NOT_FOUND for an unknown selection id on the preview operation.",
    },
]


def generated_examples(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    for binding in EXAMPLE_BINDINGS:
        kind = binding["kind"]
        if kind == "queue":
            profile_id, _, query_id = binding["binding"].partition(":")
            profile = context["profiles"][profile_id]
            query = context["queries"][profile_id][query_id]
            payload = materialize_queue_response(profile, query, context)
        elif kind == "selection_request":
            payload = materialize_selection_request(
                context["scenarios"][binding["binding"]], context
            )
        elif kind == "selection_snapshot":
            payload = materialize_selection_snapshot(
                context["scenarios"][binding["binding"]], context
            )
        elif kind == "error":
            payload = materialize_error(context["errors"][binding["binding"]], context)
        else:  # pragma: no cover - guarded by the static binding table
            raise ValueError(f"unknown example kind {kind!r}")
        output[binding["file"]] = payload
    return output


def write_examples(root: Optional[Path] = None) -> List[str]:
    base = Path(root) if root is not None else synthetic.repo_root()
    expectations = load_expectations(base)
    context = build_context(base, expectations)
    written = []
    for relative, payload in generated_examples(expectations, context).items():
        target = base / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        written.append(relative)
    return written


# --------------------------------------------------------------------------- #
# Small time helper
# --------------------------------------------------------------------------- #

def _parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _seconds_between(first: str, second: str) -> float:
    return (_parse_instant(second) - _parse_instant(first)).total_seconds()


def _ttl_seconds(created_at: str, expires_at: str) -> int:
    return int(_seconds_between(created_at, expires_at))


# --------------------------------------------------------------------------- #
# Documented fixture-preparation command
# --------------------------------------------------------------------------- #

def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Materialize the WiseWay queue/selection oracle examples."
    )
    parser.add_argument("--write-examples", action="store_true")
    parser.add_argument("--root", default=None)
    args = parser.parse_args(argv)
    if args.write_examples:
        for relative in write_examples(Path(args.root) if args.root else None):
            print(f"wrote {relative}")
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
