"""Finite positive/negative semantic fixtures for the WiseWay contract.

Every payload is complete and schema-valid.  ``expect="pass"`` cases must pass
both the canonical schema validator and the semantic invariants; ``expect="fail"``
cases are schema-valid but violate exactly one semantic invariant, named by
``invariant`` and detected by the message substring ``contains``.

WP-03 reuses :func:`contractlib.semantic.validate_fixture` on these payloads
(or on its own external fixtures) exactly as ``test_semantics`` does.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

INSTANT = "2031-05-10T09:30:00Z"
SCHEMAS = {
    "search": "#/components/schemas/SearchResponse",
    "simulation": "#/components/schemas/Simulation",
    "preview": "#/components/schemas/Preview",
    "batch": "#/components/schemas/Batch",
    "outcome": "#/components/schemas/Outcome",
    "quarantine": "#/components/schemas/QuarantineItem",
    "error": "#/components/schemas/ErrorDetails",
    "queue": "#/components/schemas/QueueResponse",
    "rule_set": "#/components/schemas/RuleSet",
    "file_metadata": "#/components/schemas/FileMetadata",
}


@dataclass(frozen=True)
class FixtureCase:
    id: str
    invariant: str
    schema: str
    expect: str
    value: Any
    contains: str = ""


def actor() -> Dict[str, Any]:
    return {
        "user_id": "user-1",
        "login": "worker.one",
        "display_name": "Worker One",
        "role": "WORKER",
    }


def location(relative_path: str, root_id: str = "root-1") -> Dict[str, Any]:
    return {
        "root_id": root_id,
        "relative_path": relative_path,
        "display_path": f"DEMO:/SandboxRoot/{relative_path}",
    }


def freshness() -> Dict[str, Any]:
    return {
        "indexed_at": INSTANT,
        "last_successful_sync_at": INSTANT,
        "status": "CURRENT",
    }


def facet() -> Dict[str, Any]:
    return {"level_id": "level-1", "level_name": "Уровень", "options": []}


def search_item(index: int = 1) -> Dict[str, Any]:
    return {
        "item_id": f"file-{index}",
        "location": location(f"Archive/Atlas/Atlas-{index}.pdf"),
        "filename": f"Atlas-{index}.pdf",
        "markers": [],
        "extension": ".pdf",
        "size_bytes": 12000,
        "modified_at": INSTANT,
        "structure_status": "VALID",
        "structure_issue": None,
    }


def search_response(**overrides: Any) -> Dict[str, Any]:
    value = {
        "request_state_id": "state-1",
        "mode": "RESULTS",
        "root_id": "root-1",
        "schema_set_version": "schema-1",
        "index_generation": "generation-1",
        "ranking_profile_version": "ranking-1",
        "applied_query_text": "atlas",
        "selected_markers": [],
        "total": 2,
        "returned_count": 1,
        "result_limit": 1,
        "limited": True,
        "items": [search_item(1)],
        "next_facet": None,
        "freshness": freshness(),
    }
    value.update(overrides)
    return value


def rule_set(
    rule_set_id: str = "ruleset-1",
    company_id: str = "company-1",
    members: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    return {
        "rule_set_id": rule_set_id,
        "company_id": company_id,
        "members": members
        if members is not None
        else [{"dictionary_id": "dictionary-1", "version_id": "version-1"}],
    }


def rule_reference(
    dictionary_id: str = "dictionary-1",
    version_id: Any = "version-1",
    rule_id: str = "rule-1",
) -> Dict[str, Any]:
    return {
        "dictionary_id": dictionary_id,
        "version_id": version_id,
        "rule_id": rule_id,
    }


def plan_row(**overrides: Any) -> Dict[str, Any]:
    value = {
        "item_id": "item-1",
        "item_revision": 3,
        "source": location("Incoming/atlas/invoice.TXT"),
        "filename": "invoice.TXT",
        "company_id": "company-1",
        "predicted_state": "WILL_MOVE",
        "reason_code": None,
        "target": location("Archive/Atlas/Invoice.TXT"),
        "matched_rules": [rule_reference()],
        "selected_rule": rule_reference(),
        "collision": None,
    }
    value.update(overrides)
    return value


def simulation(**overrides: Any) -> Dict[str, Any]:
    value = {
        "simulation_id": "simulation-1",
        "dictionary_id": "dictionary-1",
        "draft_revision": 2,
        "base_rule_set": rule_set(),
        "ready_snapshot_id": "ready-snapshot-1",
        "created_at": INSTANT,
        "expires_at": INSTANT,
        "total": 1,
        "counts": {
            "will_move": 1,
            "will_manual_review": 0,
            "requires_decision": 0,
            "not_ready": 0,
            "rule_conflicts": 0,
            "no_scenario": 0,
        },
        "warnings": [],
        "rows": [plan_row()],
        "next_cursor": None,
    }
    value.update(overrides)
    return value


def preview(**overrides: Any) -> Dict[str, Any]:
    value = {
        "preview_id": "preview-1",
        "selection_id": "selection-1",
        "company_id": "company-1",
        "rule_set": rule_set(),
        "created_at": INSTANT,
        "expires_at": INSTANT,
        "total": 1,
        "counts": {
            "will_move": 1,
            "will_manual_review": 0,
            "requires_decision": 0,
            "not_ready": 0,
            "rule_conflicts": 0,
            "no_scenario": 0,
        },
        "rows": [plan_row()],
        "next_cursor": None,
    }
    value.update(overrides)
    return value


def outcome(**overrides: Any) -> Dict[str, Any]:
    value = {
        "attempt_id": "attempt-1",
        "item_id": "item-1",
        "item_revision": 3,
        "state": "SORTED",
        "reason_code": None,
        "source": location("Incoming/atlas/invoice.TXT"),
        "planned_target": location("Archive/Atlas/Invoice.TXT"),
        "actual_location": location("Archive/Atlas/Invoice.TXT", root_id="archive-root"),
        "matched_rule": rule_reference(),
        "started_at": INSTANT,
        "finished_at": INSTANT,
    }
    value.update(overrides)
    return value


def outcome_counts(**overrides: Any) -> Dict[str, Any]:
    value = {
        "sorted": 1,
        "manual_review": 0,
        "requires_decision": 0,
        "quarantined": 0,
        "skipped": 0,
        "recovery_required": 0,
    }
    value.update(overrides)
    return value


def batch(**overrides: Any) -> Dict[str, Any]:
    value = {
        "batch_id": "batch-1",
        "company_id": "company-1",
        "actor": actor(),
        "selection_id": "selection-1",
        "preview_id": "preview-1",
        "rule_set": rule_set(),
        "status": "COMPLETED",
        "created_at": INSTANT,
        "started_at": INSTANT,
        "finished_at": INSTANT,
        "selected_count": 1,
        "completed_count": 1,
        "counts": outcome_counts(),
        "outcomes": [outcome()],
        "next_cursor": None,
    }
    value.update(overrides)
    return value


def quarantine(**overrides: Any) -> Dict[str, Any]:
    value = {
        "quarantine_id": "quarantine-1",
        "revision": 1,
        "item_id": "item-4",
        "company_id": "company-1",
        "filename": "broken.xlsx",
        "location": location("Atlas/attempt-1/broken.xlsx", root_id="quarantine-root"),
        "original_location": location("Atlas/broken.xlsx", root_id="incoming-root"),
        "reason_code": "TECHNICAL_ERROR",
        "quarantined_at": INSTANT,
        "source_attempt_id": "attempt-1",
        "recovery_operation_id": None,
        "can_return": True,
    }
    value.update(overrides)
    return value


def error(**overrides: Any) -> Dict[str, Any]:
    value = {
        "code": "NOT_FOUND",
        "message": "Объект не найден.",
        "request_id": "request-1",
        "operation_id": None,
        "retryable": False,
        "field_errors": [],
    }
    value.update(overrides)
    return value


def queue_item(**overrides: Any) -> Dict[str, Any]:
    value = {
        "item_id": "item-1",
        "item_revision": 3,
        "company_id": "company-1",
        "incoming_source_id": "incoming-1",
        "source_name": "Atlas incoming",
        "source": location("Atlas/Reports/quarterly.xlsx", root_id="incoming-root"),
        "filename": "quarterly.xlsx",
        "size_bytes": 2048,
        "modified_at": INSTANT,
        "status": "READY",
        "reason_code": None,
        "selectable": True,
        "active_attempt_id": None,
    }
    value.update(overrides)
    return value


def queue(**overrides: Any) -> Dict[str, Any]:
    value = {
        "queue_generation": "queue-gen-1",
        "items": [queue_item()],
        "matching_count": 1,
        "eligible_count": 1,
        "counters": {"ready": 1, "processing": 0, "attention": 0},
        "status_counts": [{"status": "READY", "count": 1}],
        "next_cursor": None,
    }
    value.update(overrides)
    return value


def audit_event(**overrides: Any) -> Dict[str, Any]:
    value = {
        "event_id": "event-return-1",
        "occurred_at": INSTANT,
        "actor": actor(),
        "category": "BUSINESS",
        "action": "QUARANTINE_RETURNED",
        "result": "SUCCESS",
        "request_id": "request-1",
        "operation_id": "return-1",
        "source_attempt_id": "attempt-1",
        "company_id": "company-1",
        "dictionary_id": None,
        "version_id": None,
        "rule_set_id": None,
        "batch_id": None,
        "attempt_id": None,
        "item_id": "item-4",
        "source": None,
        "target": None,
        "reason_code": None,
        "comment": None,
    }
    value.update(overrides)
    return value


def return_response(**overrides: Any) -> Dict[str, Any]:
    value = {
        "return_operation_id": "return-1",
        "item": queue_item(
            item_id="item-4",
            item_revision=2,
            source=location("Atlas/broken.xlsx", root_id="incoming-root"),
            filename="broken.xlsx",
            status="WAITING_READY",
            selectable=False,
        ),
    }
    value.update(overrides)
    return value


@dataclass(frozen=True)
class LinkedPair:
    """A finite linked fixture pair for a WP-03-style cross-object check."""

    id: str
    name: str
    source: Any
    target: Any
    fields: Tuple[Tuple[Tuple[str, ...], Tuple[str, ...]], ...]
    expect: str
    contains: str = ""


# Audit ``QUARANTINE_RETURNED`` correlation: operation_id == return_operation_id
# and source_attempt_id ties the event to the original sorting attempt.  The
# canonical contract has no audit return example sharing these IDs, so the
# correlation is proven here as an explicit finite fixture pair for WP-03 and
# the standalone boundary is documented in the handoff.
_RETURN_AUDIT_FIELDS = (
    (("quarantine", "source_attempt_id"), ("source_attempt_id",)),
    (("return", "return_operation_id"), ("operation_id",)),
    (("return", "item", "item_id"), ("item_id",)),
    (("return", "item", "company_id"), ("company_id",)),
)


def build_linked_pairs() -> List[LinkedPair]:
    return [
        LinkedPair(
            id="return-audit-positive",
            name="quarantine-return-audit",
            source={
                "quarantine": quarantine(item_id="item-4", source_attempt_id="attempt-1",
                                        original_location=location("Atlas/broken.xlsx",
                                                                   root_id="incoming-root")),
                "return": return_response(),
            },
            target=audit_event(),
            fields=_RETURN_AUDIT_FIELDS,
            expect="pass",
        ),
        LinkedPair(
            id="return-audit-negative",
            name="quarantine-return-audit",
            source={
                "quarantine": quarantine(item_id="item-4", source_attempt_id="attempt-1"),
                "return": return_response(),
            },
            target=audit_event(source_attempt_id="attempt-other"),
            fields=_RETURN_AUDIT_FIELDS,
            expect="fail",
            contains="source_attempt_id",
        ),
    ]


LINKED_PAIRS: Tuple[LinkedPair, ...] = tuple(build_linked_pairs())


def _case(
    case_id: str,
    invariant: str,
    schema_key: str,
    expect: str,
    value: Any,
    contains: str = "",
) -> FixtureCase:
    return FixtureCase(case_id, invariant, SCHEMAS[schema_key], expect, value, contains)


def build_cases() -> List[FixtureCase]:
    cases: List[FixtureCase] = []

    # --- filenames --------------------------------------------------------- #
    cases.append(_case("filename-positive", "filename-basename", "file_metadata", "pass",
                       {"filename": "Atlas-1.pdf",
                        "location": location("Archive/Atlas/Atlas-1.pdf"),
                        "size_bytes": 12000, "modified_at": INSTANT}))
    cases.append(_case("filename-negative", "filename-basename", "file_metadata", "fail",
                       {"filename": "wrong.pdf",
                        "location": location("Archive/Atlas/Atlas-1.pdf"),
                        "size_bytes": 12000, "modified_at": INSTANT},
                       "basename"))

    # --- search IDLE / RESULTS -------------------------------------------- #
    cases.append(_case("search-idle-positive", "search-idle", "search", "pass",
                       search_response(mode="IDLE", applied_query_text="", total=None,
                                       returned_count=0, result_limit=100, limited=False,
                                       items=[], next_facet=facet())))
    cases.append(_case("search-idle-negative-no-facet", "search-idle", "search", "fail",
                       search_response(mode="IDLE", applied_query_text="", total=None,
                                       returned_count=0, result_limit=100, limited=False,
                                       items=[], next_facet=None),
                       "IDLE"))
    cases.append(_case("search-results-positive", "search-results", "search", "pass",
                       search_response()))
    cases.append(_case("search-results-negative-count", "search-results", "search", "fail",
                       search_response(returned_count=0), "returned_count"))
    cases.append(_case("search-results-negative-limited", "search-results", "search", "fail",
                       search_response(limited=False), "limited"))
    cases.append(_case("search-results-negative-page", "search-results", "search", "fail",
                       search_response(total=2, returned_count=2, result_limit=1, limited=True,
                                       items=[search_item(1), search_item(2)]),
                       "exceeds result_limit"))

    # --- plan counts, pages and rule references --------------------------- #
    cases.append(_case("plan-counts-positive", "plan-counts", "simulation", "pass", simulation()))
    cases.append(_case("plan-counts-negative", "plan-counts", "simulation", "fail",
                       simulation(total=2), "first four"))
    cases.append(_case("plan-page-positive", "plan-page", "simulation", "pass", simulation()))
    cases.append(_case("plan-page-negative", "plan-page", "simulation", "fail",
                       simulation(total=0,
                                  counts={"will_move": 0, "will_manual_review": 0,
                                          "requires_decision": 0, "not_ready": 0,
                                          "rule_conflicts": 0, "no_scenario": 0}),
                       "plan page"))
    cases.append(_case("ruleset-positive", "ruleset-members", "rule_set", "pass", rule_set()))
    cases.append(_case("ruleset-negative-order", "ruleset-members", "rule_set", "fail",
                       rule_set(members=[
                           {"dictionary_id": "dictionary-2", "version_id": "version-2"},
                           {"dictionary_id": "dictionary-1", "version_id": "version-1"},
                       ]),
                       "not sorted"))
    cases.append(_case("simulation-candidate-positive", "rule-references", "simulation", "pass",
                       simulation(rows=[plan_row(
                           matched_rules=[rule_reference(version_id=None)],
                           selected_rule=rule_reference(version_id=None))])))
    cases.append(_case("simulation-candidate-negative", "rule-references", "simulation", "fail",
                       simulation(rows=[plan_row(
                           matched_rules=[rule_reference(dictionary_id="dictionary-2",
                                                         version_id=None)],
                           selected_rule=rule_reference(dictionary_id="dictionary-2",
                                                        version_id=None))]),
                       "dictionary under test"))
    cases.append(_case("simulation-published-negative", "rule-references", "simulation", "fail",
                       simulation(rows=[plan_row(
                           matched_rules=[rule_reference(version_id="version-other")],
                           selected_rule=rule_reference(version_id="version-other"))]),
                       "not a member"))
    cases.append(_case("simulation-company-negative", "rule-references", "simulation", "fail",
                       simulation(rows=[plan_row(company_id="company-other")]), "company_id"))
    cases.append(_case("preview-positive", "rule-references", "preview", "pass", preview()))
    cases.append(_case("preview-company-negative", "rule-references", "preview", "fail",
                       preview(rule_set=rule_set(company_id="company-other")),
                       "rule_set.company_id"))
    cases.append(_case("preview-published-negative", "rule-references", "preview", "fail",
                       preview(rows=[plan_row(
                           matched_rules=[rule_reference(version_id="version-other")],
                           selected_rule=rule_reference(version_id="version-other"))]),
                       "not a member"))
    cases.append(_case("preview-candidate-negative", "rule-references", "preview", "fail",
                       preview(rows=[plan_row(
                           matched_rules=[rule_reference(version_id=None)],
                           selected_rule=rule_reference(version_id=None))]),
                       "dictionary under test"))

    # --- batch completion and recovery ------------------------------------ #
    cases.append(_case("batch-positive", "batch-completion", "batch", "pass", batch()))
    cases.append(_case("batch-completed-negative", "batch-completion", "batch", "fail",
                       batch(selected_count=2, completed_count=2,
                             counts=outcome_counts(sorted=1),
                             outcomes=[outcome()]),
                       "completed_count"))
    cases.append(_case("batch-exceeds-selected-negative", "batch-completion", "batch", "fail",
                       batch(selected_count=1, completed_count=2,
                             counts=outcome_counts(sorted=2),
                             outcomes=[outcome(), outcome(attempt_id="attempt-2",
                                                          item_id="item-2")]),
                       "exceeds selected_count"))
    cases.append(_case("batch-terminal-negative", "batch-completion", "batch", "fail",
                       batch(selected_count=2, completed_count=1), "terminal batch"))
    cases.append(_case("batch-recovery-negative", "batch-completion", "batch", "fail",
                       batch(status="RUNNING", selected_count=2, completed_count=1,
                             started_at=INSTANT, finished_at=None,
                             counts=outcome_counts(sorted=1, recovery_required=1),
                             outcomes=[outcome()]),
                       "RECOVERY_REQUIRED"))
    cases.append(_case("batch-accepted-positive", "batch-completion", "batch", "pass",
                       batch(status="ACCEPTED", started_at=None, finished_at=None,
                             completed_count=0, counts=outcome_counts(sorted=0),
                             outcomes=[outcome(state="PENDING", reason_code=None,
                                               planned_target=None, actual_location=None,
                                               started_at=None, finished_at=None,
                                               matched_rule=None)])))
    cases.append(_case("batch-accepted-negative", "batch-completion", "batch", "fail",
                       batch(status="ACCEPTED", started_at=None, finished_at=None,
                             outcomes=[outcome(state="PENDING", reason_code=None,
                                               planned_target=None, actual_location=None,
                                               started_at=None, finished_at=None,
                                               matched_rule=None)]),
                       "accepted batch"))
    cases.append(_case("batch-page-negative", "batch-completion", "batch", "fail",
                       batch(selected_count=2, completed_count=1,
                             counts=outcome_counts(sorted=1),
                             outcomes=[outcome(), outcome(attempt_id="attempt-2",
                                                          item_id="item-2")]),
                       "outcomes page"))
    cases.append(_case("batch-recovery-exceeds-negative", "batch-completion", "batch", "fail",
                       batch(status="RECOVERY_REQUIRED", selected_count=2, completed_count=2,
                             started_at=INSTANT, finished_at=None,
                             counts=outcome_counts(sorted=2, recovery_required=1),
                             outcomes=[]),
                       "recovery_required"))
    cases.append(_case("batch-rule-references-positive", "batch-rule-references", "batch", "pass",
                       batch()))
    cases.append(_case("batch-rule-references-negative", "batch-rule-references", "batch", "fail",
                       batch(outcomes=[outcome(
                           matched_rule=rule_reference(version_id="version-other"))]),
                       "not a member"))

    # --- outcome placement ------------------------------------------------- #
    cases.append(_case("outcome-positive", "outcome-placement", "outcome", "pass", outcome()))
    cases.append(_case("outcome-skipped-known-positive", "outcome-placement", "outcome", "pass",
                       outcome(state="SKIPPED", reason_code="ALREADY_PROCESSING",
                               actual_location=location("Incoming/atlas/invoice.TXT"))))
    cases.append(_case("outcome-skipped-negative", "outcome-placement", "outcome", "fail",
                       outcome(state="SKIPPED", reason_code="ALREADY_PROCESSING",
                               actual_location=location("Archive/Atlas/Invoice.TXT",
                                                        root_id="archive-root")),
                       "SKIPPED"))
    cases.append(_case("outcome-requires-negative", "outcome-placement", "outcome", "fail",
                       outcome(state="REQUIRES_DECISION", reason_code="TARGET_OCCUPIED",
                               actual_location=location("Archive/Elsewhere/Invoice.TXT")),
                       "REQUIRES_DECISION"))

    # --- quarantine -------------------------------------------------------- #
    cases.append(_case("quarantine-positive", "quarantine-can-return", "quarantine", "pass",
                       quarantine()))
    cases.append(_case("quarantine-negative-blocked", "quarantine-can-return", "quarantine", "fail",
                       quarantine(can_return=False, recovery_operation_id=None),
                       "can_return=false"))
    cases.append(_case("quarantine-negative-returnable", "quarantine-can-return", "quarantine",
                       "fail",
                       quarantine(can_return=True, recovery_operation_id="recovery-1"),
                       "can_return=true"))

    # --- errors ------------------------------------------------------------ #
    cases.append(_case("error-null-positive", "error-operation-id", "error", "pass", error()))
    cases.append(_case("error-operation-negative", "error-operation-id", "error", "fail",
                       error(operation_id="recovery-1"), "before any operation"))
    cases.append(_case("error-recovery-positive", "error-recovery", "error", "pass",
                       error(code="RECOVERY_REQUIRED", operation_id="recovery-1")))
    cases.append(_case("error-recovery-negative", "error-recovery", "error", "fail",
                       error(code="RECOVERY_REQUIRED", operation_id=None),
                       "registered operation_id"))
    cases.append(_case("error-retryable-negative", "error-recovery", "error", "fail",
                       error(code="RECOVERY_REQUIRED", operation_id="recovery-1", retryable=True),
                       "must not be retryable"))

    # --- queue ------------------------------------------------------------- #
    cases.append(_case("queue-positive", "queue-consistency", "queue", "pass", queue()))
    cases.append(_case("queue-counters-negative", "queue-consistency", "queue", "fail",
                       queue(counters={"ready": 1, "processing": 0, "attention": 1}),
                       "counters.attention"))
    cases.append(_case("queue-selectable-negative", "queue-consistency", "queue", "fail",
                       queue(items=[dict(queue()["items"][0], status="PROCESSING",
                                         selectable=True)]),
                       "selectable"))

    return cases


CASES: Tuple[FixtureCase, ...] = tuple(build_cases())


def cases_by_invariant(invariant: str) -> List[FixtureCase]:
    return [case for case in CASES if case.invariant == invariant]


def mutated(case: FixtureCase) -> Any:
    return deepcopy(case.value)
