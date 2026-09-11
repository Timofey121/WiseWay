"""LT-03.5b finite canonical audit journal oracle.

``fixtures/synthetic/audit_expectations.json`` is the canonical, hand-authored
oracle for the immutable audit journal that API sections 2/10/11, TZ
AUD-01…05, QA sections 4/8 and the matrix rows Q-041/Q-043/Q-029 (return)
describe.  It connects, without duplicating, the audit descriptors already
published by:

* ``dictionary_lifecycle.json`` - the actual create/save/simulate/publish/
  restore timeline (actor, occurred_at, draft revision, version, RuleSet,
  comment, request); the dictionary event time is derived from the lifecycle
  (state ``updated_at``, simulation ``created_at`` or version ``published_at``)
  and is never a second hand-authored literal;
* ``batch_outcomes.json`` - the actual accepted batches and their 260
  per-file outcomes (attempt start, terminal result or recovery);
* ``batch_scenarios.json`` - the isolated overlap/retry/late-target/duplicate
  and session descriptors, cross-checked against the canonical universe;
* ``quarantine_returns.json`` - the manual return success and the registered
  ambiguous recovery.

The module is a *materializer and consistency checker*, not a runtime domain:

* every ``AuditEvent``, ``AuditQueryRequest``/``AuditQueryResponse``,
  ``ActorPage``, ``AuditUpdatesResponse`` and ``ErrorResponse`` is literal data
  bound to a canonical OAS schema pointer;
* the attempt events are expanded from the frozen LT-03.4a outcome rows by a
  declarative state->event recipe (the documented "literal range recipe"), so
  the 260 outcome rows can never silently drift from the journal and no attempt
  phase is duplicated;
* the finite query scenarios declare the *literal* expected ordered event ids,
  which the module re-derives from the declared events to prove the ordering,
  filters and cursor bounds are internally consistent.

No audit journal, filter engine, cursor store, actor directory or HTTP
transport is implemented - the values are declared and verified.  ``actor=null``
is only modelled for an uninitiated ``LOGIN_FAILED``; a blocked author stays in
the actor filter list with the historical display-name snapshot, and no
blocking metadata is invented as an ``Actor`` DTO field.  Search, navigation and
copy never create a BUSINESS event.  The audit descriptors remain expectations,
not measured evidence.

A documented preparation command regenerates the committed public examples::

    python tests/contract/contractlib/audit_expectations.py --write-examples
"""

from __future__ import annotations

import argparse
import copy
import functools
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:  # package import (tests, verify_contract.py)
    from . import (
        batch_outcomes,
        batch_scenarios,
        dictionary_lifecycle,
        quarantine_returns,
        synthetic,
    )
    from .schemas import validate_value
    from .search_expectations import allowed_error_codes
    from .semantic import validate_fixture
except ImportError:  # pragma: no cover - documented direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from contractlib import (  # type: ignore
        batch_outcomes,
        batch_scenarios,
        dictionary_lifecycle,
        quarantine_returns,
        synthetic,
    )
    from contractlib.schemas import validate_value  # type: ignore
    from contractlib.search_expectations import allowed_error_codes  # type: ignore
    from contractlib.semantic import validate_fixture  # type: ignore

EXPECTATIONS_RELATIVE = Path("fixtures") / "synthetic" / "audit_expectations.json"

AUDIT_EVENT_SCHEMA = "#/components/schemas/AuditEvent"
AUDIT_QUERY_REQUEST_SCHEMA = "#/components/schemas/AuditQueryRequest"
AUDIT_QUERY_RESPONSE_SCHEMA = "#/components/schemas/AuditQueryResponse"
AUDIT_UPDATES_SCHEMA = "#/components/schemas/AuditUpdatesResponse"
ACTOR_PAGE_SCHEMA = "#/components/schemas/ActorPage"
ACTOR_SCHEMA = "#/components/schemas/Actor"
ERROR_SCHEMA = "#/components/schemas/ErrorResponse"

QUERY_OPERATION = "queryAuditEvents"
UPDATES_OPERATION = "getAuditUpdates"
ACTORS_OPERATION = "listAuditActors"

# The closed OAS AuditAction enum split by category.
BUSINESS_ACTIONS = (
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
)
SYSTEM_ACTIONS = ("LOGIN_SUCCEEDED", "LOGIN_FAILED", "LOGOUT", "ACCOUNT_BLOCKED")
AUDIT_ACTIONS = BUSINESS_ACTIONS + SYSTEM_ACTIONS
AUDIT_CATEGORIES = ("BUSINESS", "SYSTEM")
AUDIT_RESULTS = ("SUCCESS", "ISSUE", "FAILED")

# Actorless SYSTEM events are only allowed for an uninitiated LOGIN_FAILED.
ACTORLESS_SYSTEM_ACTIONS = ("LOGIN_FAILED",)
# Actions that must never be authored by a null actor.
MUTATION_ACTIONS = (
    "BATCH_ACCEPTED",
    "DICTIONARY_PUBLISHED",
    "QUARANTINE_RETURNED",
)

PHASES = ("ACCEPT", "ATTEMPT_START", "ATTEMPT_FINISH", "RECOVERY", "SESSION")
PHASE_SUFFIX = {
    "ATTEMPT_START": "started",
    "ATTEMPT_FINISH": "finished",
    "RECOVERY": "recovery",
}

KNOWN_Q = ("Q-029", "Q-041", "Q-043")
ID_RE = re.compile(r"^[A-Za-z0-9-]{1,96}$")
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
MOSCOW_OFFSET = "+03:00"


# --------------------------------------------------------------------------- #
# Loading and context
# --------------------------------------------------------------------------- #

def expectations_path(root: Optional[Path] = None) -> Path:
    return (root or synthetic.repo_root()) / EXPECTATIONS_RELATIVE


def load_expectations(root: Optional[Path] = None) -> Dict[str, Any]:
    return synthetic.load_json(expectations_path(root))


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _actor_payload(spec: Dict[str, Any], snapshot: bool = False) -> Dict[str, Any]:
    name = spec.get("display_name_at_event") if snapshot else spec.get("display_name")
    return {
        "user_id": spec["user_id"],
        "login": spec["login"],
        "display_name": name,
        "role": spec["role"],
    }


@functools.lru_cache(maxsize=None)
def _linked_contexts(base_key: str) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Cache the expensive linked-fixture contexts across expectations variants."""
    base = Path(base_key)
    dictionary_ctx = dictionary_lifecycle.build_context(base)
    scenario_ctx = batch_scenarios.build_context(base)
    quarantine_ctx = quarantine_returns.build_context(base)
    return dictionary_ctx, scenario_ctx, quarantine_ctx


def build_context(
    root: Optional[Path] = None, expectations: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Load the linked fixtures and materialize the canonical event universe."""
    base = Path(root) if root is not None else synthetic.repo_root()
    if expectations is None:
        expectations = load_expectations(base)

    dictionary_ctx, scenario_ctx, quarantine_ctx = _linked_contexts(str(base))
    batch_ctx = scenario_ctx["batch"]

    actor_by_alias = {entry["alias"]: entry for entry in expectations.get("actors", [])}
    actor_by_user = {entry["user_id"]: entry for entry in expectations.get("actors", [])}

    context: Dict[str, Any] = {
        "base": base,
        "manifest": batch_ctx["manifest"],
        "document": batch_ctx["document"],
        "expectations": expectations,
        "dictionary": dictionary_ctx,
        "batch": scenario_ctx["batch"],
        "batch_expectations": scenario_ctx["batch_expectations"],
        "scenario": scenario_ctx,
        "quarantine": quarantine_ctx,
        "actor_by_alias": actor_by_alias,
        "actor_by_user": actor_by_user,
        "companies": expectations.get("companies", {}),
        "batch_universes": expectations.get("batch_universes", {}),
        "batch_request_ids": expectations.get("batch_request_ids", {}),
        "recovery_operations": expectations.get("recovery_operations", {}),
        "dictionary_actor_aliases": expectations.get("dictionary_actor_aliases", {}),
        "queries": {entry["query_id"]: entry for entry in expectations.get("queries", [])},
        "actors_pages": {
            entry["page_id"]: entry for entry in expectations.get("actors_pages", [])
        },
        "updates": {
            entry["scenario_id"]: entry
            for entry in expectations.get("updates_scenarios", [])
        },
        "errors": {
            entry["error_id"]: entry for entry in expectations.get("errors", [])
        },
    }
    context["events"] = all_events(context)
    context["event_by_id"] = {entry["payload"]["event_id"]: entry for entry in context["events"]}
    return context


