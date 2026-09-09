"""Pure matching and planning rules for Wise Way.

This module deliberately has no persistence or filesystem access.  Callers pass
the target-existence and logical-location adapters that bind these rules to a
specific storage implementation.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any


Location = dict[str, Any]
Rule = dict[str, Any]


def extension(filename: str) -> str:
    """Return the last preserved filename suffix under the Wise Way rules."""
    last_dot = filename.rfind(".")
    if last_dot <= 0 or last_dot == len(filename) - 1:
        return ""
    return filename[last_dot:]


def match_rule(rule: Rule, relative_path: str) -> bool:
    """Return whether a whole-string, case-insensitive rule mask matches."""
    mask = str(rule["mask"])
    if "**" in mask:
        return False

    if rule["match_field"] == "BASENAME":
        value = relative_path.replace("\\", "/").rsplit("/", 1)[-1]
    else:
        value = _normalise_match_path(relative_path)
        mask = _normalise_match_path(mask)

    return _match_glob(mask.casefold(), value.casefold())


def _match_glob(mask: str, value: str) -> bool:
    """Match the supported glob language without compiling a backtracking regex."""
    mask_index = value_index = 0
    last_star = -1
    retry_value = 0
    while value_index < len(value):
        if mask_index < len(mask) and (mask[mask_index] == "?" or mask[mask_index] == value[value_index]):
            mask_index += 1
            value_index += 1
        elif mask_index < len(mask) and mask[mask_index] == "*":
            last_star = mask_index
            mask_index += 1
            retry_value = value_index
        elif last_star >= 0:
            mask_index = last_star + 1
            retry_value += 1
            value_index = retry_value
        else:
            return False
    return all(char == "*" for char in mask[mask_index:])


def plan_rows(
    items: list[dict[str, Any]],
    rules: list[Rule],
    manual_target: dict[str, str],
    exists: Callable[[dict[str, str]], bool],
    *,
    location: Callable[[str, str], Location] | None = None,
    source_info: Callable[[dict[str, str]], dict[str, Any] | None] | None = None,
) -> list[dict[str, Any]]:
    """Build contract-shaped plan rows without doing filesystem operations.

    ``exists`` receives a target Location. ``source_info`` can optionally add
    metadata for an existing target to the collision object.
    """
    make_location = location or _default_location
    rows: list[dict[str, Any]] = []
    for item in items:
        rows.append(_plan_one(item, rules, manual_target, make_location))

    _apply_manual_review_collisions(rows, manual_target, exists, make_location, source_info)
    _apply_target_collisions(rows, exists, source_info)
    for row in rows:
        row.pop("_source_metadata", None)
    return rows


def plan_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Count primary predictions plus the two separate publication reasons."""
    counts = {
        "will_move": 0,
        "will_manual_review": 0,
        "requires_decision": 0,
        "not_ready": 0,
        "rule_conflicts": 0,
        "no_scenario": 0,
    }
    state_keys = {
        "WILL_MOVE": "will_move",
        "WILL_MANUAL_REVIEW": "will_manual_review",
        "REQUIRES_DECISION": "requires_decision",
        "NOT_READY": "not_ready",
    }
    for row in rows:
        counts[state_keys[row["predicted_state"]]] += 1
        is_manual_candidate = row["selected_rule"] is None and row["predicted_state"] != "NOT_READY"
        if is_manual_candidate and len(row["matched_rules"]) >= 2:
            counts["rule_conflicts"] += 1
        elif is_manual_candidate and not row["matched_rules"]:
            counts["no_scenario"] += 1
    return counts


