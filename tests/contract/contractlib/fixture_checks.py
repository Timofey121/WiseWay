"""External synthetic fixture validation for the contract runner.

The canonical OpenAPI document carries embedded examples, but WP-03 publishes
its public API examples as standalone JSON files under ``contracts/examples``
and its metadata corpus under ``fixtures/synthetic``.  This module binds those
files back to the *canonical* OAS schema pointers declared in
``fixtures/synthetic/manifest.json`` and validates every payload with the same
:func:`contractlib.semantic.validate_fixture` used for embedded examples.

No DTO is copied: the manifest stores only the canonical
``#/components/schemas/<Name>`` pointer and a file path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import synthetic
from .semantic import validate_fixture


def run_fixture_checks(report, registry, root: Optional[Path] = None) -> None:
    """Validate the manifest-bound examples, corpus, lifecycle and checksums."""
    example_check = report.check(
        "FIX-EX-001",
        "Every manifest-bound public API example validates against its canonical OAS schema",
    )
    lifecycle_check = report.check(
        "FIX-EX-002",
        "Every lifecycle before/after payload validates against its canonical SearchItem schema",
    )
    corpus_check = report.check(
        "FIX-CORPUS-001",
        "Synthetic corpus satisfies inventory/root/marker/issue acceptance invariants",
    )
    checksum_check = report.check(
        "FIX-CHK-001",
        "Fixture version/seed canonical-JSON checksums match the recomputed manifest",
    )

    base = Path(root) if root is not None else synthetic.repo_root()
    try:
        manifest = synthetic.load_manifest(synthetic.manifest_path(base))
    except Exception as exc:  # noqa: BLE001 - report unreadable fixtures
        example_check.add(f"cannot load fixture manifest: {type(exc).__name__}: {exc}")
        return

    example_count = 0
    for entry in manifest.get("examples", []):
        entry_id = entry.get("id", entry.get("file", ""))
        path = base / entry["file"]
        if not path.is_file():
            example_check.add(f"example file is missing: {entry['file']}", entry_id)
            continue
        try:
            value = synthetic.load_json(path)
        except Exception as exc:  # noqa: BLE001
            example_check.add(
                f"cannot parse {entry['file']}: {type(exc).__name__}: {exc}", entry_id
            )
            continue
        example_count += 1
        schema_errors, semantic = validate_fixture(registry, entry["schema"], value)
        for message in schema_errors:
            example_check.add(f"{message} (schema {entry['schema']})", entry_id)
        for message in semantic:
            example_check.add(message, entry_id)

    report.fixtures_validated = example_count

    try:
        corpus = synthetic.load_corpus(manifest, base)
    except Exception as exc:  # noqa: BLE001
        corpus_check.add(f"cannot load corpus: {type(exc).__name__}: {exc}")
        _check_checksums(checksum_check, manifest, base)
        return

    for message in synthetic.integrity_errors(corpus):
        corpus_check.add(message)

    materialized = None
    try:
        materialized = synthetic.materialize(corpus)
        lifecycle = synthetic.materialize_lifecycle(corpus)
    except synthetic.MarkerModelError as exc:
        corpus_check.add(f"cannot materialize corpus: {exc}")

    if materialized is not None:
        search_item = manifest["corpus"]["schema"]
        for item in materialized["files"] + materialized["service_objects"]:
            schema_errors, semantic = validate_fixture(registry, search_item, item)
            for message in schema_errors:
                corpus_check.add(f"{message} (SearchItem {item.get('item_id')})")
            for message in semantic:
                corpus_check.add(f"{message} ({item.get('item_id')})")
        report.corpus_files = len(materialized["files"])

        lifecycle_count = 0
        for stage, payload in lifecycle.items():
            for side in ("before", "after"):
                state = payload.get(side)
                if state is None:
                    continue
                lifecycle_count += 1
                schema_errors, semantic = validate_fixture(registry, search_item, state)
                for message in schema_errors:
                    lifecycle_check.add(
                        f"{message} ({stage}.{side} {state.get('item_id')})"
                    )
                for message in semantic:
                    lifecycle_check.add(
                        f"{message} ({stage}.{side} {state.get('item_id')})"
                    )
        report.lifecycle_fixtures = lifecycle_count

    _check_checksums(checksum_check, manifest, base)


def _check_checksums(checksum_check, manifest, base: Path) -> None:
    expected = synthetic.compute_checksums(manifest, base)
    declared = manifest.get("checksum") or {}
    for key in ("corpus", "combined"):
        if declared.get(key) != expected.get(key):
            checksum_check.add(
                f"checksum.{key} mismatch: declared {declared.get(key)!r}, "
                f"recomputed {expected.get(key)!r}"
            )
    declared_examples = declared.get("examples") or {}
    if set(declared_examples) != set(expected["examples"]):
        checksum_check.add(
            "checksum.examples keys differ from the manifest example ids: "
            f"{sorted(set(declared_examples) ^ set(expected['examples']))}"
        )
    for example_id, digest in expected["examples"].items():
        if declared_examples.get(example_id) != digest:
            checksum_check.add(f"checksum for example {example_id!r} mismatch")
