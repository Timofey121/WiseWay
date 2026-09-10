"""Synthetic metadata corpus loader, materializer and integrity checks.

LT-03.1a (WP-03) publishes a finite, versioned synthetic corpus for the
external demo.  The committed ``fixtures/synthetic/corpus.json`` is deliberately
compact:

* the marker alphabet lives once in ``marker_model.values``;
* each used *context* declares its explicit root + ancestor chain in
  ``marker_model.contexts`` (no path parsing and no domain decision);
* large *regular* cohorts are expressed as explicit ID/range templates.

:func:`materialize` expands those declarations deterministically into plain
JSON objects that match ``#/components/schemas/SearchItem`` exactly, so future
frontend mocks can consume the serialized result without any Python-specific
object.

``marker_id`` follows ``contracts/semantics.md``: it is stable for
``root / parents / raw / kind`` within one schema version.  The loader derives
each id from the declared root and full ancestor path, so the same raw value in
different ancestry always receives a different id and the same ancestry always
receives the same id.

Nothing here performs search, matching, ranking or any business decision.

The module is dependency-free (stdlib only) and can be run as a documented
fixture-preparation command::

    python tests/contract/contractlib/synthetic.py --write fixtures/synthetic/inventory.json
    python tests/contract/contractlib/synthetic.py --update-checksums
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MANIFEST_RELATIVE = Path("fixtures") / "synthetic" / "manifest.json"
STRUCTURE_ISSUE_CODES = (
    "MISSING_REQUIRED_LEVEL",
    "UNEXPECTED_DEPTH",
    "INVALID_LEVEL_VALUE",
    "INVALID_COMPOSITE_SEGMENT",
)
REQUIRED_LIFECYCLE_STAGES = ("create", "change", "rename", "move", "delete")
REQUIRED_EXTENSIONS = (".pdf", ".xlsx", ".docx", ".pptx", ".png", "")
REQUIRED_FILENAMES = (".env", "name.", "README", "archive.tar.gz")
LARGE_COHORT_ID = "atlas-orion-reports-103"
LARGE_COHORT_MINIMUM = 100
MARKER_FIELDS = ("marker_id", "level_id", "level_name", "raw_value", "display_value", "kind")
MARKER_KINDS = ("VALUE", "UNRECOGNIZED")


class MarkerModelError(Exception):
    """Raised when the declared marker model cannot be expanded safely."""


def repo_root() -> Path:
    """Repository root, derived from this module's location."""
    return Path(__file__).resolve().parents[3]


def manifest_path(root: Optional[Path] = None) -> Path:
    return (root or repo_root()) / MANIFEST_RELATIVE


def load_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_manifest(path: Optional[str | Path] = None) -> Dict[str, Any]:
    target = Path(path) if path is not None else manifest_path()
    return load_json(target)


def load_corpus(manifest: Dict[str, Any], root: Optional[Path] = None) -> Dict[str, Any]:
    base = root or repo_root()
    return load_json(base / manifest["corpus"]["file"])


# --------------------------------------------------------------------------- #
# Marker model: declared root + ancestor contexts
# --------------------------------------------------------------------------- #

