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

from . import batch_outcomes, batch_scenarios, dictionary_lifecycle, preview_preflight, queue_selections, rule_expectations, search_expectations, synthetic
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
    _run_dictionary_lifecycle(report, registry, base)
    _run_queue_selections(report, registry, base)
    _run_preview_preflight(report, registry, base)
    _run_batch_outcomes(report, registry, base)
    _run_batch_scenarios(report, registry, base)


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


def _run_dictionary_lifecycle(report, registry, base: Path) -> None:
    """LT-03.2b: literal dictionary lifecycle oracle and generated examples."""
    lifecycle_check = report.check(
        "FIX-DLC-001",
        "Dictionary lifecycle expectations materialize to schema-valid literal "
        "payloads and satisfy the finite draft/simulation/publication invariants",
    )
    request_check = report.check(
        "FIX-DLC-002",
        "Every lifecycle failure request is schema-classified (valid or explicitly rejected)",
    )
    examples_check = report.check(
        "FIX-DLC-003",
        "Generated public dictionary/simulation/error examples match the committed files",
    )
    try:
        expectations = dictionary_lifecycle.load_expectations(base)
        context = dictionary_lifecycle.build_context(base, expectations)
    except Exception as exc:  # noqa: BLE001 - report unreadable expectations
        lifecycle_check.add(
            f"cannot load dictionary lifecycle expectations: {type(exc).__name__}: {exc}"
        )
        return

    for message in dictionary_lifecycle.expectation_errors(expectations, context):
        lifecycle_check.add(message)
    for message in dictionary_lifecycle.request_rejection_errors(
        expectations, context, registry
    ):
        request_check.add(message)

    for state in expectations.get("states", []):
        payload = dictionary_lifecycle.materialize_dictionary(state, context)
        schema_errors, semantic = validate_fixture(
            registry, dictionary_lifecycle.DICTIONARY_SCHEMA, payload
        )
        for message in schema_errors + semantic:
            lifecycle_check.add(message, state["state_id"])
    for version in expectations.get("versions", []):
        payload = dictionary_lifecycle.materialize_version(
            context["versions"][version["version_id"]], context
        )
        schema_errors, semantic = validate_fixture(
            registry, dictionary_lifecycle.DICTIONARY_VERSION_SCHEMA, payload
        )
        for message in schema_errors + semantic:
            lifecycle_check.add(message, version["version_id"])
    for simulation in expectations.get("simulations", []):
        payload = dictionary_lifecycle.materialize_simulation(simulation, context)
        schema_errors, semantic = validate_fixture(
            registry, dictionary_lifecycle.SIMULATION_SCHEMA, payload
        )
        for message in schema_errors + semantic:
            lifecycle_check.add(message, simulation["page_id"])
    for publish in expectations.get("publishes", []):
        payload = dictionary_lifecycle.materialize_publish(publish, context)
        schema_errors, semantic = validate_fixture(
            registry, dictionary_lifecycle.PUBLISH_SCHEMA, payload
        )
        for message in schema_errors + semantic:
            lifecycle_check.add(message, publish["publish_id"])
    for page in expectations.get("version_pages", []):
        payload = dictionary_lifecycle.materialize_page_versions(page, context)
        schema_errors, semantic = validate_fixture(
            registry, dictionary_lifecycle.PAGE_VERSION_SCHEMA, payload
        )
        for message in schema_errors + semantic:
            lifecycle_check.add(message, page["page_id"])
    for failure in expectations.get("failures", []):
        payload = dictionary_lifecycle.materialize_error(failure)
        schema_errors, semantic = validate_fixture(
            registry, dictionary_lifecycle.ERROR_SCHEMA, payload
        )
        for message in schema_errors + semantic:
            lifecycle_check.add(message, failure["failure_id"])

    report.lifecycle_timeline = len(expectations.get("timeline", []))
    report.lifecycle_failures = len(expectations.get("failures", []))
    report.lifecycle_replays = len(expectations.get("replays", []))
    report.lifecycle_simulations = len(expectations.get("simulations", []))
    report.lifecycle_publishes = len(expectations.get("publishes", []))

    try:
        generated = dictionary_lifecycle.generated_examples(expectations, context)
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


