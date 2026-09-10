"""LT-03.4a finite BatchState/OutcomeState/OutcomeReasonCode oracle.

``fixtures/synthetic/batch_outcomes.json`` stores the finite, hand-authored
oracle for the accepted sorting batches and their per-file outcomes that API
section 8, TZ QUEUE-07..10 and FILE-01..06/08/09, QA section 4/8 and the matrix
rows Q-031..037/039 describe.  It builds directly on:

* ``fixtures/synthetic/queue_selections.json`` - the frozen selection snapshots
  and their literal membership (the 120 / one / multiple selections);
* ``fixtures/synthetic/preview_preflight.json`` - the accepted DIRECT/PREVIEWED
  preflight scenarios whose ``future_batch_id`` this fixture realises, plus the
  isolated preview selections and the flat manual review directory;
* ``fixtures/synthetic/rule_expectations.json`` - the complete immutable
  version/rule/RuleSet/target definitions the planned targets are derived from.

The module is a *materializer and consistency checker*, not a runtime domain:

* every Batch, BatchSummary, Outcome and BatchPage is literal data bound to a
  canonical OAS schema pointer;
* compact ``$repeat_rows`` ranges only enumerate already-declared members - they
  never match, rank or move anything;
* counts, attempts, placements, pagination, status transitions, duplicate-plan
  targets, occupied targets/names and the logical inventory contract are
  cross-checked against the frozen selection membership and the selected rule's
  configured directory plus fixed stem plus last suffix.

No matcher, priority resolver, target-name derivation, executor, backend
filesystem writer or recovery engine is implemented - the values are declared
and verified.

A documented preparation command regenerates the committed public examples::

    python tests/contract/contractlib/batch_outcomes.py --write-examples
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # package import (tests, verify_contract.py)
    from . import preview_preflight, synthetic
    from .semantic import validate_fixture
except ImportError:  # pragma: no cover - documented direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from contractlib import preview_preflight, synthetic  # type: ignore
    from contractlib.semantic import validate_fixture  # type: ignore

EXPECTATIONS_RELATIVE = Path("fixtures") / "synthetic" / "batch_outcomes.json"

BATCH_SCHEMA = "#/components/schemas/Batch"
BATCH_SUMMARY_SCHEMA = "#/components/schemas/BatchSummary"
BATCH_PAGE_SCHEMA = "#/components/schemas/BatchPage"
OUTCOME_SCHEMA = "#/components/schemas/Outcome"

KNOWN_Q = ("Q-031", "Q-032", "Q-033", "Q-034", "Q-035", "Q-036", "Q-037", "Q-039")
BATCH_STATES = ("ACCEPTED", "RUNNING", "COMPLETED", "COMPLETED_WITH_ISSUES", "RECOVERY_REQUIRED")
OUTCOME_STATES = (
    "PENDING",
    "PROCESSING",
    "SORTED",
    "MANUAL_REVIEW",
    "REQUIRES_DECISION",
    "QUARANTINED",
    "SKIPPED",
    "RECOVERY_REQUIRED",
)
REASON_CODES = (
    "NO_SCENARIO",
    "RULE_CONFLICT",
    "TARGET_OCCUPIED",
    "MANUAL_REVIEW_NAME_OCCUPIED",
    "TECHNICAL_ERROR",
    "ALREADY_PROCESSING",
    "SOURCE_CHANGED",
    "SOURCE_MISSING",
    "RECOVERY_REQUIRED",
)
MANUAL_REVIEW_REASONS = ("NO_SCENARIO", "RULE_CONFLICT")
SKIPPED_REASONS = ("ALREADY_PROCESSING", "SOURCE_CHANGED", "SOURCE_MISSING")
TERMINAL_BATCH_STATES = ("COMPLETED", "COMPLETED_WITH_ISSUES")
UNFINISHED_BATCH_STATES = ("ACCEPTED", "RUNNING", "RECOVERY_REQUIRED")

COUNT_FIELDS = (
    "sorted",
    "manual_review",
    "requires_decision",
    "quarantined",
    "skipped",
    "recovery_required",
)


# --------------------------------------------------------------------------- #
# Loading and context
# --------------------------------------------------------------------------- #

def expectations_path(root: Optional[Path] = None) -> Path:
    return (root or synthetic.repo_root()) / EXPECTATIONS_RELATIVE


def load_expectations(root: Optional[Path] = None) -> Dict[str, Any]:
    return synthetic.load_json(expectations_path(root))


def _basename(relative_path: str) -> str:
    return relative_path.rsplit("/", 1)[-1]


def _isolated_selection(entry: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = dict(entry["snapshot"])
    members: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for member in entry["members"]:
        record = dict(member)
        record.setdefault("company_id", snapshot["company_id"])
        record.setdefault("source_ready", True)
        members[record["item_id"]] = record
        order.append(record["item_id"])
    return {
        "selection_id": snapshot["selection_id"],
        "company_id": snapshot["company_id"],
        "mode": snapshot["mode"],
        "owner": entry["owner"],
        "snapshot": snapshot,
        "members": members,
        "member_order": order,
        "source": "batch_outcomes.json",
    }


def build_context(
    root: Optional[Path] = None, expectations: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Load the contract, the linked fixtures and the literal lookup tables."""
    base = Path(root) if root is not None else synthetic.repo_root()
    if expectations is None:
        expectations = load_expectations(base)
    preview = preview_preflight.build_context(base)

    selections: Dict[str, Dict[str, Any]] = dict(preview["selections"])
    for entry in expectations["selections"]:
        selections[entry["selection_id"]] = _isolated_selection(entry)

    companies = {
        alias: dict(entry) for alias, entry in expectations["companies"].items()
    }
    company_by_id = {entry["company_id"]: entry for entry in companies.values()}
    company_by_root = {entry["root_id"]: entry for entry in companies.values()}

    batches = {entry["batch_id"]: entry for entry in expectations["batches"]}
    histories = {entry["page_id"]: entry for entry in expectations["history"]}
    duplicate_targets = {
        entry["group_id"]: entry for entry in expectations["duplicate_targets"]
    }
    occupied_targets = {
        entry["object_id"]: entry for entry in expectations["occupied_targets"]
    }
    manual_review_occupied = {
        entry["object_id"]: entry for entry in expectations["manual_review_occupied"]
    }
    preflight_by_id = {
        entry["scenario_id"]: entry
        for entry in preview["expectations"]["preflight"]
    }
    accepted = {
        entry["scenario_id"]: entry for entry in expectations["accepted_preflights"]
    }

    return {
        "base": base,
        "manifest": preview["manifest"],
        "document": preview["document"],
        "expectations": expectations,
        "preview": preview,
        "preview_context": preview,
        "actors": preview["actors"],
        "selections": selections,
        "rule_sets": preview["rule_sets"],
        "targets": preview["targets"],
        "versions": preview["versions"],
        "manual_review": preview["manual_review"],
        "previews": preview["previews"],
        "prefix": preview["prefix"],
        "companies": companies,
        "company_by_id": company_by_id,
        "company_by_root": company_by_root,
        "batches": batches,
        "histories": histories,
        "duplicate_targets": duplicate_targets,
        "occupied_targets": occupied_targets,
        "manual_review_occupied": manual_review_occupied,
        "preflight_by_id": preflight_by_id,
        "accepted_preflights": accepted,
        "page_limit": expectations["constants"]["batch_page_limit"],
    }


