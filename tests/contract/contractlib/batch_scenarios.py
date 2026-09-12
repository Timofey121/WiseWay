"""LT-03.4b finite operational retry/overlap/restart scenario oracle.

``fixtures/synthetic/batch_scenarios.json`` stores the finite, hand-authored
oracle for the operational scenarios that API section 2 (idempotency) and
section 8 (batch pre/post acceptance), TZ QUEUE-07..10, AUTH-03, FILE-08/09,
QA section 4/8 and the matrix rows Q-028..030/031/032/040/044 describe.  It
builds directly on:

* ``fixtures/synthetic/batch_outcomes.json`` - the accepted LT-03.4a batches,
  outcomes, placements, occupied objects and the logical inventory contract;
* ``fixtures/synthetic/preview_preflight.json`` - the LT-03.3b accepted and
  rejected preflight scenarios plus the error payloads;
* ``fixtures/synthetic/rule_expectations.json`` - the immutable rule/RuleSet/
  target definitions and the Q-044 target resolver scenarios.

The module is a *materializer and consistency checker*, not a runtime domain:

* every scenario is a finite sequence of literal request bodies, UUID
  Idempotency-Key values, actors, instants, logical fault labels and
  synchronization barriers with declared expected batch/attempt IDs, outcomes,
  placements and audit phase/action IDs;
* isolated selections/batches are declared literally and materialized with the
  same ``batch_outcomes`` functions, so no matcher, executor, filesystem
  writer, recovery engine or concurrency primitive is implemented;
* replay, overlap, source-change, continuation, late-target, duplicate-target,
  restart and containment invariants are cross-checked against the referenced
  payloads; every fault point and barrier is a logical label and every durable
  intent is a declared requirement, never live evidence.

A documented preparation command regenerates the committed public examples::

    python tests/contract/contractlib/batch_scenarios.py --write-examples
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:  # package import (tests, verify_contract.py)
    from . import batch_outcomes, preview_preflight, synthetic
    from .expectations import EXPECTED_OPERATIONS
    from .schemas import validate_value
    from .search_expectations import allowed_error_codes
    from .semantic import validate_fixture
except ImportError:  # pragma: no cover - documented direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from contractlib import batch_outcomes, preview_preflight, synthetic  # type: ignore
    from contractlib.expectations import EXPECTED_OPERATIONS  # type: ignore
    from contractlib.schemas import validate_value  # type: ignore
    from contractlib.search_expectations import allowed_error_codes  # type: ignore
    from contractlib.semantic import validate_fixture  # type: ignore

EXPECTATIONS_RELATIVE = Path("fixtures") / "synthetic" / "batch_scenarios.json"

BATCH_REQUEST_SCHEMA = "#/components/schemas/BatchCreateRequest"
RESOLVE_TARGET_REQUEST_SCHEMA = "#/components/schemas/ResolveTargetRequest"
ERROR_SCHEMA = "#/components/schemas/ErrorResponse"
BATCH_SCHEMA = "#/components/schemas/Batch"
OUTCOME_SCHEMA = "#/components/schemas/Outcome"
AUDIT_EVENT_SCHEMA = "#/components/schemas/AuditEvent"

KNOWN_Q = ("Q-028", "Q-029", "Q-030", "Q-031", "Q-032", "Q-040", "Q-044")
CATEGORIES = (
    "IDEMPOTENCY",
    "OVERLAP",
    "SOURCE_CHANGE",
    "CONTINUATION",
    "LATE_TARGET",
    "DUPLICATE_TARGET",
    "RESTART",
    "CONTAINMENT",
)
BATCH_OPERATION = "createSortingBatch"
RESOLVE_OPERATION = "resolveTargetDirectory"
KNOWN_OPERATIONS = set(EXPECTED_OPERATIONS.values())
QUEUE_STATES = (
    "DISCOVERED",
    "WAITING_READY",
    "READY",
    "PROCESSING",
    "REQUIRES_DECISION",
    "RECOVERY_REQUIRED",
    "MISSING",
)
AUDIT_ACTIONS = (
    "DICTIONARY_CREATED",
    "DRAFT_SAVED",
    "DICTIONARY_SIMULATED",
    "DICTIONARY_PUBLISHED",
    "DICTIONARY_RESTORED",
    "BATCH_ACCEPTED",
    "FILE_ATTEMPT_STARTED",
    "FILE_ATTEMPT_FINISHED",
    "QUARANTINE_RETURNED",
    "RECOVERY_REQUIRED",
    "LOGIN_SUCCEEDED",
    "LOGIN_FAILED",
    "LOGOUT",
    "ACCOUNT_BLOCKED",
)
AUDIT_CATEGORIES = ("BUSINESS", "SYSTEM")
AUDIT_RESULTS = ("SUCCESS", "ISSUE", "FAILED")
AUDIT_PHASES = ("ACCEPT", "ATTEMPT_START", "ATTEMPT_FINISH", "RECOVERY", "SESSION")
SYSTEM_ACTIONS = ("LOGIN_SUCCEEDED", "LOGIN_FAILED", "LOGOUT", "ACCOUNT_BLOCKED")
RESTART_POINTS = (
    "RESTART-BEFORE-MUTATION",
    "RESTART-AFTER-PROVEN-COMMIT",
    "RESTART-AMBIGUOUS",
)
INTENT_PHASES = (
    "INTENT_RECORDED",
    "PHASE_PREPARED",
    "PHASE_APPLIED",
    "PHASE_CONFIRMED",
)
CONTAINMENT_PHASES = ("BEFORE_BATCH", "AFTER_BATCH")
ID_RE = re.compile(r"^[A-Za-z0-9-]{1,96}$")
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


# --------------------------------------------------------------------------- #
# Loading and context
# --------------------------------------------------------------------------- #

def expectations_path(root: Optional[Path] = None) -> Path:
    return (root or synthetic.repo_root()) / EXPECTATIONS_RELATIVE


def load_expectations(root: Optional[Path] = None) -> Dict[str, Any]:
    return synthetic.load_json(expectations_path(root))


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


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
        "source": "batch_scenarios.json",
    }


def build_context(
    root: Optional[Path] = None, expectations: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Load the linked fixtures, inject the isolated scenarios and index them."""
    base = Path(root) if root is not None else synthetic.repo_root()
    if expectations is None:
        expectations = load_expectations(base)
    batch_ctx = batch_outcomes.build_context(base)

    isolated_selections: Dict[str, Dict[str, Any]] = {}
    for entry in expectations["isolated_selections"]:
        selection = _isolated_selection(entry)
        isolated_selections[selection["selection_id"]] = selection
        batch_ctx["selections"][selection["selection_id"]] = selection

    isolated_batches = {entry["batch_id"]: entry for entry in expectations["isolated_batches"]}
    for batch_id, spec in isolated_batches.items():
        batch_ctx["batches"][batch_id] = spec

    preview_errors = dict(batch_ctx["preview"]["errors"])
    batch_errors = {entry["error_id"]: entry for entry in expectations["batch_errors"]}
    errors = dict(preview_errors)
    errors.update(batch_errors)

    scenarios = {entry["scenario_id"]: entry for entry in expectations["scenarios"]}
    audit = {entry["audit_id"]: entry for entry in expectations["audit_expectations"]}
    containment: Dict[str, Dict[str, Any]] = {}
    restart_points: Dict[str, Dict[str, Any]] = {}
    for scenario in expectations["scenarios"]:
        if scenario.get("category") == "CONTAINMENT":
            for case in scenario["before_batch"] + scenario["after_batch"]:
                containment[case["case_id"]] = case
        if scenario.get("category") == "RESTART":
            for point in scenario["points"]:
                restart_points[point["point_id"]] = point

    preview_expiries = {
        entry["preview_id"]: entry["expires_at"]
        for entry in batch_ctx["preview"]["preview_pages"].values()
    }
    target_scenarios = {
        entry["scenario_id"]: entry
        for entry in batch_ctx["preview"]["rule_expectations"]["target_scenarios"]
    }

    return {
        "base": base,
        "manifest": batch_ctx["manifest"],
        "document": batch_ctx["document"],
        "expectations": expectations,
        "batch": batch_ctx,
        "batch_expectations": batch_ctx["expectations"],
        "preview": batch_ctx["preview"],
        "actors": batch_ctx["actors"],
        "selections": batch_ctx["selections"],
        "isolated_selections": isolated_selections,
        "isolated_batches": isolated_batches,
        "rule_sets": batch_ctx["rule_sets"],
        "targets": batch_ctx["targets"],
        "previews": batch_ctx["previews"],
        "preview_expiries": preview_expiries,
        "preflight_by_id": batch_ctx["preflight_by_id"],
        "errors": errors,
        "batch_errors": batch_errors,
        "scenarios": scenarios,
        "audit": audit,
        "containment": containment,
        "restart_points": restart_points,
        "duplicate_groups": batch_ctx["duplicate_targets"],
        "occupied_targets": batch_ctx["occupied_targets"],
        "manual_review_occupied": batch_ctx["manual_review_occupied"],
        "target_scenarios": target_scenarios,
        "prefix": batch_ctx["prefix"],
        "page_limit": batch_ctx["page_limit"],
        "constants": expectations["constants"],
    }


