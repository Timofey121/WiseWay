"""LT-03.2b finite dictionary lifecycle oracle for the WiseWay synthetic demo.

``fixtures/synthetic/dictionary_lifecycle.json`` stores the finite, hand-authored
oracle for the dictionary draft/simulation/publication/history/restore flow that
DICT-08...12, API section 6 and Q-016...021/029 describe.  It builds directly on
the immutable definitions of ``rule_expectations.json`` (the three published
versions and the explicitly separated scenario-role universes) and the auth
fixture actors.

The module is a *materializer and consistency checker*, not a runtime domain:

* every request, response and error body is literal data;
* no matcher, priority selection, target-name derivation, revision bump or
  count is computed here - the values are declared and then cross-checked;
* the only helper mirrors the documented DICT-05 suffix rule so that a
  target basename can be verified against its fixed stem, exactly like the
  LT-03.2a oracle already does.

A documented preparation command regenerates the committed public examples::

    python tests/contract/contractlib/dictionary_lifecycle.py --write-examples
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # package import (tests, verify_contract.py)
    from . import rule_expectations, synthetic
    from .expectations import EXPECTED_OPERATIONS
    from .schemas import validate_value
    from .search_expectations import allowed_error_codes
except ImportError:  # pragma: no cover - documented direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from contractlib import rule_expectations, synthetic  # type: ignore
    from contractlib.expectations import EXPECTED_OPERATIONS  # type: ignore
    from contractlib.schemas import validate_value  # type: ignore
    from contractlib.search_expectations import allowed_error_codes  # type: ignore

EXPECTATIONS_RELATIVE = Path("fixtures") / "synthetic" / "dictionary_lifecycle.json"

DICTIONARY_SCHEMA = "#/components/schemas/Dictionary"
DICTIONARY_LIST_SCHEMA = "#/components/schemas/DictionaryListResponse"
DICTIONARY_VERSION_SCHEMA = "#/components/schemas/DictionaryVersion"
PAGE_VERSION_SCHEMA = "#/components/schemas/PageDictionaryVersion"
RULE_SET_SCHEMA = "#/components/schemas/RuleSet"
SIMULATION_SCHEMA = "#/components/schemas/Simulation"
PLAN_ROW_SCHEMA = "#/components/schemas/PlanRow"
PUBLISH_SCHEMA = "#/components/schemas/PublishedDictionaryResponse"
ERROR_SCHEMA = "#/components/schemas/ErrorResponse"

KNOWN_Q = ("Q-016", "Q-017", "Q-018", "Q-019", "Q-020", "Q-021", "Q-029")
KNOWN_OPERATIONS = set(EXPECTED_OPERATIONS.values())
PUBLISH_OPERATION = "publishDictionary"

_ERROR_MESSAGES = {
    "DRAFT_VERSION_CONFLICT": "Черновик изменён другим пользователем. Перечитайте его и сравните ввод.",
    "DICTIONARY_NAME_CONFLICT": "Справочник с таким названием уже существует в компании.",
    "STALE_SIMULATION": "Результат теста устарел. Выполните проверку повторно.",
    "NO_SCENARIO_ACK_REQUIRED": "Есть файлы без сценария. Подтвердите результат теста.",
    "RULE_CONFLICT": "Обнаружен конфликт правил. Публикация заблокирована.",
    "IDEMPOTENCY_KEY_REUSED": "Ключ идемпотентности уже использован с другим телом запроса.",
    "VALIDATION_ERROR": "Проверьте значения полей запроса.",
    "NOT_FOUND": "Объект не найден.",
    "INVALID_TARGET": "Целевой каталог отсутствует или недопустим.",
}

# (example id, kind, binding, canonical schema, output file, description).
EXAMPLE_BINDINGS: List[Dict[str, str]] = [
    {
        "id": "dictionary-atlas-cleanup-created",
        "kind": "dictionary",
        "binding": "state-atlas-cleanup-created",
        "schema": DICTIONARY_SCHEMA,
        "file": "contracts/examples/dictionaries/dictionary-atlas-cleanup-created.json",
        "description": "New Atlas dictionary created with an empty draft revision 0.",
    },
    {
        "id": "dictionary-atlas-cleanup-saved",
        "kind": "dictionary",
        "binding": "state-atlas-cleanup-saved",
        "schema": DICTIONARY_SCHEMA,
        "file": "contracts/examples/dictionaries/dictionary-atlas-cleanup-saved.json",
        "description": "Saved Atlas cleanup draft: expected revision 0 became revision 1.",
    },
    {
        "id": "dictionary-atlas-general-rev2",
        "kind": "dictionary",
        "binding": "state-atlas-general-rev2",
        "schema": DICTIONARY_SCHEMA,
        "file": "contracts/examples/dictionaries/dictionary-atlas-general-rev2.json",
        "description": "Shared Atlas general draft after a successful save (revision 1 -> 2).",
    },
    {
        "id": "dictionary-atlas-general-published-v2",
        "kind": "dictionary",
        "binding": "state-atlas-general-published-v2",
        "schema": DICTIONARY_SCHEMA,
        "file": "contracts/examples/dictionaries/dictionary-atlas-general-published-v2.json",
        "description": "Atlas general dictionary after publishing version 2 (history 1 -> 2).",
    },
    {
        "id": "dictionary-atlas-general-restored-v1",
        "kind": "dictionary",
        "binding": "state-atlas-general-restored-v1",
        "schema": DICTIONARY_SCHEMA,
        "file": "contracts/examples/dictionaries/dictionary-atlas-general-restored-v1.json",
        "description": "Atlas general draft restored from version 1, based_on_version_id set.",
    },
    {
        "id": "dictionary-atlas-general-manual-edit",
        "kind": "dictionary",
        "binding": "state-atlas-general-manual-edit",
        "schema": DICTIONARY_SCHEMA,
        "file": "contracts/examples/dictionaries/dictionary-atlas-general-manual-edit.json",
        "description": "Manual edit after restore clears based_on_version_id.",
    },
    {
        "id": "dictionary-atlas-general-published-v3",
        "kind": "dictionary",
        "binding": "state-atlas-general-published-v3",
        "schema": DICTIONARY_SCHEMA,
        "file": "contracts/examples/dictionaries/dictionary-atlas-general-published-v3.json",
        "description": "Atlas general dictionary after publishing the restored version 3.",
    },
    {
        "id": "dictionary-nova-scope-created",
        "kind": "dictionary",
        "binding": "state-nova-scope-created",
        "schema": DICTIONARY_SCHEMA,
        "file": "contracts/examples/dictionaries/dictionary-nova-scope-created.json",
        "description": "The same name is allowed in another company: no cross-company conflict.",
    },
    {
        "id": "dictionary-atlas-general-list",
        "kind": "dictionary_list",
        "binding": "dictionary-list-atlas",
        "schema": DICTIONARY_LIST_SCHEMA,
        "file": "contracts/examples/dictionaries/dictionary-list-atlas.json",
        "description": "Atlas dictionary list at the base state (general + invoices).",
    },
    {
        "id": "version-atlas-general-v2",
        "kind": "version",
        "binding": "version-atlas-general-v2",
        "schema": DICTIONARY_VERSION_SCHEMA,
        "file": "contracts/examples/dictionaries/version-atlas-general-v2.json",
        "description": "Immutable published Atlas general version 2.",
    },
    {
        "id": "version-atlas-general-v3",
        "kind": "version",
        "binding": "version-atlas-general-v3",
        "schema": DICTIONARY_VERSION_SCHEMA,
        "file": "contracts/examples/dictionaries/version-atlas-general-v3.json",
        "description": "Immutable published Atlas general version 3 restored from version 1.",
    },
    {
        "id": "versions-atlas-general",
        "kind": "page_versions",
        "binding": "page-atlas-general-versions",
        "schema": PAGE_VERSION_SCHEMA,
        "file": "contracts/examples/dictionaries/versions-atlas-general.json",
        "description": "Atlas general published history page: v3, v2, v1.",
    },
    {
        "id": "rule-set-atlas-v2",
        "kind": "rule_set",
        "binding": "rule-set-atlas-v2",
        "schema": RULE_SET_SCHEMA,
        "file": "contracts/examples/dictionaries/rule-set-atlas-v2.json",
        "description": "Full active Atlas RuleSet after publishing general version 2.",
    },
    {
        "id": "rule-set-atlas-v3",
        "kind": "rule_set",
        "binding": "rule-set-atlas-v3",
        "schema": RULE_SET_SCHEMA,
        "file": "contracts/examples/dictionaries/rule-set-atlas-v3.json",
        "description": "Full active Atlas RuleSet after publishing the restored version 3.",
    },
    {
        "id": "simulation-atlas-full-page1",
        "kind": "simulation",
        "binding": "page-atlas-full-1",
        "schema": SIMULATION_SCHEMA,
        "file": "contracts/examples/simulations/simulation-atlas-full-page1.json",
        "description": "Full READY simulation page 1: candidate + other dictionary + NO_SCENARIO.",
    },
    {
        "id": "simulation-atlas-full-page2",
        "kind": "simulation",
        "binding": "page-atlas-full-2",
        "schema": SIMULATION_SCHEMA,
        "file": "contracts/examples/simulations/simulation-atlas-full-page2.json",
        "description": "Full READY simulation page 2: the remaining hidden and occupied rows.",
    },
    {
        "id": "simulation-atlas-empty",
        "kind": "simulation",
        "binding": "page-atlas-empty",
        "schema": SIMULATION_SCHEMA,
        "file": "contracts/examples/simulations/simulation-atlas-empty.json",
        "description": "Zero READY items: valid EMPTY_READY_SET warning, total 0.",
    },
    {
        "id": "simulation-atlas-conflict",
        "kind": "simulation",
        "binding": "page-atlas-conflict",
        "schema": SIMULATION_SCHEMA,
        "file": "contracts/examples/simulations/simulation-atlas-conflict.json",
        "description": "Equal-priority rules with different targets: RULE_CONFLICT blocks publish.",
    },
    {
        "id": "simulation-atlas-same-target",
        "kind": "simulation",
        "binding": "page-atlas-same-target",
        "schema": SIMULATION_SCHEMA,
        "file": "contracts/examples/simulations/simulation-atlas-same-target.json",
        "description": "Equal-priority rules with the same final target: not a conflict.",
    },
    {
        "id": "simulation-atlas-v3-restored",
        "kind": "simulation",
        "binding": "page-atlas-v3-restored",
        "schema": SIMULATION_SCHEMA,
        "file": "contracts/examples/simulations/simulation-atlas-v3-restored.json",
        "description": "Simulation of the restored version 1 content over the same full READY set.",
    },
    {
        "id": "publish-atlas-general-v2",
        "kind": "publish",
        "binding": "publish-atlas-general-v2",
        "schema": PUBLISH_SCHEMA,
        "file": "contracts/examples/dictionaries/publish-atlas-general-v2.json",
        "description": "Accepted publication of Atlas general version 2 and the full RuleSet.",
    },
    {
        "id": "publish-atlas-general-v3",
        "kind": "publish",
        "binding": "publish-atlas-general-v3",
        "schema": PUBLISH_SCHEMA,
        "file": "contracts/examples/dictionaries/publish-atlas-general-v3.json",
        "description": "Accepted publication of the restored version 3 with restored_from_version_id.",
    },
    {
        "id": "error-draft-version-conflict",
        "kind": "error",
        "binding": "save-stale-revision-worker-two",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-draft-version-conflict.json",
        "description": "409 DRAFT_VERSION_CONFLICT for a stale shared draft revision.",
    },
    {
        "id": "error-dictionary-name-conflict",
        "kind": "error",
        "binding": "create-name-conflict-trim-casefold",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-dictionary-name-conflict.json",
        "description": "409 DICTIONARY_NAME_CONFLICT after trim+casefold.",
    },
    {
        "id": "error-stale-simulation",
        "kind": "error",
        "binding": "publish-stale-simulation-ruleset",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-stale-simulation.json",
        "description": "409 STALE_SIMULATION after another RuleSet member changed.",
    },
    {
        "id": "error-no-scenario-ack-required",
        "kind": "error",
        "binding": "publish-no-scenario-no-ack",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-no-scenario-ack-required.json",
        "description": "409 NO_SCENARIO_ACK_REQUIRED for a test containing NO_SCENARIO.",
    },
    {
        "id": "error-rule-conflict",
        "kind": "error",
        "binding": "publish-conflict-blocked",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-rule-conflict.json",
        "description": "409 RULE_CONFLICT blocks publication.",
    },
    {
        "id": "error-idempotency-key-reused",
        "kind": "error",
        "binding": "publish-idempotency-altered-body",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-idempotency-key-reused.json",
        "description": "409 IDEMPOTENCY_KEY_REUSED for the same key with a different body.",
    },
]


# --------------------------------------------------------------------------- #
# Loading and normalization
# --------------------------------------------------------------------------- #

def expectations_path(root: Optional[Path] = None) -> Path:
    return (root or synthetic.repo_root()) / EXPECTATIONS_RELATIVE


def load_expectations(root: Optional[Path] = None) -> Dict[str, Any]:
    return synthetic.load_json(expectations_path(root))


def _actor_payload(context: Dict[str, Any], actor_key: str) -> Dict[str, Any]:
    aliases = context["actor_aliases"]
    actor_id = aliases.get(actor_key, actor_key)
    actor = context["actors"].get(actor_id)
    if actor is None:
        raise KeyError(f"unknown synthetic actor {actor_key!r}")
    return dict(actor)


def _normalize_rule_versions(rule_exp: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    versions: Dict[str, Dict[str, Any]] = {}
    dictionaries = {
        entry["dictionary_id"]: entry for entry in rule_exp["dictionaries"]
    }
    for version in rule_exp["versions"]:
        dictionary = dictionaries[version["dictionary_id"]]
        versions[version["version_id"]] = {
            "version_id": version["version_id"],
            "dictionary_id": version["dictionary_id"],
            "version_number": version["version_number"],
            "role": version["role"],
            "rules": version["rules"],
            "published_at": "2031-05-10T09:30:00Z",
            "published_by": dictionary["updated_by"],
            "comment": "Синтетическая неизменяемая версия.",
            "restored_from_version_id": None,
            "origin": "rule-expectations",
        }
    return versions


def _normalize_lifecycle_versions(
    expectations: Dict[str, Any]
) -> Dict[str, Dict[str, Any]]:
    versions: Dict[str, Dict[str, Any]] = {}
    for version in expectations.get("versions", []):
        versions[version["version_id"]] = {
            "version_id": version["version_id"],
            "dictionary_id": version["dictionary_id"],
            "version_number": version["version_number"],
            "role": version["role"],
            "rules": version["rules"],
            "published_at": version.get("published_at", "2031-05-10T09:30:00Z"),
            "published_by": version["published_by"],
            "comment": version.get("comment", "Синтетическая неизменяемая версия."),
            "restored_from_version_id": version.get("restored_from_version_id"),
            "origin": "dictionary-lifecycle",
        }
    return versions


def build_context(
    root: Optional[Path] = None, expectations: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Load the lifecycle fixture plus the LT-03.2a definitions it builds on."""
    base = Path(root) if root is not None else synthetic.repo_root()
    if expectations is None:
        expectations = load_expectations(base)
    rule_exp = rule_expectations.load_expectations(base)
    rule_context = rule_expectations.build_context(base, rule_exp)

    context: Dict[str, Any] = {
        "base": base,
        "document": rule_context["document"],
        "expectations": expectations,
        "rule_expectations": rule_exp,
        "rule_context": rule_context,
        "actors": rule_context["actors"],
        "actor_aliases": expectations["actors"],
        "prefix": expectations["target_display_prefix"],
        "targets": rule_context["targets"],
        "sources": rule_context["sources"],
    }

    companies: Dict[str, Dict[str, Any]] = {}
    for entry in rule_exp["companies"]:
        companies[entry["company_id"]] = entry
    context["companies"] = companies

    dictionaries: Dict[str, Dict[str, Any]] = {}
    for entry in rule_exp["dictionaries"]:
        dictionaries[entry["dictionary_id"]] = {
            "dictionary_id": entry["dictionary_id"],
            "company_id": entry["company_id"],
            "name": entry["name"],
            "description": entry["description"],
            "updated_by": entry["updated_by"],
            "base_version_id": entry["active_version_id"],
        }
    for entry in expectations.get("dictionaries", []):
        dictionaries[entry["dictionary_id"]] = dict(entry)
    context["dictionaries"] = dictionaries

    versions = _normalize_rule_versions(rule_exp)
    versions.update(_normalize_lifecycle_versions(expectations))
    context["versions"] = versions

    rule_sets: Dict[str, Dict[str, Any]] = {}
    for entry in rule_exp["rule_sets"]:
        rule_sets[entry["rule_set_id"]] = {
            "rule_set_id": entry["rule_set_id"],
            "company_id": entry["company_id"],
            "role": entry.get("role", "published"),
            "members": entry["members"],
        }
    for entry in expectations.get("rule_sets", []):
        rule_sets[entry["rule_set_id"]] = {
            "rule_set_id": entry["rule_set_id"],
            "company_id": entry["company_id"],
            "role": entry.get("role", "published"),
            "members": entry["members"],
        }
    context["rule_sets"] = rule_sets

    context["states"] = {
        entry["state_id"]: entry for entry in expectations.get("states", [])
    }
    context["ready_sets"] = {
        entry["ready_set_id"]: entry for entry in expectations.get("ready_sets", [])
    }
    ready_items: Dict[str, Dict[str, Any]] = {}
    for ready_set in context["ready_sets"].values():
        for member in ready_set["members"]:
            item = dict(member)
            item["company_id"] = ready_set["company_id"]
            item["ready_set_id"] = ready_set["ready_set_id"]
            ready_items[item["item_id"]] = item
    context["ready_items"] = ready_items
    context["simulations"] = {
        entry["page_id"]: entry for entry in expectations.get("simulations", [])
    }
    context["publishes"] = {
        entry["publish_id"]: entry for entry in expectations.get("publishes", [])
    }
    context["failures"] = {
        entry["failure_id"]: entry for entry in expectations.get("failures", [])
    }
    context["replays"] = {
        entry["replay_id"]: entry for entry in expectations.get("replays", [])
    }
    context["version_pages"] = {
        entry["page_id"]: entry for entry in expectations.get("version_pages", [])
    }
    context["dictionary_lists"] = {
        entry["list_id"]: entry for entry in expectations.get("dictionary_lists", [])
    }
    return context