# --------------------------------------------------------------------------- #
# Literal expansion and materialization (never a matcher)
# --------------------------------------------------------------------------- #

def _selection_id(batch_spec: Dict[str, Any]) -> str:
    binding = batch_spec["selection"]
    if "from_preview_selection" in binding:
        return binding["from_preview_selection"]
    if "isolated" in binding:
        return binding["isolated"]
    raise ValueError(f"unknown selection binding {binding!r}")


def _repeat_rows(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    width = spec["index_width"]
    for index in range(spec["index_start"], spec["index_end"] + 1):
        row = {
            key: copy.deepcopy(value)
            for key, value in spec.items()
            if key not in ("item_prefix", "index_start", "index_end", "index_width")
        }
        row["item_id"] = f"{spec['item_prefix']}{index:0{width}d}"
        rows.append(row)
    return rows


def expand_rows(rows: Any) -> List[Dict[str, Any]]:
    """Expand a page's literal row declarations (``$repeat_rows`` entries)."""
    result: List[Dict[str, Any]] = []
    for entry in rows:
        if isinstance(entry, dict) and set(entry.keys()) == {"$repeat_rows"}:
            result.extend(_repeat_rows(entry["$repeat_rows"]))
        else:
            result.append(copy.deepcopy(entry))
    return result


def row_specs(page_spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    return expand_rows(page_spec["rows"])


def _derive_target(context: Dict[str, Any], reference: Dict[str, Any], filename: str) -> Dict[str, Any]:
    preview = context["preview"]
    rule = preview_preflight._rule_entry(preview, reference)
    if rule is None:
        raise ValueError(f"undefined rule reference {reference!r}")
    return preview_preflight._derive_target(preview, rule, filename)


def _manual_review_location(
    company: Dict[str, Any], filename: str, prefix: str
) -> Dict[str, str]:
    relative_path = company["manual_review_directory"] + "/" + filename
    return {
        "root_id": company["root_id"],
        "relative_path": relative_path,
        "display_path": prefix + "/" + relative_path,
    }


def _quarantine_location(
    company: Dict[str, Any], attempt_id: str, filename: str, prefix: str
) -> Dict[str, str]:
    relative_path = company["quarantine_directory"] + "/" + attempt_id + "/" + filename
    return {
        "root_id": company["root_id"],
        "relative_path": relative_path,
        "display_path": prefix + "/" + relative_path,
    }


def materialize_outcome(
    spec: Dict[str, Any],
    member: Dict[str, Any],
    batch_spec: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    company = context["company_by_id"][member["company_id"]]
    item_id = member["item_id"]
    attempt_id = spec.get("attempt_id") or f"attempt-{batch_spec['batch_id']}-{item_id}"
    matched_rule = copy.deepcopy(spec.get("matched_rule"))

    planned = spec.get("planned_target")
    if planned == "auto":
        if matched_rule is None:
            raise ValueError(f"{item_id}: auto target needs a matched rule")
        planned = _derive_target(context, matched_rule, member["filename"])
    elif planned is not None:
        planned = copy.deepcopy(planned)

    actual_spec = spec.get("actual")
    if actual_spec == "source":
        actual = copy.deepcopy(member["location"])
    elif actual_spec == "planned":
        actual = copy.deepcopy(planned)
    elif actual_spec == "manual_review":
        actual = _manual_review_location(company, member["filename"], context["prefix"])
    elif actual_spec == "quarantine":
        actual = _quarantine_location(
            company, attempt_id, member["filename"], context["prefix"]
        )
    elif actual_spec in (None, "null"):
        actual = None
    else:
        actual = copy.deepcopy(actual_spec)

    return {
        "attempt_id": attempt_id,
        "item_id": item_id,
        "item_revision": spec.get("item_revision", member["item_revision"]),
        "state": spec["state"],
        "reason_code": spec.get("reason_code"),
        "source": copy.deepcopy(member["location"]),
        "planned_target": planned,
        "actual_location": actual,
        "matched_rule": matched_rule,
        "started_at": spec.get("started_at"),
        "finished_at": spec.get("finished_at"),
    }


def _rule_set_payload(context: Dict[str, Any], rule_set_id: str) -> Dict[str, Any]:
    rule_set = context["rule_sets"][rule_set_id]
    return {
        "rule_set_id": rule_set["rule_set_id"],
        "company_id": rule_set["company_id"],
        "members": [dict(member) for member in rule_set["members"]],
    }


def materialize_batch_page(
    batch_spec: Dict[str, Any], page_spec: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    selection = context["selections"][_selection_id(batch_spec)]
    rows = [
        materialize_outcome(
            spec, selection["members"][spec["item_id"]], batch_spec, context
        )
        for spec in row_specs(page_spec)
    ]
    return {
        "batch_id": batch_spec["batch_id"],
        "company_id": selection["company_id"],
        "actor": copy.deepcopy(context["actors"][batch_spec["owner"]]),
        "selection_id": selection["selection_id"],
        "preview_id": batch_spec.get("preview_id"),
        "rule_set": _rule_set_payload(context, batch_spec["rule_set_id"]),
        "status": batch_spec["status"],
        "created_at": batch_spec["created_at"],
        "started_at": batch_spec["started_at"],
        "finished_at": batch_spec["finished_at"],
        "selected_count": batch_spec["selected_count"],
        "completed_count": batch_spec["completed_count"],
        "counts": dict(batch_spec["counts"]),
        "outcomes": rows,
        "next_cursor": page_spec.get("next_cursor"),
    }


def materialize_batch_summary(
    batch_spec: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    selection = context["selections"][_selection_id(batch_spec)]
    return {
        "batch_id": batch_spec["batch_id"],
        "company_id": selection["company_id"],
        "actor": copy.deepcopy(context["actors"][batch_spec["owner"]]),
        "status": batch_spec["status"],
        "created_at": batch_spec["created_at"],
        "finished_at": batch_spec["finished_at"],
        "selected_count": batch_spec["selected_count"],
        "completed_count": batch_spec["completed_count"],
        "counts": dict(batch_spec["counts"]),
    }


def materialize_history_page(
    history_spec: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    return {
        "items": [
            materialize_batch_summary(context["batches"][batch_id], context)
            for batch_id in history_spec["batch_ids"]
        ],
        "next_cursor": history_spec.get("next_cursor"),
    }


def all_outcome_payloads(
    batch_spec: Dict[str, Any], context: Dict[str, Any]
) -> List[Dict[str, Any]]:
    selection = context["selections"][_selection_id(batch_spec)]
    outcomes: List[Dict[str, Any]] = []
    for page_spec in batch_spec["pages"]:
        for spec in row_specs(page_spec):
            member = selection["members"].get(spec["item_id"])
            if member is None:
                continue
            outcomes.append(
                materialize_outcome(spec, member, batch_spec, context)
            )
    return outcomes


# --------------------------------------------------------------------------- #
# Inventory contract (logical expectation, never a measured hash)
# --------------------------------------------------------------------------- #

def _inventory_rule(
    expectations: Dict[str, Any], state: str, reason: Optional[str]
) -> Optional[Dict[str, Any]]:
    for rule in expectations["inventory"]["state_rules"]:
        if rule["state"] == state and rule["reason_code"] == reason:
            return rule
    return None


def inventory_records(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for batch_spec in expectations["batches"]:
        for outcome in all_outcome_payloads(batch_spec, context):
            rule = _inventory_rule(
                expectations, outcome["state"], outcome["reason_code"]
            )
            if rule is None:
                continue
            source_present = rule["source_present_after"]
            if outcome["state"] == "RECOVERY_REQUIRED":
                # Unknown placement -> unknown source; a known source that could
                # not be quarantined is recorded as still in place.
                source_present = (
                    None if outcome["actual_location"] is None else True
                )
            destination = (
                outcome["actual_location"] if rule["destination_present"] else None
            )
            records.append(
                {
                    "outcome_id": f"{batch_spec['batch_id']}:{outcome['item_id']}",
                    "batch_id": batch_spec["batch_id"],
                    "item_id": outcome["item_id"],
                    "state": outcome["state"],
                    "reason_code": outcome["reason_code"],
                    "source_basename": _basename(outcome["source"]["relative_path"]),
                    "destination_basename": (
                        _basename(destination["relative_path"])
                        if isinstance(destination, dict)
                        else None
                    ),
                    "source_present_after": source_present,
                    "destination_present": rule["destination_present"],
                    "content_conserved": rule["content_conserved"],
                    "content_tag": "lt034a-content-" + outcome["item_id"],
                    "checksum_kind": "logical-content-tag",
                }
            )
    return records


def inventory_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    inventory = expectations["inventory"]
    if inventory.get("kind") != "logical-inventory-expectation":
        errors.append("inventory contract must be a logical expectation, not measured evidence")
    if inventory.get("no_file_writes") is not True:
        errors.append("inventory contract must declare that no file is written")
    if not inventory.get("content_recipe", {}).get("seed"):
        errors.append("inventory content recipe must declare a deterministic seed")
    for rule in inventory["state_rules"]:
        state = rule["state"]
        reason = rule["reason_code"]
        if state not in OUTCOME_STATES:
            errors.append(f"inventory rule references unknown state {state!r}")
            continue
        if reason is not None and reason not in REASON_CODES:
            errors.append(f"inventory rule references unknown reason {reason!r}")
        moved = state in ("SORTED", "MANUAL_REVIEW", "QUARANTINED")
        if moved:
            if rule["source_present_after"] is not False:
                errors.append(
                    f"inventory {state}/{reason}: a confirmed move must not leave the source"
                )
            if rule["destination_present"] is not True:
                errors.append(
                    f"inventory {state}/{reason}: a confirmed move must present its destination"
                )
            if rule["content_conserved"] is not True:
                errors.append(
                    f"inventory {state}/{reason}: a confirmed move conserves content"
                )
        if state == "REQUIRES_DECISION":
            if rule["source_present_after"] is not True or rule["destination_present"]:
                errors.append(
                    f"inventory {state}/{reason}: the source stays in place and nothing moves"
                )
        if state == "SKIPPED" and reason == "SOURCE_MISSING":
            if rule["source_present_after"] is not False:
                errors.append("inventory SKIPPED/SOURCE_MISSING must record the source as gone")

    records = inventory_records(expectations, context)
    if not records:
        errors.append("inventory contract produced no records")
    for record in records:
        if record["checksum_kind"] != "logical-content-tag":
            errors.append(
                f"inventory {record['outcome_id']}: only a logical content tag is allowed"
            )
        if not record["content_tag"]:
            errors.append(f"inventory {record['outcome_id']}: missing content tag")
        if record["content_conserved"] and not record["destination_present"]:
            errors.append(
                f"inventory {record['outcome_id']}: conserved content needs a destination"
            )
        if record["state"] == "MANUAL_REVIEW":
            if record["destination_basename"] != record["source_basename"]:
                errors.append(
                    f"inventory {record['outcome_id']}: manual review keeps the original basename"
                )
        if record["state"] == "RECOVERY_REQUIRED":
            if record["source_present_after"] is None and record["destination_present"]:
                errors.append(
                    f"inventory {record['outcome_id']}: unknown recovery cannot present a destination"
                )

    for existing in list(inventory.get("existing_objects", [])) + list(
        expectations["occupied_targets"]
    ) + list(expectations["manual_review_occupied"]):
        if existing.get("unchanged") is not True:
            errors.append(f"existing object {existing.get('object_id')} must be unchanged")
        if not existing.get("content_tag"):
            errors.append(f"existing object {existing.get('object_id')} needs a content tag")
    return errors


# --------------------------------------------------------------------------- #
# Row / batch validation
# --------------------------------------------------------------------------- #

def _outcome_errors(
    label: str,
    spec: Dict[str, Any],
    outcome: Dict[str, Any],
    member: Dict[str, Any],
    batch_spec: Dict[str, Any],
    context: Dict[str, Any],
) -> List[str]:
    errors: List[str] = []
    state = outcome["state"]
    reason = outcome["reason_code"]
    if state not in OUTCOME_STATES:
        errors.append(f"{label}: unknown OutcomeState {state!r}")
    if reason is not None and reason not in REASON_CODES:
        errors.append(f"{label}: unknown OutcomeReasonCode {reason!r}")
    if outcome["item_revision"] != member["item_revision"]:
        errors.append(
            f"{label}: outcome revision {outcome['item_revision']} != frozen "
            f"selection revision {member['item_revision']}"
        )
    if outcome["source"] != member["location"]:
        errors.append(f"{label}: outcome source != frozen selection source")
    company = context["company_by_id"][member["company_id"]]
    started = outcome["started_at"]
    finished = outcome["finished_at"]

    if state == "PENDING":
        if started is not None or finished is not None or reason is not None:
            errors.append(f"{label}: PENDING must keep started_at/finished_at/reason null")
    elif state == "PROCESSING":
        if started is None or finished is not None or reason is not None:
            errors.append(f"{label}: PROCESSING must have started_at and no finished_at/reason")
    elif state == "SORTED":
        if reason is not None:
            errors.append(f"{label}: SORTED must have a null reason_code")
        if not isinstance(outcome["matched_rule"], dict):
            errors.append(f"{label}: SORTED must select a published rule")
        if not isinstance(outcome["planned_target"], dict):
            errors.append(f"{label}: SORTED must carry a planned target")
        if not isinstance(outcome["actual_location"], dict):
            errors.append(f"{label}: SORTED must carry its confirmed actual_location")
        if isinstance(outcome["matched_rule"], dict):
            expected = _derive_target(context, outcome["matched_rule"], member["filename"])
            if outcome["planned_target"] != expected:
                errors.append(
                    f"{label}: planned target does not equal the selected rule's "
                    "directory + fixed stem + last suffix"
                )
        if outcome["actual_location"] != outcome["planned_target"]:
            errors.append(f"{label}: SORTED actual_location must equal its planned target")
        if finished is None or started is None:
            errors.append(f"{label}: SORTED must be a finished attempt")
    elif state == "MANUAL_REVIEW":
        if reason not in MANUAL_REVIEW_REASONS:
            errors.append(f"{label}: manual review reason must be NO_SCENARIO or RULE_CONFLICT")
        if outcome["matched_rule"] is not None:
            errors.append(f"{label}: manual review carries no selected rule")
        if outcome["planned_target"] is not None:
            errors.append(f"{label}: manual review has no predicted target")
        expected = _manual_review_location(
            company, member["filename"], context["prefix"]
        )
        if outcome["actual_location"] != expected:
            errors.append(
                f"{label}: manual review must land in the flat folder with the unchanged basename"
            )
        if finished is None or started is None:
            errors.append(f"{label}: manual review must be a finished attempt")
    elif state == "REQUIRES_DECISION":
        if reason == "TARGET_OCCUPIED":
            if not isinstance(outcome["planned_target"], dict):
                errors.append(f"{label}: TARGET_OCCUPIED needs the planned target")
            if outcome["actual_location"] != outcome["source"]:
                errors.append(f"{label}: TARGET_OCCUPIED keeps the source in place")
        elif reason == "MANUAL_REVIEW_NAME_OCCUPIED":
            if outcome["planned_target"] is not None:
                errors.append(
                    f"{label}: MANUAL_REVIEW_NAME_OCCUPIED has no predicted target"
                )
            if outcome["actual_location"] != outcome["source"]:
                errors.append(
                    f"{label}: MANUAL_REVIEW_NAME_OCCUPIED keeps the source in place"
                )
        else:
            errors.append(
                f"{label}: REQUIRES_DECISION reason must be TARGET_OCCUPIED or "
                "MANUAL_REVIEW_NAME_OCCUPIED"
            )
        if finished is None or started is None:
            errors.append(f"{label}: REQUIRES_DECISION must be a finished attempt")
    elif state == "QUARANTINED":
        if reason != "TECHNICAL_ERROR":
            errors.append(f"{label}: QUARANTINED reason must be TECHNICAL_ERROR")
        if not isinstance(outcome["actual_location"], dict):
            errors.append(f"{label}: QUARANTINED needs its confirmed actual_location")
        else:
            prefix = company["quarantine_directory"] + "/"
            if not outcome["actual_location"]["relative_path"].startswith(prefix):
                errors.append(f"{label}: QUARANTINED must land under the quarantine folder")
        if finished is None or started is None:
            errors.append(f"{label}: QUARANTINED must be a finished attempt")
    elif state == "SKIPPED":
        if reason not in SKIPPED_REASONS:
            errors.append(f"{label}: SKIPPED reason is not one of the per-file skip causes")
        if outcome["actual_location"] is not None:
            errors.append(
                f"{label}: SKIPPED performs no own mutation, so actual_location must be null"
            )
        if finished is None or started is None:
            errors.append(f"{label}: SKIPPED must be a finished attempt")
    elif state == "RECOVERY_REQUIRED":
        if reason != "RECOVERY_REQUIRED":
            errors.append(f"{label}: RECOVERY_REQUIRED reason must be RECOVERY_REQUIRED")
        if finished is not None:
            errors.append(f"{label}: RECOVERY_REQUIRED stays unfinished (finished_at=null)")
        if outcome["actual_location"] is not None and outcome["actual_location"] != outcome["source"]:
            errors.append(
                f"{label}: RECOVERY_REQUIRED may only report the unchanged source or null"
            )
    else:
        errors.append(f"{label}: unsupported OutcomeState {state!r}")

    return errors


def _batch_errors(
    batch_spec: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    label = batch_spec["batch_id"]
    selection = context["selections"].get(_selection_id(batch_spec))
    if selection is None:
        return [f"{label}: unknown selection {_selection_id(batch_spec)!r}"]
    rule_set = context["rule_sets"].get(batch_spec["rule_set_id"])
    if rule_set is None:
        return [f"{label}: unknown rule_set_id {batch_spec['rule_set_id']!r}"]
    if rule_set["company_id"] != selection["company_id"]:
        errors.append(f"{label}: batch RuleSet belongs to another company")
    if batch_spec["owner"] not in context["actors"]:
        errors.append(f"{label}: owner does not resolve to an auth fixture actor")
    elif selection.get("owner") != batch_spec["owner"]:
        errors.append(f"{label}: batch owner does not own the frozen selection")
    status = batch_spec["status"]
    if status not in BATCH_STATES:
        errors.append(f"{label}: unknown BatchState {status!r}")
    if selection["snapshot"]["selected_count"] != batch_spec["selected_count"]:
        errors.append(
            f"{label}: selected_count {batch_spec['selected_count']} != frozen selection "
            f"{selection['snapshot']['selected_count']}"
        )

    mode = batch_spec.get("execution_mode")
    if mode not in ("DIRECT", "PREVIEWED"):
        errors.append(f"{label}: execution_mode must be DIRECT or PREVIEWED")
    if mode == "PREVIEWED":
        preview = context["previews"].get(batch_spec.get("preview_id"))
        if preview is None:
            errors.append(f"{label}: PREVIEWED needs a resolvable preview_id")
        elif preview["selection_id"] != selection["selection_id"]:
            errors.append(f"{label}: PREVIEWED preview does not match the selection")
    elif mode == "DIRECT" and batch_spec.get("preview_id") is not None:
        errors.append(f"{label}: DIRECT must not carry a preview_id")

    outcomes: List[Dict[str, Any]] = []
    for page_spec in batch_spec["pages"]:
        for spec in row_specs(page_spec):
            member = selection["members"].get(spec["item_id"])
            if member is None:
                errors.append(f"{label}: row {spec['item_id']} is not a frozen selection member")
                continue
            outcome = materialize_outcome(spec, member, batch_spec, context)
            outcomes.append(outcome)
            errors.extend(
                _outcome_errors(
                    f"{label}/{spec['item_id']}", spec, outcome, member, batch_spec, context
                )
            )

    if len(outcomes) != batch_spec["selected_count"]:
        errors.append(
            f"{label}: outcomes cover {len(outcomes)} rows, not selected_count "
            f"{batch_spec['selected_count']}"
        )
    attempts = [outcome["attempt_id"] for outcome in outcomes]
    if len(attempts) != len(set(attempts)):
        errors.append(f"{label}: attempt_id values must be unique inside a batch")

    derived: Dict[str, int] = {field: 0 for field in COUNT_FIELDS}
    for outcome in outcomes:
        field = {
            "SORTED": "sorted",
            "MANUAL_REVIEW": "manual_review",
            "REQUIRES_DECISION": "requires_decision",
            "QUARANTINED": "quarantined",
            "SKIPPED": "skipped",
            "RECOVERY_REQUIRED": "recovery_required",
        }.get(outcome["state"])
        if field:
            derived[field] += 1
    declared = batch_spec["counts"]
    if set(declared) != set(COUNT_FIELDS):
        errors.append(f"{label}: counts must declare exactly {COUNT_FIELDS}")
    for field in COUNT_FIELDS:
        if declared.get(field) != derived[field]:
            errors.append(
                f"{label}: counts.{field} {declared.get(field)} != materialized {derived[field]}"
            )
    established = sum(derived[field] for field in COUNT_FIELDS[:-1])
    if batch_spec["completed_count"] != established:
        errors.append(
            f"{label}: completed_count {batch_spec['completed_count']} != first five counts "
            f"{established}"
        )
    if batch_spec["completed_count"] + derived["recovery_required"] > batch_spec["selected_count"]:
        errors.append(f"{label}: completed + recovery exceeds selected_count")

    finished = batch_spec["finished_at"]
    if status in TERMINAL_BATCH_STATES and finished is None:
        errors.append(f"{label}: terminal status {status} requires finished_at")
    if status in UNFINISHED_BATCH_STATES and finished is not None:
        errors.append(f"{label}: status {status} must keep finished_at=null")
    if status == "ACCEPTED":
        if batch_spec["completed_count"] != 0:
            errors.append(f"{label}: ACCEPTED must not report completed outcomes")
        if any(outcome["state"] != "PENDING" for outcome in outcomes):
            errors.append(f"{label}: ACCEPTED may only carry PENDING outcomes")
    if status == "RUNNING":
        if not any(outcome["state"] in ("PENDING", "PROCESSING") for outcome in outcomes):
            errors.append(f"{label}: RUNNING must still have a pending or processing outcome")
        if batch_spec["completed_count"] >= batch_spec["selected_count"]:
            errors.append(f"{label}: RUNNING must be partial, not complete")
    if status == "COMPLETED":
        if any(outcome["state"] != "SORTED" for outcome in outcomes):
            errors.append(f"{label}: COMPLETED requires every outcome to be SORTED")
    if status == "COMPLETED_WITH_ISSUES":
        if any(outcome["state"] in ("PENDING", "PROCESSING") for outcome in outcomes):
            errors.append(f"{label}: COMPLETED_WITH_ISSUES must not carry pending work")
        if not any(outcome["state"] != "SORTED" for outcome in outcomes):
            errors.append(f"{label}: COMPLETED_WITH_ISSUES needs at least one issue")
    if status == "RECOVERY_REQUIRED" and derived["recovery_required"] < 1:
        errors.append(f"{label}: RECOVERY_REQUIRED needs at least one recovery outcome")

    errors.extend(_page_errors(batch_spec, context))
    errors.extend(_duplicate_target_errors(batch_spec, outcomes, context))
    errors.extend(_occupied_target_errors(batch_spec, outcomes, context))
    errors.extend(_manual_review_occupied_errors(batch_spec, outcomes, context))
    return errors


def _page_errors(batch_spec: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = batch_spec["batch_id"]
    pages = batch_spec["pages"]
    limit = context["page_limit"]
    selected = batch_spec["selected_count"]
    total = 0
    for index, page_spec in enumerate(pages):
        count = len(row_specs(page_spec))
        total += count
        if count > limit:
            errors.append(f"{label}: page {page_spec['page_id']} has {count} rows, above {limit}")
        last = index == len(pages) - 1
        cursor = page_spec.get("next_cursor")
        if last and cursor is not None:
            errors.append(f"{label}: the last page must not carry a cursor")
        if not last and cursor is None:
            errors.append(f"{label}: a non-last page must carry a cursor")
        if not last and index == 0 and selected > limit and count != limit:
            errors.append(f"{label}: the first page of a larger batch must be full")
    if total != selected:
        errors.append(f"{label}: pages cover {total} rows, not selected_count {selected}")
    return errors


def _duplicate_target_errors(
    batch_spec: Dict[str, Any],
    outcomes: List[Dict[str, Any]],
    context: Dict[str, Any],
) -> List[str]:
    errors: List[str] = []
    label = batch_spec["batch_id"]
    groups: Dict[Any, List[Dict[str, Any]]] = {}
    for outcome in outcomes:
        if outcome["state"] != "REQUIRES_DECISION" or outcome["reason_code"] != "TARGET_OCCUPIED":
            continue
        target = outcome["planned_target"]
        if not isinstance(target, dict):
            continue
        groups.setdefault((target["root_id"], target["relative_path"]), []).append(outcome)
    declared = {
        (
            entry["target"]["root_id"],
            entry["target"]["relative_path"],
        ): entry
        for entry in context["duplicate_targets"].values()
        if entry["batch_id"] == label
    }
    for key, participants in groups.items():
        if len(participants) < 2:
            if key in declared:
                errors.append(
                    f"{label}: declared duplicate target {key} has fewer than two participants"
                )
            continue
        entry = declared.get(key)
        if entry is None:
            errors.append(f"{label}: undeclared duplicate plan target {key}")
            continue
        ids = sorted(outcome["item_id"] for outcome in participants)
        if ids != sorted(entry["participants"]):
            errors.append(
                f"{label}: duplicate target participants {ids} != declared "
                f"{sorted(entry['participants'])}"
            )
        if any(
            outcome["state"] != "REQUIRES_DECISION"
            or outcome["reason_code"] != "TARGET_OCCUPIED"
            for outcome in participants
        ):
            errors.append(f"{label}: a duplicate target selected a winner")
    for key, entry in declared.items():
        if key not in groups or len(groups[key]) < 2:
            errors.append(f"{label}: declared duplicate target {key} has no collision")
    return errors


def _occupied_target_errors(
    batch_spec: Dict[str, Any],
    outcomes: List[Dict[str, Any]],
    context: Dict[str, Any],
) -> List[str]:
    errors: List[str] = []
    label = batch_spec["batch_id"]
    for entry in context["occupied_targets"].values():
        if entry["batch_id"] != label:
            continue
        outcome = next((o for o in outcomes if o["item_id"] == entry["item_id"]), None)
        if outcome is None:
            errors.append(f"{label}: occupied target item {entry['item_id']} is missing")
            continue
        if outcome["state"] != "REQUIRES_DECISION" or outcome["reason_code"] != "TARGET_OCCUPIED":
            errors.append(f"{label}: occupied target item must stay REQUIRES_DECISION")
        if outcome["planned_target"] != entry["location"]:
            errors.append(f"{label}: occupied target metadata does not match the planned target")
        if outcome["actual_location"] != outcome["source"]:
            errors.append(f"{label}: an occupied target leaves the source in incoming")
    return errors


def _manual_review_occupied_errors(
    batch_spec: Dict[str, Any],
    outcomes: List[Dict[str, Any]],
    context: Dict[str, Any],
) -> List[str]:
    errors: List[str] = []
    label = batch_spec["batch_id"]
    for entry in context["manual_review_occupied"].values():
        if entry["batch_id"] != label:
            continue
        outcome = next((o for o in outcomes if o["item_id"] == entry["item_id"]), None)
        if outcome is None:
            errors.append(f"{label}: manual review name item {entry['item_id']} is missing")
            continue
        if (
            outcome["state"] != "REQUIRES_DECISION"
            or outcome["reason_code"] != "MANUAL_REVIEW_NAME_OCCUPIED"
        ):
            errors.append(
                f"{label}: an occupied manual review name must stay REQUIRES_DECISION"
            )
        if outcome["planned_target"] is not None:
            errors.append(f"{label}: an occupied manual review name has no planned target")
        if outcome["actual_location"] != outcome["source"]:
            errors.append(f"{label}: an occupied manual review name leaves the source in incoming")
        company = context["company_by_root"][outcome["source"]["root_id"]]
        expected = _manual_review_location(
            company, _basename(outcome["source"]["relative_path"]), context["prefix"]
        )
        if entry["location"] != expected:
            errors.append(f"{label}: existing manual review object is not at the expected path")
    return errors


# --------------------------------------------------------------------------- #
# Accepted preflight / history validation
# --------------------------------------------------------------------------- #

def _accepted_preflight_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    for entry in expectations["accepted_preflights"]:
        label = entry["scenario_id"]
        preflight = context["preflight_by_id"].get(label)
        batch = context["batches"].get(entry["batch_id"])
        if preflight is None:
            errors.append(f"{label}: accepted preflight scenario is missing from the preview fixture")
            continue
        if batch is None:
            errors.append(f"{label}: accepted batch {entry['batch_id']!r} is missing")
            continue
        if not preflight["expected"].get("accepted"):
            errors.append(f"{label}: the preview fixture does not mark this scenario accepted")
        if preflight["expected"].get("future_batch_id") != batch["batch_id"]:
            errors.append(f"{label}: future_batch_id does not match the real Batch payload")
        if preflight["selection_id"] != _selection_id(batch):
            errors.append(f"{label}: preflight selection does not match the batch selection")
        if preflight.get("execution_mode") != batch.get("execution_mode"):
            errors.append(f"{label}: preflight execution_mode does not match the batch")
        if preflight["expected"].get("rule_set_id") != batch["rule_set_id"]:
            errors.append(f"{label}: preflight RuleSet does not match the batch RuleSet")
        if batch.get("execution_mode") == "PREVIEWED":
            if preflight.get("preview_id") != batch.get("preview_id"):
                errors.append(f"{label}: preflight preview_id does not match the batch")
    expected_batches = {
        entry["batch_id"] for entry in expectations["accepted_preflights"]
    }
    if len(expected_batches) != 3:
        errors.append("exactly the three accepted preflight batches must be realised")
    return errors


def _history_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    for history in expectations["history"]:
        label = history["page_id"]
        items = [context["batches"][batch_id] for batch_id in history["batch_ids"]]
        if len(items) != len({item["batch_id"] for item in items}):
            errors.append(f"{label}: history repeats a batch id")
        keyed = [
            (item["created_at"], item["batch_id"]) for item in items
        ]
        expected = sorted(keyed, key=lambda pair: (pair[0], pair[1]), reverse=True)
        if keyed != expected:
            errors.append(f"{label}: history must be ordered created_at DESC, batch_id DESC")
    return errors


def coverage_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    known: set = set(context["batches"])
    known.update(entry["group_id"] for entry in expectations["duplicate_targets"])
    known.update(entry["object_id"] for entry in expectations["occupied_targets"])
    known.update(entry["object_id"] for entry in expectations["manual_review_occupied"])
    for batch in expectations["batches"]:
        known.update(spec["item_id"] for page in batch["pages"] for spec in row_specs(page))
    coverage = expectations["coverage"]
    for q_id, references in coverage.items():
        if q_id not in KNOWN_Q:
            errors.append(f"coverage references unknown Q id {q_id}")
        for reference in references:
            if reference not in known:
                errors.append(f"coverage {q_id} references unknown id {reference}")
    for q_id in KNOWN_Q:
        if q_id not in coverage:
            errors.append(f"coverage is missing {q_id}")
    return errors


def expectation_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    for batch_spec in expectations["batches"]:
        errors.extend(_batch_errors(batch_spec, context))
    seen_attempts: Dict[str, str] = {}
    for batch_spec in expectations["batches"]:
        for outcome in all_outcome_payloads(batch_spec, context):
            attempt = outcome["attempt_id"]
            if attempt in seen_attempts:
                errors.append(
                    f"attempt {attempt!r} is reused by "
                    f"{seen_attempts[attempt]} and {batch_spec['batch_id']}"
                )
            seen_attempts[attempt] = batch_spec["batch_id"]
    errors.extend(_accepted_preflight_errors(expectations, context))
    errors.extend(_history_errors(expectations, context))
    errors.extend(coverage_errors(expectations, context))
    errors.extend(inventory_errors(expectations, context))
    return errors


# --------------------------------------------------------------------------- #
# Schema validation
# --------------------------------------------------------------------------- #

def payload_errors(
    expectations: Dict[str, Any], context: Dict[str, Any], registry
) -> List[str]:
    errors: List[str] = []
    for batch_spec in expectations["batches"]:
        for page_spec in batch_spec["pages"]:
            payload = materialize_batch_page(batch_spec, page_spec, context)
            schema_errors, semantic = validate_fixture(registry, BATCH_SCHEMA, payload)
            errors.extend(
                f"{page_spec['page_id']}: {message}" for message in schema_errors + semantic
            )
            for outcome in payload["outcomes"]:
                outcome_errors, outcome_semantic = validate_fixture(
                    registry, OUTCOME_SCHEMA, outcome
                )
                errors.extend(
                    f"{page_spec['page_id']}/{outcome['item_id']}: {message}"
                    for message in outcome_errors + outcome_semantic
                )
        summary = materialize_batch_summary(batch_spec, context)
        schema_errors, semantic = validate_fixture(registry, BATCH_SUMMARY_SCHEMA, summary)
        errors.extend(
            f"{batch_spec['batch_id']}: {message}" for message in schema_errors + semantic
        )
    for history_spec in expectations["history"]:
        payload = materialize_history_page(history_spec, context)
        schema_errors, semantic = validate_fixture(registry, BATCH_PAGE_SCHEMA, payload)
        errors.extend(
            f"{history_spec['page_id']}: {message}" for message in schema_errors + semantic
        )
    return errors


# --------------------------------------------------------------------------- #
# Generic payload links
# --------------------------------------------------------------------------- #

def build_payloads(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    payloads: Dict[str, Any] = {}
    for selection_id, selection in context["selections"].items():
        payloads[f"selection:{selection_id}"] = selection["snapshot"]
        payloads[f"membership:{selection_id}"] = list(selection["members"].values())
    for alias, actor in context["actors"].items():
        payloads[f"actor:{alias}"] = actor
    for rule_set_id, rule_set in context["rule_sets"].items():
        payloads[f"rule_set:{rule_set_id}"] = rule_set
    for entry in context["preview"]["expectations"]["preflight"]:
        payloads[f"preflight:{entry['scenario_id']}"] = entry
    for batch_spec in expectations["batches"]:
        batch_id = batch_spec["batch_id"]
        payloads[f"batch:{batch_id}"] = materialize_batch_page(
            batch_spec, batch_spec["pages"][0], context
        )
        payloads[f"batch_rows:{batch_id}"] = all_outcome_payloads(batch_spec, context)
        payloads[f"batch_summary:{batch_id}"] = materialize_batch_summary(batch_spec, context)
        for page_spec in batch_spec["pages"]:
            payloads[f"batch_page_rows:{page_spec['page_id']}"] = materialize_batch_page(
                batch_spec, page_spec, context
            )["outcomes"]
        for outcome in all_outcome_payloads(batch_spec, context):
            payloads[f"outcome:{batch_id}:{outcome['item_id']}"] = outcome
    for record in inventory_records(expectations, context):
        payloads[f"inventory:{record['batch_id']}:{record['item_id']}"] = record
    for history_spec in expectations["history"]:
        payloads[f"history:{history_spec['page_id']}"] = materialize_history_page(
            history_spec, context
        )
    for entry in expectations["occupied_targets"]:
        payloads[f"existing_object:{entry['object_id']}"] = entry
    payloads["constants"] = expectations["constants"]
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
        elif relation == "membership_equals":
            source_ids = [member["item_id"] for member in source]
            target_ids = [member["item_id"] for member in target]
            if source_ids != target_ids:
                errors.append(f"{label}: membership {source_ids} != {target_ids}")
        elif relation not in ("equals", "not_equals", "length_equals", "membership_equals"):
            errors.append(f"{label}: unknown relation {relation!r}")
    return errors


# --------------------------------------------------------------------------- #
# Negative mutations
# --------------------------------------------------------------------------- #

def _apply_mutation(payload: Any, mutation: Dict[str, Any]) -> None:
    path = list(mutation["path"])
    if not path:
        raise ValueError("mutation path must not be empty")
    parent = payload
    for part in path[:-1]:
        parent = parent[part]
    last = path[-1]
    operation = mutation["operation"]
    if operation == "set":
        parent[last] = copy.deepcopy(mutation["value"])
    elif operation == "remove":
        del parent[last]
    elif operation == "append":
        parent[last].append(copy.deepcopy(mutation["value"]))
    else:  # pragma: no cover - guarded by the static fixture
        raise ValueError(f"unknown mutation operation {operation!r}")


def mutation_errors(
    expectations: Dict[str, Any], context: Dict[str, Any], registry
) -> List[str]:
    errors: List[str] = []
    for mutation in expectations["mutations"]:
        label = mutation["mutation_id"]
        mutated = copy.deepcopy(expectations)
        _apply_mutation(mutated, mutation)
        try:
            mutated_context = build_context(context["base"], mutated)
        except Exception as exc:  # noqa: BLE001 - a mutation may break resolution
            if not mutation.get("reason"):
                errors.append(f"{label}: mutation raised {type(exc).__name__}: {exc}")
            continue
        validator = mutation["validator"]
        if validator == "expectation":
            reported = expectation_errors(mutated, mutated_context)
        elif validator == "payload":
            reported = payload_errors(mutated, mutated_context, registry)
        elif validator == "inventory":
            reported = inventory_errors(mutated, mutated_context)
        else:  # pragma: no cover - guarded by the static fixture
            errors.append(f"{label}: unknown validator {validator!r}")
            continue
        if not reported:
            errors.append(
                f"{label}: expected the {validator} validator to reject the mutation "
                f"({mutation['reason']}) but it passed"
            )
    return errors


# --------------------------------------------------------------------------- #
# Generated public examples (documented preparation path)
# --------------------------------------------------------------------------- #

# (example id, kind, binding, canonical schema, output file, description).
EXAMPLE_BINDINGS: List[Dict[str, str]] = [
    {
        "id": "batch-atlas-direct-fresh-page1",
        "kind": "batch_page",
        "binding": "batch-atlas-direct-fresh:0",
        "schema": BATCH_SCHEMA,
        "file": "contracts/examples/sorting/batch-atlas-direct-fresh-page1.json",
        "description": "LT-03.4a: ACCEPTED 120-item DIRECT batch, page 1 of 100 PENDING outcomes.",
    },
    {
        "id": "batch-atlas-direct-fresh-page2",
        "kind": "batch_page",
        "binding": "batch-atlas-direct-fresh:1",
        "schema": BATCH_SCHEMA,
        "file": "contracts/examples/sorting/batch-atlas-direct-fresh-page2.json",
        "description": "LT-03.4a: ACCEPTED 120-item DIRECT batch, page 2 of 20 PENDING outcomes.",
    },
    {
        "id": "batch-atlas-previewed-fresh-page1",
        "kind": "batch_page",
        "binding": "batch-atlas-previewed-fresh:0",
        "schema": BATCH_SCHEMA,
        "file": "contracts/examples/sorting/batch-atlas-previewed-fresh-page1.json",
        "description": "LT-03.4a: RUNNING 120-item PREVIEWED batch, page 1 full with manual review outcomes.",
    },
    {
        "id": "batch-atlas-previewed-fresh-page2",
        "kind": "batch_page",
        "binding": "batch-atlas-previewed-fresh:1",
        "schema": BATCH_SCHEMA,
        "file": "contracts/examples/sorting/batch-atlas-previewed-fresh-page2.json",
        "description": "LT-03.4a: RUNNING batch page 2 with the last manual review rows plus PENDING and PROCESSING.",
    },
    {
        "id": "batch-atlas-same-user-session",
        "kind": "batch_page",
        "binding": "batch-atlas-same-user-session:0",
        "schema": BATCH_SCHEMA,
        "file": "contracts/examples/sorting/batch-atlas-same-user-session.json",
        "description": "LT-03.4a: COMPLETED_WITH_ISSUES EXPLICIT batch accepted from a new session of the same user.",
    },
    {
        "id": "batch-atlas-hetero",
        "kind": "batch_page",
        "binding": "batch-atlas-hetero:0",
        "schema": BATCH_SCHEMA,
        "file": "contracts/examples/sorting/batch-atlas-hetero.json",
        "description": "LT-03.4a: isolated heterogeneous accepted selection with safe renames, manual review, decisions and an occupied name.",
    },
    {
        "id": "batch-atlas-conflict",
        "kind": "batch_page",
        "binding": "batch-atlas-conflict:0",
        "schema": BATCH_SCHEMA,
        "file": "contracts/examples/sorting/batch-atlas-conflict.json",
        "description": "LT-03.4a: equal-priority RULE_CONFLICT moves to flat manual review without quarantine.",
    },
    {
        "id": "batch-atlas-sorted",
        "kind": "batch_page",
        "binding": "batch-atlas-sorted:0",
        "schema": BATCH_SCHEMA,
        "file": "contracts/examples/sorting/batch-atlas-sorted.json",
        "description": "LT-03.4a: COMPLETED batch where every outcome is a confirmed safe rename.",
    },
    {
        "id": "batch-atlas-technical",
        "kind": "batch_page",
        "binding": "batch-atlas-technical:0",
        "schema": BATCH_SCHEMA,
        "file": "contracts/examples/sorting/batch-atlas-technical.json",
        "description": "LT-03.4a: RECOVERY_REQUIRED batch with confirmed quarantine, per-file skips and unknown/known recovery.",
    },
    {
        "id": "batch-history-atlas-page1",
        "kind": "history",
        "binding": "history-atlas-batches-page1",
        "schema": BATCH_PAGE_SCHEMA,
        "file": "contracts/examples/sorting/batch-history-atlas-page1.json",
        "description": "LT-03.4a: BatchSummary history ordered created_at DESC, batch_id DESC.",
    },
]


def generated_examples(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    for binding in EXAMPLE_BINDINGS:
        kind = binding["kind"]
        if kind == "batch_page":
            batch_id, _, page_index = binding["binding"].partition(":")
            batch_spec = context["batches"][batch_id]
            payload = materialize_batch_page(
                batch_spec, batch_spec["pages"][int(page_index)], context
            )
        elif kind == "history":
            payload = materialize_history_page(
                context["histories"][binding["binding"]], context
            )
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
# Documented fixture-preparation command
# --------------------------------------------------------------------------- #

def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Materialize the WiseWay batch/outcome oracle examples."
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