def _plan_one(
    item: dict[str, Any],
    rules: list[Rule],
    manual_target: dict[str, str],
    make_location: Callable[[str, str], Location],
) -> dict[str, Any]:
    base = {
        "item_id": item["item_id"],
        "item_revision": item["item_revision"],
        "source": item["source"],
        "filename": item["filename"],
        "company_id": item["company_id"],
        "predicted_state": "NOT_READY",
        "reason_code": "NOT_READY",
        "target": None,
        "matched_rules": [],
        "selected_rule": None,
        "collision": None,
        "_source_metadata": {
            "filename": item["filename"],
            "location": item["source"],
            "size_bytes": item["size_bytes"],
            "modified_at": item["modified_at"],
        },
    }
    if item["status"] not in {"READY", "REQUIRES_DECISION"} or not item["selectable"]:
        return base

    matching_rules = [
        candidate for candidate in rules if match_rule(candidate, item["source"]["relative_path"])
    ]
    if not matching_rules:
        return _with_state(base, "WILL_MANUAL_REVIEW", "NO_SCENARIO")

    minimum_priority = min(candidate["priority"] for candidate in matching_rules)
    winners = [candidate for candidate in matching_rules if candidate["priority"] == minimum_priority]
    base["matched_rules"] = [_reference(candidate) for candidate in winners]
    target_tuples = {
        _target_tuple(candidate["target"], candidate["target_stem"], item["filename"])
        for candidate in winners
    }
    if len(target_tuples) != 1:
        return _with_state(base, "WILL_MANUAL_REVIEW", "RULE_CONFLICT")

    selected = min(winners, key=lambda candidate: (candidate["dictionary_id"], candidate["rule_id"]))
    root_id, relative_path = next(iter(target_tuples))
    base["predicted_state"] = "WILL_MOVE"
    base["reason_code"] = None
    base["target"] = make_location(root_id, relative_path)
    base["selected_rule"] = _reference(selected)
    return base


def _apply_manual_review_collisions(
    rows: list[dict[str, Any]],
    manual_target: dict[str, str],
    exists: Callable[[dict[str, str]], bool],
    make_location: Callable[[str, str], Location],
    source_info: Callable[[dict[str, str]], dict[str, Any] | None] | None,
) -> None:
    for row in rows:
        if row["predicted_state"] != "WILL_MANUAL_REVIEW":
            continue
        target = make_location(
            manual_target["root_id"], _join(manual_target["relative_directory"], row["filename"])
        )
        if exists(target):
            _block(row, "MANUAL_REVIEW_NAME_OCCUPIED", "MANUAL_REVIEW_NAME", target, [], source_info)


def _apply_target_collisions(
    rows: list[dict[str, Any]],
    exists: Callable[[dict[str, str]], bool],
    source_info: Callable[[dict[str, str]], dict[str, Any] | None] | None,
) -> None:
    planned: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["predicted_state"] == "WILL_MOVE":
            target = row["target"]
            planned[(target["root_id"], target["relative_path"])].append(row)

    for matching_rows in planned.values():
        target = matching_rows[0]["target"]
        if len(matching_rows) > 1:
            for row in matching_rows:
                others = [other["item_id"] for other in matching_rows if other is not row]
                _block(row, "TARGET_OCCUPIED", "DUPLICATE_PLAN_TARGET", target, others, source_info)
        elif exists(target):
            _block(matching_rows[0], "TARGET_OCCUPIED", "EXISTING_TARGET", target, [], source_info)


def _block(
    row: dict[str, Any],
    reason_code: str,
    kind: str,
    target: Location,
    conflicting_item_ids: list[str],
    source_info: Callable[[dict[str, str]], dict[str, Any] | None] | None,
) -> None:
    row["predicted_state"] = "REQUIRES_DECISION"
    row["reason_code"] = reason_code
    row["collision"] = {
        "kind": kind,
        "source_metadata": row["_source_metadata"],
        "existing_target_metadata": source_info(target)
        if source_info and kind != "DUPLICATE_PLAN_TARGET"
        else None,
        "conflicting_item_ids": conflicting_item_ids,
    }


def _reference(rule: Rule) -> dict[str, Any]:
    return {key: rule[key] for key in ("dictionary_id", "version_id", "rule_id")}


def _target_tuple(target: dict[str, str], target_stem: str, filename: str) -> tuple[str, str]:
    return target["root_id"], _join(target["relative_directory"], target_stem + extension(filename))


def _with_state(row: dict[str, Any], state: str, reason: str) -> dict[str, Any]:
    row["predicted_state"] = state
    row["reason_code"] = reason
    return row


def _normalise_match_path(value: str) -> str:
    return value.replace("/", "\\")


def _join(directory: str, filename: str) -> str:
    return f"{directory.rstrip('/')}/{filename}" if directory else filename


def _default_location(root_id: str, relative_path: str) -> Location:
    return {"root_id": root_id, "relative_path": relative_path, "display_path": f"{root_id}:/{relative_path}"}