# --------------------------------------------------------------------------- #
# Materialization (literal ids only, never a runtime domain)
# --------------------------------------------------------------------------- #

def materialize_rule(rule_entry: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    return rule_expectations.materialize_rule(rule_entry, context)


def materialize_version(
    version: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    dictionary = context["dictionaries"][version["dictionary_id"]]
    return {
        "version_id": version["version_id"],
        "dictionary_id": version["dictionary_id"],
        "version_number": version["version_number"],
        "name": version.get("name", dictionary["name"]),
        "description": version.get("description", dictionary["description"]),
        "rules": [materialize_rule(rule, context) for rule in version["rules"]],
        "published_at": version["published_at"],
        "published_by": _actor_payload(context, version["published_by"]),
        "comment": version["comment"],
        "restored_from_version_id": version["restored_from_version_id"],
    }


def _state_rules(state: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    if "rules" in state:
        return state["rules"]
    return context["versions"][state["rules_version_id"]]["rules"]


def materialize_dictionary(
    state: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    dictionary = context["dictionaries"][state["dictionary_id"]]
    return {
        "dictionary_id": state["dictionary_id"],
        "company_id": dictionary["company_id"],
        "name": state.get("name", dictionary["name"]),
        "description": state.get("description", dictionary["description"]),
        "draft": {
            "draft_revision": state["draft_revision"],
            "rules": [
                materialize_rule(rule, context)
                for rule in _state_rules(state, context)
            ],
            "based_on_version_id": state.get("based_on_version_id"),
        },
        "active_version_id": state.get("active_version_id"),
        "versions_count": len(state.get("history", [])),
        "updated_at": state["updated_at"],
        "updated_by": _actor_payload(context, state["updated_by"]),
    }


def materialize_rule_set(
    entry: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    return {
        "rule_set_id": entry["rule_set_id"],
        "company_id": entry["company_id"],
        "members": [
            {
                "dictionary_id": member["dictionary_id"],
                "version_id": member["version_id"],
            }
            for member in entry["members"]
        ],
    }


def materialize_plan_row(
    row: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    item = context["ready_items"][row["item_id"]]
    return {
        "item_id": item["item_id"],
        "item_revision": item["item_revision"],
        "source": item["location"],
        "filename": item["filename"],
        "company_id": item["company_id"],
        "predicted_state": row["predicted_state"],
        "reason_code": row.get("reason_code"),
        "target": row.get("target"),
        "matched_rules": [dict(reference) for reference in row.get("matched_rules", [])],
        "selected_rule": (
            dict(row["selected_rule"]) if row.get("selected_rule") else None
        ),
        "collision": row.get("collision"),
    }


def materialize_simulation(
    entry: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    ready_set = context["ready_sets"][entry["ready_set_id"]]
    return {
        "simulation_id": entry["simulation_id"],
        "dictionary_id": entry["dictionary_id"],
        "draft_revision": entry["draft_revision"],
        "base_rule_set": materialize_rule_set(
            context["rule_sets"][entry["base_rule_set_id"]], context
        ),
        "ready_snapshot_id": ready_set["snapshot_id"],
        "created_at": entry["created_at"],
        "expires_at": entry["expires_at"],
        "total": entry["total"],
        "counts": dict(entry["counts"]),
        "warnings": list(entry.get("warnings", [])),
        "rows": [
            materialize_plan_row(row, context) for row in entry.get("rows", [])
        ],
        "next_cursor": entry.get("next_cursor"),
    }


def materialize_publish(
    entry: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    return {
        "dictionary": materialize_dictionary(
            context["states"][entry["after_state"]], context
        ),
        "published_version": materialize_version(
            context["versions"][entry["published_version_id"]], context
        ),
        "rule_set": materialize_rule_set(
            context["rule_sets"][entry["rule_set_id"]], context
        ),
    }


def materialize_page_versions(
    entry: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    return {
        "items": [
            materialize_version(context["versions"][version_id], context)
            for version_id in entry["items"]
        ],
        "next_cursor": entry.get("next_cursor"),
    }


def materialize_dictionary_list(
    entry: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    return {
        "items": [
            materialize_dictionary(context["states"][state_id], context)
            for state_id in entry["states"]
        ]
    }


def materialize_request(
    entry: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    """Expand the documented ``$repeat``/``target_id`` shorthand in a request."""
    request = rule_expectations._expand(dict(entry["request"]))
    if isinstance(request.get("rules"), list):
        request["rules"] = [
            materialize_rule(rule, context) for rule in request["rules"]
        ]
    return request


def materialize_error(entry: Dict[str, Any]) -> Dict[str, Any]:
    expected = entry["expected"]
    return {
        "error": {
            "code": expected["code"],
            "message": _ERROR_MESSAGES.get(expected["code"], "Ошибка запроса."),
            "request_id": "request-demo-1",
            "operation_id": expected.get("operation_id"),
            "retryable": expected.get("retryable", False),
            "field_errors": list(expected.get("field_errors", [])),
        }
    }


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

def _last_suffix(filename: str) -> str:
    """The DICT-05 last extension suffix (``.env``/``README``/``name.`` have none)."""
    dot = filename.rfind(".")
    if dot <= 0 or dot == len(filename) - 1:
        return ""
    return filename[dot:]


def _request_schema_pointer(document: Dict[str, Any], operation: str) -> Optional[str]:
    for (method, path), candidate in EXPECTED_OPERATIONS.items():
        if candidate != operation:
            continue
        node = document.get("paths", {}).get(path, {}).get(method, {})
        body = node.get("requestBody")
        if not isinstance(body, dict):
            return None
        schema = ((body.get("content") or {}).get("application/json") or {}).get(
            "schema"
        )
        if isinstance(schema, dict) and set(schema.keys()) == {"$ref"}:
            return schema["$ref"]
        return None
    return None


def _resolve_rule(
    reference: Dict[str, Any], context: Dict[str, Any], candidate_version_id: str
) -> Optional[Dict[str, Any]]:
    version_id = reference.get("version_id") or candidate_version_id
    version = context["versions"].get(version_id)
    if version is None:
        return None
    for rule in version["rules"]:
        if rule["rule_id"] == reference.get("rule_id"):
            return rule
    return None


def _scenario_errors(entry: Dict[str, Any], known: set) -> List[str]:
    label = (
        entry.get("step_id")
        or entry.get("failure_id")
        or entry.get("replay_id")
        or "scenario"
    )
    errors: List[str] = []
    if label in known:
        errors.append(f"duplicate scenario id {label!r}")
    known.add(label)
    q_ids = entry.get("q_ids") or []
    if not q_ids:
        errors.append(f"{label}: q_ids must not be empty")
    for q in q_ids:
        if q not in KNOWN_Q:
            errors.append(f"{label}: unknown Q id {q!r}")
    if not entry.get("reason"):
        errors.append(f"{label}: reason (manual trace) must not be empty")
    return errors


def _active_version_for_dictionary(
    context: Dict[str, Any], dictionary_id: str
) -> Optional[Dict[str, Any]]:
    for state in context["states"].values():
        if state["dictionary_id"] == dictionary_id and state.get("active_version_id"):
            version = context["versions"].get(state["active_version_id"])
            if version is not None:
                return version
    return None


def _target_errors(
    label: str,
    item: Dict[str, Any],
    rule: Dict[str, Any],
    target: Dict[str, Any],
    context: Dict[str, Any],
) -> List[str]:
    errors: List[str] = []
    declared = context["targets"][rule["target_id"]]
    relative_path = target.get("relative_path", "")
    directory = relative_path.rsplit("/", 1)[0]
    if target.get("root_id") != declared["root_id"] or directory != declared[
        "relative_directory"
    ]:
        errors.append(f"{label}: target is not the selected rule's configured directory")
    if target.get("display_path") != context["prefix"] + "/" + relative_path:
        errors.append(f"{label}: target display_path does not match the prefix")
    basename = relative_path.rsplit("/", 1)[-1]
    expected = rule["target_stem"] + _last_suffix(item["filename"])
    if basename != expected:
        errors.append(
            f"{label}: target basename {basename!r} != stem+suffix {expected!r}"
        )
    return errors


def _plan_row_errors(
    label: str,
    row: Dict[str, Any],
    context: Dict[str, Any],
    company_id: str,
    candidate_dictionary_id: str,
    candidate_version_id: Optional[str],
) -> List[str]:
    errors: List[str] = []
    item = context["ready_items"].get(row.get("item_id"))
    if item is None:
        return [f"{label}: row references unknown READY item {row.get('item_id')!r}"]
    if item["company_id"] != company_id:
        errors.append(f"{label}: row item belongs to another company")
    references = list(row.get("matched_rules") or [])
    selected = row.get("selected_rule")
    if isinstance(selected, dict) and selected not in references:
        errors.append(f"{label}: selected_rule is not one of matched_rules")
    for reference in references + ([selected] if isinstance(selected, dict) else []):
        if not isinstance(reference, dict):
            continue
        version_id = reference.get("version_id")
        if version_id is None and reference.get("dictionary_id") != candidate_dictionary_id:
            errors.append(
                f"{label}: null version_id must point at the candidate dictionary"
            )
        rule = _resolve_rule(reference, context, candidate_version_id or "")
        if rule is None:
            errors.append(
                f"{label}: undefined rule reference {reference.get('rule_id')!r}"
            )
    predicted = row.get("predicted_state")
    reason = row.get("reason_code")
    if predicted == "WILL_MOVE":
        if reason is not None:
            errors.append(f"{label}: WILL_MOVE must have a null reason_code")
        if not isinstance(selected, dict):
            errors.append(f"{label}: WILL_MOVE must select a rule")
        target = row.get("target")
        if not isinstance(target, dict):
            errors.append(f"{label}: WILL_MOVE must carry a target")
        elif isinstance(selected, dict):
            rule = _resolve_rule(selected, context, candidate_version_id or "")
            if rule is not None:
                errors.extend(_target_errors(label, item, rule, target, context))
    elif predicted == "WILL_MANUAL_REVIEW":
        if reason not in ("NO_SCENARIO", "RULE_CONFLICT"):
            errors.append(f"{label}: manual review must be NO_SCENARIO or RULE_CONFLICT")
        if row.get("target") is not None:
            errors.append(f"{label}: manual review must not carry a target")
        if reason == "NO_SCENARIO":
            if references or selected is not None:
                errors.append(f"{label}: NO_SCENARIO must not match any rule")
        if reason == "RULE_CONFLICT":
            if len(references) < 2:
                errors.append(f"{label}: RULE_CONFLICT needs at least two matched rules")
            if selected is not None:
                errors.append(f"{label}: RULE_CONFLICT must not select a rule")
    elif predicted == "REQUIRES_DECISION":
        if reason != "TARGET_OCCUPIED":
            errors.append(f"{label}: REQUIRES_DECISION reason must be TARGET_OCCUPIED")
        if not isinstance(row.get("collision"), dict):
            errors.append(f"{label}: REQUIRES_DECISION must carry collision details")
    return errors


def _simulation_errors(
    entry: Dict[str, Any],
    context: Dict[str, Any],
    simulation_id: str,
    pages: List[Dict[str, Any]],
) -> List[str]:
    errors: List[str] = []
    label = f"{simulation_id}/{entry['page_id']}"
    dictionary = context["dictionaries"].get(entry.get("dictionary_id"))
    if dictionary is None:
        return [f"{label}: unknown dictionary_id"]
    rule_set = context["rule_sets"].get(entry.get("base_rule_set_id"))
    if rule_set is None:
        errors.append(f"{label}: unknown base_rule_set_id")
        return errors
    if rule_set["company_id"] != dictionary["company_id"]:
        errors.append(f"{label}: base rule set belongs to another company")
    ready_set = context["ready_sets"].get(entry.get("ready_set_id"))
    if ready_set is None:
        errors.append(f"{label}: unknown ready_set_id")
        return errors
    if ready_set["company_id"] != dictionary["company_id"]:
        errors.append(f"{label}: ready set belongs to another company")
    if entry["total"] != len(ready_set["members"]):
        errors.append(
            f"{label}: total {entry['total']} does not cover the full READY set "
            f"({len(ready_set['members'])})"
        )
    counts = entry["counts"]
    first_four = (
        counts["will_move"]
        + counts["will_manual_review"]
        + counts["requires_decision"]
        + counts["not_ready"]
    )
    if first_four != entry["total"]:
        errors.append(f"{label}: the four main PlanCounts do not sum to total")
    if counts["rule_conflicts"] + counts["no_scenario"] > entry["total"]:
        errors.append(f"{label}: reason counts exceed total")
    if not entry.get("warnings") and ready_set["members"] == [] and entry["total"] == 0:
        errors.append(f"{label}: an empty READY set must warn EMPTY_READY_SET")

    # Every READY member appears exactly once across the pages.
    page_item_ids = [row["item_id"] for page in pages for row in page.get("rows", [])]
    ready_ids = [member["item_id"] for member in ready_set["members"]]
    if sorted(page_item_ids) != sorted(ready_ids):
        errors.append(f"{label}: pages do not cover exactly the READY membership")
    if len(page_item_ids) != len(set(page_item_ids)):
        errors.append(f"{label}: a READY item appears on more than one page")

    # All pages must describe the same immutable test.
    for page in pages:
        for key in (
            "dictionary_id",
            "draft_revision",
            "candidate_version_id",
            "base_rule_set_id",
            "ready_set_id",
            "universe",
            "created_at",
            "expires_at",
            "total",
            "counts",
        ):
            if page.get(key) != entry.get(key):
                errors.append(f"{label}: page {page['page_id']} disagrees on {key}")

    candidate_version_id = entry.get("candidate_version_id")
    candidate_version = context["versions"].get(candidate_version_id)
    if candidate_version is None:
        errors.append(f"{label}: unknown candidate_version_id")
    elif candidate_version["dictionary_id"] != entry["dictionary_id"]:
        errors.append(f"{label}: candidate_version_id belongs to another dictionary")
    base_members = {
        member["dictionary_id"]: member["version_id"] for member in rule_set["members"]
    }
    base_candidate = base_members.get(entry["dictionary_id"])
    if not entry.get("universe"):
        # The live base RuleSet holds the version currently being replaced; the
        # candidate draft (candidate_version_id) is not yet published.
        if base_candidate == candidate_version_id:
            errors.append(
                f"{label}: live base rule set already binds the candidate version"
            )
        elif base_candidate is not None:
            base_version = context["versions"].get(base_candidate)
            if base_version is None or base_version["role"] != "published":
                errors.append(
                    f"{label}: base rule set candidate member is not a published version"
                )
    for row in entry.get("rows", []):
        errors.extend(
            _plan_row_errors(
                label,
                row,
                context,
                dictionary["company_id"],
                entry["dictionary_id"],
                candidate_version_id,
            )
        )
    return errors


def _publish_errors(entry: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = entry.get("publish_id", "publish")
    if entry.get("operation") != PUBLISH_OPERATION:
        errors.append(f"{label}: operation must be {PUBLISH_OPERATION!r}")
    after = context["states"].get(entry.get("after_state"))
    before = context["states"].get(entry.get("before_state"))
    if after is None:
        errors.append(f"{label}: unknown after_state")
    if before is None:
        errors.append(f"{label}: unknown before_state")
    version = context["versions"].get(entry.get("published_version_id"))
    if version is None:
        errors.append(f"{label}: unknown published_version_id")
        return errors
    rule_set = context["rule_sets"].get(entry.get("rule_set_id"))
    if rule_set is None:
        errors.append(f"{label}: unknown rule_set_id")
        return errors
    if after is not None:
        if after.get("active_version_id") != version["version_id"]:
            errors.append(f"{label}: active_version_id is not the published version")
        if version["version_id"] not in after.get("history", []):
            errors.append(f"{label}: published version is not in the state history")
        if before is not None and len(after.get("history", [])) != len(
            before.get("history", [])
        ) + 1:
            errors.append(f"{label}: history did not grow by exactly the new version")
    if rule_set["company_id"] != context["dictionaries"][version["dictionary_id"]][
        "company_id"
    ]:
        errors.append(f"{label}: rule set belongs to another company")
    member = [
        m for m in rule_set["members"] if m["dictionary_id"] == version["dictionary_id"]
    ]
    if not member or member[0]["version_id"] != version["version_id"]:
        errors.append(f"{label}: rule set does not bind the published version")

    request = entry.get("request") or {}
    if request.get("comment") != version["comment"]:
        errors.append(f"{label}: publish request comment differs from the version comment")
    if after is not None and [
        rule["rule_id"] for rule in _state_rules(after, context)
    ] != [rule["rule_id"] for rule in version["rules"]]:
        errors.append(f"{label}: after_state draft rules differ from the published version")

    # The tested base RuleSet differs from the resulting RuleSet only in the
    # published dictionary: every other member is unchanged, and the published
    # member binds the new version.
    simulation = None
    for candidate in context["simulations"].values():
        if candidate["simulation_id"] == request.get("simulation_id"):
            simulation = candidate
            break
    if simulation is not None:
        base = context["rule_sets"].get(simulation["base_rule_set_id"])
        if base is not None:
            base_members = {
                m["dictionary_id"]: m["version_id"] for m in base["members"]
            }
            result_members = {
                m["dictionary_id"]: m["version_id"] for m in rule_set["members"]
            }
            if set(base_members) != set(result_members):
                errors.append(
                    f"{label}: base and result rule sets cover different dictionaries"
                )
            for dictionary_id, result_version in result_members.items():
                if dictionary_id == version["dictionary_id"]:
                    base_version = base_members.get(dictionary_id)
                    if base_version == result_version:
                        errors.append(
                            f"{label}: base rule set already binds the published version"
                        )
                    elif before is not None and base_version not in before.get(
                        "history", []
                    ):
                        errors.append(
                            f"{label}: base rule set candidate member is not the "
                            "previous active version"
                        )
                elif base_members.get(dictionary_id) != result_version:
                    errors.append(
                        f"{label}: base rule set changed another dictionary "
                        f"{dictionary_id!r} before publication"
                    )
    return errors


def _failure_errors(
    entry: Dict[str, Any], context: Dict[str, Any], known: set
) -> List[str]:
    errors: List[str] = []
    errors.extend(_scenario_errors(entry, known))
    label = entry.get("failure_id", "failure")
    operation = entry.get("operation")
    if operation not in KNOWN_OPERATIONS:
        errors.append(f"{label}: unknown operationId {operation!r}")
    expected = entry.get("expected") or {}
    allowed = allowed_error_codes(
        context["document"], operation, expected.get("status")
    )
    if expected.get("code") not in allowed:
        errors.append(
            f"{label}: code {expected.get('code')!r} is not declared by {operation!r} "
            f"for HTTP {expected.get('status')}"
        )
    if entry.get("mutates") is not False:
        errors.append(f"{label}: a failure must declare mutates=false")
    if entry.get("before_state") != entry.get("after_state"):
        errors.append(f"{label}: a failure must not change state")
    if entry.get("before_state") not in context["states"]:
        errors.append(f"{label}: unknown before_state")
    if not isinstance(entry.get("request"), dict):
        errors.append(f"{label}: request must be an object")
    return errors


def request_rejection_errors(
    expectations: Dict[str, Any], context: Dict[str, Any], registry
) -> List[str]:
    """Every declared request must be accepted, except the explicit schema rejections."""
    errors: List[str] = []
    for entry in expectations.get("failures", []):
        pointer = _request_schema_pointer(context["document"], entry["operation"])
        if pointer is None:
            errors.append(f"{entry['failure_id']}: operation has no request schema")
            continue
        schema_errors = validate_value(
            registry, pointer, materialize_request(entry, context)
        )
        if entry.get("schema_rejected") and not schema_errors:
            errors.append(
                f"{entry['failure_id']}: declared schema rejection but the request "
                "schema accepted it"
            )
        if not entry.get("schema_rejected") and schema_errors:
            errors.append(
                f"{entry['failure_id']}: request should be schema-valid: {schema_errors}"
            )
    return errors


def _batch_binding_errors(entry: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    label = entry.get("binding_id", "batch-binding")
    if entry.get("batch_exists") is not False:
        errors.append(f"{label}: batch_exists must be false until batches are implemented")
    rule_set = context["rule_sets"].get(entry.get("rule_set_id"))
    if rule_set is None:
        errors.append(f"{label}: unknown rule_set_id")
        return errors
    for version_id in entry.get("version_ids", []):
        version = context["versions"].get(version_id)
        if version is None or version["role"] != "published":
            errors.append(f"{label}: bound version {version_id!r} is not immutable published")
    if not rule_set.get("members"):
        errors.append(f"{label}: rule set has no members")
    return errors


def _audit_action_enum(document: Dict[str, Any]) -> set:
    node = document.get("components", {}).get("schemas", {}).get("AuditAction", {})
    return set(node.get("enum") or [])


def _audit_result_enum(document: Dict[str, Any]) -> set:
    node = document.get("components", {}).get("schemas", {}).get("AuditResult", {})
    return set(node.get("enum") or [])


def _audit_expectation_errors(
    entry: Dict[str, Any], context: Dict[str, Any], known: set
) -> List[str]:
    """Scenario expected actions for LT-03.5b; never claimed as audit evidence."""
    errors: List[str] = []
    label = entry.get("scenario_id", "audit-expectation")
    if label not in known:
        errors.append(f"audit expectation {label!r} references an unknown scenario")
    actions = entry.get("actions") or []
    if not actions:
        errors.append(f"audit expectation {label!r} has no actions")
    allowed_actions = _audit_action_enum(context["document"])
    for action in actions:
        if action not in allowed_actions:
            errors.append(
                f"audit expectation {label!r} uses unknown AuditAction {action!r}"
            )
    if entry.get("result") not in _audit_result_enum(context["document"]):
        errors.append(
            f"audit expectation {label!r} uses unknown AuditResult {entry.get('result')!r}"
        )
    if entry.get("evidence") is not False:
        errors.append(
            f"audit expectation {label!r} must declare evidence=false: this is an "
            "expectation, not recorded audit evidence"
        )
    return errors


def _simulation_for_expected(
    expected: Dict[str, Any], context: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    page_id = expected.get("page_id")
    if page_id:
        return context["simulations"].get(page_id)
    simulation_id = expected.get("simulation_id")
    if simulation_id:
        for entry in context["simulations"].values():
            if entry["simulation_id"] == simulation_id:
                return entry
    return None


def _timeline_crosslink_errors(
    entry: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    """Cross-links every successful timeline step to its state/simulation/publish."""
    errors: List[str] = []
    label = entry["step_id"]
    operation = entry.get("operation")
    before = context["states"].get(entry.get("before_state"))
    after = context["states"].get(entry.get("after_state"))
    expected = entry.get("expected") or {}
    request = entry.get("request") or {}

    if operation == "createDictionary":
        if after is not None:
            if after["draft_revision"] != 0:
                errors.append(f"{label}: a created dictionary must start at revision 0")
            if after.get("history"):
                errors.append(f"{label}: a created dictionary must have an empty history")
            if after.get("active_version_id") is not None:
                errors.append(f"{label}: a created dictionary must have no active version")
    elif operation == "replaceDictionaryDraft":
        if before is not None and after is not None:
            if after["draft_revision"] != before["draft_revision"] + 1:
                errors.append(
                    f"{label}: a save must increment the draft revision by exactly one"
                )
            if expected.get("draft_revision") != after["draft_revision"]:
                errors.append(f"{label}: expected draft_revision disagrees with after_state")
            requested = [rule["rule_id"] for rule in request.get("rules", [])]
            if requested and requested != [
                rule["rule_id"] for rule in _state_rules(after, context)
            ]:
                errors.append(f"{label}: after_state rules differ from the saved request")
            if before.get("based_on_version_id") is not None and after.get(
                "based_on_version_id"
            ) is not None:
                # A normal save keeps provenance; the explicit manual-edit-after-restore
                # branch must clear it and is covered by the state's own declaration.
                pass
    elif operation == "restoreDictionaryDraft":
        if before is not None and after is not None:
            if after["draft_revision"] != before["draft_revision"] + 1:
                errors.append(
                    f"{label}: a restore must increment the draft revision by exactly one"
                )
            if after.get("based_on_version_id") != request.get("version_id"):
                errors.append(
                    f"{label}: restored based_on_version_id must equal request.version_id"
                )
    elif operation == "createDictionarySimulation":
        simulation = _simulation_for_expected(expected, context)
        if before is not None:
            if request.get("expected_draft_revision") != before["draft_revision"]:
                errors.append(
                    f"{label}: request expected_draft_revision disagrees with before_state"
                )
            if expected.get("draft_revision") != before["draft_revision"]:
                errors.append(
                    f"{label}: expected draft_revision disagrees with before_state"
                )
            if simulation is not None and simulation["draft_revision"] != before["draft_revision"]:
                errors.append(
                    f"{label}: simulation draft_revision disagrees with before_state"
                )
            if simulation is not None and simulation.get("universe") != before.get("universe"):
                errors.append(
                    f"{label}: simulation universe disagrees with its before_state"
                )
    elif operation == "publishDictionary":
        publish = context["publishes"].get(expected.get("publish_id"))
        if before is not None:
            if request.get("expected_draft_revision") != before["draft_revision"]:
                errors.append(
                    f"{label}: request expected_draft_revision disagrees with before_state"
                )
            if expected.get("draft_revision") != before["draft_revision"]:
                errors.append(
                    f"{label}: expected draft_revision disagrees with before_state"
                )
        if publish is not None:
            if publish.get("before_state") != entry.get("before_state"):
                errors.append(f"{label}: publish before_state disagrees with the timeline")
            if publish.get("after_state") != entry.get("after_state"):
                errors.append(f"{label}: publish after_state disagrees with the timeline")
            version = context["versions"][publish["published_version_id"]]
            if request.get("comment") != version["comment"]:
                errors.append(
                    f"{label}: publish request comment differs from the published version"
                )
            if expected.get("active_version_id") != version["version_id"]:
                errors.append(
                    f"{label}: expected active_version_id is not the published version"
                )
            if after is not None and [
                rule["rule_id"] for rule in _state_rules(after, context)
            ] != [rule["rule_id"] for rule in version["rules"]]:
                errors.append(
                    f"{label}: after_state draft rules differ from the published version"
                )
    elif operation == "getSimulation":
        simulation = _simulation_for_expected(expected, context)
        if simulation is None:
            errors.append(f"{label}: expected simulation page is not declared")
    elif operation == "getDictionaryVersion":
        if expected.get("version_id") not in context["versions"]:
            errors.append(f"{label}: expected version_id is not declared")
    elif operation == "listDictionaryVersions":
        if expected.get("page_id") not in context["version_pages"]:
            errors.append(f"{label}: expected version page is not declared")
    return errors


def _timeline_errors(
    entry: Dict[str, Any], context: Dict[str, Any], known: set
) -> List[str]:
    errors: List[str] = []
    errors.extend(_scenario_errors(entry, known))
    label = entry["step_id"]
    operation = entry.get("operation")
    if operation not in KNOWN_OPERATIONS:
        errors.append(f"{label}: unknown operationId {operation!r}")
    before = entry.get("before_state")
    after = entry.get("after_state")
    if before is not None and before not in context["states"]:
        errors.append(f"{label}: unknown before_state")
    if after not in context["states"]:
        errors.append(f"{label}: unknown after_state")
    if entry.get("mutates") and before == after:
        errors.append(f"{label}: a mutation must change the state")
    if not entry.get("mutates") and before != after:
        errors.append(f"{label}: a non-mutation must not change the state")
    if entry.get("actor") not in context["actor_aliases"]:
        errors.append(f"{label}: unknown actor")
    errors.extend(_timeline_crosslink_errors(entry, context))
    return errors


def expectation_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    """Every structural/consistency violation of the LT-03.2b oracle data."""
    errors: List[str] = []
    prefix = expectations.get("target_display_prefix") or ""

    for key in (
        "fixture_set",
        "version",
        "seed",
        "contract_version",
        "corpus_version",
        "rule_expectations_fixture",
        "target_display_prefix",
    ):
        if not expectations.get(key):
            errors.append(f"expectations are missing {key!r}")
    if expectations.get("corpus_version") != context["rule_expectations"][
        "corpus_version"
    ]:
        errors.append(
            f"expectations corpus_version {expectations.get('corpus_version')!r} "
            f"does not match the corpus {context['rule_expectations']['corpus_version']!r}"
        )
    if expectations.get("rule_expectations_fixture") != context["rule_expectations"][
        "fixture_set"
    ]:
        errors.append("rule_expectations_fixture does not match the LT-03.2a fixture set")

    actor_ids = set(context["actors"])
    for key, actor_id in context["actor_aliases"].items():
        if actor_id not in actor_ids:
            errors.append(
                f"actor {key!r} references unknown auth fixture actor {actor_id!r}"
            )

    corpus_companies = context["companies"]
    for dictionary_id, dictionary in context["dictionaries"].items():
        if dictionary.get("company_id") not in corpus_companies:
            errors.append(f"dictionary {dictionary_id!r} references an unknown company")
        if not dictionary.get("name"):
            errors.append(f"dictionary {dictionary_id!r} has no name")

    # Versions.
    expected_versions = len(context["rule_expectations"]["versions"]) + len(
        expectations.get("versions", [])
    )
    if len(context["versions"]) != expected_versions:
        errors.append("version_id values are not unique across the two fixtures")
    for version_id, version in context["versions"].items():
        dictionary = context["dictionaries"].get(version["dictionary_id"])
        if dictionary is None:
            errors.append(
                f"version {version_id!r} references unknown dictionary "
                f"{version['dictionary_id']!r}"
            )
            continue
        if version["role"] not in ("published", "scenario"):
            errors.append(f"version {version_id!r} has unknown role {version['role']!r}")
        rule_ids: List[str] = []
        for rule in version["rules"]:
            rule_id = rule.get("rule_id")
            if rule_id in rule_ids:
                errors.append(f"version {version_id!r} repeats rule_id {rule_id!r}")
            rule_ids.append(rule_id)
            target = context["targets"].get(rule.get("target_id"))
            if target is None:
                errors.append(
                    f"version {version_id!r} rule {rule_id!r} references unknown target "
                    f"{rule.get('target_id')!r}"
                )
            elif target["company_id"] != dictionary["company_id"]:
                errors.append(
                    f"version {version_id!r} rule {rule_id!r} target belongs to another company"
                )
        restored = version["restored_from_version_id"]
        if restored is not None:
            source = context["versions"].get(restored)
            if source is None or source["dictionary_id"] != version["dictionary_id"]:
                errors.append(
                    f"version {version_id!r} restored_from_version_id is not a version "
                    "of the same dictionary"
                )

    # States.
    if len(context["states"]) != len(expectations.get("states", [])):
        errors.append("state_id values are not unique")
    for state_id, state in context["states"].items():
        dictionary = context["dictionaries"].get(state.get("dictionary_id"))
        if dictionary is None:
            errors.append(f"state {state_id!r} references an unknown dictionary")
            continue
        if not isinstance(state.get("draft_revision"), int) or state["draft_revision"] < 0:
            errors.append(f"state {state_id!r} has an invalid draft_revision")
        if "rules" not in state and state.get("rules_version_id") not in context["versions"]:
            errors.append(f"state {state_id!r} references an unknown rules_version_id")
        based_on = state.get("based_on_version_id")
        if based_on is not None:
            version = context["versions"].get(based_on)
            if version is None or version["dictionary_id"] != state["dictionary_id"]:
                errors.append(
                    f"state {state_id!r} based_on_version_id is not a version of the dictionary"
                )
        active = state.get("active_version_id")
        if active is not None:
            version = context["versions"].get(active)
            if version is None or version["dictionary_id"] != state["dictionary_id"]:
                errors.append(
                    f"state {state_id!r} active_version_id is not a version of the dictionary"
                )
            elif version["role"] != "published":
                errors.append(
                    f"state {state_id!r} active_version_id is not a published version"
                )
        history = state.get("history", [])
        for version_id in history:
            version = context["versions"].get(version_id)
            if (
                version is None
                or version["dictionary_id"] != state["dictionary_id"]
                or version["role"] != "published"
            ):
                errors.append(
                    f"state {state_id!r} history contains a non-published or foreign version"
                )
        if len(history) != len(set(history)):
            errors.append(f"state {state_id!r} history repeats a version_id")

    # Rule sets.
    if len(context["rule_sets"]) != len(expectations.get("rule_sets", [])) + len(
        context["rule_expectations"]["rule_sets"]
    ):
        errors.append("rule_set_id values are not unique")
    for rule_set_id, rule_set in context["rule_sets"].items():
        company_id = rule_set.get("company_id")
        if company_id not in corpus_companies:
            errors.append(f"rule set {rule_set_id!r} references an unknown company")
        members = rule_set.get("members") or []
        if not members:
            errors.append(f"rule set {rule_set_id!r} has no members")
        dictionary_ids = [member.get("dictionary_id") for member in members]
        if dictionary_ids != sorted(dictionary_ids):
            errors.append(f"rule set {rule_set_id!r} members are not sorted by dictionary_id")
        if len(dictionary_ids) != len(set(dictionary_ids)):
            errors.append(f"rule set {rule_set_id!r} repeats a dictionary_id")
        for member in members:
            version = context["versions"].get(member.get("version_id"))
            if version is None:
                errors.append(
                    f"rule set {rule_set_id!r} references unknown version "
                    f"{member.get('version_id')!r}"
                )
                continue
            if version["dictionary_id"] != member.get("dictionary_id"):
                errors.append(
                    f"rule set {rule_set_id!r} member points at another dictionary version"
                )
            if rule_set.get("role") == "published" and version["role"] != "published":
                errors.append(
                    f"published rule set {rule_set_id!r} must reference published versions"
                )
            if (
                context["dictionaries"].get(member.get("dictionary_id"), {}).get(
                    "company_id"
                )
                != company_id
            ):
                errors.append(
                    f"rule set {rule_set_id!r} member belongs to another company"
                )

    # Ready sets.
    if len(context["ready_sets"]) != len(expectations.get("ready_sets", [])):
        errors.append("ready_set_id values are not unique")
    for ready_set_id, ready_set in context["ready_sets"].items():
        if ready_set.get("company_id") not in corpus_companies:
            errors.append(f"ready set {ready_set_id!r} references an unknown company")
        if not ready_set.get("snapshot_id"):
            errors.append(f"ready set {ready_set_id!r} has no snapshot_id")
        seen_items: set = set()
        for member in ready_set["members"]:
            item_id = member.get("item_id")
            if item_id in seen_items:
                errors.append(f"ready set {ready_set_id!r} repeats item_id {item_id!r}")
            seen_items.add(item_id)
            location = member.get("location") or {}
            if not location.get("relative_path"):
                errors.append(f"ready set {ready_set_id!r} member has no relative_path")
            if member.get("filename") != (location.get("relative_path") or "").rsplit(
                "/", 1
            )[-1]:
                errors.append(
                    f"ready set {ready_set_id!r} filename is not the path basename"
                )
            if location.get("display_path") != prefix + "/" + location.get(
                "relative_path", ""
            ):
                errors.append(
                    f"ready set {ready_set_id!r} display_path does not match the prefix"
                )

    # Simulations.
    if len(context["simulations"]) != len(expectations.get("simulations", [])):
        errors.append("page_id values are not unique")
    simulation_groups: Dict[str, List[Dict[str, Any]]] = {}
    for entry in expectations.get("simulations", []):
        simulation_groups.setdefault(entry["simulation_id"], []).append(entry)
    for simulation_id, pages in simulation_groups.items():
        for entry in pages:
            errors.extend(_simulation_errors(entry, context, simulation_id, pages))

    # Publishes.
    if len(context["publishes"]) != len(expectations.get("publishes", [])):
        errors.append("publish_id values are not unique")
    for entry in expectations.get("publishes", []):
        errors.extend(_publish_errors(entry, context))

    # Replays and failures share the scenario-id namespace.
    if len(context["replays"]) != len(expectations.get("replays", [])):
        errors.append("replay_id values are not unique")
    if len(context["failures"]) != len(expectations.get("failures", [])):
        errors.append("failure_id values are not unique")
    known_scenarios: set = set()
    for entry in expectations.get("replays", []):
        errors.extend(_scenario_errors(entry, known_scenarios))
        original = context["publishes"].get(entry.get("original_publish_id"))
        if original is None:
            errors.append(f"{entry['replay_id']}: unknown original_publish_id")
            continue
        if entry.get("request") != original.get("request"):
            errors.append(f"{entry['replay_id']}: replay request differs from the original")
        if entry.get("idempotency_key") != original.get("idempotency_key"):
            errors.append(f"{entry['replay_id']}: replay key differs from the original")
        if entry.get("actor") != original.get("actor"):
            errors.append(f"{entry['replay_id']}: replay actor differs from the original")
        if materialize_publish(entry, context) != materialize_publish(original, context):
            errors.append(f"{entry['replay_id']}: replay result differs from the original")
        if entry.get("after_state") != entry.get("before_state"):
            errors.append(f"{entry['replay_id']}: replay must not mutate state")
    for entry in expectations.get("failures", []):
        errors.extend(_failure_errors(entry, context, known_scenarios))

    # Version pages.
    for page_id, page in context["version_pages"].items():
        dictionary = context["dictionaries"].get(page.get("dictionary_id"))
        if dictionary is None:
            errors.append(f"version page {page_id!r} references an unknown dictionary")
            continue
        for version_id in page["items"]:
            version = context["versions"].get(version_id)
            if version is None or version["dictionary_id"] != page["dictionary_id"]:
                errors.append(f"version page {page_id!r} references a foreign version")

    # Batch bindings (future expectation, no batch exists yet).
    for binding in expectations.get("batch_bindings", []):
        errors.extend(_batch_binding_errors(binding, context))

    # Timeline.
    for entry in expectations.get("timeline", []):
        errors.extend(_timeline_errors(entry, context, known_scenarios))

    # Expected audit actions (LT-03.5b consumer, not evidence).
    for entry in expectations.get("audit_expectations", []):
        errors.extend(_audit_expectation_errors(entry, context, known_scenarios))

    # Coverage.
    coverage = expectations.get("coverage") or {}
    for q in KNOWN_Q:
        if not coverage.get(q):
            errors.append(f"coverage: {q} has no scenario ids")
    for q, scenario_ids in coverage.items():
        if q not in KNOWN_Q:
            errors.append(f"coverage: unknown Q id {q!r}")
        for scenario_id in scenario_ids:
            if scenario_id not in known_scenarios:
                errors.append(
                    f"coverage: {q} references unknown scenario {scenario_id!r}"
                )
    for label in known_scenarios:
        for q in _scenario_q_ids(expectations, label):
            if label not in coverage.get(q, []):
                errors.append(f"coverage: {q} does not list scenario {label!r}")
    return errors


def _scenario_q_ids(expectations: Dict[str, Any], label: str) -> List[str]:
    for key in ("timeline", "failures", "replays"):
        for entry in expectations.get(key, []):
            if (
                entry.get("step_id") == label
                or entry.get("failure_id") == label
                or entry.get("replay_id") == label
            ):
                return entry.get("q_ids") or []
    return []


# --------------------------------------------------------------------------- #
# Generated public examples (documented preparation path)
# --------------------------------------------------------------------------- #

def generated_examples(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    for binding in EXAMPLE_BINDINGS:
        kind = binding["kind"]
        key = binding["binding"]
        if kind == "dictionary":
            payload = materialize_dictionary(context["states"][key], context)
        elif kind == "dictionary_list":
            payload = materialize_dictionary_list(context["dictionary_lists"][key], context)
        elif kind == "version":
            payload = materialize_version(context["versions"][key], context)
        elif kind == "page_versions":
            payload = materialize_page_versions(context["version_pages"][key], context)
        elif kind == "rule_set":
            payload = materialize_rule_set(context["rule_sets"][key], context)
        elif kind == "simulation":
            payload = materialize_simulation(context["simulations"][key], context)
        elif kind == "publish":
            payload = materialize_publish(context["publishes"][key], context)
        elif kind == "error":
            payload = materialize_error(context["failures"][key])
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


def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="LT-03.2b dictionary lifecycle expectation materializer/preparer."
    )
    parser.add_argument("--write-examples", action="store_true")
    args = parser.parse_args(argv)

    base = synthetic.repo_root()
    expectations = load_expectations(base)
    context = build_context(base, expectations)
    errors = expectation_errors(expectations, context)
    if errors:
        for message in errors:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1
    if args.write_examples:
        for relative in write_examples(base):
            print(f"wrote {relative}")
    print(
        f"dictionary lifecycle {expectations['fixture_set']} v{expectations['version']}: "
        f"{len(expectations.get('timeline', []))} timeline, "
        f"{len(expectations.get('failures', []))} failure, "
        f"{len(expectations.get('replays', []))} replay, "
        f"{len(expectations.get('simulations', []))} simulation page(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
