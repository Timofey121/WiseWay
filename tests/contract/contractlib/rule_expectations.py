"""LT-03.2a finite rule/target expectations for the WiseWay synthetic demo.

``fixtures/synthetic/rule_expectations.json`` stores the finite, hand-authored
oracle data that the later simulation/sorting fixtures (LT-03.2b and beyond)
consume:

* ``versions`` / ``dictionaries`` / ``rule_sets`` - complete immutable version
  definitions, the two published company dictionaries and the full active
  ``RuleSet`` of each company plus explicitly separated scenario variants with
  their own version/rule-set ids;
* ``target_directories`` - the allowlisted target directories per company;
* ``sources`` - the source identity/relative input of each rule scenario;
* ``rule_scenarios`` - an explicit rule set plus one source and the *literal*
  expected ``matched_rule_refs``, ``selected_rule``, ``target``,
  ``target_basename``, ``predicted_state`` and ``reason_code``;
* ``target_scenarios`` - target resolver oracles (resolved or rejected with an
  exact HTTP status/``error.code`` pair);
* ``invalid_rule_cases`` - invalid masks/priority/stem/target cases.  Cases the
  OAS ``Rule`` schema rejects are marked ``schema_rejected=true``; the remaining
  domain-only rejections are marked ``schema_rejected=false`` and are never
  positively validated.

Every version carries a ``role``.  ``role == "published"`` is the dictionary's
live immutable history and is the only thing the public ``Dictionary``
``versions_count`` reflects.  ``role == "scenario"`` is an isolated test
universe for the later simulation fixtures: scenario versions are referenced
only by scenario rule sets and never count as live history.  The public
``Dictionary`` examples therefore export the published timeline only.

This module is a *materializer and consistency checker*, not a rule engine.  It
looks up already-declared rules, versions, dictionaries, rule sets and target
directories by their literal ids and assembles schema-shaped payloads.  It never
matches a mask against a field, never picks a winning priority, never resolves a
conflict and never derives a target name: every one of those values is data.
``reason`` on each scenario is the manual trace that lets a reviewer verify the
expectation against DICT-01...07.

A documented preparation command regenerates the committed public examples::

    python tests/contract/contractlib/rule_expectations.py --write-examples
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # package import (tests, verify_contract.py)
    from . import synthetic
    from .expectations import EXPECTED_OPERATIONS
    from .loading import load_contract
    from .schemas import validate_value
    from .search_expectations import allowed_error_codes
except ImportError:  # pragma: no cover - documented direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from contractlib import synthetic  # type: ignore
    from contractlib.expectations import EXPECTED_OPERATIONS  # type: ignore
    from contractlib.loading import load_contract  # type: ignore
    from contractlib.schemas import validate_value  # type: ignore
    from contractlib.search_expectations import allowed_error_codes  # type: ignore

EXPECTATIONS_RELATIVE = Path("fixtures") / "synthetic" / "rule_expectations.json"
RULE_SCHEMA = "#/components/schemas/Rule"
TARGET_DIRECTORY_SCHEMA = "#/components/schemas/TargetDirectory"
DICTIONARY_SCHEMA = "#/components/schemas/Dictionary"
DICTIONARY_VERSION_SCHEMA = "#/components/schemas/DictionaryVersion"
RULE_SET_SCHEMA = "#/components/schemas/RuleSet"
PLAN_ROW_SCHEMA = "#/components/schemas/PlanRow"
ERROR_SCHEMA = "#/components/schemas/ErrorResponse"
KNOWN_Q = ("Q-015", "Q-018", "Q-044")
KNOWN_OPERATIONS = set(EXPECTED_OPERATIONS.values())
RESOLVE_OPERATION = "resolveTargetDirectory"
PREDICTIONS = ("WILL_MOVE", "WILL_MANUAL_REVIEW", "REQUIRES_DECISION", "NOT_READY")
RULE_REASON_CODES = (None, "RULE_CONFLICT", "NO_SCENARIO")

# (example id, kind, binding, canonical schema, output file, description).
EXAMPLE_BINDINGS: List[Dict[str, str]] = [
    {
        "id": "target-atlas-reports",
        "kind": "target",
        "binding": "target-atlas-reports",
        "schema": TARGET_DIRECTORY_SCHEMA,
        "file": "contracts/examples/targets/target-atlas-reports.json",
        "description": "Allowlisted Atlas Reports target directory.",
    },
    {
        "id": "target-atlas-invoices",
        "kind": "target",
        "binding": "target-atlas-invoices",
        "schema": TARGET_DIRECTORY_SCHEMA,
        "file": "contracts/examples/targets/target-atlas-invoices.json",
        "description": "Allowlisted Atlas Invoices target directory.",
    },
    {
        "id": "target-nova-north-reports",
        "kind": "target",
        "binding": "target-nova-north-reports",
        "schema": TARGET_DIRECTORY_SCHEMA,
        "file": "contracts/examples/targets/target-nova-north-reports.json",
        "description": "Allowlisted Nova North/Reports target directory.",
    },
    {
        "id": "dictionary-atlas-general",
        "kind": "dictionary",
        "binding": "dictionary-atlas-general",
        "schema": DICTIONARY_SCHEMA,
        "file": "contracts/examples/dictionaries/dictionary-atlas-general.json",
        "description": "Atlas general dictionary with its full published rule set.",
    },
    {
        "id": "dictionary-atlas-invoices",
        "kind": "dictionary",
        "binding": "dictionary-atlas-invoices",
        "schema": DICTIONARY_SCHEMA,
        "file": "contracts/examples/dictionaries/dictionary-atlas-invoices.json",
        "description": "Atlas invoices dictionary with its full published rule set.",
    },
    {
        "id": "dictionary-nova-general",
        "kind": "dictionary",
        "binding": "dictionary-nova-general",
        "schema": DICTIONARY_SCHEMA,
        "file": "contracts/examples/dictionaries/dictionary-nova-general.json",
        "description": "Nova general dictionary with its full published rule set.",
    },
    {
        "id": "version-atlas-general-v1",
        "kind": "version",
        "binding": "version-atlas-general-v1",
        "schema": DICTIONARY_VERSION_SCHEMA,
        "file": "contracts/examples/dictionaries/version-atlas-general-v1.json",
        "description": "Immutable first Atlas general version.",
    },
    {
        "id": "version-atlas-invoices-v1",
        "kind": "version",
        "binding": "version-atlas-invoices-v1",
        "schema": DICTIONARY_VERSION_SCHEMA,
        "file": "contracts/examples/dictionaries/version-atlas-invoices-v1.json",
        "description": "Immutable first Atlas invoices version.",
    },
    {
        "id": "version-nova-general-v1",
        "kind": "version",
        "binding": "version-nova-general-v1",
        "schema": DICTIONARY_VERSION_SCHEMA,
        "file": "contracts/examples/dictionaries/version-nova-general-v1.json",
        "description": "Immutable first Nova general version.",
    },
    {
        "id": "rule-set-atlas-published",
        "kind": "rule_set",
        "binding": "rule-set-atlas-published",
        "schema": RULE_SET_SCHEMA,
        "file": "contracts/examples/dictionaries/rule-set-atlas-published.json",
        "description": "Full active Atlas RuleSet (all dictionaries, sorted by dictionary_id).",
    },
    {
        "id": "rule-set-nova-published",
        "kind": "rule_set",
        "binding": "rule-set-nova-published",
        "schema": RULE_SET_SCHEMA,
        "file": "contracts/examples/dictionaries/rule-set-nova-published.json",
        "description": "Full active Nova RuleSet (all dictionaries, sorted by dictionary_id).",
    },
    {
        "id": "plan-row-atlas-archive",
        "kind": "plan_row",
        "binding": "RULE-Q015-ARCHIVE-GZ",
        "schema": PLAN_ROW_SCHEMA,
        "file": "contracts/examples/dictionaries/plan-row-atlas-archive.json",
        "description": "PlanRow for archive.tar.gz: fixed stem Archive plus the last suffix .gz.",
    },
    {
        "id": "plan-row-atlas-upper-txt",
        "kind": "plan_row",
        "binding": "RULE-Q015-UPPER-TXT-SMALLER-WINS",
        "schema": PLAN_ROW_SCHEMA,
        "file": "contracts/examples/dictionaries/plan-row-atlas-upper-txt.json",
        "description": "PlanRow where priority 10 wins over 100 and .TXT keeps its original case.",
    },
    {
        "id": "plan-row-atlas-conflict",
        "kind": "plan_row",
        "binding": "RULE-Q018-EQ-DIFF-TARGET-CONFLICT",
        "schema": PLAN_ROW_SCHEMA,
        "file": "contracts/examples/dictionaries/plan-row-atlas-conflict.json",
        "description": "PlanRow for an equal-priority conflict with different final targets.",
    },
    {
        "id": "plan-row-atlas-no-scenario",
        "kind": "plan_row",
        "binding": "RULE-Q015-NO-SCENARIO",
        "schema": PLAN_ROW_SCHEMA,
        "file": "contracts/examples/dictionaries/plan-row-atlas-no-scenario.json",
        "description": "PlanRow for a file with no matching published rule (NO_SCENARIO).",
    },
    {
        "id": "error-invalid-target",
        "kind": "error",
        "binding": "INVALID_TARGET",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-invalid-target.json",
        "description": "422 INVALID_TARGET for a missing or disallowed target directory.",
    },
    {
        "id": "error-path-outside-root",
        "kind": "error",
        "binding": "PATH_OUTSIDE_ROOT",
        "schema": ERROR_SCHEMA,
        "file": "contracts/examples/errors/error-path-outside-root.json",
        "description": "422 PATH_OUTSIDE_ROOT for a path escaping the allowed root.",
    },
]

_ERROR_MESSAGES = {
    "INVALID_TARGET": "Целевой каталог отсутствует или недопустим.",
    "PATH_OUTSIDE_ROOT": "Путь находится вне разрешённого корня.",
}


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

def expectations_path(root: Optional[Path] = None) -> Path:
    return (root or synthetic.repo_root()) / EXPECTATIONS_RELATIVE


def load_expectations(root: Optional[Path] = None) -> Dict[str, Any]:
    return synthetic.load_json(expectations_path(root))


def _load_actors(manifest: Dict[str, Any], base: Path) -> Dict[str, Dict[str, Any]]:
    actors: Dict[str, Dict[str, Any]] = {}
    for entry in manifest.get("examples", []):
        if not entry.get("id", "").startswith("auth-actor"):
            continue
        payload = synthetic.load_json(base / entry["file"])
        actors[payload["user_id"]] = payload
    return actors


def build_context(
    root: Optional[Path] = None, expectations: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Load the corpus, contract and the literal lookup tables."""
    base = Path(root) if root is not None else synthetic.repo_root()
    if expectations is None:
        expectations = load_expectations(base)
    manifest = synthetic.load_manifest(synthetic.manifest_path(base))
    corpus = synthetic.load_corpus(manifest, base)
    materialized = synthetic.materialize(corpus)
    document = load_contract(base / "contracts" / "openapi" / "wiseway-v1.yaml")
    return {
        "base": base,
        "manifest": manifest,
        "corpus": corpus,
        "document": document,
        "inventory": {item["item_id"]: item for item in materialized["files"]},
        "actors": _load_actors(manifest, base),
        "expectations": expectations,
        "prefix": expectations["target_display_prefix"],
        "targets": {t["target_id"]: t for t in expectations["target_directories"]},
        "versions": {v["version_id"]: v for v in expectations["versions"]},
        "dictionaries": {
            d["dictionary_id"]: d for d in expectations["dictionaries"]
        },
        "sources": expectations["sources"],
    }


