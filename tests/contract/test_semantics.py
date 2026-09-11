"""Tests for the semantic consistency invariants (LT-02.2).

Four layers:

1. the real contract must pass the semantic checks and report the full example
   corpus as semantically checked;
2. finite positive/negative fixtures must be schema-valid, and every negative
   fixture must trip exactly the named semantic invariant;
3. targeted mutations of the canonical document must make the specific
   semantic check fail (so the checks are not vacuous), including every
   declared finite link and the global RuleSet consistency;
4. a finite linked fixture pair proves the audit ``QUARANTINE_RETURNED``
   correlation that the canonical examples do not share.
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from contractlib import (  # noqa: E402
    build_registry,
    finite_links,
    iter_example_sites,
    link_errors,
    load_contract,
    parse_pointer,
    resolve_pointer,
    rule_set_consistency_errors,
    run_checks,
    run_semantic_checks,
    semantic_errors,
    validate_fixture,
)
from contractlib.report import Report  # noqa: E402
from fixtures import semantic_fixtures as fixtures  # noqa: E402

REPO_ROOT = HERE.parents[1]
CONTRACT = REPO_ROOT / "contracts" / "openapi" / "wiseway-v1.yaml"

# Canonical example pointers used by the mutation tests.
SEARCH_IDLE = (
    "#/paths/~1search/post/responses/200/content/application~1json/examples/idle"
)
SIMULATION_WILL_MOVE = (
    "#/paths/~1dictionaries~1{dictionary_id}~1simulate/post/responses/201/"
    "content/application~1json/examples/simulation_will_move"
)
BATCH_ACCEPTED = (
    "#/paths/~1sorting~1batches/post/responses/202/content/application~1json/"
    "examples/accepted"
)
BATCH_RUNNING = (
    "#/paths/~1sorting~1batches~1{batch_id}/get/responses/200/content/"
    "application~1json/examples/runningPartial"
)
BATCH_MIXED = (
    "#/paths/~1sorting~1batches~1{batch_id}/get/responses/200/content/"
    "application~1json/examples/mixedTerminalOutcomes"
)
QUARANTINE_LIST = (
    "#/paths/~1quarantine/get/responses/200/content/application~1json/examples/list"
)
SELECTION_EXPLICIT = (
    "#/paths/~1sorting~1selections/post/responses/201/content/application~1json/"
    "examples/explicit"
)
ERROR_RECOVERY = "#/components/examples/ErrorRECOVERY_REQUIRED"


def _example_holder(document, normalized_pointer):
    """Return the example wrapper dict (``{"value": ...}``) to mutate."""
    node = resolve_pointer(document, normalized_pointer)
    if isinstance(node, dict) and "$ref" in node:
        return resolve_pointer(document, node["$ref"])
    return node


def _example_value(document, normalized_pointer):
    holder = _example_holder(document, normalized_pointer)
    if isinstance(holder, dict) and "value" in holder:
        return holder["value"]
    return holder


def _containers(node):
    yield node
    if isinstance(node, dict):
        item = node.get("item")
        if isinstance(item, dict):
            yield item
        items = node.get("items")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            yield items[0]


def _set_field(node, path: Sequence[str], new_value: Any) -> bool:
    if len(path) == 1:
        for container in _containers(node):
            if isinstance(container, dict) and path[0] in container:
                container[path[0]] = new_value
                return True
        return False
    for container in _containers(node):
        if isinstance(container, dict) and path[0] in container:
            return _set_field(container[path[0]], path[1:], new_value)
    return False


def _delete_field(node, path: Sequence[str]) -> bool:
    if len(path) == 1:
        for container in _containers(node):
            if isinstance(container, dict) and path[0] in container:
                del container[path[0]]
                return True
        return False
    for container in _containers(node):
        if isinstance(container, dict) and path[0] in container:
            return _delete_field(container[path[0]], path[1:])
    return False


def _delete_pointer(document, pointer: str) -> None:
    parts = parse_pointer(pointer)
    parent = document
    for token in parts[:-1]:
        parent = parent[int(token)] if isinstance(parent, list) else parent[token]
    last = parts[-1]
    if isinstance(parent, list):
        del parent[int(last)]
    else:
        del parent[last]


def _error_messages(report, check_id) -> List[str]:
    for check in report.checks:
        if check.check_id == check_id:
            return [failure.render() for failure in check.failures]
    return []


class RealContractSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_contract(CONTRACT)
        cls.registry = build_registry(cls.document)
        cls.report = run_checks(cls.document, cls.registry)

    def test_every_check_passes(self):
        self.assertTrue(self.report.ok, self.report.format())

    def test_semantic_checks_are_present_and_pass(self):
        passed = {check.check_id for check in self.report.checks if check.passed}
        self.assertIn("OAS-SEM-001", passed)
        self.assertIn("OAS-SEM-002", passed)
        self.assertIn("OAS-SEM-003", passed)

    def test_every_embedded_example_is_semantically_checked(self):
        sites = list(iter_example_sites(self.document))
        self.assertEqual(len(sites), self.report.semantics_checked)
        self.assertGreaterEqual(self.report.semantics_checked, 100)

    def test_finite_links_cover_the_linked_scenarios(self):
        names = {spec.name for spec in finite_links()}
        self.assertIn("preview-from-selection", names)
        self.assertIn("batch-from-selection", names)
        self.assertIn("batch-from-preview", names)
        self.assertIn("quarantine-return", names)
        self.assertIn("audit-batch-accepted", names)
        self.assertIn("simulation-get-matches-post", names)


class FixtureSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = build_registry(load_contract(CONTRACT))

    def test_every_fixture_is_schema_valid(self):
        for case in fixtures.CASES:
            with self.subTest(case=case.id):
                schema_errors, _ = validate_fixture(self.registry, case.schema, case.value)
                self.assertEqual([], schema_errors, f"{case.id}: {schema_errors}")

    def test_positive_fixtures_pass_semantics(self):
        for case in fixtures.CASES:
            if case.expect != "pass":
                continue
            with self.subTest(case=case.id):
                schema_errors, semantic = validate_fixture(self.registry, case.schema, case.value)
                self.assertEqual([], schema_errors, schema_errors)
                self.assertEqual([], semantic, semantic)

    def test_negative_fixtures_trip_the_named_invariant(self):
        for case in fixtures.CASES:
            if case.expect != "fail":
                continue
            with self.subTest(case=case.id):
                schema_errors, semantic = validate_fixture(self.registry, case.schema, case.value)
                self.assertEqual([], schema_errors, schema_errors)
                self.assertTrue(semantic, f"{case.id}: expected a semantic failure")
                self.assertTrue(
                    any(case.contains in message for message in semantic),
                    f"{case.id}: {case.contains!r} not in {semantic}",
                )

    def test_each_invariant_has_positive_and_negative_coverage(self):
        invariants = {case.invariant for case in fixtures.CASES}
        self.assertGreaterEqual(len(invariants), 10)
        for invariant in sorted(invariants):
            expectations = {
                case.expect for case in fixtures.cases_by_invariant(invariant)
            }
            self.assertEqual(
                {"pass", "fail"}, expectations, f"{invariant} lacks coverage"
            )

    def test_validate_fixture_reuses_the_canonical_schema(self):
        # A shape defect is reported by the schema validator, not the semantics.
        broken = {"filename": "Atlas-1.pdf"}
        schema_errors, semantic = validate_fixture(
            self.registry, "#/components/schemas/FileMetadata", broken
        )
        self.assertTrue(schema_errors)
        self.assertEqual([], semantic)

    def test_batch_outcome_matched_rule_null_version_is_rejected(self):
        # The canonical schema already narrows Outcome.matched_rule.version_id;
        # the semantic rule must also reject a draft reference outside simulation.
        value = fixtures.batch(
            outcomes=[fixtures.outcome(
                matched_rule=fixtures.rule_reference(version_id=None))]
        )
        errors = semantic_errors(value, "#/components/schemas/Batch")
        self.assertTrue(any("published version" in message for message in errors), errors)

    def test_rule_set_consistency_helper(self):
        first = fixtures.rule_set(members=[{"dictionary_id": "d", "version_id": "v1"}])
        same = fixtures.rule_set(members=[{"dictionary_id": "d", "version_id": "v1"}])
        other = fixtures.rule_set(members=[{"dictionary_id": "d", "version_id": "v2"}])
        self.assertEqual([], rule_set_consistency_errors([first, same]))
        self.assertTrue(rule_set_consistency_errors([first, other]))

    def test_linked_pair_quarantine_return_audit(self):
        self.assertEqual(2, len(fixtures.LINKED_PAIRS))
        for pair in fixtures.LINKED_PAIRS:
            with self.subTest(pair=pair.id):
                errors = link_errors(pair.source, pair.target, pair.fields, pair.name)
                if pair.expect == "pass":
                    self.assertEqual([], errors, errors)
                else:
                    self.assertTrue(
                        any(pair.contains in message for message in errors), errors
                    )

    def test_linked_pair_requires_its_fields(self):
        pair = fixtures.LINKED_PAIRS[0]
        broken_source = copy.deepcopy(pair.source)
        del broken_source["quarantine"]["source_attempt_id"]
        errors = link_errors(broken_source, pair.target, pair.fields, pair.name)
        self.assertTrue(any("source field" in message for message in errors), errors)


class MutationTests(unittest.TestCase):
    """Mutating one canonical fact must trip the matching semantic check."""

    @classmethod
    def setUpClass(cls):
        cls.document = load_contract(CONTRACT)
        cls.registry = build_registry(cls.document)

    def _run_semantics(self, mutate):
        document = copy.deepcopy(self.document)
        mutate(document)
        report = Report()
        run_semantic_checks(document, report, self.registry)
        return report

    def _assert_semantic_failure(self, report, check_id, contains):
        self.assertIn(check_id, report.failed_check_ids, report.format())
        messages = _error_messages(report, check_id)
        self.assertTrue(
            any(contains in message for message in messages),
            f"{contains!r} not in {messages}",
        )

    def test_search_idle_facet_mutation(self):
        def mutate(document):
            holder = _example_holder(document, SEARCH_IDLE)
            holder["value"]["next_facet"] = None

        self._assert_semantic_failure(
            self._run_semantics(mutate), "OAS-SEM-001", "IDLE"
        )

    def test_search_returned_count_mutation(self):
        def mutate(document):
            holder = _example_holder(document, SEARCH_IDLE)
            holder["value"].update(
                {
                    "mode": "RESULTS",
                    "applied_query_text": "atlas",
                    "total": 2,
                    "returned_count": 0,
                    "result_limit": 1,
                    "limited": True,
                    "items": [],
                }
            )

        self._assert_semantic_failure(
            self._run_semantics(mutate), "OAS-SEM-001", "returned_count"
        )

    def test_plan_counts_mutation(self):
        def mutate(document):
            holder = _example_holder(document, SIMULATION_WILL_MOVE)
            holder["value"]["total"] = 2

        self._assert_semantic_failure(
            self._run_semantics(mutate), "OAS-SEM-001", "first four"
        )

    def test_batch_completed_count_mutation(self):
        def mutate(document):
            holder = _example_holder(document, BATCH_ACCEPTED)
            holder["value"]["completed_count"] = 1

        self._assert_semantic_failure(
            self._run_semantics(mutate), "OAS-SEM-001", "completed_count"
        )

    def test_batch_outcome_matched_rule_membership_mutation(self):
        def mutate(document):
            holder = _example_holder(document, BATCH_ACCEPTED)
            holder["value"]["outcomes"][0]["matched_rule"]["version_id"] = "version-other"

        self._assert_semantic_failure(
            self._run_semantics(mutate), "OAS-SEM-001", "not a member"
        )

    def test_outcome_placement_mutation(self):
        def mutate(document):
            holder = _example_holder(document, BATCH_MIXED)
            for outcome in holder["value"]["outcomes"]:
                if outcome["state"] == "SKIPPED":
                    outcome["actual_location"] = dict(
                        outcome["source"], relative_path="Archive/Elsewhere/mixed.xlsx"
                    )
                    break

        self._assert_semantic_failure(
            self._run_semantics(mutate), "OAS-SEM-001", "SKIPPED"
        )

    def test_quarantine_can_return_mutation(self):
        def mutate(document):
            holder = _example_holder(document, QUARANTINE_LIST)
            item = holder["value"]["items"][0]
            item["can_return"] = False
            item["recovery_operation_id"] = None

        self._assert_semantic_failure(
            self._run_semantics(mutate), "OAS-SEM-001", "can_return=false"
        )

    def test_error_operation_id_mutation(self):
        def mutate(document):
            holder = _example_holder(document, ERROR_RECOVERY)
            holder["value"]["error"]["operation_id"] = None

        self._assert_semantic_failure(
            self._run_semantics(mutate), "OAS-SEM-001", "registered operation_id"
        )

    def test_rule_set_consistency_mutation(self):
        def mutate(document):
            holder = _example_holder(document, BATCH_RUNNING)
            holder["value"]["rule_set"]["members"][0]["version_id"] = "version-other"

        self._assert_semantic_failure(
            self._run_semantics(mutate), "OAS-SEM-003", "inconsistent"
        )

    def test_link_mutation_preview_from_selection(self):
        def mutate(document):
            holder = _example_holder(document, SELECTION_EXPLICIT)
            holder["value"]["selection_id"] = "selection-other"

        self._assert_semantic_failure(
            self._run_semantics(mutate), "OAS-SEM-002", "preview-from-selection"
        )

    def test_link_mutation_batch_from_preview(self):
        def mutate(document):
            holder = _example_holder(document, BATCH_ACCEPTED)
            holder["value"]["rule_set"]["rule_set_id"] = "ruleset-other"

        self._assert_semantic_failure(
            self._run_semantics(mutate), "OAS-SEM-002", "batch-from-preview"
        )

    # --- parameterized coverage of every declared link --------------------- #

    def test_every_declared_link_detects_field_mismatch(self):
        for spec in finite_links():
            with self.subTest(link=spec.name):
                document = copy.deepcopy(self.document)
                source_value = _example_value(document, spec.source)
                target_value = _example_value(document, spec.target)
                if source_value is target_value:
                    # Both endpoints are the same shared component example; the
                    # endpoint/field tests below still cover this declared link.
                    continue
                target_path = spec.fields[0][1]
                self.assertTrue(
                    _set_field(target_value, target_path, "__link-mismatch__"),
                    f"{spec.name}: could not set {target_path}",
                )
                report = Report()
                run_semantic_checks(document, report, self.registry)
                messages = _error_messages(report, "OAS-SEM-002")
                self.assertTrue(
                    any(spec.name in message for message in messages), messages
                )

    def test_every_declared_link_requires_its_endpoints(self):
        for spec in finite_links():
            with self.subTest(link=spec.name):
                document = copy.deepcopy(self.document)
                _delete_pointer(document, spec.target)
                report = Report()
                run_semantic_checks(document, report, self.registry)
                messages = _error_messages(report, "OAS-SEM-002")
                self.assertTrue(
                    any(spec.name in message and "missing" in message for message in messages),
                    messages,
                )

    def test_every_declared_link_requires_its_fields(self):
        for spec in finite_links():
            with self.subTest(link=spec.name):
                document = copy.deepcopy(self.document)
                target_value = _example_value(document, spec.target)
                target_path = spec.fields[0][1]
                self.assertTrue(
                    _delete_field(target_value, target_path),
                    f"{spec.name}: could not delete {target_path}",
                )
                report = Report()
                run_semantic_checks(document, report, self.registry)
                messages = _error_messages(report, "OAS-SEM-002")
                self.assertTrue(
                    any(spec.name in message and "missing" in message for message in messages),
                    messages,
                )


if __name__ == "__main__":
    unittest.main()