# --------------------------------------------------------------------------- #
# Materialization (literal ids only, never a journal)
# --------------------------------------------------------------------------- #

def _company_id_for_batch(batch_id: str, context: Dict[str, Any]) -> Optional[str]:
    spec = context["batch"]["batches"][batch_id]
    selection = context["batch"]["selections"][batch_outcomes._selection_id(spec)]
    return selection["company_id"]


def dictionary_occurred_at(
    action: str, step: Dict[str, Any], context: Dict[str, Any]
) -> str:
    """Derive the authoritative time of a dictionary audit event.

    The time is never a second hand-authored literal: it is bound to the linked
    ``dictionary_lifecycle.json`` fixture, exactly like the actor, revision,
    version and RuleSet.  A simulated operation uses the linked simulation's
    ``created_at``; every other dictionary action uses the ``updated_at`` of the
    state the step produces, except ``DICTIONARY_PUBLISHED`` which uses the
    published version's ``published_at`` (the lifecycle declares it equal to the
    state ``updated_at``; the binding check verifies that equality).
    """
    if action == "DICTIONARY_SIMULATED":
        simulation_id = step["expected"]["simulation_id"]
        for simulation in context["dictionary"]["simulations"].values():
            if simulation["simulation_id"] == simulation_id:
                return simulation["created_at"]
        raise KeyError(f"unknown simulation {simulation_id!r}")
    state_id = step.get("after_state") or step.get("before_state")
    state = context["dictionary"]["states"][state_id]
    if action == "DICTIONARY_PUBLISHED":
        version = context["dictionary"]["versions"][step["expected"]["active_version_id"]]
        return version["published_at"]
    return state["updated_at"]