def marker_value_index(corpus: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    model = corpus.get("marker_model") or {}
    return {value["value_id"]: value for value in model.get("values", [])}


def _marker_id(root_id: str, path: Tuple[str, ...]) -> str:
    """Derive the stable marker id from the root and the full ancestor path."""
    return "marker-" + root_id + "-" + "-".join(path)


def build_marker_catalog(
    corpus: Dict[str, Any],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, List[str]]]:
    """Expand declared contexts into ``(catalog, context_chains)``.

    ``catalog`` maps ``marker_id`` to the internal marker entry (which carries
    the root and ancestor identity used for validation).  ``context_chains``
    maps a declared ``context_id`` to the ordered marker ids of its full chain.
    """
    model = corpus.get("marker_model") or {}
    levels = model.get("levels") or {}
    values = marker_value_index(corpus)
    catalog: Dict[str, Dict[str, Any]] = {}
    chains: Dict[str, List[str]] = {}
    seen_contexts: set = set()
    seen_paths: set = set()

    for context in model.get("contexts", []):
        context_id = context["context_id"]
        root_id = context["root_id"]
        path = tuple(context["path"])
        if context_id in seen_contexts:
            raise MarkerModelError(f"duplicate context_id {context_id!r}")
        seen_contexts.add(context_id)
        if not path:
            raise MarkerModelError(f"context {context_id!r} has an empty path")
        if (root_id, path) in seen_paths:
            raise MarkerModelError(f"duplicate context path for root {root_id!r}: {path}")
        seen_paths.add((root_id, path))

        chain: List[str] = []
        for index in range(1, len(path) + 1):
            prefix = path[:index]
            leaf = values.get(prefix[-1])
            if leaf is None:
                raise MarkerModelError(
                    f"context {context_id!r} references unknown value {prefix[-1]!r}"
                )
            marker_id = _marker_id(root_id, prefix)
            entry = {
                "marker_id": marker_id,
                "root_id": root_id,
                "parents": [
                    {
                        "level_id": values[parent]["level_id"],
                        "raw_value": values[parent].get("raw_value"),
                    }
                    for parent in prefix[:-1]
                ],
                "level_id": leaf["level_id"],
                "level_name": levels.get(leaf["level_id"], leaf["level_id"]),
                "raw_value": leaf.get("raw_value"),
                "display_value": leaf.get("display_value"),
                "kind": leaf.get("kind", "VALUE"),
            }
            existing = catalog.get(marker_id)
            if existing is not None and existing != entry:
                raise MarkerModelError(
                    f"marker_id {marker_id!r} maps to conflicting marker identities"
                )
            catalog[marker_id] = entry
            chain.append(marker_id)
        chains[context_id] = chain

    identities: Dict[Any, str] = {}
    for marker_id, entry in catalog.items():
        identity = (
            entry["root_id"],
            tuple((parent["level_id"], parent["raw_value"]) for parent in entry["parents"]),
            entry["level_id"],
            entry["raw_value"],
            entry["kind"],
        )
        previous = identities.get(identity)
        if previous is not None and previous != marker_id:
            raise MarkerModelError(
                f"marker identity {identity!r} maps to both {previous!r} and {marker_id!r}"
            )
        identities[identity] = marker_id
    return catalog, chains