def _run_queue_selections(report, registry, base: Path) -> None:
    """LT-03.3a: literal queue/readiness/selection oracle and generated examples."""
    oracle_check = report.check(
        "FIX-QUEUE-001",
        "Queue/selection/readiness expectations materialize to schema-valid literal "
        "payloads and satisfy the finite queue/snapshot invariants",
    )
    mutation_check = report.check(
        "FIX-QUEUE-002",
        "Invalid request payloads are classified and declared domain mutations are "
        "rejected by the consistency validators",
    )
    examples_check = report.check(
        "FIX-QUEUE-003",
        "Generated public sorting/error examples match the committed files",
    )
    try:
        expectations = queue_selections.load_expectations(base)
        context = queue_selections.build_context(base, expectations)
    except Exception as exc:  # noqa: BLE001 - report unreadable expectations
        oracle_check.add(
            f"cannot load queue/selection expectations: {type(exc).__name__}: {exc}"
        )
        return

    for message in queue_selections.expectation_errors(expectations, context):
        oracle_check.add(message)
    for message in queue_selections.error_operation_errors(expectations, context):
        oracle_check.add(message)
    for message in queue_selections.payload_errors(expectations, context, registry):
        oracle_check.add(message)
    for message in queue_selections.schema_rejection_errors(expectations, registry):
        mutation_check.add(message)
    for message in queue_selections.mutation_errors(expectations, context):
        mutation_check.add(message)

    report.queue_profiles = len(expectations.get("profiles", []))
    report.queue_queries = sum(
        len(profile.get("queries", [])) for profile in expectations.get("profiles", [])
    )
    report.selection_scenarios = len(expectations.get("selection_scenarios", []))
    report.selection_errors = len(expectations.get("selection_errors", []))
    report.readiness_sequences = len(
        (expectations.get("readiness") or {}).get("items", [])
    )
    report.ownership_scenarios = len(expectations.get("ownership", []))
    report.queue_links = len(expectations.get("links", []))
    report.queue_mutations = len(expectations.get("mutations", []))

    try:
        generated = queue_selections.generated_examples(expectations, context)
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


def _run_preview_preflight(report, registry, base: Path) -> None:
    """LT-03.3b: literal preview/preflight oracle and generated examples."""
    oracle_check = report.check(
        "FIX-PREVIEW-001",
        "Preview/preflight expectations materialize to schema-valid literal "
        "payloads and satisfy the finite preview/collision/preflight invariants",
    )
    request_check = report.check(
        "FIX-PREVIEW-002",
        "Batch/preview requests are schema-classified and declared negative "
        "mutations are rejected by the consistency validators",
    )
    examples_check = report.check(
        "FIX-PREVIEW-003",
        "Generated public preview/error examples match the committed files",
    )
    try:
        expectations = preview_preflight.load_expectations(base)
        context = preview_preflight.build_context(base, expectations)
    except Exception as exc:  # noqa: BLE001 - report unreadable expectations
        oracle_check.add(
            f"cannot load preview/preflight expectations: {type(exc).__name__}: {exc}"
        )
        return

    for message in preview_preflight.expectation_errors(expectations, context):
        oracle_check.add(message)
    for message in preview_preflight.coverage_errors(expectations, context):
        oracle_check.add(message)
    for message in preview_preflight.payload_errors(expectations, context, registry):
        oracle_check.add(message)
    for message in preview_preflight.request_schema_errors(
        expectations, context, registry
    ):
        request_check.add(message)
    for message in preview_preflight.schema_rejection_errors(expectations, registry):
        request_check.add(message)
    for message in preview_preflight.mutation_errors(expectations, context, registry):
        request_check.add(message)
    for message in preview_preflight.link_errors(expectations, context):
        oracle_check.add(message)

    report.preview_scenarios = len(context["preview_groups"])
    report.preview_rows = sum(
        len(preview_preflight.row_specs(entry)) for entry in expectations["previews"]
    )
    report.preflight_scenarios = len(expectations["preflight"])
    report.preflight_failures = sum(
        1 for entry in expectations["preflight"] if not entry["expected"]["accepted"]
    )
    report.post_acceptance_outcomes = len(expectations["post_acceptance"])

    try:
        generated = preview_preflight.generated_examples(expectations, context)
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


