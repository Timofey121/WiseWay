"""LT-03.5a finite quarantine/return lifecycle oracle.

``fixtures/synthetic/quarantine_returns.json`` stores the finite, hand-authored
oracle for the manual quarantine return that API sections 2/9/10/11, TZ
FILE-07/QUEUE-01/AUD-01/02, QA sections 4/8 and the matrix rows
Q-029 (return)/Q-038/Q-043 describe.  It builds directly on:

* ``fixtures/synthetic/batch_outcomes.json`` - the actual LT-03.4a
  ``batch-atlas-technical`` confirmed ``QUARANTINED`` outcome (its item, source
  attempt, confirmed quarantine location, original incoming source and filename)
  and the same batch's ``RECOVERY_REQUIRED`` outcomes, which must never appear in
  the confirmed quarantine list;
* the auth fixture actors and the ``rule_expectations``/``queue_selections``
  company identity (incoming source id/name) reused through
  ``batch_outcomes``.

The module is a *materializer and consistency checker*, not a runtime domain:

* every ``QuarantineItem``, ``QuarantinePage``, ``QuarantineReturnRequest``,
  ``QuarantineReturnResponse``, ``ErrorResponse`` and ``AuditEvent`` is literal
  data bound to a canonical OAS schema pointer;
* the confirmed quarantine record is derived from the frozen batch outcome, so
  the return lifecycle cannot silently drift from the accepted batch;
* success, schema-invalid comment, stale revision, occupied original path,
  unknown id, already returned record, registered ambiguous recovery, key/body/
  user replay, reused key, per-user key scope and the OAS ``can_return``
  stability semantics are declared and cross-checked.

No return executor, recovery engine, filesystem writer, idempotency store or
audit journal is implemented - the values are declared and verified.  The
``can_return`` flag is the OAS server stability flag, never an invented
permission.  The audit descriptors are expected IDs for LT-03.5b, not measured
audit evidence.

A documented preparation command regenerates the committed public examples::

    python tests/contract/contractlib/quarantine_returns.py --write-examples
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
    from . import batch_outcomes, batch_scenarios, synthetic
    from .schemas import validate_value
    from .search_expectations import allowed_error_codes
    from .semantic import validate_fixture
except ImportError:  # pragma: no cover - documented direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from contractlib import batch_outcomes, batch_scenarios, synthetic  # type: ignore
    from contractlib.schemas import validate_value  # type: ignore
    from contractlib.search_expectations import allowed_error_codes  # type: ignore
    from contractlib.semantic import validate_fixture  # type: ignore

EXPECTATIONS_RELATIVE = Path("fixtures") / "synthetic" / "quarantine_returns.json"

QUARANTINE_ITEM_SCHEMA = "#/components/schemas/QuarantineItem"
QUARANTINE_PAGE_SCHEMA = "#/components/schemas/QuarantinePage"
RETURN_REQUEST_SCHEMA = "#/components/schemas/QuarantineReturnRequest"
RETURN_RESPONSE_SCHEMA = "#/components/schemas/QuarantineReturnResponse"
ERROR_SCHEMA = "#/components/schemas/ErrorResponse"
AUDIT_EVENT_SCHEMA = "#/components/schemas/AuditEvent"

RETURN_OPERATION = "returnQuarantineItem"
KNOWN_Q = ("Q-029", "Q-038", "Q-043")
CATEGORIES = (
    "SUCCESS",
    "SCHEMA_INVALID",
    "VERSION_CONFLICT",
    "ORIGINAL_OCCUPIED",
    "NOT_FOUND",
    "ALREADY_RETURNED",
    "RECOVERY_REQUIRED",
    "KEY_REUSED",
    "USER_SCOPE",
    "CAN_RETURN_STABILITY",
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
SYSTEM_ACTIONS = ("LOGIN_SUCCEEDED", "LOGIN_FAILED", "LOGOUT", "ACCOUNT_BLOCKED")
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


def _basename(relative_path: str) -> str:
    return relative_path.rsplit("/", 1)[-1]


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _all_outcomes(batch_context: Dict[str, Any]) -> Dict[Any, Dict[str, Any]]:
    outcomes: Dict[Any, Dict[str, Any]] = {}
    for batch_id, spec in batch_context["batches"].items():
        for outcome in batch_outcomes.all_outcome_payloads(spec, batch_context):
            outcomes[(batch_id, outcome["item_id"])] = outcome
    return outcomes


def build_context(
    root: Optional[Path] = None, expectations: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Load the linked fixtures and index the literal lookup tables."""
    base = Path(root) if root is not None else synthetic.repo_root()
    if expectations is None:
        expectations = load_expectations(base)
    batch_ctx = batch_outcomes.build_context(base)

    states = {entry["state_id"]: entry for entry in expectations["quarantine_states"]}
    scenarios = {entry["scenario_id"]: entry for entry in expectations["scenarios"]}
    errors = {entry["error_id"]: entry for entry in expectations["errors"]}
    replays = {entry["replay_id"]: entry for entry in expectations["replays"]}
    audit = {entry["audit_id"]: entry for entry in expectations["audit_expectations"]}
    occupied = {
        entry["object_id"]: entry for entry in expectations["occupied_original_paths"]
    }

    return {
        "base": base,
        "manifest": batch_ctx["manifest"],
        "document": batch_ctx["document"],
        "expectations": expectations,
        "batch": batch_ctx,
        "batch_expectations": batch_ctx["expectations"],
        "actors": batch_ctx["actors"],
        "selections": batch_ctx["selections"],
        "outcomes": _all_outcomes(batch_ctx),
        "companies": expectations["companies"],
        "company_by_id": {
            entry["company_id"]: entry for entry in expectations["companies"].values()
        },
        "prefix": expectations["target_display_prefix"],
        "states": states,
        "scenarios": scenarios,
        "errors": errors,
        "replays": replays,
        "audit": audit,
        "occupied": occupied,
        "quarantine_ids": {state["quarantine_id"] for state in states.values()},
        "constants": expectations["constants"],
    }


