"""LT-03.3b finite preview and DIRECT/PREVIEWED preflight oracle.

``fixtures/synthetic/preview_preflight.json`` stores the finite, hand-authored
oracle for the non-mutating preview calculation and the pre-acceptance
``DIRECT``/``PREVIEWED`` checks that API section 7/8, QUEUE-04/05/06, DICT-12
and Q-023/026/027 describe.  It builds directly on:

* ``fixtures/synthetic/queue_selections.json`` - the immutable selection
  snapshots and their literal membership (the 120 / one / multiple selections);
* ``fixtures/synthetic/rule_expectations.json`` - the complete immutable
  version/rule/RuleSet/target definitions the preview rows are derived from.

The module is a *materializer and consistency checker*, not a runtime domain:

* every preview page, plan row, collision detail, error and preflight request is
  literal data bound to a canonical OAS schema pointer;
* the declared rows are cross-checked against the frozen selection membership
  (same item ids/revisions/sources) and against the selected rule's configured
  target directory and fixed stem plus last suffix;
* no matcher, priority resolver, target-name derivation, page counter or
  preflight algorithm is implemented - the values are declared and verified.

A documented preparation command regenerates the committed public examples::

    python tests/contract/contractlib/preview_preflight.py --write-examples
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:  # package import (tests, verify_contract.py)
    from . import queue_selections, rule_expectations, synthetic
    from .expectations import EXPECTED_OPERATIONS
    from .loading import load_contract
    from .schemas import validate_value
    from .search_expectations import allowed_error_codes
    from .semantic import validate_fixture
except ImportError:  # pragma: no cover - documented direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from contractlib import queue_selections, rule_expectations, synthetic  # type: ignore
    from contractlib.expectations import EXPECTED_OPERATIONS  # type: ignore
    from contractlib.loading import load_contract  # type: ignore
    from contractlib.schemas import validate_value  # type: ignore
    from contractlib.search_expectations import allowed_error_codes  # type: ignore
    from contractlib.semantic import validate_fixture  # type: ignore

EXPECTATIONS_RELATIVE = Path("fixtures") / "synthetic" / "preview_preflight.json"

PREVIEW_SCHEMA = "#/components/schemas/Preview"
PLAN_ROW_SCHEMA = "#/components/schemas/PlanRow"
RULE_SET_SCHEMA = "#/components/schemas/RuleSet"
SELECTION_SNAPSHOT_SCHEMA = "#/components/schemas/SelectionSnapshot"
ERROR_SCHEMA = "#/components/schemas/ErrorResponse"
BATCH_REQUEST_SCHEMA = "#/components/schemas/BatchCreateRequest"
PREVIEW_REQUEST_SCHEMA = "#/components/schemas/PreviewCreateRequest"

KNOWN_Q = ("Q-023", "Q-026", "Q-027")
PREDICTIONS = ("WILL_MOVE", "WILL_MANUAL_REVIEW", "REQUIRES_DECISION", "NOT_READY")
COLLISION_KINDS = ("EXISTING_TARGET", "DUPLICATE_PLAN_TARGET", "MANUAL_REVIEW_NAME")
REASON_CODES = (
    None,
    "NO_SCENARIO",
    "RULE_CONFLICT",
    "TARGET_OCCUPIED",
    "MANUAL_REVIEW_NAME_OCCUPIED",
)
KNOWN_OPERATIONS = set(EXPECTED_OPERATIONS.values())
DIRECT = "DIRECT"
PREVIEWED = "PREVIEWED"
BATCH_OPERATION = "createSortingBatch"
PREVIEW_OPERATION = "createSortingPreview"

# Accepted outcomes are declared but the Batch DTO result belongs to LT-03.4a.
ACCEPTED_STATUS = 202


# --------------------------------------------------------------------------- #
# Loading and context
# --------------------------------------------------------------------------- #

def expectations_path(root: Optional[Path] = None) -> Path:
    return (root or synthetic.repo_root()) / EXPECTATIONS_RELATIVE


def load_expectations(root: Optional[Path] = None) -> Dict[str, Any]:
    return synthetic.load_json(expectations_path(root))


def _linked_selection(
    binding: Dict[str, Any], queue_ctx: Dict[str, Any]
) -> Dict[str, Any]:
    scenario = queue_ctx["scenarios"][binding["from_queue_scenario"]]
    profile = queue_ctx["profiles"][scenario["profile_id"]]
    full = {
        item["item_id"]: item
        for item in queue_selections.materialize_membership(profile, queue_ctx)
    }
    members: List[Dict[str, Any]] = []
    for member in queue_selections.materialize_selection_members(scenario, queue_ctx):
        item = full[member["item_id"]]
        members.append(
            {
                "item_id": item["item_id"],
                "item_revision": item["item_revision"],
                "filename": item["filename"],
                "location": item["source"],
                "company_id": item["company_id"],
                "size_bytes": item["size_bytes"],
                "modified_at": item["modified_at"],
                "source_ready": bool(item["selectable"]),
            }
        )
    snapshot = queue_selections.materialize_selection_snapshot(scenario, queue_ctx)
    return {
        "selection_id": snapshot["selection_id"],
        "company_id": snapshot["company_id"],
        "mode": snapshot["mode"],
        "owner": binding["owner"],
        "snapshot": snapshot,
        "members": {member["item_id"]: member for member in members},
        "member_order": [member["item_id"] for member in members],
        "source": "queue_selections.json",
    }


def _isolated_selection(entry: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = dict(entry["snapshot"])
    members = {}
    for member in entry["members"]:
        record = dict(member)
        record.setdefault("company_id", snapshot["company_id"])
        members[record["item_id"]] = record
    return {
        "selection_id": snapshot["selection_id"],
        "company_id": snapshot["company_id"],
        "mode": snapshot["mode"],
        "owner": entry["owner"],
        "snapshot": snapshot,
        "members": members,
        "member_order": [member["item_id"] for member in entry["members"]],
        "source": "preview_preflight.json",
    }


def build_context(
    root: Optional[Path] = None, expectations: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Load the contract, the linked fixtures and the literal lookup tables."""
    base = Path(root) if root is not None else synthetic.repo_root()
    if expectations is None:
        expectations = load_expectations(base)
    manifest = synthetic.load_manifest(synthetic.manifest_path(base))
    document = load_contract(base / "contracts" / "openapi" / "wiseway-v1.yaml")

    queue_expectations = queue_selections.load_expectations(base)
    queue_ctx = queue_selections.build_context(base, queue_expectations)
    rule_exp = rule_expectations.load_expectations(base)
    rule_ctx = rule_expectations.build_context(base, rule_exp)

    selections: Dict[str, Dict[str, Any]] = {}
    for binding in expectations["selections"]:
        if "from_queue_scenario" in binding:
            selection = _linked_selection(binding, queue_ctx)
        else:
            selection = _isolated_selection(binding)
        selections[selection["selection_id"]] = selection

    rule_sets = {
        rule_set["rule_set_id"]: rule_set for rule_set in rule_exp["rule_sets"]
    }
    raw_actors = rule_ctx["actors"]
    actors = {
        alias: raw_actors[user_id]
        for alias, user_id in expectations["actors"].items()
        if user_id in raw_actors
    }
    errors = {entry["error_id"]: entry for entry in expectations["errors"]}
    preview_pages = {
        entry["page_id"]: entry for entry in expectations["previews"]
    }
    preview_groups: Dict[str, List[Dict[str, Any]]] = {}
    for entry in expectations["previews"]:
        preview_groups.setdefault(entry["preview_id"], []).append(entry)

    return {
        "base": base,
        "manifest": manifest,
        "document": document,
        "expectations": expectations,
        "queue_expectations": queue_expectations,
        "queue": queue_ctx,
        "rule_expectations": rule_exp,
        "rule_context": rule_ctx,
        "actors": actors,
        "companies": {
            alias: entry
            for alias, entry in expectations["companies"].items()
        },
        "prefix": expectations["target_display_prefix"],
        "targets": rule_ctx["targets"],
        "versions": rule_ctx["versions"],
        "rule_sets": rule_sets,
        "selections": selections,
        "errors": errors,
        "preview_pages": preview_pages,
        "preview_groups": preview_groups,
        "previews": {
            preview_id: {
                "preview_id": preview_id,
                "selection_id": pages[0]["selection_id"],
                "company_id": selections[pages[0]["selection_id"]]["company_id"],
                "rule_set_id": pages[0]["rule_set_id"],
            }
            for preview_id, pages in preview_groups.items()
        },
        "manual_review": expectations["manual_review"],
        "page_limit": expectations["constants"]["preview_page_limit"],
    }