# --------------------------------------------------------------------------- #
# Materialization (literal ids only, never a matcher)
# --------------------------------------------------------------------------- #

def _expand(value: Any) -> Any:
    """Expand the documented ``{"$repeat": {"char", "count"}}`` placeholder."""
    if isinstance(value, dict):
        if set(value.keys()) == {"$repeat"}:
            spec = value["$repeat"]
            return str(spec["char"]) * int(spec["count"])
        return {key: _expand(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_expand(child) for child in value]
    return value


def _actor_payload(context: Dict[str, Any], actor_key: str) -> Dict[str, Any]:
    aliases = context["expectations"].get("actors") or {}
    actor_id = aliases.get(actor_key, actor_key)
    actor = context["actors"].get(actor_id)
    if actor is None:
        raise KeyError(f"unknown synthetic actor {actor_key!r}")
    return dict(actor)


def materialize_rule(
    rule_entry: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    """Build a canonical ``Rule`` from a compact declaration (``target_id``)."""
    expanded = _expand(rule_entry)
    rule = {key: value for key, value in expanded.items() if key != "target_id"}
    target_id = expanded.get("target_id")
    if target_id is not None:
        target = context["targets"][target_id]
        rule["target"] = {
            "root_id": target["root_id"],
            "relative_directory": target["relative_directory"],
        }
    return rule


def materialize_target_directory(
    target_entry: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    return {
        "root_id": target_entry["root_id"],
        "relative_directory": target_entry["relative_directory"],
        "display_path": context["prefix"] + "/" + target_entry["relative_directory"],
    }


def materialize_version(
    version_entry: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    dictionary = context["dictionaries"][version_entry["dictionary_id"]]
    return {
        "version_id": version_entry["version_id"],
        "dictionary_id": version_entry["dictionary_id"],
        "version_number": version_entry["version_number"],
        "name": dictionary["name"],
        "description": dictionary["description"],
        "rules": [
            materialize_rule(rule, context) for rule in version_entry["rules"]
        ],
        "published_at": "2031-05-10T09:30:00Z",
        "published_by": _actor_payload(context, dictionary["updated_by"]),
        "comment": "Синтетическая неизменяемая версия.",
        "restored_from_version_id": None,
    }


def published_versions(
    expectations: Dict[str, Any], dictionary_id: str
) -> List[Dict[str, Any]]:
    """The live immutable history of a dictionary (``role == "published"``).

    ``role == "scenario"`` versions are an isolated test universe: they are
    referenced by scenario rule sets but are not part of the dictionary's live
    publication history and therefore never counted by ``versions_count``.
    """
    return [
        version
        for version in expectations["versions"]
        if version["dictionary_id"] == dictionary_id
        and version.get("role") == "published"
    ]


def materialize_dictionary(
    dictionary_entry: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    live_versions = published_versions(
        context["expectations"], dictionary_entry["dictionary_id"]
    )
    active = context["versions"][dictionary_entry["active_version_id"]]
    return {
        "dictionary_id": dictionary_entry["dictionary_id"],
        "company_id": dictionary_entry["company_id"],
        "name": dictionary_entry["name"],
        "description": dictionary_entry["description"],
        "draft": {
            "draft_revision": 1,
            "rules": [materialize_rule(rule, context) for rule in active["rules"]],
            "based_on_version_id": active["version_id"],
        },
        "active_version_id": active["version_id"],
        "versions_count": len(live_versions),
        "updated_at": dictionary_entry["updated_at"],
        "updated_by": _actor_payload(context, dictionary_entry["updated_by"]),
    }


def materialize_rule_set(rule_set_entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "rule_set_id": rule_set_entry["rule_set_id"],
        "company_id": rule_set_entry["company_id"],
        "members": [
            {
                "dictionary_id": member["dictionary_id"],
                "version_id": member["version_id"],
            }
            for member in rule_set_entry["members"]
        ],
    }


def materialize_plan_row(
    scenario: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    source = context["sources"][scenario["source_id"]]
    expected = scenario["expected"]
    return {
        "item_id": source["item_id"],
        "item_revision": source["item_revision"],
        "source": source["location"],
        "filename": source["filename"],
        "company_id": source["company_id"],
        "predicted_state": expected["predicted_state"],
        "reason_code": expected["reason_code"],
        "target": expected["target"],
        "matched_rules": expected["matched_rule_refs"],
        "selected_rule": expected["selected_rule"],
        "collision": None,
    }


def materialize_error(code: str) -> Dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": _ERROR_MESSAGES[code],
            "request_id": "request-demo-1",
            "operation_id": None,
            "retryable": False,
            "field_errors": [],
        }
    }


# --------------------------------------------------------------------------- #
# Validation (structural / consistency only; never re-derives a match)
# --------------------------------------------------------------------------- #

def _scenario_q_errors(scenario: Dict[str, Any], known: set) -> List[str]:
    label = scenario.get("scenario_id") or scenario.get("case_id") or "scenario"
    errors: List[str] = []
    if label in known:
        errors.append(f"duplicate scenario id {label!r}")
    known.add(label)
    q_ids = scenario.get("q_ids") or []
    if not q_ids:
        errors.append(f"{label}: q_ids must not be empty")
    for q in q_ids:
        if q not in KNOWN_Q:
            errors.append(f"{label}: unknown Q id {q!r}")
    if not scenario.get("parameters"):
        errors.append(f"{label}: parameters must not be empty")
    if not scenario.get("reason"):
        errors.append(f"{label}: reason (manual trace) must not be empty")
    return errors


def _rule_entry(
    versions: Dict[str, Any], reference: Dict[str, Any]
) -> Dict[str, Any]:
    version = versions[reference["version_id"]]
    for rule in version["rules"]:
        if rule["rule_id"] == reference["rule_id"]:
            return rule
    raise KeyError(f"unknown rule {reference['rule_id']!r}")


def _target_tuple(rule_entry: Dict[str, Any], targets: Dict[str, Any]) -> tuple:
    target = targets[rule_entry["target_id"]]
    return (
        target["root_id"],
        target["relative_directory"],
        rule_entry["target_stem"],
    )


def expectation_errors(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> List[str]:
    """Every structural/consistency violation of the LT-03.2a oracle data."""
    errors: List[str] = []
    prefix = expectations.get("target_display_prefix") or ""

    for key in (
        "fixture_set",
        "version",
        "seed",
        "contract_version",
        "corpus_version",
        "target_display_prefix",
    ):
        if not expectations.get(key):
            errors.append(f"expectations are missing {key!r}")
    if expectations.get("corpus_version") != context["corpus"]["version"]:
        errors.append(
            f"expectations corpus_version {expectations.get('corpus_version')!r} "
            f"does not match corpus {context['corpus']['version']!r}"
        )
    if expectations.get("contract_version") != context["corpus"]["contract_version"]:
        errors.append("expectations contract_version does not match the corpus")

    # Actors must be the exact auth fixture actors.
    actor_ids = set(context["actors"])
    actor_aliases = expectations.get("actors") or {}
    for key, actor_id in actor_aliases.items():
        if actor_id not in actor_ids:
            errors.append(
                f"actor {key!r} references unknown auth fixture actor {actor_id!r}"
            )

    corpus_companies = {
        company["company_id"]: company
        for company in context["corpus"].get("companies", [])
    }
    for company in expectations.get("companies", []):
        corpus_company = corpus_companies.get(company.get("company_id"))
        if corpus_company is None or corpus_company.get("name") != company.get("name"):
            errors.append(
                f"company {company.get('company_id')!r} does not match the corpus company"
            )
            continue
        if company.get("incoming_source_ids") != corpus_company.get("incoming_source_ids"):
            errors.append(
                f"company {company.get('company_id')!r} incoming_source_ids do not "
                "match the corpus company"
            )

    # Target directories.
    targets = context["targets"]
    for target_id, target in targets.items():
        if target.get("company_id") not in corpus_companies:
            errors.append(f"target {target_id!r} references an unknown company")
        if not target.get("relative_directory"):
            errors.append(f"target {target_id!r} has no relative_directory")
        if not target.get("root_id"):
            errors.append(f"target {target_id!r} has no root_id")

    # Versions and their rules.
    versions = context["versions"]
    dictionaries = context["dictionaries"]
    dictionary_company = {
        dictionary_id: dictionary["company_id"]
        for dictionary_id, dictionary in dictionaries.items()
    }
    for version_id, version in versions.items():
        dictionary_id = version.get("dictionary_id")
        if dictionary_id not in dictionaries:
            errors.append(
                f"version {version_id!r} references unknown dictionary {dictionary_id!r}"
            )
            continue
        if version.get("role") not in ("published", "scenario"):
            errors.append(
                f"version {version_id!r} has an unknown role {version.get('role')!r}"
            )
        rule_ids: List[str] = []
        for rule in version.get("rules", []):
            rule_id = rule.get("rule_id")
            if rule_id in rule_ids:
                errors.append(f"version {version_id!r} repeats rule_id {rule_id!r}")
            rule_ids.append(rule_id)
            target_id = rule.get("target_id")
            if target_id is None:
                errors.append(
                    f"rule {rule_id!r} in version {version_id!r} has no target_id"
                )
                continue
            target = targets.get(target_id)
            if target is None:
                errors.append(
                    f"rule {rule_id!r} references unknown target {target_id!r}"
                )
            elif target["company_id"] != dictionary_company[dictionary_id]:
                errors.append(
                    f"rule {rule_id!r} target {target_id!r} belongs to another company"
                )

    # Dictionaries and their active versions.
    for dictionary_id, dictionary in dictionaries.items():
        active = versions.get(dictionary.get("active_version_id"))
        if active is None:
            errors.append(
                f"dictionary {dictionary_id!r} has an unknown active_version_id"
            )
        elif active["dictionary_id"] != dictionary_id:
            errors.append(
                f"dictionary {dictionary_id!r} active version belongs to "
                f"{active['dictionary_id']!r}"
            )
        elif active.get("role") != "published":
            errors.append(
                f"dictionary {dictionary_id!r} active version is not a published version"
            )
        live_versions = published_versions(expectations, dictionary_id)
        if not live_versions:
            errors.append(f"dictionary {dictionary_id!r} has no published version")
        live_numbers = [version["version_number"] for version in live_versions]
        if len(live_numbers) != len(set(live_numbers)):
            errors.append(
                f"dictionary {dictionary_id!r} published version_number values are not unique"
            )
        if dictionary.get("company_id") not in corpus_companies:
            errors.append(f"dictionary {dictionary_id!r} references an unknown company")
        if actor_aliases.get(dictionary.get("updated_by")) not in actor_ids:
            errors.append(f"dictionary {dictionary_id!r} references an unknown actor")

    # Rule sets.
    rule_sets = {entry["rule_set_id"]: entry for entry in expectations["rule_sets"]}
    if len(rule_sets) != len(expectations["rule_sets"]):
        errors.append("rule_set_id values are not unique")
    for rule_set_id, rule_set in rule_sets.items():
        company_id = rule_set.get("company_id")
        if company_id not in corpus_companies:
            errors.append(f"rule set {rule_set_id!r} references an unknown company")
        members = rule_set.get("members") or []
        if not members:
            errors.append(f"rule set {rule_set_id!r} has no members")
        seen_dictionaries: set = set()
        for member in members:
            dictionary_id = member.get("dictionary_id")
            if dictionary_id in seen_dictionaries:
                errors.append(
                    f"rule set {rule_set_id!r} repeats dictionary {dictionary_id!r}"
                )
            seen_dictionaries.add(dictionary_id)
            version = versions.get(member.get("version_id"))
            if version is None:
                errors.append(
                    f"rule set {rule_set_id!r} references unknown version "
                    f"{member.get('version_id')!r}"
                )
            elif version["dictionary_id"] != dictionary_id:
                errors.append(
                    f"rule set {rule_set_id!r} member {dictionary_id!r} points at "
                    f"a version of {version['dictionary_id']!r}"
                )
            elif dictionary_company.get(dictionary_id) != company_id:
                errors.append(
                    f"rule set {rule_set_id!r} member {dictionary_id!r} belongs to "
                    "another company"
                )
            elif (
                rule_set.get("role") == "published"
                and version.get("role") != "published"
            ):
                errors.append(
                    f"published rule set {rule_set_id!r} must reference published "
                    f"versions, found {version.get('role')!r}"
                )
        member_pairs = sorted(
            (member["dictionary_id"], member["version_id"]) for member in members
        )
        if member_pairs != sorted(
            member_pairs, key=lambda pair: pair[0]
        ):
            errors.append(f"rule set {rule_set_id!r} members are not sorted by dictionary_id")
        if rule_set.get("role") == "published":
            active_pairs = sorted(
                (dictionary_id, dictionary["active_version_id"])
                for dictionary_id, dictionary in dictionaries.items()
                if dictionary["company_id"] == company_id
            )
            if member_pairs != active_pairs:
                errors.append(
                    f"published rule set {rule_set_id!r} is not the full active set "
                    f"{active_pairs}"
                )

    # Sources.
    sources = context["sources"]
    for source_id, source in sources.items():
        for key in ("item_id", "item_revision", "company_id", "filename", "location"):
            if key not in source:
                errors.append(f"source {source_id!r} is missing {key!r}")
        location = source.get("location") or {}
        for key in ("root_id", "relative_path", "display_path"):
            if not location.get(key):
                errors.append(f"source {source_id!r} location is missing {key!r}")
        relative_path = location.get("relative_path", "")
        if relative_path and source.get("filename") != relative_path.rsplit("/", 1)[-1]:
            errors.append(
                f"source {source_id!r} filename is not the basename of relative_path"
            )
        if relative_path and location.get("display_path") != prefix + "/" + relative_path:
            errors.append(
                f"source {source_id!r} display_path does not match the prefix"
            )
        if source.get("company_id") not in corpus_companies:
            errors.append(f"source {source_id!r} references an unknown company")
        corpus_item_id = source.get("corpus_item_id")
        if corpus_item_id:
            item = context["inventory"].get(corpus_item_id)
            if item is None:
                errors.append(
                    f"source {source_id!r} references unknown corpus item "
                    f"{corpus_item_id!r}"
                )
            else:
                if item["filename"] != source["filename"]:
                    errors.append(
                        f"source {source_id!r} filename disagrees with the corpus item"
                    )
                if item["location"]["root_id"] != location.get("root_id"):
                    errors.append(
                        f"source {source_id!r} root disagrees with the corpus item"
                    )
                if item["location"]["relative_path"] != relative_path:
                    errors.append(
                        f"source {source_id!r} path disagrees with the corpus item"
                    )

    known_scenarios: set = set()

    # Rule scenarios.
    scenarios = {s["scenario_id"]: s for s in expectations["rule_scenarios"]}
    for scenario_id, scenario in scenarios.items():
        errors.extend(_scenario_q_errors(scenario, known_scenarios))
        rule_set = rule_sets.get(scenario.get("rule_set_id"))
        if rule_set is None:
            errors.append(f"{scenario_id}: unknown rule_set_id")
            continue
        source = sources.get(scenario.get("source_id"))
        if source is None:
            errors.append(f"{scenario_id}: unknown source_id")
            continue
        if source.get("company_id") != rule_set.get("company_id"):
            errors.append(f"{scenario_id}: source company does not match the rule set")

        expected = scenario.get("expected") or {}
        matched = expected.get("matched_rule_refs") or []
        selected = expected.get("selected_rule")
        member_pairs = {
            (member["dictionary_id"], member["version_id"])
            for member in rule_set["members"]
        }
        for reference in list(matched) + ([selected] if selected else []):
            pair = (reference.get("dictionary_id"), reference.get("version_id"))
            if pair not in member_pairs:
                errors.append(
                    f"{scenario_id}: rule reference {pair!r} is not a member of the rule set"
                )
            version = versions.get(reference.get("version_id"))
            if version is None or not any(
                rule["rule_id"] == reference.get("rule_id")
                for rule in version.get("rules", [])
            ):
                errors.append(
                    f"{scenario_id}: undefined rule reference "
                    f"{reference.get('rule_id')!r}"
                )
        keys = [(ref["dictionary_id"], ref["rule_id"]) for ref in matched]
        if keys != sorted(keys):
            errors.append(f"{scenario_id}: matched_rule_refs are not sorted by id")
        if selected is not None and selected not in matched:
            errors.append(f"{scenario_id}: selected_rule is not one of matched_rule_refs")

        predicted = expected.get("predicted_state")
        reason_code = expected.get("reason_code")
        target = expected.get("target")
        if predicted not in PREDICTIONS:
            errors.append(f"{scenario_id}: unknown predicted_state {predicted!r}")
        if reason_code not in RULE_REASON_CODES:
            errors.append(f"{scenario_id}: unknown reason_code {reason_code!r}")

        if not matched:
            if (
                selected is not None
                or predicted != "WILL_MANUAL_REVIEW"
                or reason_code != "NO_SCENARIO"
                or target is not None
            ):
                errors.append(
                    f"{scenario_id}: no match must be WILL_MANUAL_REVIEW/NO_SCENARIO "
                    "with a null target"
                )
        elif reason_code == "RULE_CONFLICT":
            if len(matched) < 2:
                errors.append(f"{scenario_id}: RULE_CONFLICT needs at least two matches")
            if selected is not None:
                errors.append(f"{scenario_id}: RULE_CONFLICT must not select a rule")
            if predicted != "WILL_MANUAL_REVIEW" or target is not None:
                errors.append(
                    f"{scenario_id}: RULE_CONFLICT must be WILL_MANUAL_REVIEW with "
                    "a null target"
                )
            tuples = {
                _target_tuple(_rule_entry(versions, ref), targets)
                for ref in matched
            }
            if len(tuples) < 2:
                errors.append(
                    f"{scenario_id}: RULE_CONFLICT matched rules share one final target"
                )
        elif selected is None:
            errors.append(f"{scenario_id}: a matched scenario must select a rule")
        else:
            if predicted != "WILL_MOVE" or reason_code is not None:
                errors.append(
                    f"{scenario_id}: a resolved match must be WILL_MOVE with a null "
                    "reason_code"
                )
            if not isinstance(target, dict):
                errors.append(f"{scenario_id}: WILL_MOVE must carry a target")
            else:
                basename = expected.get("target_basename")
                relative_path = target.get("relative_path", "")
                if relative_path.rsplit("/", 1)[-1] != basename:
                    errors.append(
                        f"{scenario_id}: target_basename is not the target basename"
                    )
                if target.get("display_path") != prefix + "/" + relative_path:
                    errors.append(
                        f"{scenario_id}: target display_path does not match the prefix"
                    )
                directory = relative_path.rsplit("/", 1)[0]
                allowlist = {
                    (t["root_id"], t["relative_directory"])
                    for t in targets.values()
                    if t["company_id"] == rule_set["company_id"]
                }
                if (target.get("root_id"), directory) not in allowlist:
                    errors.append(f"{scenario_id}: target is not an allowlisted directory")
                stem = expected.get("final_stem") or ""
                suffix = expected.get("suffix") or ""
                if basename != stem + suffix:
                    errors.append(
                        f"{scenario_id}: final_stem+suffix does not equal target_basename"
                    )

        # Equal minimal priority: all matched rules must share one final target.
        if reason_code is None and len(matched) > 1:
            priorities = {
                _rule_entry(versions, reference)["priority"] for reference in matched
            }
            if len(priorities) == 1:
                tuples = {
                    _target_tuple(_rule_entry(versions, reference), targets)
                    for reference in matched
                }
                if len(tuples) != 1:
                    errors.append(
                        f"{scenario_id}: equal-priority matches must share one final target"
                    )

    # Target resolver scenarios.
    for scenario in expectations["target_scenarios"]:
        label = scenario["scenario_id"]
        errors.extend(_scenario_q_errors(scenario, known_scenarios))
        if scenario.get("operation") != RESOLVE_OPERATION:
            errors.append(f"{label}: operation must be {RESOLVE_OPERATION!r}")
        if scenario.get("company_id") not in corpus_companies:
            errors.append(f"{label}: unknown company")
        request = scenario.get("request") or {}
        if not request.get("display_path"):
            errors.append(f"{label}: request.display_path must not be empty")
        expected = scenario.get("expected") or {}
        outcome = expected.get("outcome")
        if outcome == "RESOLVED":
            target = targets.get(expected.get("target_id"))
            if target is None:
                errors.append(f"{label}: unknown resolved target_id")
            else:
                if target["company_id"] != scenario.get("company_id"):
                    errors.append(f"{label}: resolved target belongs to another company")
                if prefix + "/" + target["relative_directory"] != request.get("display_path"):
                    errors.append(f"{label}: resolved display_path does not match")
        elif outcome == "REJECTED":
            status = expected.get("status")
            allowed = allowed_error_codes(
                context["document"], RESOLVE_OPERATION, status
            )
            if expected.get("code") not in allowed:
                errors.append(
                    f"{label}: code {expected.get('code')!r} is not declared by "
                    f"{RESOLVE_OPERATION!r} for HTTP {status}"
                )
        else:
            errors.append(f"{label}: unknown outcome {outcome!r}")

    # Invalid rule cases.
    for case in expectations["invalid_rule_cases"]:
        label = case["case_id"]
        errors.extend(_scenario_q_errors(case, known_scenarios))
        if case.get("operation") not in KNOWN_OPERATIONS:
            errors.append(f"{label}: unknown operationId")
        if not isinstance(case.get("schema_rejected"), bool):
            errors.append(f"{label}: schema_rejected must be boolean")
        expected = case.get("expected") or {}
        allowed = allowed_error_codes(
            context["document"], case.get("operation"), expected.get("status")
        )
        if expected.get("code") not in allowed:
            errors.append(
                f"{label}: code {expected.get('code')!r} is not declared by "
                f"{case.get('operation')!r} for HTTP {expected.get('status')}"
            )
        if not case.get("rule"):
            errors.append(f"{label}: rule must not be empty")
        rule = case.get("rule") or {}
        target = rule.get("target")
        if not case.get("schema_rejected") and isinstance(target, dict):
            company_id = case.get("company_id")
            allowlist = {
                (t["root_id"], t["relative_directory"])
                for t in targets.values()
                if t["company_id"] == company_id
            }
            allowed_target = (
                target.get("root_id"),
                target.get("relative_directory"),
            ) in allowlist
            if allowed_target and expected.get("code") != "VALIDATION_ERROR":
                errors.append(
                    f"{label}: allowed target but code is not VALIDATION_ERROR"
                )
            if not allowed_target and expected.get("code") != "INVALID_TARGET":
                errors.append(
                    f"{label}: disallowed target but code is not INVALID_TARGET"
                )

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
    all_scenarios = (
        expectations["rule_scenarios"]
        + expectations["target_scenarios"]
        + expectations["invalid_rule_cases"]
    )
    for scenario in all_scenarios:
        label = scenario.get("scenario_id") or scenario.get("case_id")
        for q in scenario.get("q_ids", []):
            if label not in coverage.get(q, []):
                errors.append(f"coverage: {q} does not list scenario {label!r}")
    return errors


def schema_rejection_errors(
    expectations: Dict[str, Any], registry
) -> List[str]:
    """Confirm the declared schema-level rejection of invalid rule cases.

    Cases marked ``schema_rejected=true`` must fail the canonical ``Rule``
    schema; the domain-only cases must pass the schema (the JSON Schema cannot
    express the business rule) and are therefore never positively validated.
    """
    errors: List[str] = []
    for case in expectations["invalid_rule_cases"]:
        label = case["case_id"]
        rule = _expand(case["rule"])
        schema_errors = validate_value(registry, RULE_SCHEMA, rule)
        if case.get("schema_rejected") and not schema_errors:
            errors.append(
                f"{label}: declared schema rejection but the Rule schema accepted it"
            )
        if not case.get("schema_rejected") and schema_errors:
            errors.append(
                f"{label}: declared schema-valid but the Rule schema rejected it: "
                f"{schema_errors}"
            )
    return errors


# --------------------------------------------------------------------------- #
# Generated public examples (documented preparation path)
# --------------------------------------------------------------------------- #

def generated_examples(
    expectations: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    scenarios = {s["scenario_id"]: s for s in expectations["rule_scenarios"]}
    output: Dict[str, Any] = {}
    for binding in EXAMPLE_BINDINGS:
        kind = binding["kind"]
        key = binding["binding"]
        if kind == "target":
            output[binding["file"]] = materialize_target_directory(
                context["targets"][key], context
            )
        elif kind == "dictionary":
            output[binding["file"]] = materialize_dictionary(
                context["dictionaries"][key], context
            )
        elif kind == "version":
            output[binding["file"]] = materialize_version(context["versions"][key], context)
        elif kind == "rule_set":
            output[binding["file"]] = materialize_rule_set(
                next(
                    entry
                    for entry in expectations["rule_sets"]
                    if entry["rule_set_id"] == key
                )
            )
        elif kind == "plan_row":
            output[binding["file"]] = materialize_plan_row(scenarios[key], context)
        elif kind == "error":
            output[binding["file"]] = materialize_error(key)
        else:  # pragma: no cover - guarded by the static binding table
            raise ValueError(f"unknown example kind {kind!r}")
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
        description="LT-03.2a rule/target expectation materializer/preparer."
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
        f"rule expectations {expectations['fixture_set']} v{expectations['version']}: "
        f"{len(expectations['rule_scenarios'])} rule, "
        f"{len(expectations['target_scenarios'])} target, "
        f"{len(expectations['invalid_rule_cases'])} invalid-rule scenario(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