# --------------------------------------------------------------------------- #
# Materialization (literal ids only, never a matcher)
# --------------------------------------------------------------------------- #

def batch_page(batch_id: str, context: Dict[str, Any], index: int = 0) -> Dict[str, Any]:
    spec = context["batch"]["batches"][batch_id]
    return batch_outcomes.materialize_batch_page(spec, spec["pages"][index], context["batch"])


def all_outcomes(batch_id: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
    spec = context["batch"]["batches"][batch_id]
    return batch_outcomes.all_outcome_payloads(spec, context["batch"])


def outcome_payload(
    batch_id: str, item_id: str, context: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    for outcome in all_outcomes(batch_id, context):
        if outcome["item_id"] == item_id:
            return outcome
    return None


def attempt_ids(batch_id: str, context: Dict[str, Any]) -> List[str]:
    return [outcome["attempt_id"] for outcome in all_outcomes(batch_id, context)]


def materialize_request(body: Dict[str, Any]) -> Dict[str, Any]:
    return copy.deepcopy(body)


def materialize_error(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "error": {
            "code": entry["code"],
            "message": entry.get("message", "safe synthetic error"),
            "request_id": entry.get("request_id", "request-demo-1"),
            "operation_id": entry.get("operation_id"),
            "retryable": entry.get("retryable", False),
            "field_errors": entry.get("field_errors", []),
        }
    }


def _batch_company_id(batch_id: str, context: Dict[str, Any]) -> Optional[str]:
    spec = context["batch"]["batches"][batch_id]
    selection = context["batch"]["selections"][batch_outcomes._selection_id(spec)]
    return selection["company_id"]


def materialize_audit_event(entry: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    batch_id = entry.get("batch_id")
    company_id = _batch_company_id(batch_id, context) if batch_id else None
    actor = context["actors"][entry["actor"]] if entry.get("actor") else None
    return {
        "event_id": entry["audit_id"],
        "occurred_at": entry["occurred_at"],
        "actor": actor,
        "category": entry["category"],
        "action": entry["action"],
        "result": entry["result"],
        "request_id": entry["request_id"],
        "operation_id": entry.get("operation_id"),
        "source_attempt_id": entry.get("source_attempt_id"),
        "company_id": company_id,
        "dictionary_id": None,
        "version_id": None,
        "rule_set_id": None,
        "batch_id": batch_id,
        "attempt_id": entry.get("attempt_id"),
        "item_id": entry.get("item_id"),
        "source": None,
        "target": None,
        "reason_code": None,
        "comment": None,
    }


# --------------------------------------------------------------------------- #
# Scenario expectation checks
# --------------------------------------------------------------------------- #

def _common_scenario_errors(scenario: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = scenario.get("scenario_id", "<missing>")
    if not isinstance(label, str) or not ID_RE.match(label):
        errors.append(f"{label}: scenario_id must be a valid Id")
    if scenario.get("category") not in CATEGORIES:
        errors.append(f"{label}: unknown category {scenario.get('category')!r}")
    q_ids = scenario.get("q_ids")
    if not isinstance(q_ids, list) or not q_ids:
        errors.append(f"{label}: q_ids must be a non-empty list")
    else:
        for q_id in q_ids:
            if q_id not in KNOWN_Q:
                errors.append(f"{label}: unknown Q id {q_id!r}")
    if not scenario.get("title"):
        errors.append(f"{label}: title must not be empty")
    if not scenario.get("reason"):
        errors.append(f"{label}: reason (manual trace) must not be empty")
    for audit_id in scenario.get("expected_audit", []):
        if audit_id not in context["audit"]:
            errors.append(f"{label}: expected_audit references unknown {audit_id!r}")
    return errors


def _uuid_errors(label: str, key_id: str, value: Any) -> List[str]:
    errors: List[str] = []
    if not isinstance(value, str) or not UUID_RE.match(value):
        errors.append(f"{label}: {key_id} must be a UUID string")
    return errors


def _fault_errors(label: str, fault: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if not fault.get("fault_id") or not fault.get("kind") or not fault.get("setup"):
        errors.append(f"{label}: a fault needs fault_id/kind/setup")
    if fault.get("no_outside_access") is not True:
        errors.append(f"{label}: a logical fault must declare no_outside_access=true")
    try:
        _instant(fault.get("at", ""))
    except (TypeError, ValueError):
        errors.append(f"{label}: fault.at must be an Instant")
    return errors


def _idempotency_errors(scenario: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = scenario["scenario_id"]
    operation = scenario.get("operation")
    if operation != BATCH_OPERATION:
        errors.append(f"{label}: idempotency scenarios operate createSortingBatch")
    if "replays" in scenario:
        errors.extend(_idempotency_replay_errors(scenario, context))
    elif "modified_body" in scenario:
        errors.extend(_idempotency_modified_errors(scenario, context))
    elif "scoped_actor" in scenario:
        errors.extend(_idempotency_scope_errors(scenario, context))
    elif "first" in scenario and "retry" in scenario:
        errors.extend(_idempotency_retry_errors(scenario, context))
    else:
        errors.append(f"{label}: unknown idempotency scenario shape")
    return errors


def _idempotency_replay_errors(scenario: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = scenario["scenario_id"]
    actor = scenario.get("actor")
    if actor not in context["actors"]:
        errors.append(f"{label}: actor does not resolve to an auth fixture actor")
    errors.extend(_uuid_errors(label, "idempotency_key", scenario.get("idempotency_key")))
    errors.extend(_fault_errors(label, scenario.get("fault", {})))
    batch_id = scenario.get("accepted_batch_id")
    batch = context["batch"]["batches"].get(batch_id)
    if batch is None:
        errors.append(f"{label}: unknown accepted batch {batch_id!r}")
        return errors
    if batch.get("owner") != actor:
        errors.append(f"{label}: accepted batch owner is not the scenario actor")
    body = scenario.get("body", {})
    if batch.get("execution_mode") != body.get("execution_mode"):
        errors.append(f"{label}: accepted batch execution_mode disagrees with the body")
    selection = context["selections"].get(body.get("selection_id"))
    if selection is None:
        errors.append(f"{label}: body selection does not resolve")
        return errors
    expires = selection["snapshot"]["expires_at"]
    for replay in scenario["replays"]:
        repl_label = replay.get("replay_id", "?")
        if not (replay.get("same_key") and replay.get("same_user") and replay.get("same_body")):
            errors.append(f"{label}/{repl_label}: a replay must reuse key/user/body")
        expected = replay.get("expected", {})
        if expected.get("batch_id") != batch_id:
            errors.append(f"{label}/{repl_label}: replay must return the original batch")
        if expected.get("new_attempts") != 0:
            errors.append(f"{label}/{repl_label}: a replay must not create an attempt")
        if expected.get("http") != 202 or expected.get("result") != "BATCH":
            errors.append(f"{label}/{repl_label}: a replay returns the 202 batch")
        try:
            at = _instant(replay.get("at", ""))
        except (TypeError, ValueError):
            errors.append(f"{label}/{repl_label}: replay.at must be an Instant")
            continue
        timing = replay.get("timing")
        if timing == "before_dependency_expiry":
            if at >= _instant(expires):
                errors.append(f"{label}/{repl_label}: replay is not before the dependency expiry")
        elif timing == "after_snapshot_expiry":
            if at <= _instant(expires):
                errors.append(f"{label}/{repl_label}: replay is not after the snapshot expiry")
        elif timing == "after_preview_expiry":
            preview_id = body.get("preview_id")
            preview_expiry = context["preview_expiries"].get(preview_id)
            if preview_expiry is None:
                errors.append(f"{label}/{repl_label}: body needs a resolvable preview_id")
            elif at <= _instant(preview_expiry):
                errors.append(f"{label}/{repl_label}: replay is not after the preview expiry")
        else:
            errors.append(f"{label}/{repl_label}: unknown replay timing {timing!r}")
    return errors


def _idempotency_modified_errors(scenario: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = scenario["scenario_id"]
    if scenario.get("original_body") == scenario.get("modified_body"):
        errors.append(f"{label}: the modified body must differ from the original body")
    errors.extend(_uuid_errors(label, "idempotency_key", scenario.get("idempotency_key")))
    if context["batch"]["batches"].get(scenario.get("original_batch_id")) is None:
        errors.append(f"{label}: original_batch_id does not resolve")
    expected = scenario.get("expected", {})
    if expected.get("http") != 409:
        errors.append(f"{label}: a reused key with a new body must be 409")
    if expected.get("code") != "IDEMPOTENCY_KEY_REUSED":
        errors.append(f"{label}: a reused key with a new body is IDEMPOTENCY_KEY_REUSED")
    error_entry = context["errors"].get(expected.get("error_id"))
    if error_entry is None:
        errors.append(f"{label}: expected error_id does not resolve")
    else:
        if (
            error_entry.get("code") != expected.get("code")
            or error_entry.get("status") != expected.get("http")
            or error_entry.get("operation") != BATCH_OPERATION
        ):
            errors.append(f"{label}: the referenced error disagrees with operation/status/code")
    if expected.get("batch_created") is not False or expected.get("new_attempts") != 0:
        errors.append(f"{label}: a key conflict must not create a batch or attempt")
    return errors


def _idempotency_scope_errors(scenario: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = scenario["scenario_id"]
    errors.extend(_uuid_errors(label, "idempotency_key", scenario.get("idempotency_key")))
    if scenario.get("original_actor") == scenario.get("scoped_actor"):
        errors.append(f"{label}: a separate scope needs two different users")
    if scenario.get("original_batch_id") == scenario.get("scoped_batch_id"):
        errors.append(f"{label}: a separate scope must produce a different batch")
    scoped = context["batch"]["batches"].get(scenario.get("scoped_batch_id"))
    if scoped is None:
        errors.append(f"{label}: scoped_batch_id does not resolve")
    elif scoped.get("owner") != scenario.get("scoped_actor"):
        errors.append(f"{label}: the scoped batch is not owned by the scoped actor")
    expected = scenario.get("expected", {})
    if not expected.get("separate_scope"):
        errors.append(f"{label}: the same key string for another user is a separate scope")
    if expected.get("idempotency_conflict"):
        errors.append(f"{label}: another user is not an idempotency conflict")
    if not expected.get("same_key_string"):
        errors.append(f"{label}: the scenario must reuse the same key string")
    if expected.get("http") != 202 or expected.get("result") != "BATCH":
        errors.append(f"{label}: the scoped operation is accepted")
    replay = scenario.get("replay", {})
    replay_expected = replay.get("expected", {})
    if replay_expected.get("batch_id") != scenario.get("scoped_batch_id"):
        errors.append(f"{label}: the scoped replay must return the scoped batch")
    if replay_expected.get("new_attempts") != 0:
        errors.append(f"{label}: the scoped replay must not create an attempt")
    return errors


def _idempotency_retry_errors(scenario: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = scenario["scenario_id"]
    first = scenario["first"]
    retry = scenario["retry"]
    errors.extend(_uuid_errors(label, "first.idempotency_key", first.get("idempotency_key")))
    errors.extend(_uuid_errors(label, "retry.idempotency_key", retry.get("idempotency_key")))
    if first.get("idempotency_key") == retry.get("idempotency_key"):
        errors.append(f"{label}: a manual retry must use a new key")
    first_expected = first.get("expected", {})
    if first_expected.get("http") != 409 or first_expected.get("result") != "ERROR":
        errors.append(f"{label}: the first attempt must be refused")
    allowed = allowed_error_codes(context["document"], BATCH_OPERATION, first_expected.get("http"))
    if first_expected.get("code") not in allowed:
        errors.append(f"{label}: the first refusal code is not declared by the operation")
    if first_expected.get("batch_created") is not False:
        errors.append(f"{label}: a refused first attempt creates no batch")
    if first_expected.get("attempts"):
        errors.append(f"{label}: a refused first attempt creates no attempt")
    error_entry = context["errors"].get(first_expected.get("error_id"))
    if error_entry is None:
        errors.append(f"{label}: first expected error_id does not resolve")
    elif (
        error_entry.get("code") != first_expected.get("code")
        or error_entry.get("status") != first_expected.get("http")
    ):
        errors.append(f"{label}: the first refusal error disagrees with status/code")
    retry_expected = retry.get("expected", {})
    if retry_expected.get("http") != 202 or retry_expected.get("result") != "BATCH":
        errors.append(f"{label}: the corrected retry is accepted")
    batch = context["batch"]["batches"].get(retry_expected.get("batch_id"))
    if batch is None:
        errors.append(f"{label}: retry batch does not resolve")
    else:
        if retry_expected.get("attempts") != attempt_ids(batch["batch_id"], context):
            errors.append(f"{label}: retry attempts do not equal the new batch attempts")
    if not retry_expected.get("new_key") or not retry_expected.get("new_attempt"):
        errors.append(f"{label}: the retry must be a new key and a new attempt")
    return errors


def _overlap_errors(scenario: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = scenario["scenario_id"]
    winner = scenario["winner"]
    loser = scenario["loser"]
    if winner["actor"] == loser["actor"]:
        errors.append(f"{label}: the overlap needs two different actors")
    winner_selection = context["selections"].get(winner["selection_id"])
    loser_selection = context["selections"].get(loser["selection_id"])
    if winner_selection is None or loser_selection is None:
        errors.append(f"{label}: overlap selections do not resolve")
        return errors
    shared = scenario["shared_item_id"]
    if shared not in winner_selection["members"] or shared not in loser_selection["members"]:
        errors.append(f"{label}: the shared item is not in both selections")
        return errors
    winner_member = winner_selection["members"][shared]
    loser_member = loser_selection["members"][shared]
    if winner_member["location"] != loser_member["location"]:
        errors.append(f"{label}: the shared item has different locations")
    if winner_member["item_revision"] != loser_member["item_revision"]:
        errors.append(f"{label}: the shared item has different revisions")
    winner_batch = context["batch"]["batches"].get(winner["batch_id"])
    loser_batch = context["batch"]["batches"].get(loser["batch_id"])
    if winner_batch is None or loser_batch is None:
        errors.append(f"{label}: overlap batches do not resolve")
        return errors
    if winner_batch.get("owner") != winner["actor"]:
        errors.append(f"{label}: the winner batch owner is not the winner actor")
    if loser_batch.get("owner") != loser["actor"]:
        errors.append(f"{label}: the loser batch owner is not the loser actor")
    winner_outcome = outcome_payload(winner["batch_id"], shared, context)
    loser_outcome = outcome_payload(loser["batch_id"], shared, context)
    if winner_outcome is None or loser_outcome is None:
        errors.append(f"{label}: the shared item has no outcome in one batch")
        return errors
    expected = scenario["expected"]
    if expected.get("winner_shared_state") != "SORTED" or winner_outcome["state"] != "SORTED":
        errors.append(f"{label}: the winner must sort the shared item")
    if expected.get("loser_shared_state") != "SKIPPED" or loser_outcome["state"] != "SKIPPED":
        errors.append(f"{label}: the loser shared outcome must be SKIPPED")
    if loser_outcome["reason_code"] != "ALREADY_PROCESSING":
        errors.append(f"{label}: the loser shared reason must be ALREADY_PROCESSING")
    if loser_outcome["actual_location"] is not None:
        errors.append(f"{label}: the losing run must not move the shared file")
    if expected.get("shared_claim_count") != 1:
        errors.append(f"{label}: at most one shared claim/real execution is allowed")
    if _instant(loser["claim_at"]) <= _instant(winner["claim_at"]):
        errors.append(f"{label}: the temporal barrier requires the winner claim first")
    if expected.get("second_move"):
        errors.append(f"{label}: no second move is allowed")
    if not expected.get("content_revision_unchanged_by_claim"):
        errors.append(f"{label}: a claim must not change the content revision")
    if winner_outcome["item_revision"] != loser_outcome["item_revision"]:
        errors.append(f"{label}: the shared content revision changed across the claim")
    if winner_outcome["item_revision"] != winner_member["item_revision"]:
        errors.append(f"{label}: the shared content revision differs from the selection")
    for side, batch_id in (("winner", winner["batch_id"]), ("loser", loser["batch_id"])):
        selection = winner_selection if side == "winner" else loser_selection
        for item_id in scenario["independent_safe_items"][side]:
            if item_id not in selection["members"]:
                errors.append(f"{label}: independent {side} item {item_id} is not selected")
                continue
            item_outcome = outcome_payload(batch_id, item_id, context)
            if item_outcome is None or item_outcome["state"] != "SORTED":
                errors.append(f"{label}: independent {side} item {item_id} must be SORTED")
    if winner_batch.get("status") != "COMPLETED":
        errors.append(f"{label}: the winner batch is COMPLETED")
    if loser_batch.get("status") != "COMPLETED_WITH_ISSUES":
        errors.append(f"{label}: the loser batch is COMPLETED_WITH_ISSUES")
    sync = scenario["synchronization"]
    if sync.get("before") != "winner_claim" or sync.get("after") != "loser_attempt":
        errors.append(f"{label}: the barrier must order winner claim before loser attempt")
    if not sync.get("label") or not sync.get("setup"):
        errors.append(f"{label}: the barrier needs a label and a setup")
    for key, body in (("winner", winner.get("body", {})), ("loser", loser.get("body", {}))):
        if body.get("selection_id") != (winner if key == "winner" else loser)["selection_id"]:
            errors.append(f"{label}: {key} body selection does not match the scenario")
        if body.get("execution_mode") != "DIRECT":
            errors.append(f"{label}: {key} body must be a DIRECT batch request")
    return errors


def _source_change_errors(scenario: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = scenario["scenario_id"]
    for entry in scenario["before_acceptance"]:
        preflight = context["preflight_by_id"].get(entry["ref"])
        if preflight is None:
            errors.append(f"{label}: unknown preflight {entry['ref']!r}")
            continue
        if preflight["expected"].get("code") != entry["code"]:
            errors.append(f"{label}: {entry['ref']} code disagrees with the preflight")
        if preflight["expected"].get("status") != entry["http"]:
            errors.append(f"{label}: {entry['ref']} status disagrees with the preflight")
        if entry.get("batch_created") is not False or entry.get("file_operations") is not False:
            errors.append(f"{label}: a source change before acceptance touches nothing")
    after = scenario["after_acceptance"]
    outcome = outcome_payload(after["batch_id"], after["item_id"], context)
    if outcome is None:
        errors.append(f"{label}: the after-acceptance outcome does not resolve")
    else:
        if outcome["state"] != after["state"] or outcome["reason_code"] != after["reason_code"]:
            errors.append(f"{label}: the after-acceptance outcome state/reason disagrees")
        if outcome["actual_location"] is not None:
            errors.append(f"{label}: a changed source after acceptance performs no operation")
    if after.get("expected_queue_status") not in QUEUE_STATES:
        errors.append(f"{label}: unknown expected_queue_status")
    if after.get("expected_queue_status") != "WAITING_READY":
        errors.append(f"{label}: a changed source returns to WAITING_READY")
    if after.get("actual_location") is not None:
        errors.append(f"{label}: a changed source declares no actual location")
    if after.get("mutation") != "none" or not after.get("return_to_waiting_ready"):
        errors.append(f"{label}: the after-acceptance outcome mutates nothing")
    for fault in scenario["faults"]:
        errors.extend(_fault_errors(label, fault))
    return errors


def _continuation_errors(scenario: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = scenario["scenario_id"]
    batch = context["batch"]["batches"].get(scenario["accepted_batch_id"])
    if batch is None:
        errors.append(f"{label}: accepted_batch_id does not resolve")
    elif batch.get("owner") != scenario["author"]:
        errors.append(f"{label}: the accepted batch author disagrees")
    if scenario.get("new_viewer") == scenario.get("author"):
        errors.append(f"{label}: the new viewer must differ from the author")
    for step in scenario["steps"]:
        kind = step.get("kind")
        if kind not in ("LOGOUT", "READ", "ABSENT_OPERATION"):
            errors.append(f"{label}: unknown step kind {kind!r}")
        if kind == "READ":
            expected = step["expected"]
            if expected.get("http") != 200:
                errors.append(f"{label}/{step['step_id']}: a batch read is 200")
            if expected.get("author") is not None and expected["author"] != scenario["author"]:
                errors.append(f"{label}/{step['step_id']}: the author must stay unchanged")
        if kind == "ABSENT_OPERATION":
            expected = step["expected"]
            if expected.get("cancel_operation_available") is not False:
                errors.append(f"{label}: no batch cancel operation exists")
            if expected.get("new_viewer_is_author") is not False:
                errors.append(f"{label}: a new viewer never becomes the author")
            if expected.get("batch_cancelled") is not False:
                errors.append(f"{label}: the batch is not cancelled")
            if expected.get("new_batch_created") is not False:
                errors.append(f"{label}: the batch is not recreated")
    return errors


def _late_target_errors(scenario: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = scenario["scenario_id"]
    if scenario.get("after_acceptance_of") not in context["batch"]["batches"]:
        errors.append(f"{label}: after_acceptance_of does not resolve")
    outcome_spec = scenario["outcome"]
    outcome = outcome_payload(outcome_spec["batch_id"], outcome_spec["item_id"], context)
    if outcome is None:
        errors.append(f"{label}: the late-target outcome does not resolve")
        return errors
    if outcome["state"] != "REQUIRES_DECISION" or outcome["reason_code"] != "TARGET_OCCUPIED":
        errors.append(f"{label}: a late occupied target is REQUIRES_DECISION/TARGET_OCCUPIED")
    if outcome["actual_location"] != outcome["source"]:
        errors.append(f"{label}: a late occupied target keeps the source in place")
    existing = context["occupied_targets"].get(scenario["existing_object_id"]) or context[
        "manual_review_occupied"
    ].get(scenario["existing_object_id"])
    if existing is None:
        errors.append(f"{label}: existing_object_id does not resolve")
    else:
        if existing.get("unchanged") is not True:
            errors.append(f"{label}: the existing object must stay unchanged")
        if outcome["planned_target"] != existing["location"]:
            errors.append(f"{label}: the planned target is not the existing object")
    errors.extend(_fault_errors(label, scenario["fault"]))
    return errors


def _duplicate_target_errors(scenario: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = scenario["scenario_id"]
    group = context["duplicate_groups"].get(scenario["group_id"])
    if group is None:
        errors.append(f"{label}: group_id does not resolve")
        return errors
    participants = list(group["participants"])
    orders = [run["input_order"] for run in scenario["runs"]]
    if not orders or any(sorted(order) != sorted(participants) for order in orders):
        errors.append(f"{label}: run input orders must cover exactly the group participants")
    if len(orders) < 2 or orders[0] == orders[1]:
        errors.append(f"{label}: the scenario needs a reversed input order")
    elif orders[1] != list(reversed(orders[0])):
        errors.append(f"{label}: the second run must reverse the first input order")
    expected = scenario["expected"]
    if expected.get("winner") is not None:
        errors.append(f"{label}: a duplicate plan target selects no winner")
    if expected.get("all_participants") != "REQUIRES_DECISION":
        errors.append(f"{label}: every participant is REQUIRES_DECISION")
    if expected.get("all_reasons") != "TARGET_OCCUPIED":
        errors.append(f"{label}: every participant reason is TARGET_OCCUPIED")
    for item_id in participants:
        outcome = outcome_payload(scenario["batch_id"], item_id, context)
        if outcome is None:
            errors.append(f"{label}: participant {item_id} has no outcome")
            continue
        if outcome["state"] != "REQUIRES_DECISION" or outcome["reason_code"] != "TARGET_OCCUPIED":
            errors.append(f"{label}: participant {item_id} must stay REQUIRES_DECISION")
        if outcome["actual_location"] != outcome["source"]:
            errors.append(f"{label}: participant {item_id} keeps the source in place")
        if outcome["planned_target"] != group["target"]:
            errors.append(f"{label}: participant {item_id} target is not the shared target")
    safe = outcome_payload(scenario["batch_id"], scenario["independent_safe_file"], context)
    if safe is None or safe["state"] != "SORTED":
        errors.append(f"{label}: the independent safe file still sorts")
    return errors


def _restart_errors(scenario: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = scenario["scenario_id"]
    if scenario.get("live_evidence") is not False:
        errors.append(f"{label}: restart scenarios are declared requirements, not live evidence")
    point_ids = [point["point_id"] for point in scenario["points"]]
    if set(point_ids) != set(RESTART_POINTS):
        errors.append(f"{label}: the three restart points must all appear exactly once")
    for point in scenario["points"]:
        point_label = f"{label}/{point['point_id']}"
        if point.get("batch_id") not in context["batch"]["batches"]:
            errors.append(f"{point_label}: batch_id does not resolve")
        intent = point.get("durable_intent")
        if not isinstance(intent, list) or not intent:
            errors.append(f"{point_label}: durable_intent must be a non-empty list")
        else:
            for phase in intent:
                if phase not in INTENT_PHASES:
                    errors.append(f"{point_label}: unknown durable intent phase {phase!r}")
            if intent != [phase for phase in INTENT_PHASES if phase in intent]:
                errors.append(f"{point_label}: durable intent phases must be ordered")
        expected = point["expected"]
        if expected.get("blind_retry") is not False:
            errors.append(f"{point_label}: no blind retry is allowed")
        if not expected.get("intent_survives_restart"):
            errors.append(f"{point_label}: durable intent must survive the restart")
        if point["point_id"] == "RESTART-AMBIGUOUS":
            if expected.get("final_results") != "RECOVERY_REQUIRED":
                errors.append(f"{point_label}: an ambiguous result stays RECOVERY_REQUIRED")
            if not expected.get("registered_operation_id"):
                errors.append(f"{point_label}: an ambiguous result registers an operation_id")
            if expected.get("finished_at") is not None:
                errors.append(f"{point_label}: an ambiguous batch stays unfinished")
        else:
            if expected.get("final_results") != 1:
                errors.append(f"{point_label}: a proven outcome yields exactly one final result")
            if expected.get("second_move"):
                errors.append(f"{point_label}: a proven outcome is not moved twice")
    for item_id in scenario["ambiguous_outcomes"]:
        outcome = outcome_payload("batch-atlas-technical", item_id, context)
        if outcome is None or outcome["state"] != "RECOVERY_REQUIRED":
            errors.append(f"{label}: ambiguous outcome {item_id} must be RECOVERY_REQUIRED")
    return errors


def _containment_errors(scenario: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = scenario["scenario_id"]
    if scenario.get("no_outside_access") is not True:
        errors.append(f"{label}: containment scenarios never access outside the sandbox")
    for case in scenario["before_batch"]:
        case_label = f"{label}/{case['case_id']}"
        operation = case.get("operation")
        if operation not in KNOWN_OPERATIONS:
            errors.append(f"{case_label}: unknown operationId {operation!r}")
            continue
        expected = case["expected"]
        allowed = allowed_error_codes(context["document"], operation, expected.get("http"))
        if expected.get("code") not in allowed:
            errors.append(
                f"{case_label}: code {expected.get('code')!r} is not declared by {operation!r} "
                f"for HTTP {expected.get('http')}"
            )
        if expected.get("result") != "ERROR":
            errors.append(f"{case_label}: a pre-batch containment case is an HTTP refusal")
        if expected.get("batch_created") is not False:
            errors.append(f"{case_label}: a pre-batch refusal creates no batch")
        if case.get("no_outside_access") is not True:
            errors.append(f"{case_label}: the fault must declare no_outside_access=true")
        if operation == BATCH_OPERATION:
            error_entry = context["errors"].get(expected.get("error_ref"))
            if error_entry is None:
                errors.append(f"{case_label}: error_ref does not resolve")
            elif (
                error_entry.get("code") != expected.get("code")
                or error_entry.get("status") != expected.get("http")
                or error_entry.get("operation") != operation
            ):
                errors.append(f"{case_label}: the referenced error disagrees")
        else:
            target = context["target_scenarios"].get(expected.get("target_scenario"))
            if target is None:
                errors.append(f"{case_label}: target_scenario does not resolve")
            elif (
                target["expected"].get("code") != expected.get("code")
                or target["expected"].get("status") != expected.get("http")
            ):
                errors.append(f"{case_label}: the target resolver scenario disagrees")
    for case in scenario["after_batch"]:
        case_label = f"{label}/{case['case_id']}"
        if case.get("no_outside_access") is not True:
            errors.append(f"{case_label}: the fault must declare no_outside_access=true")
        expected = case["expected"]
        outcome_spec = expected.get("outcome", {})
        outcome = outcome_payload(outcome_spec.get("batch_id"), outcome_spec.get("item_id"), context)
        if outcome is None:
            errors.append(f"{case_label}: the per-file outcome does not resolve")
        else:
            if (
                outcome["state"] != outcome_spec.get("state")
                or outcome["reason_code"] != outcome_spec.get("reason_code")
            ):
                errors.append(f"{case_label}: the per-file outcome disagrees")
        if expected.get("outside_access") is not False:
            errors.append(f"{case_label}: a containment fault never reads/writes outside")
        if expected.get("blind_retry") is not False:
            errors.append(f"{case_label}: a containment fault is never retried blindly")
        if case.get("exact_recovery_available") is False:
            if outcome is not None and outcome["state"] != "RECOVERY_REQUIRED":
                errors.append(f"{case_label}: no exact recovery keeps the safe RECOVERY_REQUIRED")
            if expected.get("invented_outcome") is not False:
                errors.append(f"{case_label}: an unknown recovery must not invent an outcome")
    return errors


def _scenario_errors(scenario: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors = _common_scenario_errors(scenario, context)
    category = scenario.get("category")
    if category == "IDEMPOTENCY":
        errors.extend(_idempotency_errors(scenario, context))
    elif category == "OVERLAP":
        errors.extend(_overlap_errors(scenario, context))
    elif category == "SOURCE_CHANGE":
        errors.extend(_source_change_errors(scenario, context))
    elif category == "CONTINUATION":
        errors.extend(_continuation_errors(scenario, context))
    elif category == "LATE_TARGET":
        errors.extend(_late_target_errors(scenario, context))
    elif category == "DUPLICATE_TARGET":
        errors.extend(_duplicate_target_errors(scenario, context))
    elif category == "RESTART":
        errors.extend(_restart_errors(scenario, context))
    elif category == "CONTAINMENT":
        errors.extend(_containment_errors(scenario, context))
    return errors


# --------------------------------------------------------------------------- #
# Audit and coverage checks
# --------------------------------------------------------------------------- #

def _audit_errors(expectations: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    seen_keys: Dict[str, str] = {}
    for entry in expectations["audit_expectations"]:
        label = entry.get("audit_id", "<missing>")
        if not isinstance(label, str) or not ID_RE.match(label):
            errors.append(f"{label}: audit_id must be a valid Id")
        if entry.get("scenario_id") not in context["scenarios"]:
            errors.append(f"{label}: scenario_id does not resolve")
        if entry.get("phase") not in AUDIT_PHASES:
            errors.append(f"{label}: unknown phase {entry.get('phase')!r}")
        if entry.get("action") not in AUDIT_ACTIONS:
            errors.append(f"{label}: action is not a closed OAS AuditAction")
        if entry.get("category") not in AUDIT_CATEGORIES:
            errors.append(f"{label}: unknown category")
        if entry.get("result") not in AUDIT_RESULTS:
            errors.append(f"{label}: unknown result")
        try:
            _instant(entry.get("occurred_at", ""))
        except (TypeError, ValueError):
            errors.append(f"{label}: occurred_at must be an Instant")
        unique = entry.get("unique_key")
        if not unique:
            errors.append(f"{label}: unique_key must not be empty")
        elif unique in seen_keys:
            errors.append(f"{label}: unique_key duplicates {seen_keys[unique]}")
        else:
            seen_keys[unique] = label
        if not ID_RE.match(str(entry.get("request_id", ""))):
            errors.append(f"{label}: request_id must be a valid Id")
        for field in ("operation_id", "source_attempt_id", "batch_id", "attempt_id", "item_id"):
            value = entry.get(field)
            if value is not None and not ID_RE.match(str(value)):
                errors.append(f"{label}: {field} must be a valid Id or null")
        action = entry.get("action")
        category = entry.get("category")
        actor = entry.get("actor")
        if category == "BUSINESS" and actor is None:
            errors.append(f"{label}: a BUSINESS event always has an actor")
        if action in SYSTEM_ACTIONS and category != "SYSTEM":
            errors.append(f"{label}: {action} is a SYSTEM event")
        if action not in SYSTEM_ACTIONS and category != "BUSINESS":
            errors.append(f"{label}: {action} is a BUSINESS event")
        if actor is not None and actor not in context["actors"]:
            errors.append(f"{label}: actor does not resolve to an auth fixture actor")
        batch_id = entry.get("batch_id")
        if batch_id is not None and batch_id not in context["batch"]["batches"]:
            errors.append(f"{label}: batch_id does not resolve")
        if action == "BATCH_ACCEPTED":
            if entry.get("attempt_id") is not None or actor is None:
                errors.append(f"{label}: a batch acceptance has an actor and no attempt")
            if entry.get("operation_id") != batch_id:
                errors.append(f"{label}: a batch acceptance operation_id is its batch_id")
        attempt_id = entry.get("attempt_id")
        if attempt_id is not None:
            if batch_id is None:
                errors.append(f"{label}: an attempt event needs its batch_id")
            else:
                attempts = attempt_ids(batch_id, context)
                if attempt_id not in attempts:
                    errors.append(f"{label}: attempt_id is not an outcome of the batch")
                if entry.get("item_id") is not None:
                    outcome = outcome_payload(batch_id, entry["item_id"], context)
                    if outcome is None:
                        errors.append(f"{label}: item_id is not an outcome of the batch")
                    elif outcome["attempt_id"] != attempt_id:
                        errors.append(f"{label}: item_id and attempt_id disagree")
            if action in ("FILE_ATTEMPT_STARTED", "FILE_ATTEMPT_FINISHED"):
                if entry.get("operation_id") != attempt_id:
                    errors.append(f"{label}: a per-file operation_id equals its attempt_id")
        if action == "RECOVERY_REQUIRED":
            if category != "BUSINESS":
                errors.append(f"{label}: recovery is a BUSINESS event")
            if entry.get("source_attempt_id") != attempt_id:
                errors.append(f"{label}: recovery links source_attempt_id to the attempt")
    for scenario in expectations["scenarios"]:
        for audit_id in scenario.get("expected_audit", []):
            if audit_id not in context["audit"]:
                errors.append(f"{scenario['scenario_id']}: unknown audit id {audit_id!r}")
    return errors


def coverage_errors(expectations: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    known = set(context["scenarios"])
    coverage = expectations.get("coverage", {})
    for q_id, references in coverage.items():
        if q_id not in KNOWN_Q:
            errors.append(f"coverage references unknown Q id {q_id}")
        for reference in references:
            if reference not in known:
                errors.append(f"coverage {q_id} references unknown id {reference}")
    for q_id in KNOWN_Q:
        if not coverage.get(q_id):
            errors.append(f"coverage is missing {q_id}")
    return errors


def identity_errors(expectations: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    """Isolated ids must not silently overwrite a linked fixture object."""
    errors: List[str] = []
    known_batches = {
        spec["batch_id"] for spec in context["batch_expectations"]["batches"]
    }
    for spec in expectations["isolated_batches"]:
        if spec["batch_id"] in known_batches:
            errors.append(
                f"{spec['batch_id']}: an isolated batch must not reuse a linked batch id"
            )
    known_selections = {
        entry["selection_id"]
        for entry in context["preview"]["expectations"]["selections"]
    }
    for entry in expectations["isolated_selections"]:
        if entry["selection_id"] in known_selections:
            errors.append(
                f"{entry['selection_id']}: an isolated selection must not reuse a linked selection id"
            )
    for spec in expectations["isolated_batches"]:
        rule_set = context["rule_sets"].get(spec.get("rule_set_id"))
        selection = context["selections"].get(batch_outcomes._selection_id(spec))
        if rule_set is None or selection is None:
            continue
        if rule_set["company_id"] != selection["company_id"]:
            errors.append(f"{spec['batch_id']}: the RuleSet belongs to another company")
    return errors


def inventory_errors(expectations: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    """The isolated batches obey the linked logical inventory contract."""
    errors: List[str] = []
    inventory = context["batch_expectations"]["inventory"]
    if inventory.get("kind") != "logical-inventory-expectation":
        errors.append("the linked batch inventory contract must stay a logical expectation")
    if inventory.get("no_file_writes") is not True:
        errors.append("the linked batch inventory contract must declare no file writes")
    rules = {
        (rule["state"], rule["reason_code"]): rule
        for rule in inventory["state_rules"]
    }
    for spec in expectations["isolated_batches"]:
        for outcome in batch_outcomes.all_outcome_payloads(spec, context["batch"]):
            label = f"{spec['batch_id']}/{outcome['item_id']}"
            rule = rules.get((outcome["state"], outcome["reason_code"]))
            if rule is None:
                errors.append(f"{label}: no logical inventory rule for this state/reason")
                continue
            destination = (
                outcome["actual_location"]
                if outcome["actual_location"] != outcome["source"]
                else None
            )
            if rule["destination_present"] and destination is None:
                errors.append(f"{label}: a confirmed destination must be recorded")
            if not rule["destination_present"] and destination is not None:
                errors.append(f"{label}: no destination may be recorded for this outcome")
    return errors


def expectation_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    seen: set = set()
    for scenario in expectations["scenarios"]:
        scenario_id = scenario.get("scenario_id")
        if scenario_id in seen:
            errors.append(f"duplicate scenario id {scenario_id!r}")
        seen.add(scenario_id)
        errors.extend(_scenario_errors(scenario, context))
    for spec in expectations["isolated_batches"]:
        errors.extend(batch_outcomes._batch_errors(spec, context["batch"]))
    errors.extend(identity_errors(expectations, context))
    errors.extend(inventory_errors(expectations, context))
    errors.extend(_audit_errors(expectations, context))
    errors.extend(coverage_errors(expectations, context))
    return errors


# --------------------------------------------------------------------------- #
# Schema validation
# --------------------------------------------------------------------------- #

def _scenario_request_bodies(
    scenario: Dict[str, Any],
) -> List[Tuple[str, Dict[str, Any], str]]:
    """(label, body, schema pointer) for every schema-bound request."""
    out: List[Tuple[str, Dict[str, Any], str]] = []
    label = scenario.get("scenario_id", "?")
    if isinstance(scenario.get("body"), dict):
        out.append((f"{label}/body", scenario["body"], BATCH_REQUEST_SCHEMA))
    if isinstance(scenario.get("original_body"), dict):
        out.append((f"{label}/original_body", scenario["original_body"], BATCH_REQUEST_SCHEMA))
    if isinstance(scenario.get("modified_body"), dict):
        out.append((f"{label}/modified_body", scenario["modified_body"], BATCH_REQUEST_SCHEMA))
    if isinstance(scenario.get("scoped_body"), dict):
        out.append((f"{label}/scoped_body", scenario["scoped_body"], BATCH_REQUEST_SCHEMA))
    for key in ("first", "retry"):
        block = scenario.get(key)
        if isinstance(block, dict) and isinstance(block.get("body"), dict):
            out.append((f"{label}/{key}/body", block["body"], BATCH_REQUEST_SCHEMA))
    for side in ("winner", "loser"):
        block = scenario.get(side)
        if isinstance(block, dict) and isinstance(block.get("body"), dict):
            out.append((f"{label}/{side}/body", block["body"], BATCH_REQUEST_SCHEMA))
    for case in scenario.get("before_batch", []):
        body = case.get("request")
        if not isinstance(body, dict):
            continue
        pointer = (
            BATCH_REQUEST_SCHEMA if case.get("operation") == BATCH_OPERATION
            else RESOLVE_TARGET_REQUEST_SCHEMA
        )
        out.append((f"{label}/{case.get('case_id')}/request", body, pointer))
    return out


def payload_errors(
    expectations: Dict[str, Any], context: Dict[str, Any], registry
) -> List[str]:
    errors: List[str] = []
    for scenario in expectations["scenarios"]:
        for label, body, pointer in _scenario_request_bodies(scenario):
            for message in validate_value(registry, pointer, body):
                errors.append(f"{label}: {message}")
    for entry in expectations["batch_errors"]:
        schema_errors, semantic = validate_fixture(registry, ERROR_SCHEMA, materialize_error(entry))
        errors.extend(f"{entry['error_id']}: {message}" for message in schema_errors + semantic)
    for spec in expectations["isolated_batches"]:
        for page_spec in spec["pages"]:
            payload = batch_outcomes.materialize_batch_page(spec, page_spec, context["batch"])
            schema_errors, semantic = validate_fixture(registry, BATCH_SCHEMA, payload)
            errors.extend(
                f"{page_spec['page_id']}: {message}" for message in schema_errors + semantic
            )
            for outcome in payload["outcomes"]:
                schema_errors, semantic = validate_fixture(registry, OUTCOME_SCHEMA, outcome)
                errors.extend(
                    f"{page_spec['page_id']}/{outcome['item_id']}: {message}"
                    for message in schema_errors + semantic
                )
    for entry in expectations["audit_expectations"]:
        payload = materialize_audit_event(entry, context)
        schema_errors, semantic = validate_fixture(registry, AUDIT_EVENT_SCHEMA, payload)
        errors.extend(f"{entry['audit_id']}: {message}" for message in schema_errors + semantic)
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
        for item_id, member in selection["members"].items():
            payloads[f"selection_member:{selection_id}:{item_id}"] = member
    for alias, actor in context["actors"].items():
        payloads[f"actor:{alias}"] = actor
    for rule_set_id, rule_set in context["rule_sets"].items():
        payloads[f"rule_set:{rule_set_id}"] = rule_set
    for entry in context["preflight_by_id"].values():
        payloads[f"preflight:{entry['scenario_id']}"] = entry
    for error_id, entry in context["errors"].items():
        payloads[f"error:{error_id}"] = materialize_error(entry)
    for batch_id, spec in context["batch"]["batches"].items():
        payloads[f"batch:{batch_id}"] = batch_outcomes.materialize_batch_page(
            spec, spec["pages"][0], context["batch"]
        )
        payloads[f"batch_rows:{batch_id}"] = batch_outcomes.all_outcome_payloads(
            spec, context["batch"]
        )
        for outcome in payloads[f"batch_rows:{batch_id}"]:
            payloads[f"outcome:{batch_id}:{outcome['item_id']}"] = outcome
    for scenario in expectations["scenarios"]:
        payloads[f"scenario:{scenario['scenario_id']}"] = scenario
    for entry in expectations["audit_expectations"]:
        payloads[f"audit:{entry['audit_id']}"] = entry
    for case_id, case in context["containment"].items():
        payloads[f"containment:{case_id}"] = case
    for point_id, point in context["restart_points"].items():
        payloads[f"restart_point:{point_id}"] = point
    for group_id, group in context["duplicate_groups"].items():
        payloads[f"group:{group_id}"] = group
    for object_id, entry in context["occupied_targets"].items():
        payloads[f"existing_object:{object_id}"] = entry
    for object_id, entry in context["manual_review_occupied"].items():
        payloads[f"existing_object:{object_id}"] = entry
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
        try:
            source = _resolve_path(payloads[link["source"]["payload"]], link["source"]["path"])
            target = _resolve_path(payloads[link["target"]["payload"]], link["target"]["path"])
        except KeyError as exc:
            errors.append(f"{label}: unresolved payload/path {exc}")
            continue
        relation = link["relation"]
        if relation == "equals" and source != target:
            errors.append(f"{label}: {source!r} != {target!r}")
        elif relation == "not_equals" and source == target:
            errors.append(f"{label}: expected different values, both {source!r}")
        elif relation == "is_null" and source is not None:
            errors.append(f"{label}: expected null, got {source!r}")
        elif relation == "not_null" and source is None:
            errors.append(f"{label}: expected a non-null value")
        elif relation == "length_equals" and len(source) != target:
            errors.append(f"{label}: length {len(source)} != {target}")
        elif relation == "membership_equals":
            source_ids = [member["item_id"] for member in source]
            target_ids = [member["item_id"] for member in target]
            if source_ids != target_ids:
                errors.append(f"{label}: membership {source_ids} != {target_ids}")
        elif relation not in (
            "equals",
            "not_equals",
            "is_null",
            "not_null",
            "length_equals",
            "membership_equals",
        ):
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
        elif validator == "audit":
            reported = _audit_errors(mutated, mutated_context)
        elif validator == "coverage":
            reported = coverage_errors(mutated, mutated_context)
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

EXAMPLE_BINDINGS: List[Dict[str, str]] = [
    {
        "id": "batch-overlap-winner",
        "kind": "batch_page",
        "binding": "batch-overlap-winner:0",
        "schema": BATCH_SCHEMA,
        "file": "contracts/examples/sorting/batch-overlap-winner.json",
        "description": "LT-03.4b: overlap winner batch that claims and sorts the shared item plus its independent safe item.",
    },
    {
        "id": "batch-overlap-loser",
        "kind": "batch_page",
        "binding": "batch-overlap-loser:0",
        "schema": BATCH_SCHEMA,
        "file": "contracts/examples/sorting/batch-overlap-loser.json",
        "description": "LT-03.4b: overlap loser batch with SKIPPED/ALREADY_PROCESSING for the claimed shared item and a sorted independent safe item.",
    },
]


def generated_examples(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    for binding in EXAMPLE_BINDINGS:
        if binding["kind"] != "batch_page":  # pragma: no cover - static table
            raise ValueError(f"unknown example kind {binding['kind']!r}")
        batch_id, _, page_index = binding["binding"].partition(":")
        output[binding["file"]] = batch_page(batch_id, context, int(page_index))
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
        description="Materialize the WiseWay batch operational scenario examples."
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