def materialize_dictionary_event(
    descriptor: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    step = next(
        item
        for item in context["dictionary"]["expectations"]["timeline"]
        if item["step_id"] == descriptor["timeline_step"]
    )
    state_id = step.get("after_state") or step.get("before_state")
    state = context["dictionary"]["states"][state_id]
    dictionary_id = state["dictionary_id"]
    dictionary = context["dictionary"]["dictionaries"][dictionary_id]
    action = descriptor["action"]
    version_id: Optional[str] = None
    rule_set_id: Optional[str] = None
    comment: Optional[str] = None
    operation_id: Optional[str] = dictionary_id
    if action == "DICTIONARY_PUBLISHED":
        version_id = step["expected"]["active_version_id"]
        publish = context["dictionary"]["publishes"][step["expected"]["publish_id"]]
        rule_set_id = publish["rule_set_id"]
        comment = step["request"]["comment"]
        operation_id = version_id
    elif action == "DICTIONARY_RESTORED":
        version_id = step["expected"]["based_on_version_id"]
        operation_id = version_id
    elif action == "DICTIONARY_SIMULATED":
        operation_id = step["expected"]["simulation_id"]
    actor_spec = context["actor_by_alias"][
        context["dictionary_actor_aliases"][step["actor"]]
    ]
    return {
        "event_id": descriptor["event_id"],
        "occurred_at": dictionary_occurred_at(action, step, context),
        "actor": _actor_payload(actor_spec, snapshot=True),
        "category": "BUSINESS",
        "action": action,
        "result": descriptor.get("result", "SUCCESS"),
        "request_id": descriptor["request_id"],
        "operation_id": operation_id,
        "source_attempt_id": None,
        "company_id": dictionary["company_id"],
        "dictionary_id": dictionary_id,
        "version_id": version_id,
        "rule_set_id": rule_set_id,
        "batch_id": None,
        "attempt_id": None,
        "item_id": None,
        "source": None,
        "target": None,
        "reason_code": None,
        "comment": comment,
    }


def materialize_explicit_event(
    descriptor: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    actor_spec = context["actor_by_alias"].get(descriptor.get("actor"))
    actor = _actor_payload(actor_spec, snapshot=True) if actor_spec else None
    return {
        "event_id": descriptor["event_id"],
        "occurred_at": descriptor["occurred_at"],
        "actor": actor,
        "category": descriptor["category"],
        "action": descriptor["action"],
        "result": descriptor["result"],
        "request_id": descriptor["request_id"],
        "operation_id": descriptor.get("operation_id"),
        "source_attempt_id": descriptor.get("source_attempt_id"),
        "company_id": descriptor.get("company_id"),
        "dictionary_id": descriptor.get("dictionary_id"),
        "version_id": descriptor.get("version_id"),
        "rule_set_id": descriptor.get("rule_set_id"),
        "batch_id": descriptor.get("batch_id"),
        "attempt_id": descriptor.get("attempt_id"),
        "item_id": descriptor.get("item_id"),
        "source": copy.deepcopy(descriptor.get("source")),
        "target": copy.deepcopy(descriptor.get("target")),
        "reason_code": descriptor.get("reason_code"),
        "comment": descriptor.get("comment"),
    }


def materialize_return_event(
    audit_id: str, context: Dict[str, Any]
) -> Dict[str, Any]:
    entry = context["quarantine"]["audit"][audit_id]
    return quarantine_returns.materialize_audit_event(entry, context["quarantine"])


def _attempt_event(
    batch_id: str,
    batch_spec: Dict[str, Any],
    row: Dict[str, Any],
    rule_event: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    attempt_id = row["attempt_id"]
    phase = rule_event["phase"]
    suffix = PHASE_SUFFIX[phase]
    action = rule_event["action"]
    operation_id = attempt_id
    source_attempt_id: Optional[str] = None
    if action == "RECOVERY_REQUIRED":
        operation_id = context["recovery_operations"].get(attempt_id, attempt_id)
        source_attempt_id = attempt_id
    target = None
    if rule_event.get("target") == "actual_location":
        target = copy.deepcopy(row.get("actual_location"))
    actor_spec = context["actor_by_alias"][batch_spec["owner"]]
    return {
        "event_id": f"audit-{attempt_id}-{suffix}",
        "occurred_at": row.get(rule_event["time_field"]),
        "actor": _actor_payload(actor_spec, snapshot=True),
        "category": "BUSINESS",
        "action": action,
        "result": rule_event["result"],
        "request_id": context["batch_request_ids"][batch_id],
        "operation_id": operation_id,
        "source_attempt_id": source_attempt_id,
        "company_id": _company_id_for_batch(batch_id, context),
        "dictionary_id": None,
        "version_id": None,
        "rule_set_id": batch_spec.get("rule_set_id"),
        "batch_id": batch_id,
        "attempt_id": attempt_id,
        "item_id": row["item_id"],
        "source": copy.deepcopy(row.get("source")),
        "target": target,
        "reason_code": row.get("reason_code") if phase != "ATTEMPT_START" else None,
        "comment": None,
    }


def _batch_accept_event(
    batch_id: str, batch_spec: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    actor_spec = context["actor_by_alias"][batch_spec["owner"]]
    return {
        "event_id": f"audit-{batch_id}-accepted",
        "occurred_at": batch_spec["created_at"],
        "actor": _actor_payload(actor_spec, snapshot=True),
        "category": "BUSINESS",
        "action": "BATCH_ACCEPTED",
        "result": "SUCCESS",
        "request_id": context["batch_request_ids"][batch_id],
        "operation_id": batch_id,
        "source_attempt_id": None,
        "company_id": _company_id_for_batch(batch_id, context),
        "dictionary_id": None,
        "version_id": None,
        "rule_set_id": batch_spec.get("rule_set_id"),
        "batch_id": batch_id,
        "attempt_id": None,
        "item_id": None,
        "source": None,
        "target": None,
        "reason_code": None,
        "comment": None,
    }


def materialize_isolated_event(
    descriptor: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    batch_id = descriptor["batch_id"]
    row = batch_scenarios.outcome_payload(
        batch_id, descriptor["item_id"], context["scenario"]
    )
    if row is None:
        raise ValueError(f"unknown isolated outcome {batch_id}/{descriptor['item_id']}")
    phase = descriptor["phase"]
    operation_id = row["attempt_id"]
    source_attempt_id: Optional[str] = None
    if descriptor["action"] == "RECOVERY_REQUIRED":
        operation_id = context["recovery_operations"].get(row["attempt_id"], row["attempt_id"])
        source_attempt_id = row["attempt_id"]
    occurred_at = row.get("started_at") if phase == "ATTEMPT_START" else row.get("finished_at")
    if phase == "RECOVERY":
        occurred_at = row.get("started_at")
    target = None
    if phase == "ATTEMPT_FINISH" and descriptor.get("target") == "actual_location":
        target = copy.deepcopy(row.get("actual_location"))
    actor_spec = context["actor_by_alias"][descriptor["actor"]]
    return {
        "event_id": descriptor["event_id"],
        "occurred_at": occurred_at,
        "actor": _actor_payload(actor_spec, snapshot=True),
        "category": "BUSINESS",
        "action": descriptor["action"],
        "result": descriptor["result"],
        "request_id": descriptor["request_id"],
        "operation_id": operation_id,
        "source_attempt_id": source_attempt_id,
        "company_id": _company_id_for_batch(batch_id, context),
        "dictionary_id": None,
        "version_id": None,
        "rule_set_id": None,
        "batch_id": batch_id,
        "attempt_id": row["attempt_id"],
        "item_id": row["item_id"],
        "source": copy.deepcopy(row.get("source")),
        "target": target,
        "reason_code": row.get("reason_code") if phase != "ATTEMPT_START" else None,
        "comment": None,
    }


def _rules_by_state(expectations: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        rule["state"]: rule for rule in expectations.get("attempt_event_rules", [])
    }


def _collect_batch_events(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    expectations = context["expectations"]
    rules = _rules_by_state(expectations)
    events: List[Dict[str, Any]] = []
    for batch_id, universe in context["batch_universes"].items():
        batch_spec = context["batch"]["batches"].get(batch_id)
        if batch_spec is None:
            continue
        accept = _batch_accept_event(batch_id, batch_spec, context)
        events.append(
            {
                "payload": accept,
                "universe": universe,
                "kind": "batch",
                "phase": "ACCEPT",
                "batch_id": batch_id,
                "attempt_id": None,
                "item_id": None,
            }
        )
        for row in batch_outcomes.all_outcome_payloads(batch_spec, context["batch"]):
            rule = rules.get(row["state"])
            if rule is None:
                continue
            for rule_event in rule.get("events", []):
                payload = _attempt_event(batch_id, batch_spec, row, rule_event, context)
                events.append(
                    {
                        "payload": payload,
                        "universe": universe,
                        "kind": "attempt",
                        "phase": rule_event["phase"],
                        "batch_id": batch_id,
                        "attempt_id": row["attempt_id"],
                        "item_id": row["item_id"],
                    }
                )
    return events


def all_events(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    expectations = context["expectations"]
    events: List[Dict[str, Any]] = []
    for descriptor in expectations.get("dictionary_events", []):
        payload = materialize_dictionary_event(descriptor, context)
        events.append(
            {
                "payload": payload,
                "universe": descriptor["universe"],
                "kind": "dictionary",
                "phase": None,
                "batch_id": None,
                "attempt_id": None,
                "item_id": None,
            }
        )
    for descriptor in expectations.get("explicit_events", []):
        payload = materialize_explicit_event(descriptor, context)
        events.append(
            {
                "payload": payload,
                "universe": descriptor["universe"],
                "kind": "explicit",
                "phase": descriptor.get("phase"),
                "batch_id": descriptor.get("batch_id"),
                "attempt_id": descriptor.get("attempt_id"),
                "item_id": descriptor.get("item_id"),
            }
        )
    for audit_id in expectations.get("return_event_ids", []):
        payload = materialize_return_event(audit_id, context)
        events.append(
            {
                "payload": payload,
                "universe": "primary",
                "kind": "return",
                "phase": None,
                "batch_id": payload.get("batch_id"),
                "attempt_id": payload.get("attempt_id"),
                "item_id": payload.get("item_id"),
            }
        )
    events.extend(_collect_batch_events(context))
    for descriptor in expectations.get("isolated_events", []):
        payload = materialize_isolated_event(descriptor, context)
        events.append(
            {
                "payload": payload,
                "universe": descriptor["universe"],
                "kind": "isolated",
                "phase": descriptor["phase"],
                "batch_id": descriptor["batch_id"],
                "attempt_id": payload["attempt_id"],
                "item_id": payload["item_id"],
            }
        )
    return events


# --------------------------------------------------------------------------- #
# Query computation (validated against the declared literal ids)
# --------------------------------------------------------------------------- #

def _event_matches(payload: Dict[str, Any], request: Dict[str, Any]) -> bool:
    if request.get("company_id") is not None and payload["company_id"] != request["company_id"]:
        return False
    occurred = payload["occurred_at"]
    if not (request["from"] <= occurred < request["to"]):
        return False
    actor_id = request.get("actor_id")
    if actor_id is not None:
        actor = payload.get("actor")
        if actor is None or actor["user_id"] != actor_id:
            return False
    if request.get("action") is not None and payload["action"] != request["action"]:
        return False
    if request.get("result") is not None and payload["result"] != request["result"]:
        return False
    text = request.get("query_text") or ""
    if text:
        haystack: List[str] = []
        for side in ("source", "target"):
            location = payload.get(side)
            if isinstance(location, dict):
                haystack.append(location["relative_path"])
                haystack.append(location["display_path"])
        if text.casefold() not in " ".join(haystack).casefold():
            return False
    return True


def _sort_key(entry: Dict[str, Any]) -> Tuple[str, str]:
    payload = entry["payload"]
    return (payload["occurred_at"], payload["event_id"])


def compute_query(
    expectations: Dict[str, Any], context: Dict[str, Any], query: Dict[str, Any]
) -> Dict[str, Any]:
    """Re-derive one query result from the declared events and filters."""
    universe = query["universe"]
    request = query["request"]
    events = [entry for entry in context["events"] if entry["universe"] == universe]
    matched = [entry for entry in events if _event_matches(entry["payload"], request)]
    viewer_role = query.get("viewer_role")
    if viewer_role == "WORKER":
        # A worker only sees the shared BUSINESS journal.
        matched = [entry for entry in matched if entry["payload"]["category"] == "BUSINESS"]
    elif viewer_role not in (None, "ADMIN"):
        raise ValueError(f"unknown viewer_role {viewer_role!r}")
    matched.sort(key=_sort_key, reverse=True)
    frozen = query.get("frozen_newest_event_id")
    if frozen:
        frozen_entry = context["event_by_id"].get(frozen)
        if frozen_entry is None:
            raise ValueError(f"unknown frozen_newest_event_id {frozen!r}")
        bound = _sort_key(frozen_entry)
        matched = [entry for entry in matched if _sort_key(entry) <= bound]
    newest = matched[0]["payload"]["event_id"] if matched else None
    after = query.get("cursor_after_event_id")
    offset = 0
    if after:
        index = next(
            (i for i, entry in enumerate(matched) if entry["payload"]["event_id"] == after),
            None,
        )
        offset = (index + 1) if index is not None else len(matched)
    page = matched[offset : offset + request["limit"]]
    has_more = (offset + len(page)) < len(matched)
    if has_more and not query.get("next_cursor"):
        raise ValueError("a query with more events must declare a next_cursor")
    next_cursor = query.get("next_cursor") if has_more else None
    return {
        "items": [entry["payload"] for entry in page],
        "event_ids": [entry["payload"]["event_id"] for entry in page],
        "next_cursor": next_cursor,
        "newest_event_id": newest,
        "all_categories": sorted({entry["payload"]["category"] for entry in matched}),
    }


# --------------------------------------------------------------------------- #
# Materialization of the query/actor/update responses
# --------------------------------------------------------------------------- #

def materialize_query_response(
    expectations: Dict[str, Any], context: Dict[str, Any], query: Dict[str, Any]
) -> Dict[str, Any]:
    result = compute_query(expectations, context, query)
    return {
        "items": result["items"],
        "next_cursor": result["next_cursor"],
        "newest_event_id": result["newest_event_id"],
    }


def materialize_actors_page(
    page: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    items = []
    for alias in page["actor_aliases"]:
        spec = context["actor_by_alias"][alias]
        items.append(_actor_payload(spec, snapshot=False))
    return {"items": items, "next_cursor": page.get("next_cursor")}


def materialize_updates(
    scenario: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    if scenario.get("empty_journal"):
        # The initial journal is empty and sends no after_event_id.
        return {"has_new_events": False}
    known = context["event_by_id"]
    after = scenario.get("after_event_id")
    if after is None:
        # No lower bound: any accessible event means there is something to show.
        has_new = bool(context["events"])
    else:
        entry = known.get(after)
        if entry is None:
            has_new = True
        else:
            bound = _sort_key(entry)
            has_new = any(_sort_key(other) > bound for other in context["events"])
    return {"has_new_events": has_new}


def materialize_error(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "error": {
            "code": entry["code"],
            "message": entry.get("message", "safe synthetic error"),
            "request_id": entry.get("request_id", "request-audit-demo-1"),
            "operation_id": entry.get("operation_id"),
            "retryable": entry.get("retryable", False),
            "field_errors": entry.get("field_errors", []),
        }
    }


# --------------------------------------------------------------------------- #
# Structure and cross-fixture expectation checks
# --------------------------------------------------------------------------- #

def _business_actor_errors(expectations: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    for entry in context["events"]:
        payload = entry["payload"]
        label = payload["event_id"]
        action = payload["action"]
        category = payload["category"]
        actor = payload.get("actor")
        if category == "BUSINESS" and action not in BUSINESS_ACTIONS:
            errors.append(f"{label}: a BUSINESS event must use a BUSINESS action")
        if category == "SYSTEM" and action not in SYSTEM_ACTIONS:
            errors.append(f"{label}: a SYSTEM event must use a SYSTEM action")
        if category == "BUSINESS" and actor is None:
            errors.append(f"{label}: a BUSINESS event always has an actor")
        if category == "SYSTEM":
            if action in ("LOGIN_SUCCEEDED", "LOGOUT", "ACCOUNT_BLOCKED") and actor is None:
                errors.append(f"{label}: {action} is a SYSTEM event with an initiator")
            if actor is None and action not in ACTORLESS_SYSTEM_ACTIONS:
                errors.append(f"{label}: only an uninitiated LOGIN_FAILED may omit the actor")
        if actor is None and action in MUTATION_ACTIONS:
            errors.append(f"{label}: {action} must never be authored by a null actor")
        if actor is not None and actor["user_id"] not in context["actor_by_user"]:
            errors.append(f"{label}: actor does not resolve to a declared audit actor")
    return errors


def _phase_errors(expectations: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    seen: Dict[Tuple[str, str], str] = {}
    for entry in context["events"]:
        phase = entry["phase"]
        attempt_id = entry["attempt_id"]
        if attempt_id is None or phase is None:
            continue
        key = (entry["universe"], f"{attempt_id}:{phase}")
        if key in seen:
            errors.append(
                f"{entry['payload']['event_id']}: duplicate attempt/phase with {seen[key]}"
            )
        else:
            seen[key] = entry["payload"]["event_id"]
    return errors


def _attempt_state_map(context: Dict[str, Any]) -> Dict[str, str]:
    """attempt_id -> declared outcome state for the linked batches."""
    states: Dict[str, str] = {}
    for batch_id, universe in context["batch_universes"].items():
        spec = context["batch"]["batches"].get(batch_id)
        if spec is None:
            continue
        for row in batch_outcomes.all_outcome_payloads(spec, context["batch"]):
            states[row["attempt_id"]] = row["state"]
    for descriptor in context["expectations"].get("isolated_events", []):
        row = batch_scenarios.outcome_payload(
            descriptor["batch_id"], descriptor["item_id"], context["scenario"]
        )
        if row is not None:
            states[row["attempt_id"]] = row["state"]
    return states


def _attempt_completeness_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    observed: Dict[str, set] = {}
    for entry in context["events"]:
        if entry["kind"] != "attempt":
            continue
        observed.setdefault(entry["attempt_id"], set()).add(entry["phase"])
    states = _attempt_state_map(context)
    for attempt_id, phases in observed.items():
        state = states.get(attempt_id)
        if "ATTEMPT_START" not in phases:
            errors.append(f"{attempt_id}: a described attempt must have a start event")
        if state == "PROCESSING":
            if "ATTEMPT_FINISH" in phases or "RECOVERY" in phases:
                errors.append(f"{attempt_id}: a PROCESSING attempt has no terminal yet")
        elif state == "RECOVERY_REQUIRED":
            if "RECOVERY" not in phases:
                errors.append(f"{attempt_id}: a recovery-required attempt needs its recovery event")
            if "ATTEMPT_FINISH" in phases:
                errors.append(f"{attempt_id}: a recovery-required attempt has no finish event")
        else:
            if "ATTEMPT_FINISH" not in phases:
                errors.append(f"{attempt_id}: a terminal attempt needs its finish event")
    return errors


def _universe_errors(expectations: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    known = {entry["universe_id"] for entry in expectations.get("universes", [])}
    for entry in context["events"]:
        if entry["universe"] not in known:
            errors.append(
                f"{entry['payload']['event_id']}: unknown universe {entry['universe']!r}"
            )
    primary = {
        entry["payload"]["event_id"]
        for entry in context["events"]
        if entry["universe"] == "primary"
    }
    # Alternate histories must never share an event id with the primary feed.
    for entry in context["events"]:
        if entry["universe"] != "primary" and entry["payload"]["event_id"] in primary:
            errors.append(
                f"{entry['payload']['event_id']}: an isolated universe must not reuse "
                "a primary event id"
            )
    return errors


def _dictionary_binding_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    for descriptor in expectations.get("dictionary_events", []):
        label = descriptor.get("event_id", "<missing>")
        step = next(
            (
                item
                for item in context["dictionary"]["expectations"]["timeline"]
                if item["step_id"] == descriptor.get("timeline_step")
            ),
            None,
        )
        if step is None:
            errors.append(f"{label}: timeline_step does not resolve")
            continue
        if descriptor.get("action") != "DICTIONARY_SIMULATED" and step.get("mutates") is not True:
            errors.append(f"{label}: a read step must not create a BUSINESS event")
        if descriptor.get("action") == "DICTIONARY_SIMULATED" and step.get("operation") != "createDictionarySimulation":
            errors.append(f"{label}: DICTIONARY_SIMULATED must bind a simulation step")
        if descriptor.get("action") not in BUSINESS_ACTIONS:
            errors.append(f"{label}: a dictionary event must use a BUSINESS action")
        if descriptor.get("action") not in (
            "DICTIONARY_CREATED",
            "DRAFT_SAVED",
            "DICTIONARY_SIMULATED",
            "DICTIONARY_PUBLISHED",
            "DICTIONARY_RESTORED",
        ):
            errors.append(f"{label}: unexpected dictionary action")
        payload = materialize_dictionary_event(descriptor, context)
        expected_actor = context["actor_by_alias"][
            context["dictionary_actor_aliases"][step["actor"]]
        ]
        if payload["actor"]["user_id"] != expected_actor["user_id"]:
            errors.append(f"{label}: the event actor must be the timeline step actor")
        expected_revision = step["expected"]["draft_revision"]
        if descriptor.get("draft_revision") != expected_revision:
            errors.append(f"{label}: the bound draft revision must match the timeline")
        # The event time is derived from the linked lifecycle fixture, never a
        # second hand-authored literal.  A descriptor must not carry its own
        # ``occurred_at`` that could silently drift from the authoritative time.
        # The authoritative value is read here directly from the lifecycle
        # context, independently of the materializer, so the check cannot become
        # a tautology.
        if "occurred_at" in descriptor:
            errors.append(
                f"{label}: a dictionary event must not declare an independent occurred_at"
            )
        state_id = step.get("after_state") or step.get("before_state")
        if descriptor.get("action") == "DICTIONARY_SIMULATED":
            simulation_id = step["expected"]["simulation_id"]
            authoritative = next(
                simulation["created_at"]
                for simulation in context["dictionary"]["simulations"].values()
                if simulation["simulation_id"] == simulation_id
            )
        elif descriptor.get("action") == "DICTIONARY_PUBLISHED":
            state = context["dictionary"]["states"][state_id]
            version = context["dictionary"]["versions"][
                step["expected"]["active_version_id"]
            ]
            authoritative = version["published_at"]
            if state["updated_at"] != authoritative:
                errors.append(
                    f"{label}: the published state.updated_at must equal the "
                    f"version published_at"
                )
        else:
            authoritative = context["dictionary"]["states"][state_id]["updated_at"]
        if payload["occurred_at"] != authoritative:
            errors.append(
                f"{label}: occurred_at {payload['occurred_at']!r} must equal the "
                f"lifecycle field {authoritative!r}"
            )
        if descriptor.get("action") == "DICTIONARY_PUBLISHED":
            if descriptor.get("comment") != step["request"]["comment"]:
                errors.append(f"{label}: the publish comment must match the request")
            if payload["version_id"] != step["expected"]["active_version_id"]:
                errors.append(f"{label}: the published version must match the timeline")
        if descriptor.get("action") == "DICTIONARY_RESTORED":
            if payload["version_id"] != step["expected"]["based_on_version_id"]:
                errors.append(f"{label}: the restored version must match the timeline")
        if payload["dictionary_id"] not in context["dictionary"]["dictionaries"]:
            errors.append(f"{label}: dictionary_id does not resolve to the timeline")
    return errors


def _return_link_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    qr = context["quarantine"]
    return_event = next(
        (
            entry
            for entry in context["events"]
            if entry["payload"]["action"] == "QUARANTINE_RETURNED"
        ),
        None,
    )
    recovery_event = next(
        (
            entry
            for entry in context["events"]
            if entry["payload"]["action"] == "RECOVERY_REQUIRED"
        ),
        None,
    )
    if return_event is None or recovery_event is None:
        errors.append("the return lifecycle must be represented by both audit events")
        return errors
    success = qr["scenarios"]["QR-RETURN-SUCCESS"]
    if return_event["payload"]["operation_id"] != success["expected"]["return_operation_id"]:
        errors.append("the QUARANTINE_RETURNED operation_id must be the return_operation_id")
    item = quarantine_returns.materialize_quarantine_item(
        qr["states"]["QR-STATE-CONFIRMED"], qr
    )
    if return_event["payload"]["source_attempt_id"] != item["source_attempt_id"]:
        errors.append("the return event must link the original source attempt")
    ambiguous = qr["scenarios"]["QR-RECOVERY-AMBIGUOUS"]
    if recovery_event["payload"]["operation_id"] != ambiguous["expected"]["operation_id"]:
        errors.append("the recovery event operation_id must be the registered operation")
    error_entry = qr["errors"][ambiguous["expected"]["error_id"]]
    if recovery_event["payload"]["operation_id"] != error_entry["operation_id"]:
        errors.append("the recovery audit operation_id must match error.operation_id")
    if recovery_event["payload"]["target"] is not None:
        errors.append("an ambiguous return recovery has no confirmed target")
    return errors


def _descriptor_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    """Every published LT-03.4b audit descriptor is represented canonically."""
    errors: List[str] = []
    canonical = context["events"]
    for descriptor in context["scenario"]["expectations"]["audit_expectations"]:
        label = descriptor["audit_id"]
        matches = [
            entry
            for entry in canonical
            if entry["payload"]["action"] == descriptor["action"]
            and entry["payload"]["batch_id"] == descriptor.get("batch_id")
            and entry["attempt_id"] == descriptor.get("attempt_id")
            and (
                descriptor.get("phase") is None
                or entry["phase"] == descriptor.get("phase")
            )
        ]
        if not matches:
            errors.append(f"{label}: no canonical audit event represents this descriptor")
            continue
        entry = matches[0]["payload"]
        if entry["result"] != descriptor["result"]:
            errors.append(f"{label}: the canonical result disagrees with the descriptor")
        if entry["occurred_at"] != descriptor["occurred_at"]:
            errors.append(f"{label}: the canonical occurred_at disagrees with the descriptor")
        expected_actor = context["actor_by_alias"].get(descriptor.get("actor"))
        if expected_actor is not None:
            actor = entry.get("actor")
            if actor is None or actor["user_id"] != expected_actor["user_id"]:
                errors.append(f"{label}: the canonical actor disagrees with the descriptor")
    return errors


def _viewer_swap_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    swap = expectations.get("viewer_swap") or {}
    batch_id = swap.get("batch_id")
    event = context["event_by_id"].get(f"audit-{batch_id}-accepted")
    if event is None:
        errors.append("viewer_swap: the accepted batch event does not resolve")
        return errors
    if swap.get("viewer") not in context["actor_by_alias"]:
        errors.append("viewer_swap: viewer does not resolve")
    expected = context["actor_by_alias"].get(swap.get("accepted_actor"))
    if expected is None:
        errors.append("viewer_swap: accepted_actor does not resolve")
    elif event["payload"]["actor"]["user_id"] != expected["user_id"]:
        errors.append("viewer_swap: the accepted actor must not change under a viewer swap")
    return errors


def _time_errors(expectations: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    timezone_spec = expectations.get("timezone") or {}
    if timezone_spec.get("id") != "Europe/Moscow":
        errors.append("the query day must be declared in Europe/Moscow")
    try:
        start = _instant(timezone_spec["from_utc"])
        end = _instant(timezone_spec["to_utc"])
        if not start < end:
            errors.append("the Moscow query day must be a positive interval")
    except (KeyError, TypeError, ValueError):
        errors.append("the Moscow query day must declare valid UTC instants")
    if timezone_spec.get("utc_offset") != MOSCOW_OFFSET:
        errors.append("the Moscow UTC offset must be +03:00")
    for entry in context["events"]:
        label = entry["payload"]["event_id"]
        try:
            _instant(entry["payload"]["occurred_at"])
        except (TypeError, ValueError):
            errors.append(f"{label}: occurred_at must be an Instant")
    # The primary dictionary flow is declared in timeline order and must be
    # chronologically non-decreasing; the isolated scenario universes are not
    # interleaved with it.
    previous: Optional[datetime] = None
    for descriptor in expectations.get("dictionary_events", []):
        if descriptor.get("universe") != "primary":
            continue
        try:
            step = next(
                item
                for item in context["dictionary"]["expectations"]["timeline"]
                if item["step_id"] == descriptor.get("timeline_step")
            )
            moment = _instant(
                dictionary_occurred_at(descriptor["action"], step, context)
            )
        except (TypeError, ValueError, KeyError, StopIteration):
            continue
        if previous is not None and moment < previous:
            errors.append(
                f"{descriptor['event_id']}: the primary dictionary timeline must be chronological"
            )
        previous = moment
    return errors


def _query_declaration_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    seen: set = set()
    for query in expectations.get("queries", []):
        label = query.get("query_id", "<missing>")
        if not isinstance(label, str) or not ID_RE.match(label):
            errors.append(f"{label}: query_id must be a valid Id")
        if label in seen:
            errors.append(f"{label}: duplicate query id")
        seen.add(label)
        if query.get("operation") != QUERY_OPERATION:
            errors.append(f"{label}: operation must be {QUERY_OPERATION}")
        request = query.get("request")
        if not isinstance(request, dict):
            errors.append(f"{label}: request must be an object")
            continue
        if request.get("limit", 0) > 100 or request.get("limit", 0) < 1:
            errors.append(f"{label}: limit must stay within 1..100")
        if query.get("universe") not in {
            entry["universe_id"] for entry in expectations.get("universes", [])
        }:
            errors.append(f"{label}: universe does not resolve")
        expected = query.get("expected")
        if not isinstance(expected, dict):
            errors.append(f"{label}: expected must be an object")
            continue
        if len(expected.get("event_ids", [])) > 100:
            errors.append(f"{label}: a page must never exceed 100 events")
        for event_id in expected.get("event_ids", []):
            if event_id not in context["event_by_id"]:
                errors.append(f"{label}: expected event id {event_id!r} does not resolve")
        if expected.get("event_ids") and expected.get("newest_event_id") is None:
            errors.append(f"{label}: a non-empty page declares newest_event_id")
        if not expected.get("event_ids") and expected.get("newest_event_id") is not None:
            errors.append(f"{label}: an empty page has newest_event_id=null")
    return errors


def query_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    for query in expectations.get("queries", []):
        label = query["query_id"]
        try:
            actual = compute_query(expectations, context, query)
        except Exception as exc:  # noqa: BLE001 - surface resolution problems
            errors.append(f"{label}: cannot compute the query: {type(exc).__name__}: {exc}")
            continue
        expected = query["expected"]
        if actual["event_ids"] != expected.get("event_ids"):
            errors.append(
                f"{label}: expected {expected.get('event_ids')} != computed {actual['event_ids']}"
            )
        if actual["next_cursor"] != expected.get("next_cursor"):
            errors.append(
                f"{label}: expected next_cursor {expected.get('next_cursor')!r} "
                f"!= computed {actual['next_cursor']!r}"
            )
        if actual["newest_event_id"] != expected.get("newest_event_id"):
            errors.append(
                f"{label}: expected newest_event_id {expected.get('newest_event_id')!r} "
                f"!= computed {actual['newest_event_id']!r}"
            )
        # Literal filter consistency: every returned event satisfies the filter.
        for event_id in expected.get("event_ids", []):
            entry = context["event_by_id"].get(event_id)
            if entry is None:
                continue
            if not _event_matches(entry["payload"], query["request"]):
                errors.append(f"{label}: returned event {event_id!r} violates the declared filter")
        viewer_role = query.get("viewer_role")
        if viewer_role == "WORKER":
            if actual["all_categories"] != ["BUSINESS"]:
                errors.append(f"{label}: a WORKER query must only see the BUSINESS journal")
            for event_id in expected.get("event_ids", []):
                entry = context["event_by_id"].get(event_id)
                if entry is not None and entry["payload"]["category"] != "BUSINESS":
                    errors.append(f"{label}: a WORKER query must not return {event_id!r}")
        elif viewer_role == "ADMIN":
            if "SYSTEM" not in actual["all_categories"]:
                errors.append(f"{label}: an ADMIN query must also see the SYSTEM journal")
        # Frozen upper bound: declared late events stay outside the page.
        frozen = query.get("frozen_newest_event_id")
        if frozen:
            bound = _sort_key(context["event_by_id"][frozen])
            for event_id in query.get("new_events", []):
                entry = context["event_by_id"].get(event_id)
                if entry is None:
                    errors.append(f"{label}: new event {event_id!r} does not resolve")
                    continue
                if _sort_key(entry) <= bound:
                    errors.append(f"{label}: new event {event_id!r} must be newer than the frozen bound")
                if event_id in expected.get("event_ids", []):
                    errors.append(f"{label}: a frozen page must not include the new event {event_id!r}")
    return errors


def actors_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    for page in expectations.get("actors_pages", []):
        label = page.get("page_id", "<missing>")
        if page.get("operation") != ACTORS_OPERATION:
            errors.append(f"{label}: operation must be {ACTORS_OPERATION}")
        try:
            payload = materialize_actors_page(page, context)
        except KeyError as exc:
            errors.append(f"{label}: actor alias does not resolve {exc}")
            continue
        ids = [item["user_id"] for item in payload["items"]]
        if ids != page.get("expected_user_ids"):
            errors.append(f"{label}: actor list {ids} != declared {page.get('expected_user_ids')}")
        if len(ids) != len(set(ids)):
            errors.append(f"{label}: the actor page repeats an actor")
        if payload["next_cursor"] != page.get("next_cursor"):
            errors.append(f"{label}: next_cursor disagrees with the declaration")
        for item in payload["items"]:
            if set(item.keys()) != {"user_id", "login", "display_name", "role"}:
                errors.append(f"{label}: an Actor must not carry invented fields")
        prefix = (page.get("prefix") or "").casefold()
        for item in payload["items"]:
            if prefix and not (
                item["login"].casefold().startswith(prefix)
                or item["display_name"].casefold().startswith(prefix)
            ):
                errors.append(f"{label}: {item['user_id']} does not match the prefix")
    blocked = [entry for entry in expectations.get("actors", []) if entry.get("blocked")]
    if not blocked:
        errors.append("the actor filter list must include a blocked author")
    else:
        blocked_user = blocked[0]["user_id"]
        listed = any(
            blocked_user in page.get("expected_user_ids", [])
            for page in expectations.get("actors_pages", [])
        )
        if not listed:
            errors.append("a blocked author with accessible events must stay in the actor list")
    return errors


def updates_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    for scenario in expectations.get("updates_scenarios", []):
        label = scenario.get("scenario_id", "<missing>")
        if scenario.get("operation") != UPDATES_OPERATION:
            errors.append(f"{label}: operation must be {UPDATES_OPERATION}")
        actual = materialize_updates(scenario, context)
        if actual != scenario.get("expected"):
            errors.append(f"{label}: updates {actual} != declared {scenario.get('expected')}")
        after = scenario.get("after_event_id")
        if after is not None and after not in context["event_by_id"]:
            errors.append(f"{label}: after_event_id does not resolve")
    return errors


def no_business_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    actions = {entry["payload"]["action"] for entry in context["events"]}
    for scenario in expectations.get("no_business_scenarios", []):
        label = scenario.get("scenario_id", "<missing>")
        if scenario.get("before_event_count") != scenario.get("after_event_count"):
            errors.append(f"{label}: a read operation must not change the journal size")
        if scenario.get("expected_events"):
            errors.append(f"{label}: a read operation must not declare a BUSINESS event")
        for action in scenario.get("forbidden_actions", []):
            if action in actions:
                errors.append(f"{label}: read-only operation produced {action}")
    if not expectations.get("no_business_scenarios"):
        errors.append("the read-only no-BUSINESS scenarios must be declared")
    return errors


def headers_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    headers = expectations.get("safe_headers") or {}
    if headers.get("cache_control") != "no-store":
        errors.append("the audit responses must declare Cache-Control: no-store")
    if not ID_RE.match(str(headers.get("request_id", ""))):
        errors.append("the safe X-Request-ID must be a valid Id")
    document = context["document"]
    operation_paths = {
        "queryAuditEvents": ("post", "/audit/query"),
        "getAuditUpdates": ("get", "/audit/updates"),
        "listAuditActors": ("get", "/audit/actors"),
    }
    for operation in headers.get("operations", []):
        method, path = operation_paths[operation]
        responses = document["paths"][path][method]["responses"]
        response = responses["200"]
        declared = response.get("headers") or {}
        for header in ("X-Request-ID", "Cache-Control"):
            if header not in declared:
                errors.append(f"{operation}: the 200 response must declare {header}")
    for error_id in headers.get("error_request_id_links", []):
        entry = context["errors"].get(error_id)
        if entry is None:
            errors.append(f"safe_headers: error {error_id!r} does not resolve")
        elif entry.get("request_id") != headers.get("request_id"):
            errors.append(f"safe_headers: {error_id} request_id must match the header")
    return errors


def _request_id_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    """Every event carries the request envelope that produced it."""
    errors: List[str] = []
    for entry in context["events"]:
        payload = entry["payload"]
        label = payload["event_id"]
        if not ID_RE.match(str(payload.get("request_id", ""))):
            errors.append(f"{label}: request_id must be a valid Id")
        batch_id = payload.get("batch_id")
        if entry["kind"] in ("batch", "attempt", "isolated") and batch_id in context["batch_request_ids"]:
            expected = context["batch_request_ids"][batch_id]
            if payload["request_id"] != expected:
                errors.append(
                    f"{label}: request_id must match the accepted batch request envelope"
                )
    return errors


def update_button_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    """The finite update-button semantics: query -> new event -> update."""
    errors: List[str] = []
    button = expectations.get("update_button")
    if not button:
        return ["the update-button finite steps must be declared"]
    initial_query = context["queries"].get(button.get("query_id"))
    fresh_query = context["queries"].get(button.get("fresh_query_id"))
    if initial_query is None or fresh_query is None:
        return ["the update-button queries must resolve"]
    initial = compute_query(expectations, context, initial_query)
    fresh = compute_query(expectations, context, fresh_query)
    new_event_id = button["new_event_id"]
    if initial["newest_event_id"] != button["initial_newest_event_id"]:
        errors.append("update-button: the initial query newest disagrees with the declaration")
    if fresh["newest_event_id"] != new_event_id:
        errors.append("update-button: pressing update must surface the new event")
    if new_event_id not in fresh["event_ids"]:
        errors.append("update-button: the new event must appear in the refreshed page")
    indicator = materialize_updates(
        {"after_event_id": button["initial_newest_event_id"]}, context
    )
    if indicator != {"has_new_events": True}:
        errors.append("update-button: the indicator must report the new event")
    cleared = materialize_updates({"after_event_id": new_event_id}, context)
    if cleared != {"has_new_events": False}:
        errors.append("update-button: no new events remain after the newest")
    actions = [step.get("action") for step in button.get("steps", [])]
    expected_actions = ["QUERY", "EVENT_ARRIVES", "UPDATES", "PRESS_UPDATE", "UPDATES"]
    if actions != expected_actions:
        errors.append("update-button: the finite steps must describe query->event->indicator->update->indicator")
    return errors


def coverage_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    known = {entry["payload"]["event_id"] for entry in context["events"]}
    known.update(entry["query_id"] for entry in expectations.get("queries", []))
    known.update(entry["page_id"] for entry in expectations.get("actors_pages", []))
    known.update(entry["scenario_id"] for entry in expectations.get("updates_scenarios", []))
    known.update(entry["scenario_id"] for entry in expectations.get("no_business_scenarios", []))
    known.update(entry["error_id"] for entry in expectations.get("errors", []))
    known.update(link["link_id"] for link in expectations.get("links", []))
    button = expectations.get("update_button") or {}
    if button.get("scenario_id"):
        known.add(button["scenario_id"])
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
    seen_ids: set = set()
    for entry in context["events"]:
        event_id = entry["payload"]["event_id"]
        if not ID_RE.match(event_id):
            errors.append(f"{event_id}: event_id must be a valid Id")
        if event_id in seen_ids:
            errors.append(f"{event_id}: duplicate event id")
        seen_ids.add(event_id)
    present = {entry["payload"]["action"] for entry in context["events"]}
    for action in AUDIT_ACTIONS:
        if action not in present:
            errors.append(f"the canonical journal must represent {action}")
    errors.extend(_business_actor_errors(expectations, context))
    errors.extend(_phase_errors(expectations, context))
    errors.extend(_attempt_completeness_errors(expectations, context))
    errors.extend(_universe_errors(expectations, context))
    errors.extend(_dictionary_binding_errors(expectations, context))
    errors.extend(_return_link_errors(expectations, context))
    errors.extend(_descriptor_errors(expectations, context))
    errors.extend(_viewer_swap_errors(expectations, context))
    errors.extend(_time_errors(expectations, context))
    errors.extend(_request_id_errors(expectations, context))
    errors.extend(_query_declaration_errors(expectations, context))
    errors.extend(query_errors(expectations, context))
    errors.extend(actors_errors(expectations, context))
    errors.extend(updates_errors(expectations, context))
    errors.extend(update_button_errors(expectations, context))
    errors.extend(no_business_errors(expectations, context))
    errors.extend(headers_errors(expectations, context))
    errors.extend(coverage_errors(expectations, context))
    return errors


# --------------------------------------------------------------------------- #
# Schema validation
# --------------------------------------------------------------------------- #

def payload_errors(
    expectations: Dict[str, Any], context: Dict[str, Any], registry
) -> List[str]:
    errors: List[str] = []
    for entry in context["events"]:
        payload = entry["payload"]
        schema_errors, semantic = validate_fixture(registry, AUDIT_EVENT_SCHEMA, payload)
        errors.extend(
            f"{payload['event_id']}: {message}" for message in schema_errors + semantic
        )
    for query in expectations.get("queries", []):
        for message in validate_value(registry, AUDIT_QUERY_REQUEST_SCHEMA, query["request"]):
            errors.append(f"{query['query_id']}: {message}")
        response = materialize_query_response(expectations, context, query)
        schema_errors, semantic = validate_fixture(
            registry, AUDIT_QUERY_RESPONSE_SCHEMA, response
        )
        errors.extend(
            f"{query['query_id']}: {message}" for message in schema_errors + semantic
        )
    for page in expectations.get("actors_pages", []):
        response = materialize_actors_page(page, context)
        schema_errors, semantic = validate_fixture(registry, ACTOR_PAGE_SCHEMA, response)
        errors.extend(f"{page['page_id']}: {message}" for message in schema_errors + semantic)
    for scenario in expectations.get("updates_scenarios", []):
        response = materialize_updates(scenario, context)
        schema_errors, semantic = validate_fixture(registry, AUDIT_UPDATES_SCHEMA, response)
        errors.extend(f"{scenario['scenario_id']}: {message}" for message in schema_errors + semantic)
    for error in expectations.get("errors", []):
        payload = materialize_error(error)
        schema_errors, semantic = validate_fixture(registry, ERROR_SCHEMA, payload)
        errors.extend(f"{error['error_id']}: {message}" for message in schema_errors + semantic)
    return errors


def error_operation_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    for entry in expectations.get("errors", []):
        allowed = allowed_error_codes(
            context["document"], entry["operation"], entry["status"]
        )
        if entry["code"] not in allowed:
            errors.append(
                f"{entry['error_id']}: {entry['code']!r} is not declared by "
                f"{entry['operation']!r} for HTTP {entry['status']}"
            )
    return errors


# --------------------------------------------------------------------------- #
# Generic payload links
# --------------------------------------------------------------------------- #

def build_payloads(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    payloads: Dict[str, Any] = {}
    for entry in context["events"]:
        payloads[f"event:{entry['payload']['event_id']}"] = entry["payload"]
    for query in expectations.get("queries", []):
        payloads[f"query:{query['query_id']}"] = materialize_query_response(
            expectations, context, query
        )
    for page in expectations.get("actors_pages", []):
        payloads[f"actors_page:{page['page_id']}"] = materialize_actors_page(page, context)
    for scenario in expectations.get("updates_scenarios", []):
        payloads[f"updates:{scenario['scenario_id']}"] = materialize_updates(scenario, context)
    for error in expectations.get("errors", []):
        payloads[f"error:{error['error_id']}"] = materialize_error(error)
    for alias, spec in context["actor_by_alias"].items():
        payloads[f"actor:{alias}"] = _actor_payload(spec, snapshot=False)
        payloads[f"actor_snapshot:{alias}"] = _actor_payload(spec, snapshot=True)
    # Linked fixture payloads reused by the audit links.
    qr = context["quarantine"]
    payloads["return_response:QR-RETURN-SUCCESS"] = quarantine_returns.materialize_return_response(
        qr["scenarios"]["QR-RETURN-SUCCESS"], qr
    )
    payloads["quarantine_item:QR-STATE-CONFIRMED"] = quarantine_returns.materialize_quarantine_item(
        qr["states"]["QR-STATE-CONFIRMED"], qr
    )
    for error_id, entry in qr["errors"].items():
        payloads[f"error:{error_id}"] = quarantine_returns.materialize_error(entry)
    for batch_id, spec in context["batch"]["batches"].items():
        payloads[f"batch:{batch_id}"] = spec
    for version_id in (
        "version-atlas-general-v1",
        "version-atlas-general-v2",
        "version-atlas-general-v3",
        "version-atlas-invoices-v2",
    ):
        payloads[f"dictionary_version:{version_id}"] = dictionary_lifecycle.materialize_version(
            context["dictionary"]["versions"][version_id], context["dictionary"]
        )
    for rule_set_id in (
        "rule-set-atlas-v2",
        "rule-set-atlas-v2-invoices-v2",
        "rule-set-atlas-v3",
    ):
        payloads[f"rule_set:{rule_set_id}"] = copy.deepcopy(
            context["dictionary"]["rule_sets"][rule_set_id]
        )
    headers = expectations.get("safe_headers") or {}
    payloads["safe_headers"] = {
        "X-Request-ID": headers.get("request_id"),
        "Cache-Control": headers.get("cache_control"),
    }
    payloads["empty_list"] = []
    payloads["null_value"] = None
    payloads["false_value"] = False
    payloads["true_value"] = True
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
        elif relation not in ("equals", "not_equals", "is_null", "not_null"):
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
    for mutation in expectations.get("mutations", []):
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
        try:
            if validator == "expectation":
                reported = expectation_errors(mutated, mutated_context)
            elif validator == "payload":
                reported = payload_errors(mutated, mutated_context, registry)
            elif validator == "query":
                reported = query_errors(mutated, mutated_context)
            elif validator == "actors":
                reported = actors_errors(mutated, mutated_context)
            elif validator == "updates":
                reported = updates_errors(mutated, mutated_context)
            elif validator == "no_business":
                reported = no_business_errors(mutated, mutated_context)
            elif validator == "headers":
                reported = headers_errors(mutated, mutated_context)
            elif validator == "link":
                reported = link_errors(mutated, mutated_context)
            elif validator == "coverage":
                reported = coverage_errors(mutated, mutated_context)
            elif validator == "descriptor":
                reported = _descriptor_errors(mutated, mutated_context)
            elif validator == "error_operation":
                reported = error_operation_errors(mutated, mutated_context)
            else:  # pragma: no cover - guarded by the static fixture
                errors.append(f"{label}: unknown validator {validator!r}")
                continue
        except Exception as exc:  # noqa: BLE001 - a mutation may break resolution
            if not mutation.get("reason"):
                errors.append(f"{label}: validator raised {type(exc).__name__}: {exc}")
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
        "id": "audit-query-day-atlas",
        "kind": "query_response",
        "binding": "AUD-Q-DAY-ATLAS",
        "schema": AUDIT_QUERY_RESPONSE_SCHEMA,
        "file": "contracts/examples/audit/audit-query-day-atlas.json",
        "description": "LT-03.5b: first Moscow-day page of the shared BUSINESS journal (occurred_at DESC, event_id DESC).",
    },
    {
        "id": "audit-query-batch-accepted",
        "kind": "query_response",
        "binding": "AUD-Q-ACTION-BATCH-ACCEPTED",
        "schema": AUDIT_QUERY_RESPONSE_SCHEMA,
        "file": "contracts/examples/audit/audit-query-batch-accepted.json",
        "description": "LT-03.5b: action filter BATCH_ACCEPTED with the literal accepted-event ids.",
    },
    {
        "id": "audit-query-issue",
        "kind": "query_response",
        "binding": "AUD-Q-RESULT-ISSUE",
        "schema": AUDIT_QUERY_RESPONSE_SCHEMA,
        "file": "contracts/examples/audit/audit-query-issue.json",
        "description": "LT-03.5b: result filter ISSUE with the literal terminal/recovery event ids.",
    },
    {
        "id": "audit-query-cursor-page2",
        "kind": "query_response",
        "binding": "AUD-Q-PRIMARY-PAGE2",
        "schema": AUDIT_QUERY_RESPONSE_SCHEMA,
        "file": "contracts/examples/audit/audit-query-cursor-page2.json",
        "description": "LT-03.5b: cursor page bounded to the frozen upper bound under new events.",
    },
    {
        "id": "audit-query-empty-window",
        "kind": "query_response",
        "binding": "AUD-Q-EMPTY-WINDOW",
        "schema": AUDIT_QUERY_RESPONSE_SCHEMA,
        "file": "contracts/examples/audit/audit-query-empty-window.json",
        "description": "LT-03.5b: empty window returns items=[], next_cursor=null and newest_event_id=null.",
    },
    {
        "id": "audit-actors-atlas",
        "kind": "actors_page",
        "binding": "AUD-ACTORS-ALL",
        "schema": ACTOR_PAGE_SCHEMA,
        "file": "contracts/examples/audit/audit-actors-atlas.json",
        "description": "LT-03.5b: filterable authors including the blocked author with its current display snapshot.",
    },
    {
        "id": "audit-updates-after-known",
        "kind": "updates",
        "binding": "AUD-UPDATES-AFTER-KNOWN",
        "schema": AUDIT_UPDATES_SCHEMA,
        "file": "contracts/examples/audit/audit-updates-after-known.json",
        "description": "LT-03.5b: has_new_events=true for an after_event_id that precedes the newest event.",
    },
    {
        "id": "error-audit-validation",
        "kind": "error",
        "binding": "error-audit-validation",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/audit/error-audit-validation.json",
        "description": "LT-03.5b: 422 VALIDATION_ERROR for an invalid audit query interval.",
    },
]


def generated_examples(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    for binding in EXAMPLE_BINDINGS:
        kind = binding["kind"]
        if kind == "query_response":
            payload = materialize_query_response(
                expectations, context, context["queries"][binding["binding"]]
            )
        elif kind == "actors_page":
            payload = materialize_actors_page(
                context["actors_pages"][binding["binding"]], context
            )
        elif kind == "updates":
            payload = materialize_updates(context["updates"][binding["binding"]], context)
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
        description="Materialize the WiseWay canonical audit journal examples."
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
