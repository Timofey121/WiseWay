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

from . import rule_expectations, search_expectations, synthetic
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
    _run_search_expectations(report, registry, base)
    _run_rule_expectations(report, registry, base)


def _run_search_expectations(report, registry, base: Path) -> None:
    """LT-03.1b: literal search/facet/auth/error oracle and generated examples."""
    search_check = report.check(
        "FIX-SRCH-001",
        "Search/facet/auth/error expectations materialize to schema-valid literal responses",
    )
    examples_check = report.check(
        "FIX-SRCH-002",
        "Generated public search/error examples match the committed files",
    )
    try:
        expectations = search_expectations.load_expectations(base)
        context = search_expectations.build_context(base)
    except Exception as exc:  # noqa: BLE001 - report unreadable expectations
        search_check.add(f"cannot load search expectations: {type(exc).__name__}: {exc}")
        return

    for message in search_expectations.expectation_errors(expectations, context):
        search_check.add(message)

    for scenario in expectations.get("search_scenarios", []):
        payload = search_expectations.materialize_search_response(
            expectations, scenario, context
        )
        schema_errors, semantic = validate_fixture(
            registry, search_expectations.SEARCH_SCHEMA, payload
        )
        for message in schema_errors + semantic:
            search_check.add(message, scenario["scenario_id"])
    for scenario in expectations.get("facet_scenarios", []):
        payload = search_expectations.materialize_facet_response(
            expectations, scenario, context
        )
        schema_errors, semantic = validate_fixture(
            registry, search_expectations.FACET_SCHEMA, payload
        )
        for message in schema_errors + semantic:
            search_check.add(message, scenario["scenario_id"])
    for scenario in expectations.get("error_scenarios", []):
        payload = search_expectations.materialize_error_response(scenario)
        schema_errors, semantic = validate_fixture(
            registry, search_expectations.ERROR_SCHEMA, payload
        )
        for message in schema_errors + semantic:
            search_check.add(message, scenario["scenario_id"])
    for profile in expectations.get("sort_profiles", []):
        for entry in profile.get("inputs", []):
            schema_errors, semantic = validate_fixture(
                registry, search_expectations.SEARCH_ITEM, entry
            )
            for message in schema_errors + semantic:
                search_check.add(message, profile["scenario_id"])

    report.search_scenarios = len(expectations.get("search_scenarios", []))
    report.facet_scenarios = len(expectations.get("facet_scenarios", []))
    report.error_scenarios = len(expectations.get("error_scenarios", []))
    report.race_scenarios = len(expectations.get("race_scenarios", []))
    report.format_samples = len(expectations.get("format_samples", []))

    try:
        generated = search_expectations.generated_examples(expectations, context)
    except Exception as exc:  # noqa: BLE001
        examples_check.add(f"cannot regenerate examples: {type(exc).__name__}: {exc}")
        return
    for relative, payload in generated.items():
        target = base / relative
        if not target.is_file():
            examples_check.add(f"generated example is missing: {relative}")
            continue
        try:
            committed = synthetic.load_json(target)
        except Exception as exc:  # noqa: BLE001
            examples_check.add(f"cannot parse {relative}: {type(exc).__name__}: {exc}")
            continue
        if committed != payload:
            examples_check.add(f"committed example differs from regeneration: {relative}")


def _run_rule_expectations(report, registry, base: Path) -> None:
    """LT-03.2a: literal rule/target oracle and generated examples."""
    rule_check = report.check(
        "FIX-RULE-001",
        "Rule/target expectations materialize to schema-valid literal payloads "
        "and satisfy the finite rule invariants",
    )
    examples_check = report.check(
        "FIX-RULE-002",
        "Generated public rule/target examples match the committed files",
    )
    try:
        expectations = rule_expectations.load_expectations(base)
        context = rule_expectations.build_context(base, expectations)
    except Exception as exc:  # noqa: BLE001 - report unreadable expectations
        rule_check.add(f"cannot load rule expectations: {type(exc).__name__}: {exc}")
        return

    for message in rule_expectations.expectation_errors(expectations, context):
        rule_check.add(message)
    for message in rule_expectations.schema_rejection_errors(expectations, registry):
        rule_check.add(message)

    for target in expectations.get("target_directories", []):
        payload = rule_expectations.materialize_target_directory(target, context)
        schema_errors, semantic = validate_fixture(
            registry, rule_expectations.TARGET_DIRECTORY_SCHEMA, payload
        )
        for message in schema_errors + semantic:
            rule_check.add(message, target["target_id"])
    for version in expectations.get("versions", []):
        payload = rule_expectations.materialize_version(version, context)
        schema_errors, semantic = validate_fixture(
            registry, rule_expectations.DICTIONARY_VERSION_SCHEMA, payload
        )
        for message in schema_errors + semantic:
            rule_check.add(message, version["version_id"])
    for scenario in expectations.get("rule_scenarios", []):
        payload = rule_expectations.materialize_plan_row(scenario, context)
        schema_errors, semantic = validate_fixture(
            registry, rule_expectations.PLAN_ROW_SCHEMA, payload
        )
        for message in schema_errors + semantic:
            rule_check.add(message, scenario["scenario_id"])

    report.rule_scenarios = len(expectations.get("rule_scenarios", []))
    report.target_scenarios = len(expectations.get("target_scenarios", []))
    report.invalid_rule_cases = len(expectations.get("invalid_rule_cases", []))

    try:
        generated = rule_expectations.generated_examples(expectations, context)
    except Exception as exc:  # noqa: BLE001
        examples_check.add(f"cannot regenerate examples: {type(exc).__name__}: {exc}")
        return
    for relative, payload in generated.items():
        target = base / relative
        if not target.is_file():
            examples_check.add(f"generated example is missing: {relative}")
            continue
        try:
            committed = synthetic.load_json(target)
        except Exception as exc:  # noqa: BLE001
            examples_check.add(f"cannot parse {relative}: {type(exc).__name__}: {exc}")
            continue
        if committed != payload:
            examples_check.add(f"committed example differs from regeneration: {relative}")


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
    declared_fixtures = declared.get("fixtures") or {}
    if set(declared_fixtures) != set(expected["fixtures"]):
        checksum_check.add(
            "checksum.fixtures keys differ from the manifest fixture ids: "
            f"{sorted(set(declared_fixtures) ^ set(expected['fixtures']))}"
        )
    for fixture_id, digest in expected["fixtures"].items():
        if declared_fixtures.get(fixture_id) != digest:
            checksum_check.add(f"checksum for fixture {fixture_id!r} mismatch")