# --------------------------------------------------------------------------- #
# Materialization (literal ids only, never a matcher)
# --------------------------------------------------------------------------- #

def _repeat_rows(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index in range(spec["index_start"], spec["index_end"] + 1):
        item_id = f"{spec['item_prefix']}{index:0{spec['index_width']}d}"
        rows.append(
            {
                "item_id": item_id,
                "item_revision": spec.get("item_revision"),
                "predicted_state": spec["predicted_state"],
                "reason_code": spec.get("reason_code"),
                "target": copy.deepcopy(spec.get("target")),
                "matched_rules": copy.deepcopy(spec.get("matched_rules", [])),
                "selected_rule": copy.deepcopy(spec.get("selected_rule")),
                "collision": copy.deepcopy(spec.get("collision")),
            }
        )
    return rows


def row_specs(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Expand a page's literal row declarations (``$repeat_rows`` or a list)."""
    rows = entry["rows"]
    if isinstance(rows, dict) and set(rows.keys()) == {"$repeat_rows"}:
        return _repeat_rows(rows["$repeat_rows"])
    return [copy.deepcopy(row) for row in rows]


def materialize_plan_row(
    spec: Dict[str, Any], member: Dict[str, Any]
) -> Dict[str, Any]:
    return {
        "item_id": member["item_id"],
        "item_revision": (
            spec["item_revision"]
            if spec.get("item_revision") is not None
            else member["item_revision"]
        ),
        "source": dict(member["location"]),
        "filename": member["filename"],
        "company_id": member["company_id"],
        "predicted_state": spec["predicted_state"],
        "reason_code": spec.get("reason_code"),
        "target": copy.deepcopy(spec.get("target")),
        "matched_rules": [dict(ref) for ref in spec.get("matched_rules", [])],
        "selected_rule": (
            dict(spec["selected_rule"]) if spec.get("selected_rule") else None
        ),
        "collision": copy.deepcopy(spec.get("collision")),
    }


def materialize_preview(entry: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    selection = context["selections"][entry["selection_id"]]
    rule_set = context["rule_sets"][entry["rule_set_id"]]
    rows = [
        materialize_plan_row(spec, selection["members"][spec["item_id"]])
        for spec in row_specs(entry)
    ]
    return {
        "preview_id": entry["preview_id"],
        "selection_id": entry["selection_id"],
        "company_id": selection["company_id"],
        "rule_set": {
            "rule_set_id": rule_set["rule_set_id"],
            "company_id": rule_set["company_id"],
            "members": [dict(member) for member in rule_set["members"]],
        },
        "created_at": entry["created_at"],
        "expires_at": entry["expires_at"],
        "total": entry["total"],
        "counts": dict(entry["counts"]),
        "rows": rows,
        "next_cursor": entry.get("next_cursor"),
    }


def materialize_error(entry: Dict[str, Any]) -> Dict[str, Any]:
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


def materialize_request(entry: Dict[str, Any]) -> Dict[str, Any]:
    operation = entry["operation"]
    if operation == BATCH_OPERATION:
        request: Dict[str, Any] = {
            "selection_id": entry["selection_id"],
            "execution_mode": entry["execution_mode"],
        }
        if entry["execution_mode"] == PREVIEWED:
            request["preview_id"] = entry["preview_id"]
        return request
    if operation == PREVIEW_OPERATION:
        return {"selection_id": entry["selection_id"]}
    raise ValueError(f"unknown preflight operation {operation!r}")


def materialize_invalid_request(entry: Dict[str, Any]) -> Any:
    return copy.deepcopy(entry["value"])


# --------------------------------------------------------------------------- #
# Rule / target lookups (literal declarations, never a match)
# --------------------------------------------------------------------------- #

def _rule_entry(context: Dict[str, Any], reference: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    version = context["versions"].get(reference.get("version_id"))
    if version is None:
        return None
    for rule in version.get("rules", []):
        if rule["rule_id"] == reference.get("rule_id"):
            return rule
    return None


def _last_suffix(filename: str) -> str:
    """The DICT-05 last extension suffix (``.env``/``README``/``name.`` have none)."""
    dot = filename.rfind(".")
    if dot <= 0 or dot == len(filename) - 1:
        return ""
    return filename[dot:]


def _target_tuple(context: Dict[str, Any], rule: Dict[str, Any]) -> Tuple[str, str, str]:
    target = context["targets"][rule["target_id"]]
    return (target["root_id"], target["relative_directory"], rule["target_stem"])


def _derive_target(
    context: Dict[str, Any], rule: Dict[str, Any], filename: str
) -> Dict[str, str]:
    target = context["targets"][rule["target_id"]]
    relative_path = (
        target["relative_directory"] + "/" + rule["target_stem"] + _last_suffix(filename)
    )
    return {
        "root_id": target["root_id"],
        "relative_path": relative_path,
        "display_path": context["prefix"] + "/" + relative_path,
    }


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _seconds_between(first: str, second: str) -> float:
    return (_instant(second) - _instant(first)).total_seconds()


# --------------------------------------------------------------------------- #
# Row / collision validation
# --------------------------------------------------------------------------- #

def _reference_errors(
    label: str, row: Dict[str, Any], context: Dict[str, Any], rule_set: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    references = list(row.get("matched_rules") or [])
    selected = row.get("selected_rule")
    member_pairs = {
        (member["dictionary_id"], member["version_id"]) for member in rule_set["members"]
    }
    keys = [(ref["dictionary_id"], ref["rule_id"]) for ref in references]
    if keys != sorted(keys):
        errors.append(f"{label}: matched_rules are not sorted by dictionary_id then rule_id")
    for reference in references + ([selected] if isinstance(selected, dict) else []):
        if reference.get("version_id") is None:
            errors.append(
                f"{label}: preview rule reference must be a published version, "
                "never a null draft"
            )
        pair = (reference.get("dictionary_id"), reference.get("version_id"))
        if pair not in member_pairs:
            errors.append(
                f"{label}: rule reference {pair!r} is not a member of the preview RuleSet"
            )
        if _rule_entry(context, reference) is None:
            errors.append(
                f"{label}: undefined rule reference {reference.get('rule_id')!r}"
            )
    if isinstance(selected, dict) and selected not in references:
        errors.append(f"{label}: selected_rule is not one of matched_rules")
    return errors


def _collision_errors(
    label: str,
    row: Dict[str, Any],
    context: Dict[str, Any],
) -> List[str]:
    errors: List[str] = []
    collision = row.get("collision")
    if not isinstance(collision, dict):
        errors.append(f"{label}: REQUIRES_DECISION must carry collision details")
        return errors
    kind = collision.get("kind")
    if kind not in COLLISION_KINDS:
        errors.append(f"{label}: unknown collision kind {kind!r}")
    source_metadata = collision.get("source_metadata")
    existing = collision.get("existing_target_metadata")
    ids = collision.get("conflicting_item_ids")
    if not isinstance(source_metadata, dict):
        errors.append(f"{label}: collision.source_metadata must be present")
    else:
        if source_metadata.get("filename") != row["filename"]:
            errors.append(f"{label}: collision source filename does not match the row")
        if source_metadata.get("location") != row["source"]:
            errors.append(f"{label}: collision source location does not match the row")
    if not isinstance(ids, list):
        errors.append(f"{label}: collision.conflicting_item_ids must be a list")

    if kind == "EXISTING_TARGET":
        if row["reason_code"] != "TARGET_OCCUPIED":
            errors.append(f"{label}: EXISTING_TARGET reason must be TARGET_OCCUPIED")
        if not isinstance(existing, dict):
            errors.append(f"{label}: EXISTING_TARGET needs existing_target_metadata")
        elif existing.get("location") != row.get("target"):
            errors.append(
                f"{label}: existing target metadata is not the planned target"
            )
        if ids:
            errors.append(f"{label}: EXISTING_TARGET conflicting_item_ids must be empty")
        if not isinstance(row.get("target"), dict):
            errors.append(f"{label}: EXISTING_TARGET must carry the planned target")
    elif kind == "DUPLICATE_PLAN_TARGET":
        if row["reason_code"] != "TARGET_OCCUPIED":
            errors.append(
                f"{label}: DUPLICATE_PLAN_TARGET reason must be TARGET_OCCUPIED"
            )
        if existing is not None:
            errors.append(
                f"{label}: DUPLICATE_PLAN_TARGET existing_target_metadata must be null"
            )
        if not ids:
            errors.append(
                f"{label}: DUPLICATE_PLAN_TARGET must list every participant item id"
            )
        elif row["item_id"] not in ids:
            errors.append(
                f"{label}: the row item is missing from conflicting_item_ids"
            )
        if not isinstance(row.get("target"), dict):
            errors.append(f"{label}: DUPLICATE_PLAN_TARGET must carry the shared target")
    elif kind == "MANUAL_REVIEW_NAME":
        if row["reason_code"] != "MANUAL_REVIEW_NAME_OCCUPIED":
            errors.append(
                f"{label}: MANUAL_REVIEW_NAME reason must be MANUAL_REVIEW_NAME_OCCUPIED"
            )
        if ids:
            errors.append(f"{label}: MANUAL_REVIEW_NAME conflicting_item_ids must be empty")
        if row.get("target") is not None:
            errors.append(f"{label}: MANUAL_REVIEW_NAME target must be null")
        if not isinstance(existing, dict):
            errors.append(f"{label}: MANUAL_REVIEW_NAME needs existing_target_metadata")
        else:
            manual = context["manual_review"].get(row["company_id"])
            if manual is None:
                errors.append(f"{label}: no declared manual review directory")
            else:
                expected = (
                    manual["relative_directory"] + "/" + row["filename"]
                )
                location = existing.get("location") or {}
                if location.get("relative_path") != expected:
                    errors.append(
                        f"{label}: occupying manual review file is not "
                        f"{expected!r}"
                    )
    return errors


def _row_errors(
    label: str,
    row: Dict[str, Any],
    context: Dict[str, Any],
    selection: Dict[str, Any],
    rule_set: Dict[str, Any],
) -> List[str]:
    errors: List[str] = []
    predicted = row["predicted_state"]
    reason = row.get("reason_code")
    if predicted not in PREDICTIONS:
        errors.append(f"{label}: unknown predicted_state {predicted!r}")
    if reason not in REASON_CODES:
        errors.append(f"{label}: unknown reason_code {reason!r}")
    errors.extend(_reference_errors(label, row, context, rule_set))

    member = selection["members"][row["item_id"]]
    references = list(row.get("matched_rules") or [])
    selected = row.get("selected_rule")

    if predicted == "WILL_MOVE":
        if reason is not None:
            errors.append(f"{label}: WILL_MOVE must have a null reason_code")
        if row.get("collision") is not None:
            errors.append(f"{label}: WILL_MOVE must not carry collision details")
        if not isinstance(selected, dict):
            errors.append(f"{label}: WILL_MOVE must select a rule")
        if not isinstance(row.get("target"), dict):
            errors.append(f"{label}: WILL_MOVE must carry a target")
        elif isinstance(selected, dict):
            rule = _rule_entry(context, selected)
            if rule is not None and _derive_target(context, rule, row["filename"]) != row["target"]:
                errors.append(
                    f"{label}: target does not equal the selected rule's "
                    "configured directory + fixed stem + last suffix"
                )
        if references:
            resolved = [_rule_entry(context, reference) for reference in references]
            selected_rule = (
                _rule_entry(context, selected) if isinstance(selected, dict) else None
            )
            if all(rule is not None for rule in resolved) and selected_rule is not None:
                priorities = [rule["priority"] for rule in resolved]
                if selected_rule["priority"] != min(priorities):
                    errors.append(
                        f"{label}: selected_rule is not the minimum-priority match"
                    )
                equal = [
                    reference
                    for reference, rule in zip(references, resolved)
                    if rule["priority"] == min(priorities)
                ]
                if len(equal) > 1:
                    expected = sorted(
                        ((ref["dictionary_id"], ref["rule_id"]) for ref in equal)
                    )[0]
                    chosen = (selected["dictionary_id"], selected["rule_id"])
                    if chosen != expected:
                        errors.append(
                            f"{label}: equal-priority attribution is not stable "
                            "dictionary_id then rule_id"
                        )
    elif predicted == "WILL_MANUAL_REVIEW":
        if reason not in ("NO_SCENARIO", "RULE_CONFLICT"):
            errors.append(
                f"{label}: manual review reason must be NO_SCENARIO or RULE_CONFLICT"
            )
        if row.get("target") is not None:
            errors.append(f"{label}: manual review must not carry a target")
        if row.get("collision") is not None:
            errors.append(f"{label}: manual review must not carry collision details")
        if reason == "NO_SCENARIO":
            if references or selected is not None:
                errors.append(f"{label}: NO_SCENARIO must not match any rule")
        elif reason == "RULE_CONFLICT":
            if len(references) < 2:
                errors.append(f"{label}: RULE_CONFLICT needs at least two matched rules")
            if selected is not None:
                errors.append(f"{label}: RULE_CONFLICT must not select a rule")
            resolved = [_rule_entry(context, reference) for reference in references]
            if all(rule is not None for rule in resolved):
                targets = {_target_tuple(context, rule) for rule in resolved}
                if len(targets) < 2:
                    errors.append(
                        f"{label}: RULE_CONFLICT matched rules share one final target"
                    )
                priorities = {rule["priority"] for rule in resolved}
                if len(priorities) != 1:
                    errors.append(
                        f"{label}: RULE_CONFLICT must be a conflict of equal minimal priority"
                    )
    elif predicted == "REQUIRES_DECISION":
        if reason not in ("TARGET_OCCUPIED", "MANUAL_REVIEW_NAME_OCCUPIED"):
            errors.append(
                f"{label}: REQUIRES_DECISION reason must be TARGET_OCCUPIED or "
                "MANUAL_REVIEW_NAME_OCCUPIED"
            )
        errors.extend(_collision_errors(label, row, context))
    elif predicted == "NOT_READY":
        if member.get("source_ready") is not False:
            errors.append(
                f"{label}: NOT_READY requires a source that is no longer ready"
            )
        if row.get("target") is not None:
            errors.append(f"{label}: NOT_READY must not carry a target")
        if row.get("collision") is not None:
            errors.append(f"{label}: NOT_READY must not carry collision details")
    else:
        # Remaining predictions are not expected by this finite oracle.
        errors.append(f"{label}: unsupported predicted_state {predicted!r}")
    return errors


# --------------------------------------------------------------------------- #
# Preview page-group validation
# --------------------------------------------------------------------------- #

def _preview_group_errors(
    preview_id: str, pages: List[Dict[str, Any]], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    label = preview_id
    first = pages[0]
    selection = context["selections"].get(first["selection_id"])
    if selection is None:
        return [f"{label}: unknown selection_id {first['selection_id']!r}"]
    rule_set = context["rule_sets"].get(first["rule_set_id"])
    if rule_set is None:
        return [f"{label}: unknown rule_set_id {first['rule_set_id']!r}"]
    if rule_set["company_id"] != selection["company_id"]:
        errors.append(f"{label}: preview RuleSet belongs to another company")

    for key in (
        "selection_id",
        "rule_set_id",
        "preview_id",
        "owner",
        "created_at",
        "expires_at",
        "total",
        "counts",
    ):
        for page in pages:
            if page.get(key) != first.get(key):
                errors.append(
                    f"{label}: page {page['page_id']} disagrees on {key}"
                )

    total = first["total"]
    if total != selection["snapshot"]["selected_count"]:
        errors.append(
            f"{label}: preview total {total} != selection selected_count "
            f"{selection['snapshot']['selected_count']}"
        )
    counts = first["counts"]
    first_four = (
        counts["will_move"]
        + counts["will_manual_review"]
        + counts["requires_decision"]
        + counts["not_ready"]
    )
    if first_four != total:
        errors.append(
            f"{label}: the four main PlanCounts sum to {first_four}, not total {total}"
        )
    if counts["rule_conflicts"] + counts["no_scenario"] > total:
        errors.append(f"{label}: reason counts exceed total")

    expires = first["expires_at"]
    selection_expires = selection["snapshot"]["expires_at"]
    if _instant(expires) > _instant(selection_expires):
        errors.append(
            f"{label}: preview expires_at {expires} is after selection expires_at "
            f"{selection_expires}"
        )
    if _instant(first["created_at"]) < _instant(selection["snapshot"]["created_at"]):
        errors.append(f"{label}: preview was created before its selection snapshot")

    rows: List[Dict[str, Any]] = []
    seen: set = set()
    for page in pages:
        materialized = materialize_preview(page, context)["rows"]
        if len(materialized) > context["page_limit"]:
            errors.append(
                f"{label}: page {page['page_id']} has {len(materialized)} rows, "
                f"above the {context['page_limit']}-row limit"
            )
        for row in materialized:
            if row["item_id"] in seen:
                errors.append(
                    f"{label}: item {row['item_id']} appears on more than one page"
                )
            seen.add(row["item_id"])
            rows.append(row)

    expected_ids = selection["member_order"]
    if sorted(seen) != sorted(expected_ids):
        errors.append(
            f"{label}: preview rows do not cover exactly the frozen selection "
            "membership"
        )
    if len(expected_ids) > context["page_limit"]:
        if first.get("next_cursor") is None:
            errors.append(
                f"{label}: a selection above one page must continue with a cursor"
            )
        if len(materialize_preview(first, context)["rows"]) != context["page_limit"]:
            errors.append(
                f"{label}: the first page of a larger preview must be full"
            )
    else:
        if first.get("next_cursor") is not None:
            errors.append(f"{label}: a single-page preview must not carry a cursor")
    last = pages[-1]
    if last.get("next_cursor") is not None:
        errors.append(f"{label}: the last preview page must not carry a cursor")

    for row in rows:
        member = selection["members"].get(row["item_id"])
        if member is None:
            continue
        if row["item_revision"] != member["item_revision"]:
            errors.append(
                f"{label}/{row['item_id']}: preview revision {row['item_revision']} "
                f"!= frozen selection revision {member['item_revision']}"
            )
        if row["source"] != member["location"]:
            errors.append(
                f"{label}/{row['item_id']}: preview source != frozen selection source"
            )
        if row["filename"] != member["filename"]:
            errors.append(
                f"{label}/{row['item_id']}: preview filename != frozen selection filename"
            )
        if row["company_id"] != selection["company_id"]:
            errors.append(
                f"{label}/{row['item_id']}: preview row belongs to another company"
            )
        errors.extend(
            _row_errors(
                f"{label}/{row['item_id']}", row, context, selection, rule_set
            )
        )

    for predicted, key in (
        ("WILL_MOVE", "will_move"),
        ("WILL_MANUAL_REVIEW", "will_manual_review"),
        ("REQUIRES_DECISION", "requires_decision"),
        ("NOT_READY", "not_ready"),
    ):
        actual = sum(1 for row in rows if row["predicted_state"] == predicted)
        if counts[key] != actual:
            errors.append(
                f"{label}: counts.{key} {counts[key]} != {actual} materialized rows"
            )
    for reason, key in (("NO_SCENARIO", "no_scenario"), ("RULE_CONFLICT", "rule_conflicts")):
        actual = sum(1 for row in rows if row["reason_code"] == reason)
        if counts[key] != actual:
            errors.append(
                f"{label}: counts.{key} {counts[key]} != {actual} materialized rows"
            )

    errors.extend(_duplicate_target_errors(label, rows, context))
    return errors


def _duplicate_target_errors(
    label: str, rows: List[Dict[str, Any]], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    duplicates: Dict[Any, List[Dict[str, Any]]] = {}
    for row in rows:
        collision = row.get("collision")
        if not isinstance(collision, dict):
            continue
        if collision.get("kind") != "DUPLICATE_PLAN_TARGET":
            continue
        key = (
            row["target"]["root_id"],
            row["target"]["relative_path"],
        ) if isinstance(row.get("target"), dict) else None
        duplicates.setdefault(key, []).append(row)
    for key, participants in duplicates.items():
        ids = sorted(row["item_id"] for row in participants)
        declared = participants[0]["collision"].get("conflicting_item_ids") or []
        if sorted(declared) != ids:
            errors.append(
                f"{label}: DUPLICATE_PLAN_TARGET participants {ids} do not match "
                f"conflicting_item_ids {sorted(declared)}"
            )
        if len(participants) < 2:
            errors.append(
                f"{label}: DUPLICATE_PLAN_TARGET {key} has fewer than two participants"
            )
    return errors


# --------------------------------------------------------------------------- #
# Preflight / post-acceptance validation
# --------------------------------------------------------------------------- #

def _preflight_errors(entry: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = entry["scenario_id"]
    operation = entry["operation"]
    if operation not in KNOWN_OPERATIONS:
        errors.append(f"{label}: unknown operationId {operation!r}")
    if not entry.get("precondition"):
        errors.append(f"{label}: precondition must not be empty")
    if not entry.get("reason"):
        errors.append(f"{label}: reason (manual trace) must not be empty")
    for key in ("owner", "requesting_actor"):
        if entry.get(key) not in context["actors"]:
            errors.append(f"{label}: {key} does not resolve to an auth fixture actor")
    expected = entry["expected"]
    if expected.get("accepted"):
        if expected.get("status") != ACCEPTED_STATUS:
            errors.append(f"{label}: an accepted batch must expect 202")
        if expected.get("code") is not None:
            errors.append(f"{label}: an accepted batch must not carry an error code")
        if expected.get("batch_created") is not True:
            errors.append(f"{label}: an accepted batch must declare batch_created=true")
        if expected.get("file_operations") is not False:
            errors.append(
                f"{label}: acceptance happens before any file operation"
            )
        if not expected.get("future_batch_id"):
            errors.append(
                f"{label}: an accepted batch must state the expected future batch id"
            )
        if expected.get("rule_set_id") not in context["rule_sets"]:
            errors.append(f"{label}: an accepted batch must bind a declared RuleSet")
        if "batch" in entry:
            errors.append(
                f"{label}: the Batch payload result belongs to LT-03.4a"
            )
        if entry.get("error_id") is not None:
            errors.append(f"{label}: an accepted batch must not reference an error")
        if entry["new_session"] and entry["owner"] != entry["requesting_actor"]:
            errors.append(f"{label}: a new session must be the same user")
        if entry["execution_mode"] == PREVIEWED:
            selection = context["selections"].get(entry["selection_id"])
            preview = context["previews"].get(entry.get("preview_id"))
            if preview is None:
                errors.append(f"{label}: PREVIEWED needs a resolvable preview_id")
            elif selection is None:
                errors.append(f"{label}: PREVIEWED needs a resolvable selection_id")
            elif preview["selection_id"] != selection["selection_id"]:
                errors.append(f"{label}: PREVIEWED preview does not match the selection")
        if entry["execution_mode"] == DIRECT and entry.get("preview_id") is not None:
            errors.append(f"{label}: DIRECT must not carry a preview_id")
    else:
        if expected.get("batch_created") is not False:
            errors.append(f"{label}: a rejected preflight must not create a batch")
        if expected.get("file_operations") is not False:
            errors.append(
                f"{label}: a rejected preflight must not touch the filesystem"
            )
        if expected.get("future_batch_id") is not None:
            errors.append(f"{label}: a rejected preflight has no future batch id")
        status = expected.get("status")
        code = expected.get("code")
        allowed = allowed_error_codes(context["document"], operation, status)
        if code not in allowed:
            errors.append(
                f"{label}: code {code!r} is not declared by {operation!r} for HTTP {status}"
            )
        error_entry = context["errors"].get(entry.get("error_id"))
        if error_entry is None:
            errors.append(f"{label}: a rejected preflight must reference an error")
        elif (
            error_entry["operation"] != operation
            or error_entry["status"] != status
            or error_entry["code"] != code
        ):
            errors.append(
                f"{label}: the referenced error does not match operation/status/code"
            )
        if "batch" in entry:
            errors.append(f"{label}: a rejected preflight must not embed a batch")
        cause = entry.get("cause")
        expired = entry.get("expired") or {}
        if code == "SELECTION_CHANGED":
            if operation == BATCH_OPERATION and entry["execution_mode"] != DIRECT:
                errors.append(
                    f"{label}: SELECTION_CHANGED is the DIRECT source preflight"
                )
            if cause not in ("source_changed", "source_missing"):
                errors.append(f"{label}: SELECTION_CHANGED needs a source cause")
        elif code == "STALE_PREVIEW":
            if operation == BATCH_OPERATION and entry["execution_mode"] != PREVIEWED:
                errors.append(f"{label}: STALE_PREVIEW is the PREVIEWED preflight")
            if cause not in ("source_changed", "rules_changed", "target_changed", "preview_ttl"):
                errors.append(f"{label}: STALE_PREVIEW needs a stale dependency cause")
        elif code == "SELECTION_EXPIRED":
            if not expired.get("selection"):
                errors.append(f"{label}: SELECTION_EXPIRED needs an expired selection")
        elif code == "INVALID_STATE":
            if not (entry.get("company_mismatch") or entry.get("pairing_mismatch")):
                errors.append(
                    f"{label}: INVALID_STATE needs a company or pairing mismatch"
                )
        elif code == "NOT_FOUND":
            if cause not in ("unknown_selection", "unknown_preview"):
                errors.append(f"{label}: NOT_FOUND needs an unknown id cause")
        elif code == "FORBIDDEN":
            if entry["owner"] == entry["requesting_actor"]:
                errors.append(f"{label}: FORBIDDEN needs another user")
    return errors


def _post_acceptance_errors(entry: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = entry["outcome_id"]
    if not entry.get("reason"):
        errors.append(f"{label}: reason (manual trace) must not be empty")
    if entry.get("batch_created") is not True:
        errors.append(f"{label}: the batch is already accepted")
    if entry.get("global_refusal") is not False:
        errors.append(f"{label}: a per-file outcome is not a global refusal")
    status = entry.get("http_status")
    if isinstance(status, int) and 400 <= status < 500:
        errors.append(
            f"{label}: a per-file outcome is not an HTTP preflight rejection"
        )
    if entry.get("operation") not in KNOWN_OPERATIONS:
        errors.append(f"{label}: unknown operationId")
    document = context["document"]
    states = set(document["components"]["schemas"]["OutcomeState"]["enum"])
    reasons = set(
        document["components"]["schemas"]["OutcomeReasonCode"]["anyOf"][0]["enum"]
    )
    if entry.get("state") not in states:
        errors.append(f"{label}: unknown OutcomeState {entry.get('state')!r}")
    if entry.get("reason_code") not in reasons:
        errors.append(f"{label}: unknown OutcomeReasonCode {entry.get('reason_code')!r}")
    return errors


# --------------------------------------------------------------------------- #
# Aggregate expectation check
# --------------------------------------------------------------------------- #

def coverage_errors(expectations: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    known: set = set()
    known.update(context["selections"])
    known.update(entry["page_id"] for entry in expectations["previews"])
    known.update(entry["scenario_id"] for entry in expectations["preflight"])
    known.update(entry["outcome_id"] for entry in expectations["post_acceptance"])
    known.update(entry["error_id"] for entry in expectations["errors"])
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

    # Declared rule sets used by previews must be full and resolved.
    for entry in expectations["previews"]:
        rule_set = context["rule_sets"].get(entry["rule_set_id"])
        if rule_set is None:
            errors.append(f"{entry['page_id']}: unknown rule_set_id")
            continue
        if not rule_set.get("members"):
            errors.append(f"{entry['page_id']}: preview RuleSet has no members")
        for member in rule_set["members"]:
            if not member.get("version_id"):
                errors.append(
                    f"{entry['page_id']}: preview RuleSet member has a null draft version"
                )
    published = context["rule_sets"].get("rule-set-atlas-published")
    if published is None:
        errors.append("the accepted rule-set-atlas-published is missing")
    else:
        linked = [
            entry
            for entry in expectations["previews"]
            if entry["rule_set_id"] == "rule-set-atlas-published"
        ]
        if not linked:
            errors.append(
                "at least one preview must use the accepted published RuleSet"
            )

    for preview_id, pages in context["preview_groups"].items():
        errors.extend(_preview_group_errors(preview_id, pages, context))

    for entry in expectations["preflight"]:
        errors.extend(_preflight_errors(entry, context))
    for entry in expectations["post_acceptance"]:
        errors.extend(_post_acceptance_errors(entry, context))

    # Preflight failures must resolve their selection/preview precondition.
    for entry in expectations["preflight"]:
        selection = context["selections"].get(entry.get("selection_id"))
        preview = (
            context["previews"].get(entry["preview_id"])
            if entry.get("preview_id")
            else None
        )
        if entry.get("company_mismatch"):
            if selection is None or preview is None:
                errors.append(
                    f"{entry['scenario_id']}: company mismatch needs both objects"
                )
            elif selection["company_id"] == preview["company_id"]:
                errors.append(
                    f"{entry['scenario_id']}: declared company mismatch is not one"
                )
        if entry.get("pairing_mismatch"):
            if selection is None or preview is None:
                errors.append(
                    f"{entry['scenario_id']}: pairing mismatch needs both objects"
                )
            elif preview["selection_id"] == selection["selection_id"]:
                errors.append(
                    f"{entry['scenario_id']}: declared pairing mismatch is not one"
                )
    return errors


# --------------------------------------------------------------------------- #
# Schema validation and negative mutations
# --------------------------------------------------------------------------- #

def payload_errors(
    expectations: Dict[str, Any], context: Dict[str, Any], registry
) -> List[str]:
    errors: List[str] = []
    for selection_id, selection in context["selections"].items():
        schema_errors, semantic = validate_fixture(
            registry, SELECTION_SNAPSHOT_SCHEMA, selection["snapshot"]
        )
        errors.extend(
            f"selection {selection_id}: {message}"
            for message in schema_errors + semantic
        )
    for entry in expectations["previews"]:
        payload = materialize_preview(entry, context)
        schema_errors, semantic = validate_fixture(registry, PREVIEW_SCHEMA, payload)
        errors.extend(f"{entry['page_id']}: {message}" for message in schema_errors + semantic)
        for row in payload["rows"]:
            row_errors, row_semantic = validate_fixture(registry, PLAN_ROW_SCHEMA, row)
            errors.extend(
                f"{entry['page_id']}/{row['item_id']}: {message}"
                for message in row_errors + row_semantic
            )
    for rule_set_id in sorted({entry["rule_set_id"] for entry in expectations["previews"]}):
        payload = {
            "rule_set_id": rule_set_id,
            "company_id": context["rule_sets"][rule_set_id]["company_id"],
            "members": [dict(m) for m in context["rule_sets"][rule_set_id]["members"]],
        }
        schema_errors, semantic = validate_fixture(registry, RULE_SET_SCHEMA, payload)
        errors.extend(f"rule_set {rule_set_id}: {message}" for message in schema_errors + semantic)
    for entry in expectations["errors"]:
        payload = materialize_error(entry)
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


def request_schema_errors(
    expectations: Dict[str, Any], context: Dict[str, Any], registry
) -> List[str]:
    """Every preflight request is schema-classified by its operation body."""
    errors: List[str] = []
    for entry in expectations["preflight"]:
        label = entry["scenario_id"]
        pointer = (
            BATCH_REQUEST_SCHEMA
            if entry["operation"] == BATCH_OPERATION
            else PREVIEW_REQUEST_SCHEMA
        )
        schema_errors = validate_value(registry, pointer, materialize_request(entry))
        errors.extend(f"{label}: {message}" for message in schema_errors)
    return errors


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
        if mutation["validator"] == "schema":
            reported = schema_rejection_errors(mutated, registry)
        else:
            reported = expectation_errors(mutated, mutated_context)
        if not reported:
            errors.append(
                f"{label}: expected the {mutation['validator']} validator to reject the "
                f"mutation ({mutation['reason']}) but it passed"
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
        payloads[f"member_order:{selection_id}"] = list(selection["member_order"])
    for entry in expectations["previews"]:
        payload = materialize_preview(entry, context)
        payloads[f"preview:{entry['page_id']}"] = payload
        payloads[f"rows:{entry['page_id']}"] = payload["rows"]
    for rule_set_id, rule_set in context["rule_sets"].items():
        payloads[f"rule_set:{rule_set_id}"] = rule_set
    for entry in expectations["errors"]:
        payloads[f"error:{entry['error_id']}"] = materialize_error(entry)
        payloads[f"error_meta:{entry['error_id']}"] = entry
    for entry in expectations["preflight"]:
        payloads[f"preflight:{entry['scenario_id']}"] = entry
        payloads[f"request:{entry['scenario_id']}"] = materialize_request(entry)
    for entry in expectations["post_acceptance"]:
        payloads[f"outcome:{entry['outcome_id']}"] = entry
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
    for link in expectations.get("links", []):
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
# Generated public examples (documented preparation path)
# --------------------------------------------------------------------------- #

# (example id, kind, binding, canonical schema, output file, description).
EXAMPLE_BINDINGS: List[Dict[str, str]] = [
    {
        "id": "preview-atlas-allmatching-120-page1",
        "kind": "preview",
        "binding": "preview-atlas-allmatching-120-page1",
        "schema": PREVIEW_SCHEMA,
        "file": "contracts/examples/sorting/preview-atlas-allmatching-120-page1.json",
        "description": "LT-03.3b: page 1 of the 120-item preview; all rows NO_SCENARIO with no target.",
    },
    {
        "id": "preview-atlas-explicit-one",
        "kind": "preview",
        "binding": "preview-atlas-explicit-one",
        "schema": PREVIEW_SCHEMA,
        "file": "contracts/examples/sorting/preview-atlas-explicit-one.json",
        "description": "LT-03.3b: single-item EXPLICIT preview (total=1).",
    },
    {
        "id": "preview-atlas-explicit-multiple",
        "kind": "preview",
        "binding": "preview-atlas-explicit-multiple",
        "schema": PREVIEW_SCHEMA,
        "file": "contracts/examples/sorting/preview-atlas-explicit-multiple.json",
        "description": "LT-03.3b: three-item EXPLICIT preview (total=3).",
    },
    {
        "id": "preview-atlas-hetero",
        "kind": "preview",
        "binding": "preview-atlas-hetero",
        "schema": PREVIEW_SCHEMA,
        "file": "contracts/examples/sorting/preview-atlas-hetero.json",
        "description": "LT-03.3b: isolated heterogeneous preview covering all four Prediction kinds and all three CollisionDetails kinds.",
    },
    {
        "id": "preview-atlas-conflict",
        "kind": "preview",
        "binding": "preview-atlas-conflict",
        "schema": PREVIEW_SCHEMA,
        "file": "contracts/examples/sorting/preview-atlas-conflict.json",
        "description": "LT-03.3b: isolated equal-priority RULE_CONFLICT preview.",
    },
    {
        "id": "error-batch-selection-changed",
        "kind": "error",
        "binding": "PF-ERR-BATCH-CHANGED",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-batch-selection-changed.json",
        "description": "LT-03.3b: 409 SELECTION_CHANGED on the DIRECT batch preflight.",
    },
    {
        "id": "error-batch-stale-preview",
        "kind": "error",
        "binding": "PF-ERR-BATCH-STALE",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-batch-stale-preview.json",
        "description": "LT-03.3b: 409 STALE_PREVIEW on the PREVIEWED batch preflight.",
    },
    {
        "id": "error-batch-selection-expired",
        "kind": "error",
        "binding": "PF-ERR-BATCH-EXPIRED",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-batch-selection-expired.json",
        "description": "LT-03.3b: 409 SELECTION_EXPIRED on the batch operation.",
    },
    {
        "id": "error-batch-invalid-state",
        "kind": "error",
        "binding": "PF-ERR-BATCH-INVALID-STATE",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-batch-invalid-state.json",
        "description": "LT-03.3b: 409 INVALID_STATE for a mismatched selection/preview pair.",
    },
    {
        "id": "error-batch-selection-not-found",
        "kind": "error",
        "binding": "PF-ERR-BATCH-NOT-FOUND",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-batch-selection-not-found.json",
        "description": "LT-03.3b: 404 NOT_FOUND for an unknown selection/preview id.",
    },
    {
        "id": "error-batch-forbidden",
        "kind": "error",
        "binding": "PF-ERR-BATCH-FORBIDDEN",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-batch-forbidden.json",
        "description": "LT-03.3b: 403 FORBIDDEN for another user of a bound selection.",
    },
    {
        "id": "error-preview-selection-expired",
        "kind": "error",
        "binding": "PF-ERR-PREVIEW-EXPIRED",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-preview-selection-expired.json",
        "description": "LT-03.3b: 409 SELECTION_EXPIRED on the preview operation.",
    },
    {
        "id": "error-preview-selection-changed",
        "kind": "error",
        "binding": "PF-ERR-PREVIEW-CHANGED",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-preview-selection-changed.json",
        "description": "LT-03.3b: 409 SELECTION_CHANGED on the preview operation.",
    },
]


def generated_examples(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    for binding in EXAMPLE_BINDINGS:
        kind = binding["kind"]
        if kind == "preview":
            payload = materialize_preview(
                context["preview_pages"][binding["binding"]], context
            )
        elif kind == "error":
            payload = materialize_error(context["errors"][binding["binding"]])
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
        description="Materialize the WiseWay preview/preflight oracle examples."
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