# --------------------------------------------------------------------------- #
# Materialization (literal ids only, never an executor)
# --------------------------------------------------------------------------- #

def _outcome(context: Dict[str, Any], reference: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return context["outcomes"].get((reference["batch_id"], reference["item_id"]))


def _member(context: Dict[str, Any], batch_id: str, item_id: str) -> Dict[str, Any]:
    spec = context["batch"]["batches"][batch_id]
    selection = context["batch"]["selections"][batch_outcomes._selection_id(spec)]
    return selection["members"][item_id]


def materialize_quarantine_item(
    state: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    outcome = _outcome(context, state["outcome"])
    if outcome is None:
        raise ValueError(f"unknown quarantine outcome {state['outcome']!r}")
    company = context["companies"][state["company"]]
    return {
        "quarantine_id": state["quarantine_id"],
        "revision": state["revision"],
        "item_id": outcome["item_id"],
        "company_id": company["company_id"],
        "filename": _basename(outcome["source"]["relative_path"]),
        "location": copy.deepcopy(outcome["actual_location"]),
        "original_location": copy.deepcopy(outcome["source"]),
        "reason_code": outcome["reason_code"],
        "quarantined_at": state["quarantined_at"],
        "source_attempt_id": outcome["attempt_id"],
        "recovery_operation_id": state["recovery_operation_id"],
        "can_return": state["can_return"],
    }


def materialize_quarantine_page(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    page = expectations["quarantine_page"]
    items = [
        materialize_quarantine_item(context["states"][state_id], context)
        for state_id in page["state_ids"]
    ]
    return {"items": items, "next_cursor": page.get("next_cursor")}


def materialize_return_request(scenario: Dict[str, Any]) -> Dict[str, Any]:
    return copy.deepcopy(scenario["body"])


def materialize_returned_item(
    scenario: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    state = context["states"][scenario["record_state"]]
    outcome = _outcome(context, state["outcome"])
    if outcome is None:
        raise ValueError(f"unknown quarantine outcome {state['outcome']!r}")
    company = context["companies"][state["company"]]
    member = _member(context, state["outcome"]["batch_id"], outcome["item_id"])
    return {
        "item_id": outcome["item_id"],
        "item_revision": scenario["returned_item_revision"],
        "company_id": company["company_id"],
        "incoming_source_id": company["incoming_source_id"],
        "source_name": company["source_name"],
        "source": copy.deepcopy(outcome["source"]),
        "filename": _basename(outcome["source"]["relative_path"]),
        "size_bytes": member["size_bytes"],
        "modified_at": scenario["returned_modified_at"],
        "status": "WAITING_READY",
        "reason_code": None,
        "selectable": False,
        "active_attempt_id": None,
    }


def materialize_return_response(
    scenario: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    return {
        "return_operation_id": scenario["expected"]["return_operation_id"],
        "item": materialize_returned_item(scenario, context),
    }


def materialize_error(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "error": {
            "code": entry["code"],
            "message": entry.get("message", "safe synthetic error"),
            "request_id": entry.get("request_id", "request-quarantine-demo-1"),
            "operation_id": entry.get("operation_id"),
            "retryable": entry.get("retryable", False),
            "field_errors": entry.get("field_errors", []),
        }
    }


def materialize_audit_event(
    entry: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    state = context["states"][entry["record_state"]]
    outcome = _outcome(context, state["outcome"])
    if outcome is None:
        raise ValueError(f"unknown quarantine outcome {state['outcome']!r}")
    company = context["companies"][state["company"]]
    actor = context["actors"][entry["actor"]] if entry.get("actor") else None
    source = (
        copy.deepcopy(outcome["actual_location"])
        if entry.get("source") == "quarantine"
        else None
    )
    target = (
        copy.deepcopy(outcome["source"]) if entry.get("target") == "original" else None
    )
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
        "company_id": company["company_id"],
        "dictionary_id": None,
        "version_id": None,
        "rule_set_id": None,
        "batch_id": state["outcome"]["batch_id"],
        "attempt_id": entry.get("attempt_id"),
        "item_id": outcome["item_id"],
        "source": source,
        "target": target,
        "reason_code": entry.get("reason_code"),
        "comment": entry.get("comment"),
    }


# --------------------------------------------------------------------------- #
# Scenario expectation checks
# --------------------------------------------------------------------------- #

def _uuid_errors(label: str, key_id: str, value: Any) -> List[str]:
    errors: List[str] = []
    if not isinstance(value, str) or not UUID_RE.match(value):
        errors.append(f"{label}: {key_id} must be a UUID string")
    return errors


def _error_reference_errors(
    label: str, expected: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    entry = context["errors"].get(expected.get("error_id"))
    if entry is None:
        errors.append(f"{label}: expected.error_id does not resolve")
        return errors
    if entry["code"] != expected.get("code"):
        errors.append(f"{label}: referenced error code disagrees with expected.code")
    if entry["status"] != expected.get("http"):
        errors.append(f"{label}: referenced error status disagrees with expected.http")
    if entry["operation"] != RETURN_OPERATION:
        errors.append(f"{label}: referenced error belongs to another operation")
    allowed = allowed_error_codes(
        context["document"], RETURN_OPERATION, expected.get("http")
    )
    if entry["code"] not in allowed:
        errors.append(
            f"{label}: error code {entry['code']!r} is not declared by "
            f"{RETURN_OPERATION!r} for HTTP {expected.get('http')}"
        )
    return errors


def _common_scenario_errors(
    scenario: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    label = scenario.get("scenario_id", "<missing>")
    if not isinstance(label, str) or not ID_RE.match(label):
        errors.append(f"{label}: scenario_id must be a valid Id")
    category = scenario.get("category")
    if category not in CATEGORIES:
        errors.append(f"{label}: unknown category {category!r}")
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
    if scenario.get("operation") != RETURN_OPERATION:
        errors.append(f"{label}: operation must be {RETURN_OPERATION}")
    actor = scenario.get("actor")
    if actor not in context["actors"]:
        errors.append(f"{label}: actor does not resolve to an auth fixture actor")
    errors.extend(
        _uuid_errors(label, "idempotency_key", scenario.get("idempotency_key"))
    )
    body = scenario.get("body")
    if not isinstance(body, dict):
        errors.append(f"{label}: body must be an object")
    else:
        revision = body.get("expected_revision")
        if not _is_int(revision) or revision < 0:
            errors.append(f"{label}: body.expected_revision must be a Revision")
        if not isinstance(body.get("comment"), str):
            errors.append(f"{label}: body.comment must be a string")
    expected = scenario.get("expected")
    if not isinstance(expected, dict):
        errors.append(f"{label}: expected must be an object")
        return errors
    if category != "CAN_RETURN_STABILITY":
        if not _is_int(expected.get("http")):
            errors.append(f"{label}: expected.http must be an integer")
        if expected.get("result") not in ("RETURN", "ERROR"):
            errors.append(f"{label}: expected.result must be RETURN or ERROR")
        if expected.get("result") == "ERROR":
            errors.extend(_error_reference_errors(label, expected, context))
    if expected.get("new_move"):
        errors.append(f"{label}: a return must never perform a second move")
    return errors


def _success_errors(scenario: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = scenario["scenario_id"]
    expected = scenario["expected"]
    state = context["states"].get(scenario.get("record_state"))
    if state is None:
        return [f"{label}: record_state does not resolve"]
    if state.get("returned"):
        errors.append(f"{label}: a successful return needs a not-yet-returned record")
    if state.get("can_return") is not True:
        errors.append(f"{label}: a successful return needs can_return=true")
    if state.get("recovery_operation_id") is not None:
        errors.append(f"{label}: a returnable record must not carry recovery_operation_id")
    if scenario["body"]["expected_revision"] != state["revision"]:
        errors.append(f"{label}: expected_revision must equal the current quarantine revision")
    if expected.get("http") != 200 or expected.get("result") != "RETURN":
        errors.append(f"{label}: a successful return is 200/RETURN")
    if not expected.get("return_operation_id"):
        errors.append(f"{label}: a success declares return_operation_id")
    if expected.get("item_status") != "WAITING_READY":
        errors.append(f"{label}: a returned item is WAITING_READY")
    if expected.get("selectable") is not False:
        errors.append(f"{label}: a returned item is not selectable")
    if expected.get("active_attempt_id") is not None:
        errors.append(f"{label}: a returned item has no active attempt")
    if expected.get("reason_code") is not None:
        errors.append(f"{label}: a returned item has no reason_code")
    if expected.get("no_autosort") is not True:
        errors.append(f"{label}: a return never auto-starts sorting")
    if expected.get("new_batch") is not False or expected.get("new_attempt") is not False:
        errors.append(f"{label}: a return creates no batch and no attempt")
    if expected.get("second_move") is not False:
        errors.append(f"{label}: a return performs exactly one move")
    if expected.get("source_preserved") is not True:
        errors.append(f"{label}: the returned source is the original incoming path")
    outcome = _outcome(context, state["outcome"])
    if outcome is None:
        errors.append(f"{label}: the quarantine outcome does not resolve")
        return errors
    item = materialize_returned_item(scenario, context)
    if item["source"] != outcome["source"]:
        errors.append(f"{label}: the returned item source must be the original incoming path")
    if item["filename"] != _basename(item["source"]["relative_path"]):
        errors.append(f"{label}: the returned filename must be the basename of its source")
    if not _is_int(item["item_revision"]) or item["item_revision"] <= outcome["item_revision"]:
        errors.append(f"{label}: the returned item_revision must grow past the quarantined revision")
    if not scenario.get("returned_modified_at"):
        errors.append(f"{label}: a success declares the returned modified_at")
    else:
        try:
            _instant(scenario["returned_modified_at"])
        except (TypeError, ValueError):
            errors.append(f"{label}: returned_modified_at must be an Instant")
    return errors


def _schema_invalid_errors(scenario: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = scenario["scenario_id"]
    if scenario.get("schema_rejected") is not True:
        errors.append(f"{label}: a schema-invalid request must declare schema_rejected=true")
    expected = scenario["expected"]
    if expected.get("http") != 422:
        errors.append(f"{label}: a schema-invalid comment is 422")
    if expected.get("code") != "VALIDATION_ERROR":
        errors.append(f"{label}: a schema-invalid comment is VALIDATION_ERROR")
    if expected.get("mutates") is not False or expected.get("new_move") is not False:
        errors.append(f"{label}: a rejected request mutates nothing")
    return errors


def _version_conflict_errors(
    scenario: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    label = scenario["scenario_id"]
    state = context["states"].get(scenario.get("record_state"))
    if state is None:
        return [f"{label}: record_state does not resolve"]
    if scenario["body"]["expected_revision"] == state["revision"]:
        errors.append(f"{label}: a stale revision must differ from the current revision")
    expected = scenario["expected"]
    if expected.get("http") != 409 or expected.get("code") != "QUARANTINE_VERSION_CONFLICT":
        errors.append(f"{label}: a stale revision is 409 QUARANTINE_VERSION_CONFLICT")
    if expected.get("mutates") is not False:
        errors.append(f"{label}: a version conflict mutates nothing")
    return errors


def _original_occupied_errors(
    scenario: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    label = scenario["scenario_id"]
    state = context["states"].get(scenario.get("record_state"))
    if state is None:
        return [f"{label}: record_state does not resolve"]
    occupied = context["occupied"].get(scenario.get("occupied_object"))
    if occupied is None:
        errors.append(f"{label}: occupied_object does not resolve")
    else:
        outcome = _outcome(context, state["outcome"])
        if outcome is None:
            errors.append(f"{label}: the quarantine outcome does not resolve")
        elif occupied.get("location") != outcome["source"]:
            errors.append(
                f"{label}: the occupied object must sit at the quarantine record's "
                "original incoming path"
            )
        if occupied.get("unchanged") is not True:
            errors.append(f"{label}: an occupied original path preserves the existing object")
    expected = scenario["expected"]
    if expected.get("http") != 409 or expected.get("code") != "ORIGINAL_PATH_OCCUPIED":
        errors.append(f"{label}: an occupied original path is 409 ORIGINAL_PATH_OCCUPIED")
    if expected.get("mutates") is not False or expected.get("new_move") is not False:
        errors.append(f"{label}: an occupied original path moves nothing")
    if expected.get("existing_unchanged") is not True:
        errors.append(f"{label}: an occupied original path leaves the existing object intact")
    return errors


def _not_found_errors(scenario: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = scenario["scenario_id"]
    unknown = scenario.get("unknown_quarantine_id")
    if unknown is None:
        errors.append(f"{label}: unknown_quarantine_id must be set")
    elif unknown in context["quarantine_ids"]:
        errors.append(f"{label}: unknown_quarantine_id must not be a known quarantine record")
    expected = scenario["expected"]
    if expected.get("http") != 404 or expected.get("code") != "NOT_FOUND":
        errors.append(f"{label}: an unknown quarantine id is 404 NOT_FOUND")
    if expected.get("mutates") is not False:
        errors.append(f"{label}: an unknown id mutates nothing")
    return errors


def _already_returned_errors(
    scenario: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    label = scenario["scenario_id"]
    if scenario.get("precondition") != "RETURNED":
        errors.append(f"{label}: an already-returned record must declare precondition RETURNED")
    expected = scenario["expected"]
    if expected.get("http") != 409 or expected.get("code") != "INVALID_STATE":
        errors.append(f"{label}: an already-returned record with a new key is 409 INVALID_STATE")
    if expected.get("mutates") is not False or expected.get("second_return") is not False:
        errors.append(f"{label}: an already-returned record is not returned again")
    state = context["states"].get(scenario.get("record_state"))
    if state is not None and scenario["body"]["expected_revision"] <= state["revision"]:
        errors.append(
            f"{label}: an already-returned record is evaluated on its advanced revision"
        )
    return errors


def _recovery_required_errors(
    scenario: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    label = scenario["scenario_id"]
    state = context["states"].get(scenario.get("record_state"))
    if state is None:
        return [f"{label}: record_state does not resolve"]
    if state.get("can_return") is not False:
        errors.append(f"{label}: an ambiguous return record must have can_return=false")
    if not state.get("recovery_operation_id"):
        errors.append(f"{label}: an ambiguous return record must expose recovery_operation_id")
    expected = scenario["expected"]
    if expected.get("http") != 409 or expected.get("code") != "RECOVERY_REQUIRED":
        errors.append(f"{label}: an ambiguous return is 409 RECOVERY_REQUIRED")
    if not expected.get("operation_id"):
        errors.append(f"{label}: an ambiguous return exposes a non-null error.operation_id")
    if expected.get("operation_id") != state.get("recovery_operation_id"):
        errors.append(
            f"{label}: error.operation_id must equal the quarantine recovery_operation_id"
        )
    if expected.get("can_return") is not False:
        errors.append(f"{label}: an ambiguous return declares can_return=false")
    if expected.get("produced_item") is not False:
        errors.append(f"{label}: an ambiguous return produces no returned item")
    if expected.get("actual_placement") is not None:
        errors.append(f"{label}: an ambiguous return has no confirmed placement")
    error_entry = context["errors"].get(expected.get("error_id"))
    if error_entry is not None:
        if error_entry.get("operation_id") != expected.get("operation_id"):
            errors.append(f"{label}: the referenced error must carry the registered operation_id")
        if error_entry.get("retryable") is not False:
            errors.append(f"{label}: a registered recovery is not retryable")
    return errors


def _key_reused_errors(scenario: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = scenario["scenario_id"]
    original = context["scenarios"].get(scenario.get("replay_of"))
    if original is None:
        errors.append(f"{label}: replay_of does not resolve to a scenario")
    else:
        if scenario.get("same_key") is not True:
            errors.append(f"{label}: a reused key must reuse the original key")
        if scenario.get("same_user") is not True:
            errors.append(f"{label}: a reused key must reuse the original user")
        if scenario.get("same_body") is not False:
            errors.append(f"{label}: a reused key must change the body")
        if scenario.get("idempotency_key") != original.get("idempotency_key"):
            errors.append(f"{label}: the key must equal the original scenario key")
        if scenario.get("body") == original.get("body"):
            errors.append(f"{label}: the modified body must differ from the original body")
    expected = scenario["expected"]
    if expected.get("http") != 409 or expected.get("code") != "IDEMPOTENCY_KEY_REUSED":
        errors.append(f"{label}: a reused key with a new body is 409 IDEMPOTENCY_KEY_REUSED")
    if expected.get("idempotency_conflict") is not True:
        errors.append(f"{label}: a reused key is an idempotency conflict")
    return errors


def _user_scope_errors(scenario: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = scenario["scenario_id"]
    if scenario.get("original_actor") == scenario.get("scoped_actor"):
        errors.append(f"{label}: a separate scope needs two different users")
    original = context["scenarios"].get(scenario.get("original_scenario"))
    if original is None:
        errors.append(f"{label}: original_scenario does not resolve")
    elif scenario.get("idempotency_key") != original.get("idempotency_key"):
        errors.append(f"{label}: the scenario must reuse the same key string")
    if scenario.get("actor") != scenario.get("scoped_actor"):
        errors.append(f"{label}: the scoped actor must send the request")
    expected = scenario["expected"]
    if expected.get("separate_scope") is not True:
        errors.append(f"{label}: another user with the same key string is a separate scope")
    if expected.get("idempotency_conflict"):
        errors.append(f"{label}: another user is not a global key conflict")
    if expected.get("code") == "IDEMPOTENCY_KEY_REUSED":
        errors.append(f"{label}: another user must not be reported as a key conflict")
    if expected.get("http") != 409 or expected.get("code") != "INVALID_STATE":
        errors.append(f"{label}: the scoped operation is evaluated on current state (409 INVALID_STATE)")
    state = context["states"].get(scenario.get("record_state"))
    if state is not None and scenario["body"]["expected_revision"] <= state["revision"]:
        errors.append(
            f"{label}: the scoped operation is evaluated on the advanced revision"
        )
    return errors


def _can_return_stability_errors(
    scenario: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    label = scenario["scenario_id"]
    state = context["states"].get(scenario.get("record_state"))
    if state is None:
        return [f"{label}: record_state does not resolve"]
    if state.get("can_return") is not False:
        errors.append(f"{label}: the observation needs an unstable record (can_return=false)")
    if state.get("recovery_operation_id") is None:
        errors.append(f"{label}: an unstable record carries its recovery_operation_id")
    expected = scenario["expected"]
    if expected.get("can_return") is not False:
        errors.append(f"{label}: can_return is false for the ambiguous record")
    if expected.get("recovery_operation_id") != state.get("recovery_operation_id"):
        errors.append(f"{label}: the observation must match the record recovery_operation_id")
    if expected.get("permission_based") is not False:
        errors.append(f"{label}: can_return must not be modelled as a permission")
    if expected.get("role_based") is not False:
        errors.append(f"{label}: can_return must not be modelled as a role grant")
    return errors


def _scenario_errors(scenario: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors = _common_scenario_errors(scenario, context)
    category = scenario.get("category")
    dispatch = {
        "SUCCESS": _success_errors,
        "SCHEMA_INVALID": _schema_invalid_errors,
        "VERSION_CONFLICT": _version_conflict_errors,
        "ORIGINAL_OCCUPIED": _original_occupied_errors,
        "NOT_FOUND": _not_found_errors,
        "ALREADY_RETURNED": _already_returned_errors,
        "RECOVERY_REQUIRED": _recovery_required_errors,
        "KEY_REUSED": _key_reused_errors,
        "USER_SCOPE": _user_scope_errors,
        "CAN_RETURN_STABILITY": _can_return_stability_errors,
    }
    handler = dispatch.get(category)
    if handler is not None:
        errors.extend(handler(scenario, context))
    return errors


def _replay_errors(replay: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = replay.get("replay_id", "<missing>")
    if not isinstance(label, str) or not ID_RE.match(label):
        errors.append(f"{label}: replay_id must be a valid Id")
    original = context["scenarios"].get(replay.get("of"))
    if original is None:
        errors.append(f"{label}: of does not resolve to a scenario")
        return errors
    if not (replay.get("same_key") and replay.get("same_user") and replay.get("same_body")):
        errors.append(f"{label}: a replay must reuse key/user/body")
    if replay.get("idempotency_key", original["idempotency_key"]) != original["idempotency_key"]:
        errors.append(f"{label}: a replay must reuse the original key")
    if replay.get("body", original["body"]) != original["body"]:
        errors.append(f"{label}: a replay must reuse the original body")
    try:
        _instant(replay.get("at", ""))
    except (TypeError, ValueError):
        errors.append(f"{label}: replay.at must be an Instant")
    after = replay.get("record_revision_after")
    if not _is_int(after) or after <= original["body"]["expected_revision"]:
        errors.append(
            f"{label}: the replay must be evaluated after the quarantine revision changed"
        )
    expected = replay["expected"]
    if expected.get("new_move") is not False:
        errors.append(f"{label}: a replay must not perform a second move")
    if expected.get("new_attempt") is not False:
        errors.append(f"{label}: a replay must not create a new attempt")
    if expected.get("new_event") is not False:
        errors.append(f"{label}: a replay must not add a duplicate audit event")
    if original["category"] == "SUCCESS":
        if expected.get("http") != 200 or expected.get("result") != "RETURN":
            errors.append(f"{label}: a success replay returns the same 200/RETURN")
        if expected.get("return_operation_id") != original["expected"]["return_operation_id"]:
            errors.append(f"{label}: a success replay returns the original return_operation_id")
    elif original["category"] == "RECOVERY_REQUIRED":
        if expected.get("http") != 409 or expected.get("result") != "ERROR":
            errors.append(f"{label}: a recovery replay returns the same 409/RECOVERY_REQUIRED")
        if expected.get("code") != "RECOVERY_REQUIRED":
            errors.append(f"{label}: a recovery replay keeps the RECOVERY_REQUIRED code")
        if expected.get("operation_id") != original["expected"]["operation_id"]:
            errors.append(f"{label}: a recovery replay returns the registered operation_id")
    else:
        errors.append(f"{label}: a replay must follow a success or a registered recovery")
    return errors


def _inventory_errors(expectations: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    """The logical return inventory expectation (never a measured hash)."""
    errors: List[str] = []
    inventory = expectations["return_inventory"]
    if inventory.get("kind") != "logical-inventory-expectation":
        errors.append("return inventory must be a logical expectation, not measured evidence")
    if inventory.get("no_file_writes") is not True:
        errors.append("return inventory must declare that no file is written")
    success = inventory.get("success", {})
    if success.get("source_quarantine_present_after") is not False:
        errors.append("a successful return removes the file from quarantine")
    if success.get("original_present_after") is not True:
        errors.append("a successful return restores the original incoming path")
    if success.get("content_conserved") is not True:
        errors.append("a successful return conserves content")
    if success.get("prior_batch_unchanged") is not True:
        errors.append("a successful return leaves the prior batch unchanged")
    ambiguous = inventory.get("ambiguous", {})
    if ambiguous.get("source_quarantine_present_after") is not None:
        errors.append("an ambiguous return asserts no quarantine side")
    if ambiguous.get("original_present_after") is not None:
        errors.append("an ambiguous return asserts no original side")
    if ambiguous.get("content_conserved") is not None:
        errors.append("an ambiguous return asserts no content conservation")
    if ambiguous.get("prior_batch_unchanged") is not True:
        errors.append("an ambiguous return still leaves the prior batch unchanged")
    success_scenario = context["scenarios"].get("QR-RETURN-SUCCESS")
    if success_scenario is None or success_scenario["category"] != "SUCCESS":
        errors.append("the return inventory needs the declared success scenario")
    recovery_scenario = context["scenarios"].get("QR-RECOVERY-AMBIGUOUS")
    if recovery_scenario is None or recovery_scenario["category"] != "RECOVERY_REQUIRED":
        errors.append("the return inventory needs the declared ambiguous recovery scenario")
    return errors


def _record_errors(expectations: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    """Every quarantine record stays bound to the frozen confirmed outcome."""
    errors: List[str] = []
    for state in expectations["quarantine_states"]:
        label = state.get("state_id", "<missing>")
        outcome = _outcome(context, state["outcome"])
        if outcome is None:
            errors.append(f"{label}: the quarantine outcome does not resolve")
            continue
        if outcome.get("state") != "QUARANTINED":
            errors.append(f"{label}: a quarantine record must reference a QUARANTINED outcome")
        try:
            quarantined = _instant(state["quarantined_at"])
        except (TypeError, ValueError):
            errors.append(f"{label}: quarantined_at must be an Instant")
            continue
        finished = outcome.get("finished_at")
        if finished is None:
            errors.append(f"{label}: a confirmed quarantine outcome must be finished")
        else:
            try:
                if quarantined != _instant(finished):
                    errors.append(
                        f"{label}: quarantined_at must equal the confirmed quarantine finish time"
                    )
            except (TypeError, ValueError):
                errors.append(f"{label}: the linked outcome finished_at is not an Instant")
        if not state.get("reason"):
            errors.append(f"{label}: reason must not be empty")
    return errors


def _prior_batch_errors(expectations: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    prior = expectations["prior_batch"]
    batch = context["batch"]["batches"].get(prior["batch_id"])
    if batch is None:
        errors.append("prior_batch.batch_id does not resolve to a linked batch")
        return errors
    if batch.get("status") != prior["status"]:
        errors.append("the linked prior batch status changed; it must stay immutable")
    if batch.get("finished_at") != prior["finished_at"]:
        errors.append("the linked prior batch finished_at changed; it must stay immutable")
    outcome = context["outcomes"].get((prior["batch_id"], prior["quarantine_item_id"]))
    if outcome is None:
        errors.append("prior_batch.quarantine_item_id is not an outcome of the linked batch")
    elif outcome.get("state") != "QUARANTINED" or outcome.get("reason_code") != "TECHNICAL_ERROR":
        errors.append("the linked quarantine outcome must be QUARANTINED/TECHNICAL_ERROR")
    return errors


def _quarantine_list_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    derived_confirmed: List[Any] = []
    derived_recovery: List[Any] = []
    for (batch_id, item_id), outcome in sorted(context["outcomes"].items()):
        if outcome["state"] == "QUARANTINED":
            derived_confirmed.append((batch_id, item_id))
        elif outcome["state"] == "RECOVERY_REQUIRED":
            derived_recovery.append((batch_id, item_id))

    declared_confirmed = [
        (ref["batch_id"], ref["item_id"]) for ref in expectations["confirmed_outcomes"]
    ]
    declared_recovery = [
        (ref["batch_id"], ref["item_id"]) for ref in expectations["recovery_outcomes"]
    ]
    if sorted(declared_confirmed) != sorted(derived_confirmed):
        errors.append(
            "declared confirmed quarantine outcomes do not match the linked batch outcomes"
        )
    if sorted(declared_recovery) != sorted(derived_recovery):
        errors.append(
            "declared recovery outcomes do not match the linked batch outcomes"
        )

    page_items: List[Dict[str, Any]] = []
    for state_id in expectations["quarantine_page"]["state_ids"]:
        state = context["states"].get(state_id)
        if state is None:
            errors.append(f"quarantine page references unknown state {state_id!r}")
            continue
        outcome = _outcome(context, state["outcome"])
        if (
            outcome is None
            or outcome["state"] != "QUARANTINED"
            or not isinstance(outcome["actual_location"], dict)
        ):
            errors.append(
                f"quarantine page state {state_id!r} is not a confirmed quarantine outcome"
            )
            continue
        page_items.append(materialize_quarantine_item(state, context))

    page_ids = [item["item_id"] for item in page_items]
    confirmed_ids = [ref["item_id"] for ref in expectations["confirmed_outcomes"]]
    if page_ids != confirmed_ids:
        errors.append(
            f"quarantine page items {page_ids} != confirmed quarantine outcomes {confirmed_ids}"
        )
    recovery_ids = {ref["item_id"] for ref in expectations["recovery_outcomes"]}
    if set(page_ids) & recovery_ids:
        errors.append(
            "a recovery-required outcome must not appear in the confirmed quarantine list"
        )
    if len(page_ids) != len(set(page_ids)):
        errors.append("the quarantine page repeats an item")
    return errors


def _audit_errors(expectations: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    return_operations = {
        scenario["expected"].get("return_operation_id")
        for scenario in expectations["scenarios"]
        if scenario["category"] == "SUCCESS"
    }
    recovery_operations = {
        scenario["expected"].get("operation_id")
        for scenario in expectations["scenarios"]
        if scenario["category"] == "RECOVERY_REQUIRED"
    }
    return_actors = {
        scenario["expected"].get("return_operation_id"): scenario["actor"]
        for scenario in expectations["scenarios"]
        if scenario["category"] == "SUCCESS"
    }
    seen_keys: Dict[str, str] = {}
    for entry in expectations["audit_expectations"]:
        label = entry.get("audit_id", "<missing>")
        if not isinstance(label, str) or not ID_RE.match(label):
            errors.append(f"{label}: audit_id must be a valid Id")
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
        actor = entry.get("actor")
        if actor not in context["actors"]:
            errors.append(f"{label}: actor does not resolve to an auth fixture actor")
        if entry.get("evidence") is not False:
            errors.append(f"{label}: an audit descriptor is not measured audit evidence")
        action = entry.get("action")
        if action in SYSTEM_ACTIONS and entry.get("category") != "SYSTEM":
            errors.append(f"{label}: {action} is a SYSTEM event")
        if action not in SYSTEM_ACTIONS and entry.get("category") != "BUSINESS":
            errors.append(f"{label}: {action} is a BUSINESS event")
        state = context["states"].get(entry.get("record_state"))
        if state is None:
            errors.append(f"{label}: record_state does not resolve")
            continue
        outcome = _outcome(context, state["outcome"])
        if outcome is None:
            errors.append(f"{label}: the quarantine outcome does not resolve")
            continue
        if entry.get("source_attempt_id") != outcome["attempt_id"]:
            errors.append(
                f"{label}: source_attempt_id must link the original sorting attempt"
            )
        if action == "QUARANTINE_RETURNED":
            if entry.get("operation_id") not in return_operations:
                errors.append(
                    f"{label}: QUARANTINE_RETURNED operation_id must be a return_operation_id"
                )
            if return_actors.get(entry.get("operation_id")) != actor:
                errors.append(
                    f"{label}: the return event actor must be the return operation actor"
                )
            if entry.get("source") != "quarantine" or entry.get("target") != "original":
                errors.append(
                    f"{label}: a return event moves the quarantine location to the original path"
                )
        elif action == "RECOVERY_REQUIRED":
            if entry.get("operation_id") not in recovery_operations:
                errors.append(
                    f"{label}: RECOVERY_REQUIRED operation_id must be the registered recovery"
                )
            if entry.get("target") is not None:
                errors.append(f"{label}: an ambiguous recovery has no confirmed target")
        else:
            errors.append(f"{label}: unexpected audit action for the return lifecycle")
    return errors


def coverage_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    known = set(context["scenarios"])
    known.update(replay["replay_id"] for replay in expectations["replays"])
    known.update(error["error_id"] for error in expectations["errors"])
    known.update(state["state_id"] for state in expectations["quarantine_states"])
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
    for replay in expectations["replays"]:
        errors.extend(_replay_errors(replay, context))
    errors.extend(_record_errors(expectations, context))
    errors.extend(_inventory_errors(expectations, context))
    errors.extend(_prior_batch_errors(expectations, context))
    errors.extend(_quarantine_list_errors(expectations, context))
    errors.extend(_audit_errors(expectations, context))
    errors.extend(coverage_errors(expectations, context))
    return errors


# --------------------------------------------------------------------------- #
# Schema validation
# --------------------------------------------------------------------------- #

def payload_errors(
    expectations: Dict[str, Any], context: Dict[str, Any], registry
) -> List[str]:
    errors: List[str] = []
    for state in expectations["quarantine_states"]:
        item = materialize_quarantine_item(state, context)
        schema_errors, semantic = validate_fixture(registry, QUARANTINE_ITEM_SCHEMA, item)
        errors.extend(f"{state['state_id']}: {message}" for message in schema_errors + semantic)
    page = materialize_quarantine_page(expectations, context)
    schema_errors, semantic = validate_fixture(registry, QUARANTINE_PAGE_SCHEMA, page)
    errors.extend(f"quarantine_page: {message}" for message in schema_errors + semantic)

    for scenario in expectations["scenarios"]:
        label = scenario["scenario_id"]
        if scenario.get("schema_rejected"):
            continue
        for message in validate_value(
            registry, RETURN_REQUEST_SCHEMA, materialize_return_request(scenario)
        ):
            errors.append(f"{label}: {message}")
        if scenario["category"] == "SUCCESS":
            response = materialize_return_response(scenario, context)
            schema_errors, semantic = validate_fixture(
                registry, RETURN_RESPONSE_SCHEMA, response
            )
            errors.extend(f"{label}: {message}" for message in schema_errors + semantic)

    for error in expectations["errors"]:
        schema_errors, semantic = validate_fixture(
            registry, ERROR_SCHEMA, materialize_error(error)
        )
        errors.extend(f"{error['error_id']}: {message}" for message in schema_errors + semantic)

    for entry in expectations["audit_expectations"]:
        payload = materialize_audit_event(entry, context)
        schema_errors, semantic = validate_fixture(registry, AUDIT_EVENT_SCHEMA, payload)
        errors.extend(f"{entry['audit_id']}: {message}" for message in schema_errors + semantic)
    return errors


def schema_rejection_errors(
    expectations: Dict[str, Any], registry
) -> List[str]:
    errors: List[str] = []
    for scenario in expectations["scenarios"]:
        label = scenario["scenario_id"]
        schema_errors = validate_value(
            registry, RETURN_REQUEST_SCHEMA, materialize_return_request(scenario)
        )
        if scenario.get("schema_rejected") and not schema_errors:
            errors.append(f"{label}: declared schema rejection but the schema accepted it")
        if not scenario.get("schema_rejected") and schema_errors:
            errors.append(
                f"{label}: declared schema-valid but the schema rejected it: {schema_errors}"
            )
    return errors


# --------------------------------------------------------------------------- #
# Generic payload links
# --------------------------------------------------------------------------- #

def build_payloads(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    payloads: Dict[str, Any] = {}
    for state_id, state in context["states"].items():
        payloads[f"quarantine_item:{state_id}"] = materialize_quarantine_item(state, context)
    payloads["quarantine_page"] = materialize_quarantine_page(expectations, context)
    for (batch_id, item_id), outcome in context["outcomes"].items():
        payloads[f"outcome:{batch_id}:{item_id}"] = outcome
    for batch_id, spec in context["batch"]["batches"].items():
        payloads[f"batch:{batch_id}"] = spec
    for scenario in expectations["scenarios"]:
        payloads[f"scenario:{scenario['scenario_id']}"] = scenario
        if scenario["category"] == "SUCCESS":
            payloads[f"return_request:{scenario['scenario_id']}"] = materialize_return_request(
                scenario
            )
            payloads[f"return_response:{scenario['scenario_id']}"] = materialize_return_response(
                scenario, context
            )
    for replay in expectations["replays"]:
        payloads[f"replay:{replay['replay_id']}"] = replay
    for error in expectations["errors"]:
        payloads[f"error:{error['error_id']}"] = materialize_error(error)
    for entry in expectations["audit_expectations"]:
        payloads[f"audit:{entry['audit_id']}"] = materialize_audit_event(entry, context)
    for obj in expectations["occupied_original_paths"]:
        payloads[f"existing_object:{obj['object_id']}"] = obj
    payloads["null_value"] = None
    payloads["false_value"] = False
    payloads["true_value"] = True
    payloads["constants"] = expectations["constants"]
    return payloads


def link_errors(
    expectations: Dict[str, Any],
    context: Dict[str, Any],
    payloads: Optional[Dict[str, Any]] = None,
) -> List[str]:
    if payloads is None:
        payloads = build_payloads(expectations, context)
    return batch_scenarios.link_errors(expectations, context, payloads)


# --------------------------------------------------------------------------- #
# Negative mutations
# --------------------------------------------------------------------------- #

def mutation_errors(
    expectations: Dict[str, Any], context: Dict[str, Any], registry
) -> List[str]:
    errors: List[str] = []
    for mutation in expectations["mutations"]:
        label = mutation["mutation_id"]
        mutated = copy.deepcopy(expectations)
        batch_scenarios._apply_mutation(mutated, mutation)
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
        elif validator == "schema":
            reported = schema_rejection_errors(mutated, registry)
        elif validator == "link":
            reported = link_errors(mutated, mutated_context)
        elif validator == "list":
            reported = _quarantine_list_errors(mutated, mutated_context)
        elif validator == "inventory":
            reported = _inventory_errors(mutated, mutated_context)
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

# (example id, kind, binding, canonical schema, output file, description).
EXAMPLE_BINDINGS: List[Dict[str, str]] = [
    {
        "id": "quarantine-item-atlas-technical",
        "kind": "quarantine_item",
        "binding": "QR-STATE-CONFIRMED",
        "schema": QUARANTINE_ITEM_SCHEMA,
        "file": "contracts/examples/quarantine/quarantine-item-atlas-technical.json",
        "description": "LT-03.5a: confirmed quarantine record derived from the LT-03.4a QUARANTINED outcome.",
    },
    {
        "id": "quarantine-item-atlas-ambiguous",
        "kind": "quarantine_item",
        "binding": "QR-STATE-AMBIGUOUS",
        "schema": QUARANTINE_ITEM_SCHEMA,
        "file": "contracts/examples/quarantine/quarantine-item-atlas-ambiguous.json",
        "description": "LT-03.5a: ambiguous return record with can_return=false and a registered recovery_operation_id.",
    },
    {
        "id": "quarantine-list-atlas",
        "kind": "quarantine_page",
        "binding": None,
        "schema": QUARANTINE_PAGE_SCHEMA,
        "file": "contracts/examples/quarantine/quarantine-list-atlas.json",
        "description": "LT-03.5a: confirmed quarantine list containing only the QUARANTINED outcome.",
    },
    {
        "id": "quarantine-return-request",
        "kind": "return_request",
        "binding": "QR-RETURN-SUCCESS",
        "schema": RETURN_REQUEST_SCHEMA,
        "file": "contracts/examples/quarantine/quarantine-return-request.json",
        "description": "LT-03.5a: valid return request with the current revision and a 1..500 comment.",
    },
    {
        "id": "quarantine-return-response",
        "kind": "return_response",
        "binding": "QR-RETURN-SUCCESS",
        "schema": RETURN_RESPONSE_SCHEMA,
        "file": "contracts/examples/quarantine/quarantine-return-response.json",
        "description": "LT-03.5a: successful return response with a WAITING_READY, non-selectable QueueItem and the original source.",
    },
    {
        "id": "error-quarantine-comment-validation",
        "kind": "error",
        "binding": "error-quarantine-comment-validation",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-quarantine-comment-validation.json",
        "description": "LT-03.5a: 422 VALIDATION_ERROR for an out-of-range return comment.",
    },
    {
        "id": "error-quarantine-version-conflict",
        "kind": "error",
        "binding": "error-quarantine-version-conflict",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-quarantine-version-conflict.json",
        "description": "LT-03.5a: 409 QUARANTINE_VERSION_CONFLICT for a stale expected_revision.",
    },
    {
        "id": "error-original-path-occupied",
        "kind": "error",
        "binding": "error-original-path-occupied",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-original-path-occupied.json",
        "description": "LT-03.5a: 409 ORIGINAL_PATH_OCCUPIED without moving anything.",
    },
    {
        "id": "error-quarantine-not-found",
        "kind": "error",
        "binding": "error-quarantine-not-found",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-quarantine-not-found.json",
        "description": "LT-03.5a: 404 NOT_FOUND for an unknown quarantine id.",
    },
    {
        "id": "error-quarantine-invalid-state",
        "kind": "error",
        "binding": "error-quarantine-invalid-state",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-quarantine-invalid-state.json",
        "description": "LT-03.5a: 409 INVALID_STATE for an already returned record with a new key.",
    },
    {
        "id": "error-quarantine-recovery-required",
        "kind": "error",
        "binding": "error-quarantine-recovery-required",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-quarantine-recovery-required.json",
        "description": "LT-03.5a: 409 RECOVERY_REQUIRED with the registered operation_id.",
    },
    {
        "id": "error-quarantine-idempotency-key-reused",
        "kind": "error",
        "binding": "error-quarantine-idempotency-key-reused",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-quarantine-idempotency-key-reused.json",
        "description": "LT-03.5a: 409 IDEMPOTENCY_KEY_REUSED for the same key with a different body.",
    },
]


def generated_examples(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    for binding in EXAMPLE_BINDINGS:
        kind = binding["kind"]
        if kind == "quarantine_item":
            payload = materialize_quarantine_item(
                context["states"][binding["binding"]], context
            )
        elif kind == "quarantine_page":
            payload = materialize_quarantine_page(expectations, context)
        elif kind == "return_request":
            payload = materialize_return_request(context["scenarios"][binding["binding"]])
        elif kind == "return_response":
            payload = materialize_return_response(
                context["scenarios"][binding["binding"]], context
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
        description="Materialize the WiseWay quarantine/return oracle examples."
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
