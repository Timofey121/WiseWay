"""Semantic consistency invariants for WiseWay contract examples and fixtures.

The canonical schema validator (:mod:`contractlib.schemas`) proves that a
payload matches the published shape.  The checks here assert the *cross-field*
and *cross-example* rules that the OpenAPI shape cannot express, for example:

* ``SearchResponse`` result counts equal ``min(total, result_limit)``;
* ``PlanCounts`` first four counters sum to ``total`` while reason counters are
  supplemental;
* page arrays never exceed their whole-set total and a ``null`` cursor is not
  treated as proof of completeness;
* a filename equals the basename of its logical location, including nested
  ``FileMetadata``;
* ``RuleSet`` membership and published/candidate rule references agree;
* batch completion/recovery counters and per-file placements agree;
* ``error.operation_id`` is ``null`` before an operation exists and non-null
  for a registered recovery.

The validators are intentionally independent from the OpenAPI document: they
accept a plain instance plus an optional canonical schema pointer, so WP-03 can
reuse them for external synthetic fixtures.  ``validate_fixture`` is the
convenience entry point for that use case.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .loading import pointer
from .report import Report
from .schemas import validate_value

# --------------------------------------------------------------------------- #
# Low-level helpers
# --------------------------------------------------------------------------- #

_MISSING = object()


def _basename(relative_path: str) -> str:
    return relative_path.rsplit("/", 1)[-1]


def _dedupe(messages: Iterable[str]) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for message in messages:
        if message not in seen:
            seen.add(message)
            out.append(message)
    return out


def _containers(value: Any) -> Iterable[Dict[str, Any]]:
    """Yield *value* and the page/wrapper objects that may hold its fields."""
    if isinstance(value, dict):
        yield value
        item = value.get("item")
        if isinstance(item, dict):
            yield item
        items = value.get("items")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            yield items[0]


def _field_of(value: Any, path: Sequence[str]) -> Any:
    """Read a field path, transparently unwrapping ``items[0]``/``item``."""
    current = value
    for key in path:
        found: Any = _MISSING
        for container in _containers(current):
            if key in container:
                found = container[key]
                break
        if found is _MISSING:
            return _MISSING
        current = found
    return current


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# --------------------------------------------------------------------------- #
# Per-payload validators
# --------------------------------------------------------------------------- #

def filename_location_errors(node: Dict[str, Any]) -> List[str]:
    """A filename must be the basename of its logical location/source path."""
    errors: List[str] = []
    filename = node.get("filename")
    if not isinstance(filename, str):
        return errors
    for key in ("location", "source"):
        location = node.get(key)
        if not isinstance(location, dict):
            continue
        relative_path = location.get("relative_path")
        if not isinstance(relative_path, str):
            continue
        basename = _basename(relative_path)
        if filename != basename:
            errors.append(
                f"filename {filename!r} is not the basename {basename!r} of "
                f"{key}.relative_path {relative_path!r}"
            )
    return errors


def search_response_errors(value: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    mode = value.get("mode")
    items = value.get("items")
    total = value.get("total")
    returned = value.get("returned_count")
    limit = value.get("result_limit")
    limited = value.get("limited")
    if mode == "IDLE":
        if total is not None:
            errors.append("search IDLE total must be null")
        if items != []:
            errors.append("search IDLE items must be empty")
        if returned != 0:
            errors.append("search IDLE returned_count must be 0")
        if limited is not False:
            errors.append("search IDLE limited must be false")
        if value.get("next_facet") is None:
            errors.append("search IDLE must expose the first facet (next_facet)")
    elif mode == "RESULTS":
        if total is None:
            errors.append("search RESULTS total must not be null")
        elif (
            isinstance(items, list)
            and _integer(total)
            and _integer(returned)
            and _integer(limit)
        ):
            if returned != len(items):
                errors.append(
                    f"search RESULTS returned_count {returned} != items.length {len(items)}"
                )
            if len(items) > limit:
                errors.append(
                    f"search RESULTS items.length {len(items)} exceeds result_limit {limit}"
                )
            expected = min(total, limit)
            if returned != expected:
                errors.append(
                    f"search RESULTS returned_count {returned} != min(total {total}, "
                    f"result_limit {limit}) = {expected}"
                )
            if bool(limited) != (total > limit):
                errors.append(
                    f"search RESULTS limited {limited} != (total {total} > result_limit {limit})"
                )
    return errors


def plan_counts_errors(total: Any, counts: Dict[str, Any]) -> List[str]:
    """``total`` equals the first four counters; reason counters are extra."""
    errors: List[str] = []
    try:
        first_four = sum(
            counts[key]
            for key in ("will_move", "will_manual_review", "requires_decision", "not_ready")
        )
    except (KeyError, TypeError):
        return errors
    if first_four != total:
        errors.append(
            f"plan counts first four counters sum to {first_four}, but total is {total}"
        )
    return errors


def plan_page_errors(rows: Any, total: Any) -> List[str]:
    if isinstance(rows, list) and _integer(total) and len(rows) > total:
        return [f"plan page has {len(rows)} rows, exceeding the whole-set total {total}"]
    return []


def rule_set_errors(value: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    members = value.get("members")
    if not isinstance(members, list):
        return errors
    dictionary_ids = [
        member.get("dictionary_id")
        for member in members
        if isinstance(member, dict)
    ]
    if dictionary_ids != sorted(dictionary_ids):
        errors.append(
            f"rule set members are not sorted by dictionary_id: {dictionary_ids}"
        )
    if len(dictionary_ids) != len(set(dictionary_ids)):
        errors.append(f"rule set repeats dictionary_id values: {dictionary_ids}")
    for member in members:
        if isinstance(member, dict) and not member.get("version_id"):
            errors.append("rule set member is missing its published version_id")
    return errors


def _rule_set_signature(rule_set: Dict[str, Any]) -> Tuple[Any, Tuple[Tuple[Any, Any], ...]]:
    members = rule_set.get("members")
    ordered = tuple(
        (member.get("dictionary_id"), member.get("version_id"))
        for member in members
        if isinstance(member, dict)
    ) if isinstance(members, list) else ()
    return (rule_set.get("company_id"), ordered)


def rule_set_consistency_errors(rule_sets: Iterable[Dict[str, Any]]) -> List[str]:
    """One ``rule_set_id`` must always denote the same company and members.

    Reusable by WP-03: pass every ``RuleSet`` instance found in a document or
    fixture set and receive a failure for each id that maps to more than one
    company/member signature.
    """
    signatures: Dict[Any, set] = {}
    for rule_set in rule_sets:
        if not isinstance(rule_set, dict):
            continue
        rule_set_id = rule_set.get("rule_set_id")
        if rule_set_id is None:
            continue
        signatures.setdefault(rule_set_id, set()).add(_rule_set_signature(rule_set))
    errors: List[str] = []
    for rule_set_id in sorted(signatures, key=str):
        distinct = signatures[rule_set_id]
        if len(distinct) > 1:
            errors.append(
                f"rule set {rule_set_id!r} maps to {len(distinct)} inconsistent "
                "company/member signatures"
            )
    return errors


def _reference_errors(
    rows: Any,
    members: Optional[set],
    candidate_dictionary: Optional[str],
) -> List[str]:
    """Validate ``RuleReference`` values inside plan rows.

    ``version_id=None`` is only allowed for the dictionary currently under test
    (the candidate draft).  A published reference must belong to the enclosing
    ``RuleSet``.
    """
    errors: List[str] = []
    if not isinstance(rows, list):
        return errors
    for row in rows:
        if not isinstance(row, dict):
            continue
        references = list(row.get("matched_rules") or [])
        selected = row.get("selected_rule")
        if isinstance(selected, dict):
            if selected not in references:
                errors.append(
                    "plan row selected_rule is not one of its matched_rules"
                )
            references = references + [selected]
        for reference in references:
            if not isinstance(reference, dict):
                continue
            dictionary_id = reference.get("dictionary_id")
            version_id = reference.get("version_id")
            if version_id is None:
                if candidate_dictionary is None or dictionary_id != candidate_dictionary:
                    errors.append(
                        "rule reference with version_id=null must point at the "
                        f"dictionary under test, found {dictionary_id!r}"
                    )
            elif members is not None and (dictionary_id, version_id) not in members:
                errors.append(
                    f"published rule reference {dictionary_id!r}/{version_id!r} is "
                    "not a member of the enclosing rule set"
                )
    return errors


def simulation_errors(value: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    base_rule_set = value.get("base_rule_set")
    members: Optional[set] = None
    company_id = None
    if isinstance(base_rule_set, dict):
        company_id = base_rule_set.get("company_id")
        members = {
            (member.get("dictionary_id"), member.get("version_id"))
            for member in base_rule_set.get("members") or []
            if isinstance(member, dict)
        }
    counts = value.get("counts")
    if isinstance(counts, dict):
        errors += plan_counts_errors(value.get("total"), counts)
    rows = value.get("rows")
    errors += plan_page_errors(rows, value.get("total"))
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and company_id is not None and row.get("company_id") != company_id:
                errors.append(
                    "simulation row company_id does not match the base rule set company_id"
                )
    errors += _reference_errors(rows, members, value.get("dictionary_id"))
    return errors


def preview_errors(value: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    rule_set = value.get("rule_set")
    members: Optional[set] = None
    if isinstance(rule_set, dict):
        members = {
            (member.get("dictionary_id"), member.get("version_id"))
            for member in rule_set.get("members") or []
            if isinstance(member, dict)
        }
        if rule_set.get("company_id") != value.get("company_id"):
            errors.append("preview rule_set.company_id does not match preview.company_id")
    counts = value.get("counts")
    if isinstance(counts, dict):
        errors += plan_counts_errors(value.get("total"), counts)
    rows = value.get("rows")
    errors += plan_page_errors(rows, value.get("total"))
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get("company_id") != value.get("company_id"):
                errors.append("preview row company_id does not match preview.company_id")
    # A preview is materialised from published versions, never from a draft.
    errors += _reference_errors(rows, members, candidate_dictionary=None)
    return errors


_BATCH_TERMINAL_STATES = ("COMPLETED", "COMPLETED_WITH_ISSUES")
_OUTCOME_COUNT_FIELDS = {
    "SORTED": "sorted",
    "MANUAL_REVIEW": "manual_review",
    "REQUIRES_DECISION": "requires_decision",
    "QUARANTINED": "quarantined",
    "SKIPPED": "skipped",
    "RECOVERY_REQUIRED": "recovery_required",
}


def batch_errors(value: Dict[str, Any]) -> List[str]:
    """Batch/BatchSummary completion and recovery consistency."""
    errors: List[str] = []
    counts = value.get("counts")
    selected = value.get("selected_count")
    completed = value.get("completed_count")
    status = value.get("status")
    if not isinstance(counts, dict):
        return errors
    try:
        established = sum(
            counts[key]
            for key in ("sorted", "manual_review", "requires_decision", "quarantined", "skipped")
        )
    except (KeyError, TypeError):
        return errors
    recovery = counts.get("recovery_required")
    if completed != established:
        errors.append(
            f"batch completed_count {completed} != first five outcome counts {established}"
        )
    if _integer(completed) and _integer(selected) and completed > selected:
        errors.append(
            f"batch completed_count {completed} exceeds selected_count {selected}"
        )
    if (
        _integer(completed)
        and _integer(recovery)
        and _integer(selected)
        and completed + recovery > selected
    ):
        errors.append(
            f"batch completed_count {completed} + recovery_required {recovery} "
            f"exceeds selected_count {selected}"
        )
    if _integer(recovery) and recovery > 0 and status != "RECOVERY_REQUIRED":
        errors.append(
            f"batch recovery_required {recovery} > 0 requires status RECOVERY_REQUIRED, "
            f"found {status!r}"
        )
    if status in _BATCH_TERMINAL_STATES:
        if counts.get("recovery_required"):
            errors.append("terminal batch must not carry recovery_required outcomes")
        if completed != selected:
            errors.append(
                f"terminal batch status {status!r} requires completed_count {completed} "
                f"to equal selected_count {selected}"
            )
    if status == "ACCEPTED" and completed != 0:
        errors.append("accepted batch must not report completed outcomes yet")
    rule_set = value.get("rule_set")
    members: Optional[set] = None
    if isinstance(rule_set, dict):
        if rule_set.get("company_id") != value.get("company_id"):
            errors.append("batch rule_set.company_id does not match batch.company_id")
        members = {
            (member.get("dictionary_id"), member.get("version_id"))
            for member in rule_set.get("members") or []
            if isinstance(member, dict)
        }
    outcomes = value.get("outcomes")
    if isinstance(outcomes, list):
        if _integer(selected) and len(outcomes) > selected:
            errors.append(
                f"batch outcomes page {len(outcomes)} exceeds selected_count {selected}"
            )
        tally: Dict[str, int] = {}
        for outcome in outcomes:
            if not isinstance(outcome, dict):
                continue
            count_field = _OUTCOME_COUNT_FIELDS.get(outcome.get("state"))
            if count_field:
                tally[count_field] = tally.get(count_field, 0) + 1
            # A batch is a published plan: its per-file matched rule must be a
            # published member of the batch RuleSet.  A null version is only
            # valid for the draft under test in a Simulation.
            matched_rule = outcome.get("matched_rule")
            if isinstance(matched_rule, dict):
                if matched_rule.get("version_id") is None:
                    errors.append(
                        "batch outcome matched_rule must reference a published "
                        "version; version_id=null is only valid for a simulation draft"
                    )
                elif members is not None and (
                    matched_rule.get("dictionary_id"),
                    matched_rule.get("version_id"),
                ) not in members:
                    errors.append(
                        "batch outcome matched_rule "
                        f"{matched_rule.get('dictionary_id')!r}/"
                        f"{matched_rule.get('version_id')!r} is not a member of the "
                        "batch rule set"
                    )
        for count_field, seen in tally.items():
            declared = counts.get(count_field)
            if _integer(declared) and seen > declared:
                errors.append(
                    f"batch outcomes page has {seen} {count_field} but the whole batch "
                    f"declares {declared}"
                )
    return errors


def outcome_errors(value: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    state = value.get("state")
    actual = value.get("actual_location")
    source = value.get("source")
    if state in ("SORTED", "MANUAL_REVIEW", "QUARANTINED") and actual is None:
        errors.append(f"outcome {state} must carry its confirmed actual_location")
    # ``actual_location=null`` means "placement not established"; a known
    # placement is not forbidden.  A skipped/undecided attempt performs no move,
    # so any reported placement must be the unchanged source.
    if state == "SKIPPED" and actual is not None and actual != source:
        errors.append(
            "outcome SKIPPED performs no move, so actual_location must be null or "
            "equal to source"
        )
    if state == "REQUIRES_DECISION" and actual is not None and actual != source:
        errors.append(
            "outcome REQUIRES_DECISION keeps the source in place, so actual_location "
            "must be null or equal to source"
        )
    return errors


def quarantine_item_errors(value: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    can_return = value.get("can_return")
    recovery_operation_id = value.get("recovery_operation_id")
    if can_return is False and recovery_operation_id is None:
        errors.append(
            "quarantine item with can_return=false must expose recovery_operation_id"
        )
    if can_return is True and recovery_operation_id is not None:
        errors.append(
            "quarantine item with can_return=true must not expose recovery_operation_id"
        )
    return errors


def error_details_errors(value: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    code = value.get("code")
    operation_id = value.get("operation_id")
    if code == "RECOVERY_REQUIRED":
        if operation_id is None:
            errors.append(
                "error RECOVERY_REQUIRED must carry the registered operation_id"
            )
        if value.get("retryable") is not False:
            errors.append("error RECOVERY_REQUIRED must not be retryable")
    elif operation_id is not None:
        errors.append(
            f"error {code!r} has operation_id {operation_id!r} before any operation "
            "was registered"
        )
    return errors


def queue_response_errors(value: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    counters = value.get("counters")
    status_counts = value.get("status_counts")
    if isinstance(counters, dict) and isinstance(status_counts, list):
        by_status = {
            entry.get("status"): entry.get("count")
            for entry in status_counts
            if isinstance(entry, dict)
        }
        expected = {
            "ready": by_status.get("READY", 0),
            "processing": by_status.get("PROCESSING", 0),
            "attention": by_status.get("REQUIRES_DECISION", 0)
            + by_status.get("RECOVERY_REQUIRED", 0),
        }
        for key, expected_value in expected.items():
            if counters.get(key) != expected_value:
                errors.append(
                    f"queue counters.{key} {counters.get(key)} != status_counts {expected_value}"
                )
    items = value.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("selectable") is True and (
                item.get("status") not in ("READY", "REQUIRES_DECISION")
                or item.get("active_attempt_id") is not None
            ):
                errors.append(
                    "queue item is selectable only when READY/REQUIRES_DECISION "
                    "without an active attempt"
                )
    return errors


def _is_search_response(value: Dict[str, Any]) -> bool:
    return {"mode", "total", "returned_count", "result_limit", "limited", "items"} <= set(value)


def _is_simulation(value: Dict[str, Any]) -> bool:
    return {"simulation_id", "base_rule_set", "counts", "rows", "total"} <= set(value)


def _is_preview(value: Dict[str, Any]) -> bool:
    return {"preview_id", "selection_id", "rule_set", "counts", "rows", "total"} <= set(value)


def _is_batch(value: Dict[str, Any]) -> bool:
    return {"batch_id", "outcomes", "selected_count", "completed_count", "counts"} <= set(value)


def _is_batch_summary(value: Dict[str, Any]) -> bool:
    return (
        {"batch_id", "status", "selected_count", "completed_count", "counts"} <= set(value)
        and "outcomes" not in value
    )


def _is_outcome(value: Dict[str, Any]) -> bool:
    return {"attempt_id", "item_id", "state", "source", "planned_target", "actual_location"} <= set(value)


def _is_quarantine_item(value: Dict[str, Any]) -> bool:
    return {"quarantine_id", "can_return"} <= set(value)


def _is_error_details(value: Dict[str, Any]) -> bool:
    return {"code", "request_id", "operation_id", "retryable", "field_errors"} <= set(value)


def _is_queue_response(value: Dict[str, Any]) -> bool:
    return {"queue_generation", "counters", "status_counts"} <= set(value)


def _is_rule_set(value: Dict[str, Any]) -> bool:
    return {"rule_set_id", "members", "company_id"} <= set(value)


_SHAPE_VALIDATORS: Tuple[Tuple[Callable[[Dict[str, Any]], bool], Callable[[Dict[str, Any]], List[str]]], ...] = (
    (_is_search_response, search_response_errors),
    (_is_simulation, simulation_errors),
    (_is_preview, preview_errors),
    (_is_batch, batch_errors),
    (_is_batch_summary, batch_errors),
    (_is_outcome, outcome_errors),
    (_is_quarantine_item, quarantine_item_errors),
    (_is_error_details, error_details_errors),
    (_is_queue_response, queue_response_errors),
    (_is_rule_set, rule_set_errors),
)

_SCHEMA_VALIDATORS: Dict[str, Callable[[Dict[str, Any]], List[str]]] = {
    "SearchResponse": search_response_errors,
    "Simulation": simulation_errors,
    "Preview": preview_errors,
    "Batch": batch_errors,
    "BatchSummary": batch_errors,
    "Outcome": outcome_errors,
    "QuarantineItem": quarantine_item_errors,
    "ErrorDetails": error_details_errors,
    "QueueResponse": queue_response_errors,
    "RuleSet": rule_set_errors,
}


def _schema_name(schema_pointer: Optional[str]) -> Optional[str]:
    if not isinstance(schema_pointer, str):
        return None
    prefix = "#/components/schemas/"
    if schema_pointer.startswith(prefix):
        return schema_pointer[len(prefix):]
    return None


def _collect(node: Any, errors: List[str]) -> None:
    if isinstance(node, dict):
        errors.extend(filename_location_errors(node))
        for predicate, validator in _SHAPE_VALIDATORS:
            if predicate(node):
                errors.extend(validator(node))
        for child in node.values():
            _collect(child, errors)
    elif isinstance(node, list):
        for child in node:
            _collect(child, errors)


def _collect_rule_sets(node: Any, out: List[Dict[str, Any]]) -> None:
    """Gather every ``RuleSet`` instance reachable from *node*."""
    if isinstance(node, dict):
        if _is_rule_set(node):
            out.append(node)
        for child in node.values():
            _collect_rule_sets(child, out)
    elif isinstance(node, list):
        for child in node:
            _collect_rule_sets(child, out)


def semantic_errors(value: Any, schema_pointer: Optional[str] = None) -> List[str]:
    """Return every semantic consistency failure for *value*.

    *schema_pointer* is the canonical ``#/components/schemas/<Name>`` pointer
    when the caller knows it (fixtures); media/response pointers simply fall
    back to shape detection.  The function never validates the JSON Schema
    shape itself -- use :func:`validate_fixture` for the combined check.
    """
    errors: List[str] = []
    name = _schema_name(schema_pointer)
    if name in _SCHEMA_VALIDATORS and isinstance(value, dict):
        errors.extend(_SCHEMA_VALIDATORS[name](value))
    _collect(value, errors)
    return _dedupe(errors)


def validate_fixture(registry, schema_pointer: str, value: Any) -> Tuple[List[str], List[str]]:
    """Validate an external fixture: return ``(schema_errors, semantic_errors)``.

    Semantic checks only run when the canonical schema accepts the value, so a
    shape defect is reported once, by the schema validator.  This is the entry
    point WP-03 should reuse for its synthetic fixtures.
    """
    schema_errors = validate_value(registry, schema_pointer, value)
    if schema_errors:
        return schema_errors, []
    return [], semantic_errors(value, schema_pointer)


# --------------------------------------------------------------------------- #
# Finite explicit example links
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class LinkSpec:
    """An explicit, finite link between two canonical embedded examples."""

    name: str
    source: str
    target: str
    fields: Tuple[Tuple[Tuple[str, ...], Tuple[str, ...]], ...]


def link_errors(
    source: Any,
    target: Any,
    fields: Tuple[Tuple[Tuple[str, ...], Tuple[str, ...]], ...],
    name: str,
) -> List[str]:
    """Compare declared field pairs and fail when a required field is absent.

    Reusable by WP-03 for external linked fixture pairs.  A missing endpoint is
    handled by the caller; a missing *field* is a failure here, never a silent
    skip.
    """
    errors: List[str] = []
    for source_path, target_path in fields:
        left = _field_of(source, source_path)
        right = _field_of(target, target_path)
        if left is _MISSING:
            errors.append(f"{name}: source field {'.'.join(source_path)} is missing")
        if right is _MISSING:
            errors.append(f"{name}: target field {'.'.join(target_path)} is missing")
        if left is not _MISSING and right is not _MISSING and left != right:
            errors.append(
                f"{name}: {'.'.join(source_path)} {left!r} != "
                f"{'.'.join(target_path)} {right!r}"
            )
    return errors


def media_example_pointer(path: str, method: str, location: Tuple[str, ...], name: str) -> str:
    """Build the normalized pointer of a request/response media example."""
    parts: List[Any] = ["paths", path, method]
    if location[0] == "responses":
        parts += ["responses", location[1], "content", "application/json"]
    else:
        parts += ["requestBody", "content", "application/json"]
    parts += ["examples", name]
    return pointer(parts)


def _field(source: str, target: str) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    return ((source,), (target,))


def _path_field(
    source: Tuple[str, ...], target: Tuple[str, ...]
) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    return (source, target)


_SELECTION_EXPLICIT = media_example_pointer(
    "/sorting/selections", "post", ("responses", "201"), "explicit"
)
_PREVIEW_CALCULATED = media_example_pointer(
    "/sorting/previews", "post", ("responses", "201"), "calculated"
)
_BATCH_ACCEPTED = media_example_pointer(
    "/sorting/batches", "post", ("responses", "202"), "accepted"
)


def finite_links() -> Tuple[LinkSpec, ...]:
    """Return the reviewed finite links between canonical examples.

    Only examples that share concrete IDs are linked.  Independent scenarios
    (for example the standalone ``runningPartial``/``recoveryRequired`` batches
    or the all-matching selection) are intentionally not linked, because
    inferring a relationship would invent domain semantics.
    """
    return (
        LinkSpec(
            name="search-idle",
            source=media_example_pointer("/search", "post", ("requestBody",), "idle"),
            target=media_example_pointer("/search", "post", ("responses", "200"), "idle"),
            fields=(
                _field("request_state_id", "request_state_id"),
                _field("root_id", "root_id"),
                _field("schema_set_version", "schema_set_version"),
            ),
        ),
        LinkSpec(
            name="search-words",
            source=media_example_pointer("/search", "post", ("requestBody",), "words"),
            target=media_example_pointer("/search", "post", ("responses", "200"), "found"),
            fields=(
                _field("request_state_id", "request_state_id"),
                _field("root_id", "root_id"),
                _field("schema_set_version", "schema_set_version"),
            ),
        ),
        LinkSpec(
            name="search-facet",
            source=media_example_pointer(
                "/search/facet", "post", ("requestBody",), "companyAlternatives"
            ),
            target=media_example_pointer(
                "/search/facet", "post", ("responses", "200"), "alternatives"
            ),
            fields=(
                _field("request_state_id", "request_state_id"),
                _field("root_id", "root_id"),
                _field("schema_set_version", "schema_set_version"),
            ),
        ),
        LinkSpec(
            name="preview-from-selection",
            source=_SELECTION_EXPLICIT,
            target=_PREVIEW_CALCULATED,
            fields=(
                _field("selection_id", "selection_id"),
                _field("company_id", "company_id"),
                _field("selected_count", "total"),
            ),
        ),
        LinkSpec(
            name="batch-from-selection",
            source=_SELECTION_EXPLICIT,
            target=_BATCH_ACCEPTED,
            fields=(
                _field("selection_id", "selection_id"),
                _field("company_id", "company_id"),
                _field("selected_count", "selected_count"),
            ),
        ),
        LinkSpec(
            name="batch-from-preview",
            source=_PREVIEW_CALCULATED,
            target=_BATCH_ACCEPTED,
            fields=(
                _field("preview_id", "preview_id"),
                _field("company_id", "company_id"),
                _path_field(("rule_set", "rule_set_id"), ("rule_set", "rule_set_id")),
            ),
        ),
        LinkSpec(
            name="batch-request-previewed",
            source=_PREVIEW_CALCULATED,
            target=media_example_pointer(
                "/sorting/batches", "post", ("requestBody",), "previewed"
            ),
            fields=(
                _field("preview_id", "preview_id"),
                _field("selection_id", "selection_id"),
            ),
        ),
        LinkSpec(
            name="preview-get-matches-post",
            source=_PREVIEW_CALCULATED,
            target=media_example_pointer(
                "/sorting/previews/{preview_id}", "get", ("responses", "200"), "firstPage"
            ),
            fields=(
                _field("preview_id", "preview_id"),
                _field("selection_id", "selection_id"),
                _field("company_id", "company_id"),
                _field("total", "total"),
                _field("counts", "counts"),
                _path_field(("rule_set", "rule_set_id"), ("rule_set", "rule_set_id")),
            ),
        ),
        LinkSpec(
            name="simulation-get-matches-post",
            source=media_example_pointer(
                "/dictionaries/{dictionary_id}/simulate",
                "post",
                ("responses", "201"),
                "simulation_will_move",
            ),
            target=media_example_pointer(
                "/simulations/{simulation_id}", "get", ("responses", "200"), "simulation_page"
            ),
            fields=(
                _field("simulation_id", "simulation_id"),
                _field("dictionary_id", "dictionary_id"),
                _field("ready_snapshot_id", "ready_snapshot_id"),
                _field("total", "total"),
                _field("counts", "counts"),
            ),
        ),
        LinkSpec(
            name="quarantine-return",
            source=media_example_pointer("/quarantine", "get", ("responses", "200"), "list"),
            target=media_example_pointer(
                "/quarantine/{quarantine_id}/return", "post", ("responses", "200"), "returned"
            ),
            fields=(
                _field("item_id", "item_id"),
                _field("company_id", "company_id"),
                _field("filename", "filename"),
                _field("original_location", "source"),
            ),
        ),
        LinkSpec(
            name="quarantine-return-request",
            source=media_example_pointer("/quarantine", "get", ("responses", "200"), "list"),
            target=media_example_pointer(
                "/quarantine/{quarantine_id}/return", "post", ("requestBody",), "return"
            ),
            fields=(_field("revision", "expected_revision"),),
        ),
        LinkSpec(
            name="audit-batch-accepted",
            source=_BATCH_ACCEPTED,
            target=media_example_pointer("/audit/query", "post", ("responses", "200"), "events"),
            fields=(
                _field("batch_id", "batch_id"),
                _field("company_id", "company_id"),
                _path_field(("rule_set", "rule_set_id"), ("rule_set_id",)),
            ),
        ),
    )


# --------------------------------------------------------------------------- #
# Document integration
# --------------------------------------------------------------------------- #

def _normalized_pointer(site_pointer: str) -> str:
    suffix = "/value"
    if site_pointer.endswith(suffix):
        return site_pointer[: -len(suffix)]
    return site_pointer


def run_semantic_checks(document: Dict[str, Any], report: Report, registry=None) -> None:
    """Apply semantic invariants to every embedded example and finite link.

    The canonical JSON Schema validator is reused as the gate: an example that
    does not match its published schema is left to the dedicated example check
    instead of producing semantic noise.
    """
    # Imported lazily to avoid a module import cycle with examples.py.
    from .examples import iter_example_sites, resolve_example_value

    example_check = report.check(
        "OAS-SEM-001",
        "Every embedded example satisfies semantic consistency invariants",
    )
    link_check = report.check(
        "OAS-SEM-002",
        "Finite explicit example links are mutually consistent",
    )
    rule_set_check = report.check(
        "OAS-SEM-003",
        "One rule_set_id always denotes the same company and members",
    )

    index: Dict[str, Any] = {}
    rule_sets: List[Dict[str, Any]] = []
    checked = 0
    for site in iter_example_sites(document):
        value, error = resolve_example_value(document, site)
        if error is not None:
            continue
        index[_normalized_pointer(site.pointer)] = value
        _collect_rule_sets(value, rule_sets)
        if registry is not None:
            try:
                schema_failed = bool(validate_value(registry, site.schema_pointer, value))
            except Exception:
                # A broken reference graph is reported by the structural checks;
                # it must not abort the semantic pass.
                schema_failed = False
            if schema_failed:
                # Shape failures are reported by the canonical example check.
                continue
        checked += 1
        for message in semantic_errors(value, site.schema_pointer):
            example_check.add(message, site.pointer)
    report.semantics_checked = checked

    for message in rule_set_consistency_errors(rule_sets):
        rule_set_check.add(message)

    for spec in finite_links():
        source = index.get(spec.source, _MISSING)
        target = index.get(spec.target, _MISSING)
        if source is _MISSING:
            link_check.add(
                f"{spec.name}: declared source example {spec.source} is missing",
                spec.source,
            )
            continue
        if target is _MISSING:
            link_check.add(
                f"{spec.name}: declared target example {spec.target} is missing",
                spec.target,
            )
            continue
        for message in link_errors(source, target, spec.fields, spec.name):
            link_check.add(message, spec.target)