def _run_batch_outcomes(report, registry, base: Path) -> None:
    """LT-03.4a: literal batch/outcome oracle and generated examples."""
    oracle_check = report.check(
        "FIX-BATCH-001",
        "Batch/outcome expectations materialize to schema-valid literal payloads "
        "and satisfy the finite state/reason/placement/count/pagination invariants",
    )
    mutation_check = report.check(
        "FIX-BATCH-002",
        "Declared batch/outcome negative mutations are rejected by the "
        "consistency validators",
    )
    examples_check = report.check(
        "FIX-BATCH-003",
        "Generated public batch/outcome examples match the committed files",
    )
    try:
        expectations = batch_outcomes.load_expectations(base)
        context = batch_outcomes.build_context(base, expectations)
    except Exception as exc:  # noqa: BLE001 - report unreadable expectations
        oracle_check.add(
            f"cannot load batch/outcome expectations: {type(exc).__name__}: {exc}"
        )
        return

    for message in batch_outcomes.expectation_errors(expectations, context):
        oracle_check.add(message)
    for message in batch_outcomes.payload_errors(expectations, context, registry):
        oracle_check.add(message)
    for message in batch_outcomes.inventory_errors(expectations, context):
        oracle_check.add(message)
    for message in batch_outcomes.link_errors(expectations, context):
        oracle_check.add(message)
    for message in batch_outcomes.mutation_errors(expectations, context, registry):
        mutation_check.add(message)

    report.batch_scenarios = len(expectations["batches"])
    report.batch_pages = sum(len(batch["pages"]) for batch in expectations["batches"])
    report.batch_outcomes = sum(
        len(batch_outcomes.row_specs(page))
        for batch in expectations["batches"]
        for page in batch["pages"]
    )
    report.batch_summaries = sum(len(page["batch_ids"]) for page in expectations["history"])
    report.batch_mutations = len(expectations["mutations"])
    report.batch_links = len(expectations["links"])

    try:
        generated = batch_outcomes.generated_examples(expectations, context)
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


def _run_batch_scenarios(report, registry, base: Path) -> None:
    """LT-03.4b: literal operational retry/overlap/restart scenario oracle."""
    oracle_check = report.check(
        "FIX-SCN-001",
        "Operational batch scenarios materialize to schema-valid literal requests/"
        "responses and satisfy the finite idempotency/overlap/restart invariants",
    )
    mutation_check = report.check(
        "FIX-SCN-002",
        "Declared batch-scenario negative mutations are rejected by the "
        "consistency validators",
    )
    examples_check = report.check(
        "FIX-SCN-003",
        "Generated public overlap batch examples match the committed files",
    )
    try:
        expectations = batch_scenarios.load_expectations(base)
        context = batch_scenarios.build_context(base, expectations)
    except Exception as exc:  # noqa: BLE001 - report unreadable expectations
        oracle_check.add(
            f"cannot load batch-scenario expectations: {type(exc).__name__}: {exc}"
        )
        return

    for message in batch_scenarios.expectation_errors(expectations, context):
        oracle_check.add(message)
    for message in batch_scenarios.identity_errors(expectations, context):
        oracle_check.add(message)
    for message in batch_scenarios.inventory_errors(expectations, context):
        oracle_check.add(message)
    for message in batch_scenarios.payload_errors(expectations, context, registry):
        oracle_check.add(message)
    for message in batch_scenarios.link_errors(expectations, context):
        oracle_check.add(message)
    for message in batch_scenarios.mutation_errors(expectations, context, registry):
        mutation_check.add(message)

    report.scenario_scenarios = len(expectations["scenarios"])
    report.scenario_replays = sum(
        len(scenario.get("replays", [])) for scenario in expectations["scenarios"]
    )
    report.scenario_containment = len(context["containment"])
    report.scenario_audit = len(expectations["audit_expectations"])
    report.scenario_mutations = len(expectations["mutations"])
    report.scenario_links = len(expectations["links"])

    try:
        generated = batch_scenarios.generated_examples(expectations, context)
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