def marker_index(corpus: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return build_marker_catalog(corpus)[0]


def marker_payload(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {field: entry[field] for field in MARKER_FIELDS}


def marker_model_errors(corpus: Dict[str, Any]) -> List[str]:
    """Static validation of the declared marker alphabet and contexts."""
    errors: List[str] = []
    model = corpus.get("marker_model") or {}
    levels = model.get("levels") or {}
    values = model.get("values") or []
    contexts = model.get("contexts") or []
    root_ids = {root.get("root_id") for root in corpus.get("roots", [])}
    schema_roots = (corpus.get("schema") or {}).get("roots") or {}

    value_ids = [value.get("value_id") for value in values]
    if len(value_ids) != len(set(value_ids)):
        errors.append("marker_model.values contains duplicate value_id values")
    for value in values:
        value_id = value.get("value_id")
        if value.get("level_id") not in levels:
            errors.append(
                f"marker value {value_id!r} references unknown level {value.get('level_id')!r}"
            )
        if value.get("kind") not in MARKER_KINDS:
            errors.append(f"marker value {value_id!r} has unknown kind {value.get('kind')!r}")
        if value.get("kind") == "UNRECOGNIZED" and value.get("raw_value") is not None:
            errors.append(f"UNRECOGNIZED marker value {value_id!r} must have raw_value null")
        if value.get("kind") == "VALUE" and not value.get("raw_value"):
            errors.append(f"VALUE marker value {value_id!r} must have a raw_value")

    value_index = {value.get("value_id"): value for value in values}
    seen_contexts: set = set()
    seen_paths: set = set()
    for context in contexts:
        context_id = context.get("context_id")
        root_id = context.get("root_id")
        path = context.get("path") or []
        if context_id in seen_contexts:
            errors.append(f"duplicate context_id {context_id!r}")
        seen_contexts.add(context_id)
        if root_id not in root_ids:
            errors.append(f"context {context_id!r} references unknown root {root_id!r}")
        if (root_id, tuple(path)) in seen_paths:
            errors.append(f"duplicate context path for root {root_id!r}: {path}")
        seen_paths.add((root_id, tuple(path)))
        if not path:
            errors.append(f"context {context_id!r} has an empty path")
            continue
        schema_levels = schema_roots.get(root_id, {}).get("levels") or []
        if len(path) > len(schema_levels):
            leaf_value = value_index.get(path[-1], {})
            if leaf_value.get("kind") != "UNRECOGNIZED":
                errors.append(
                    f"context {context_id!r} is deeper than the declared schema for root "
                    f"{root_id!r} ({len(path)} > {len(schema_levels)} levels)"
                )
        for position, value_id in enumerate(path):
            value = value_index.get(value_id)
            if value is None:
                errors.append(f"context {context_id!r} references unknown value {value_id!r}")
                continue
            if position < len(schema_levels) and value["level_id"] != schema_levels[position]:
                errors.append(
                    f"context {context_id!r} value {value_id!r} level {value['level_id']!r} "
                    f"does not match root schema level {schema_levels[position]!r}"
                )
    return errors


def context_reference_errors(
    corpus: Dict[str, Any], chains: Dict[str, List[str]]
) -> List[str]:
    """Report dangling ``marker_context`` references without crashing."""
    errors: List[str] = []

    def check(record: Optional[Dict[str, Any]], label: str) -> None:
        if not record:
            return
        context_id = record.get("marker_context")
        if context_id is not None and context_id not in chains:
            errors.append(f"{label} references unknown marker_context {context_id!r}")

    for record in corpus.get("files", []):
        check(record, record.get("item_id", "file"))
    for cohort in corpus.get("cohorts", []):
        check(cohort, cohort.get("cohort_id", "cohort"))
    for record in corpus.get("service_objects", []):
        check(record, record.get("item_id", "service object"))
    for stage, payload in (corpus.get("lifecycle") or {}).items():
        for side in ("before", "after"):
            check(payload.get(side), f"lifecycle.{stage}.{side}")
    return errors


# --------------------------------------------------------------------------- #
# Deterministic materialization
# --------------------------------------------------------------------------- #

def _default_display_path(corpus: Dict[str, Any], root_id: str, relative_path: str) -> str:
    for root in corpus.get("roots", []):
        if root.get("root_id") == root_id:
            return root["display_prefix"].rstrip("/") + "/" + relative_path
    raise KeyError(f"unknown root_id {root_id!r} in corpus")


def materialize_record(
    corpus: Dict[str, Any],
    catalog: Dict[str, Dict[str, Any]],
    chains: Dict[str, List[str]],
    record: Dict[str, Any],
) -> Dict[str, Any]:
    """Turn one compact corpus record into a plain ``SearchItem`` payload."""
    root_id = record["root_id"]
    relative_path = record["relative_path"]
    filename = record.get("filename") or relative_path.rsplit("/", 1)[-1]
    display_path = record.get("display_path") or _default_display_path(
        corpus, root_id, relative_path
    )
    defaults = corpus.get("defaults", {})
    context_id = record.get("marker_context")
    marker_ids: List[str] = []
    if context_id:
        if context_id not in chains:
            raise MarkerModelError(
                f"record {record.get('item_id')!r} references unknown marker_context {context_id!r}"
            )
        marker_ids = chains[context_id]
    return {
        "item_id": record["item_id"],
        "location": {
            "root_id": root_id,
            "relative_path": relative_path,
            "display_path": display_path,
        },
        "filename": filename,
        "markers": [marker_payload(catalog[marker_id]) for marker_id in marker_ids],
        "extension": record.get("extension", ""),
        "size_bytes": record.get("size_bytes", defaults.get("size_bytes", 0)),
        "modified_at": record.get("modified_at", defaults.get("modified_at")),
        "structure_status": record.get(
            "structure_status", defaults.get("structure_status", "VALID")
        ),
        "structure_issue": record.get("structure_issue"),
    }


def expand_cohort(corpus: Dict[str, Any], cohort: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Expand an explicit ID/range template into compact records.

    The expansion is a literal ``{index}`` substitution only; it performs no
    matching and makes no business decision.
    """
    pad = int(cohort.get("index_pad", 4))
    start = int(cohort.get("index_start", 1))
    records: List[Dict[str, Any]] = []
    for offset in range(int(cohort["count"])):
        index = str(start + offset).zfill(pad)

        def expand(pattern: Optional[str]) -> Optional[str]:
            return pattern.replace("{index}", index) if pattern else None

        records.append(
            {
                "item_id": expand(cohort["item_id_pattern"]),
                "root_id": cohort["root_id"],
                "relative_path": expand(cohort["relative_path_pattern"]),
                "filename": expand(cohort.get("filename_pattern")),
                "display_path": expand(cohort.get("display_path_pattern")),
                "extension": cohort.get("extension", ""),
                "size_bytes": cohort.get("size_bytes", corpus.get("defaults", {}).get("size_bytes", 0)),
                "modified_at": cohort.get("modified_at", corpus.get("defaults", {}).get("modified_at")),
                "marker_context": cohort.get("marker_context"),
            }
        )
    return records


def materialize(corpus: Dict[str, Any]) -> Dict[str, Any]:
    """Materialize the corpus into plain JSON ``SearchItem`` payloads."""
    catalog, chains = build_marker_catalog(corpus)
    files = [
        materialize_record(corpus, catalog, chains, record)
        for record in corpus.get("files", [])
    ]
    for cohort in corpus.get("cohorts", []):
        for record in expand_cohort(corpus, cohort):
            files.append(materialize_record(corpus, catalog, chains, record))
    service_objects = [
        materialize_record(corpus, catalog, chains, record)
        for record in corpus.get("service_objects", [])
    ]
    return {"files": files, "service_objects": service_objects}


def inventory(corpus: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Searchable inventory: materialized files excluding service objects."""
    return materialize(corpus)["files"]


def materialize_lifecycle(corpus: Dict[str, Any]) -> Dict[str, Any]:
    catalog, chains = build_marker_catalog(corpus)
    out: Dict[str, Any] = {}
    for stage, payload in (corpus.get("lifecycle") or {}).items():
        before = payload.get("before")
        after = payload.get("after")
        out[stage] = {
            "item_id": payload["item_id"],
            "before": materialize_record(corpus, catalog, chains, before) if before else None,
            "after": materialize_record(corpus, catalog, chains, after) if after else None,
        }
    return out


# --------------------------------------------------------------------------- #
# Integrity checks
# --------------------------------------------------------------------------- #

def _referenced_item_ids(node: Any) -> List[str]:
    found: List[str] = []
    if isinstance(node, dict):
        for value in node.values():
            found.extend(_referenced_item_ids(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_referenced_item_ids(value))
    elif isinstance(node, str) and (
        node.startswith("file-") or node.startswith("service-")
    ):
        found.append(node)
    return found


def _referenced_contexts(corpus: Dict[str, Any]) -> set:
    referenced: set = set()

    def collect(record: Optional[Dict[str, Any]]) -> None:
        if record and record.get("marker_context"):
            referenced.add(record["marker_context"])

    for record in corpus.get("files", []):
        collect(record)
    for cohort in corpus.get("cohorts", []):
        collect(cohort)
    for record in corpus.get("service_objects", []):
        collect(record)
    for payload in (corpus.get("lifecycle") or {}).values():
        collect(payload.get("before"))
        collect(payload.get("after"))
    return referenced


def path_marker_errors(
    item: Dict[str, Any], label: Optional[str] = None
) -> List[str]:
    """Assert recognized VALUE markers equal the leading path segments.

    This is a *fixture consistency* assertion, not a parser that generates
    golden values: it checks the already-materialized ``markers`` against the
    already-declared ``relative_path`` (case-sensitive, canonical ``/``).  The
    filename segment is excluded; a structural deviation may leave additional
    trailing segments after the recognized prefix.
    """
    errors: List[str] = []
    name = label or item.get("item_id", "record")
    relative_path = item.get("location", {}).get("relative_path", "")
    leading = relative_path.split("/")[:-1]
    markers = item.get("markers", [])
    if len(markers) > len(leading):
        errors.append(
            f"{name}: {len(markers)} recognized marker(s) exceed the "
            f"{len(leading)} leading path segment(s)"
        )
        return errors
    for index, marker in enumerate(markers):
        if marker.get("raw_value") != leading[index]:
            errors.append(
                f"{name}: marker {marker.get('marker_id')!r} raw "
                f"{marker.get('raw_value')!r} does not match path segment "
                f"{leading[index]!r} at position {index}"
            )
    return errors


def _all_path_marker_errors(
    materialized: Dict[str, Any], lifecycle: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    for item in materialized["files"] + materialized["service_objects"]:
        errors.extend(path_marker_errors(item))
    for stage, payload in lifecycle.items():
        for side in ("before", "after"):
            state = payload.get(side)
            if state is not None:
                errors.extend(path_marker_errors(state, label=f"lifecycle.{stage}.{side}"))
    return errors


def integrity_errors(
    corpus: Dict[str, Any],
    materialized: Optional[Dict[str, Any]] = None,
    lifecycle: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Return every violation of the LT-03.1a corpus acceptance invariants."""
    errors: List[str] = []

    for key in ("fixture_set", "version", "seed", "contract_version"):
        if not corpus.get(key):
            errors.append(f"corpus is missing {key!r}")

    roots = corpus.get("roots") or []
    root_ids = [root.get("root_id") for root in roots]
    if len(roots) != 2:
        errors.append(f"corpus must declare exactly two logical roots, found {len(roots)}")
    if len(set(root_ids)) != len(root_ids):
        errors.append(f"root_id values are not unique: {root_ids}")
    for root in roots:
        for key in (
            "root_id",
            "label",
            "display_prefix",
            "schema_set_version",
            "index_generation",
            "indexed_at",
        ):
            if not root.get(key):
                errors.append(f"root {root.get('root_id')!r} is missing {key!r}")

    schema_roots = (corpus.get("schema") or {}).get("roots") or {}
    if set(schema_roots) != set(root_ids):
        errors.append("schema.roots keys do not match the declared root_id values")

    companies = corpus.get("companies") or []
    if {company.get("name") for company in companies} != {"Atlas", "Nova"}:
        errors.append("corpus must declare the synthetic companies Atlas and Nova")
    for company in companies:
        for key in ("company_id", "name", "incoming_source_ids"):
            if key not in company:
                errors.append(f"company {company.get('company_id')!r} is missing {key!r}")

    model_errors = marker_model_errors(corpus)
    errors.extend(model_errors)
    if model_errors:
        return errors

    try:
        catalog, chains = build_marker_catalog(corpus)
    except MarkerModelError as exc:
        errors.append(str(exc))
        return errors

    reference_errors = context_reference_errors(corpus, chains)
    errors.extend(reference_errors)
    if reference_errors:
        return errors

    referenced_contexts = _referenced_contexts(corpus)
    for context in (corpus.get("marker_model") or {}).get("contexts", []):
        leaf_value = marker_value_index(corpus).get(context["path"][-1], {})
        if leaf_value.get("kind") == "VALUE" and context["context_id"] not in referenced_contexts:
            errors.append(
                f"VALUE context {context['context_id']!r} is not referenced by any corpus object"
            )
    used_values = {
        value_id
        for context in (corpus.get("marker_model") or {}).get("contexts", [])
        for value_id in context["path"]
    }
    for value in (corpus.get("marker_model") or {}).get("values", []):
        if value["value_id"] not in used_values:
            errors.append(f"marker value {value['value_id']!r} is not used by any context")

    try:
        materialized = materialized if materialized is not None else materialize(corpus)
        lifecycle = lifecycle if lifecycle is not None else materialize_lifecycle(corpus)
    except MarkerModelError as exc:
        errors.append(str(exc))
        return errors

    files = materialized["files"]
    services = materialized["service_objects"]
    errors.extend(_all_path_marker_errors(materialized, lifecycle))
    known_ids = [item["item_id"] for item in files] + [item["item_id"] for item in services]
    if len(known_ids) != len(set(known_ids)):
        duplicates = sorted({item_id for item_id in known_ids if known_ids.count(item_id) > 1})
        errors.append(f"item_id values are not unique across the corpus: {duplicates}")
    known = set(known_ids)

    for item in files:
        root_id = item["location"]["root_id"]
        if root_id not in root_ids:
            errors.append(f"{item['item_id']}: unknown root_id {root_id!r}")

    by_root: Dict[str, set] = {root_id: set() for root_id in root_ids}
    for item in files:
        by_root.setdefault(item["location"]["root_id"], set()).add(item["item_id"])
    for root_id, ids in by_root.items():
        if not ids:
            errors.append(f"root {root_id!r} has no searchable files")
    if len(by_root) == 2:
        (first, second) = sorted(by_root)
        if by_root[first] & by_root[second]:
            errors.append("logical roots share file item_ids and are not disjoint")

    inventory_paths = {item["location"]["relative_path"] for item in files}
    for service in services:
        if service["item_id"] in {item["item_id"] for item in files}:
            errors.append(f"service object {service['item_id']!r} leaks into the inventory")
        if service["location"]["relative_path"] in inventory_paths:
            errors.append(
                f"service path {service['location']['relative_path']!r} leaks into the inventory"
            )

    # Raw-case variants: same level/ancestry/lowercased raw, distinct ids.
    case_groups: Dict[Any, set] = {}
    for entry in catalog.values():
        if entry["kind"] != "VALUE":
            continue
        key = (
            entry["root_id"],
            tuple((parent["level_id"], parent["raw_value"]) for parent in entry["parents"]),
            entry["level_id"],
            entry["raw_value"].lower(),
        )
        case_groups.setdefault(key, set()).add(entry["marker_id"])
    if not any(len(ids) > 1 for ids in case_groups.values()):
        errors.append("no raw-case marker variants with distinct ids are declared")
    section_ids = {
        entry["marker_id"]
        for entry in catalog.values()
        if entry["level_id"] == "level-section" and entry["raw_value"] == "Archive"
    }
    if len(section_ids) < 2:
        errors.append("the same Archive section marker id is reused across roots")

    # Structural issues: all four kinds with first-deviation metadata.
    issue_codes: Dict[str, List[Dict[str, Any]]] = {}
    root_levels = {root_id: schema_roots[root_id]["levels"] for root_id in schema_roots}
    for item in files:
        if item["structure_status"] != "UNRECOGNIZED":
            continue
        issue = item.get("structure_issue")
        if not issue:
            errors.append(f"{item['item_id']}: UNRECOGNIZED without structure_issue")
            continue
        for key in ("level_name", "code", "message"):
            if not issue.get(key):
                errors.append(f"{item['item_id']}: structure_issue is missing {key!r}")
        if issue.get("code") not in STRUCTURE_ISSUE_CODES:
            errors.append(f"{item['item_id']}: unknown structure issue code {issue.get('code')!r}")
        issue_codes.setdefault(issue.get("code"), []).append(item)
        levels = root_levels[item["location"]["root_id"]]
        marker_levels = [marker["level_id"] for marker in item["markers"]]
        if marker_levels != levels[: len(marker_levels)]:
            errors.append(
                f"{item['item_id']}: recognized markers are not a prefix of the schema levels"
            )
    for code in STRUCTURE_ISSUE_CODES:
        if not issue_codes.get(code):
            errors.append(f"no corpus file exercises structure issue {code}")

    # File type / name coverage.
    extensions = {item["extension"] for item in files}
    for extension in REQUIRED_EXTENSIONS:
        if extension not in extensions:
            errors.append(f"no corpus file has extension {extension!r}")
    filenames = {item["filename"] for item in files}
    for name in REQUIRED_FILENAMES:
        if name not in filenames:
            errors.append(f"no corpus file is named {name!r}")
    if not any(item["size_bytes"] == 0 for item in files):
        errors.append("no zero-byte corpus file is present")
    if not any(item["extension"] == ".TXT" for item in files):
        errors.append("no corpus file keeps the original upper-case .TXT extension")

    # Large finite branch.
    cohort_counts = {cohort["cohort_id"]: int(cohort["count"]) for cohort in corpus.get("cohorts", [])}
    if cohort_counts.get(LARGE_COHORT_ID, 0) != 103:
        errors.append(
            f"cohort {LARGE_COHORT_ID!r} must contain exactly 103 files, "
            f"found {cohort_counts.get(LARGE_COHORT_ID)!r}"
        )
    if not any(count > LARGE_COHORT_MINIMUM for count in cohort_counts.values()):
        errors.append(f"no cohort exceeds the {LARGE_COHORT_MINIMUM} display limit")

    # Controls, lifecycle and prepared search inputs must reference real items.
    controls = corpus.get("controls") or {}
    for group in ("content_only", "old_path"):
        for entry in controls.get(group, []):
            if entry.get("item_id") not in known:
                errors.append(f"controls.{group} references unknown item_id {entry.get('item_id')!r}")

    for stage in REQUIRED_LIFECYCLE_STAGES:
        if stage not in lifecycle:
            errors.append(f"lifecycle stage {stage!r} is missing")
    for stage, payload in lifecycle.items():
        stage_id = payload.get("item_id")
        if not stage_id:
            errors.append(f"lifecycle.{stage} has no item_id")
            continue
        if stage != "create" and payload.get("before") is None:
            errors.append(f"lifecycle.{stage} must carry a before state")
        if stage != "delete" and payload.get("after") is None:
            errors.append(f"lifecycle.{stage} must carry an after state")
        if stage == "create" and payload.get("before") is not None:
            errors.append("lifecycle.create must not carry a before state")
        if stage == "delete" and payload.get("after") is not None:
            errors.append("lifecycle.delete must not carry an after state")
        for side in ("before", "after"):
            state = payload.get(side)
            if state is not None and state.get("item_id") != stage_id:
                errors.append(
                    f"lifecycle.{stage}.{side} item_id {state.get('item_id')!r} "
                    f"does not match stage item_id {stage_id!r}"
                )

    for reference in _referenced_item_ids(corpus.get("search_inputs") or {}):
        if reference not in known:
            errors.append(f"search_inputs references unknown item_id {reference!r}")

    return errors


# --------------------------------------------------------------------------- #
# Checksums (canonical JSON, independent of checkout line endings)
# --------------------------------------------------------------------------- #

def content_hash(path: str | Path) -> str:
    """Hash JSON content canonically so LF/CRLF checkouts hash identically.

    Non-JSON payloads fall back to raw bytes.  The canonical form is the parsed
    value re-serialized with sorted keys, no insignificant whitespace and UTF-8
    encoding, so the digest depends only on the JSON meaning.
    """
    data = Path(path).read_bytes()
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return hashlib.sha256(data).hexdigest()
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def compute_checksums(manifest: Dict[str, Any], root: Optional[Path] = None) -> Dict[str, Any]:
    """Recompute the stable canonical-JSON sha256 checksums of the manifest."""
    base = root or repo_root()
    corpus_hash = content_hash(base / manifest["corpus"]["file"])
    examples = {
        entry["id"]: content_hash(base / entry["file"])
        for entry in manifest.get("examples", [])
    }
    combined_input = (
        f"fixture_set={manifest['fixture_set']}\n"
        f"version={manifest['version']}\n"
        f"seed={manifest['seed']}\n"
        f"corpus={corpus_hash}\n"
    )
    for entry in manifest.get("examples", []):
        combined_input += f"{entry['id']}={examples[entry['id']]}\n"
    return {
        "algorithm": "sha256",
        "canonicalization": "json.dumps(parse(content), sort_keys=True, separators=(',', ':'), ensure_ascii=False)",
        "corpus": corpus_hash,
        "examples": examples,
        "combined": hashlib.sha256(combined_input.encode("utf-8")).hexdigest(),
    }


def materialized_document(corpus: Dict[str, Any]) -> Dict[str, Any]:
    """The plain JSON payload written by ``--write`` for mocks/consumers."""
    materialized = materialize(corpus)
    return {
        "fixture_set": corpus["fixture_set"],
        "version": corpus["version"],
        "seed": corpus["seed"],
        "files": materialized["files"],
        "service_objects": materialized["service_objects"],
        "lifecycle": materialize_lifecycle(corpus),
    }


# --------------------------------------------------------------------------- #
# Documented fixture-preparation command
# --------------------------------------------------------------------------- #

def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize the WiseWay synthetic corpus.")
    parser.add_argument("--manifest", default=str(manifest_path()))
    parser.add_argument("--write", help="Write the materialized plain JSON payload to this path.")
    parser.add_argument(
        "--update-checksums",
        action="store_true",
        help="Recompute and persist manifest.checksum in place.",
    )
    args = parser.parse_args(argv)

    manifest_file = Path(args.manifest)
    manifest = load_manifest(manifest_file)
    root = manifest_file.resolve().parents[2]
    corpus = load_corpus(manifest, root)
    errors = integrity_errors(corpus)
    if errors:
        for message in errors:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1

    if args.write:
        target = Path(args.write)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(materialized_document(corpus), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print(f"wrote {target}")

    if args.update_checksums:
        checksum = manifest.get("checksum") or {}
        checksum.update(compute_checksums(manifest, root))
        manifest["checksum"] = checksum
        with open(manifest_file, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print(f"updated checksums in {manifest_file}")

    materialized = materialize(corpus)
    print(
        f"corpus {corpus['fixture_set']} v{corpus['version']} seed={corpus['seed']}: "
        f"{len(materialized['files'])} searchable file(s), "
        f"{len(materialized['service_objects'])} service object(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
