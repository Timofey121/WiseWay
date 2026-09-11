"""Tests for the LT-03.4a literal batch/outcome expectations.

The expectations are an *independent* oracle: these tests check that the literal
data is internally consistent, schema-valid, fully traced to the matrix Q ids and
that the committed public examples equal the materialized literals.  No test
matches a rule, resolves a priority, derives a target name, counts a page,
executes a file operation or writes a file; the materializer only expands
already-declared literal ids and cross-checks the declared values against the
frozen selection membership and the selected rule's configured target.
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from contractlib import build_registry, load_contract  # noqa: E402
from contractlib import batch_outcomes as bo  # noqa: E402
from contractlib import synthetic  # noqa: E402

REPO_ROOT = HERE.parents[1]
CONTRACT = REPO_ROOT / "contracts" / "openapi" / "wiseway-v1.yaml"

_MISSING = object()


class BatchMixin:
    @classmethod
    def setUpClass(cls):
        cls.registry = build_registry(load_contract(CONTRACT))
        cls.expectations = bo.load_expectations(REPO_ROOT)
        cls.context = bo.build_context(REPO_ROOT, cls.expectations)

    def context_for(self, expectations):
        return bo.build_context(REPO_ROOT, expectations)

    def batch(self, batch_id):
        return self.context["batches"][batch_id]

    def page(self, batch_id, index=0):
        spec = self.batch(batch_id)
        return bo.materialize_batch_page(spec, spec["pages"][index], self.context)

    def outcomes(self, batch_id):
        return bo.all_outcome_payloads(self.batch(batch_id), self.context)

    def outcome(self, batch_id, item_id):
        return next(
            outcome
            for outcome in self.outcomes(batch_id)
            if outcome["item_id"] == item_id
        )

    def all_outcomes(self):
        rows = []
        for batch_spec in self.expectations["batches"]:
            rows.extend(bo.all_outcome_payloads(batch_spec, self.context))
        return rows

    def mutate(self, expectations, operation, path, value=_MISSING):
        mutated = copy.deepcopy(expectations)
        mutation = {"operation": operation, "path": path}
        if value is not _MISSING:
            mutation["value"] = value
        bo._apply_mutation(mutated, mutation)
        return mutated


class OracleStructureTests(BatchMixin, unittest.TestCase):
    def test_expectations_have_no_structural_errors(self):
        self.assertEqual([], bo.expectation_errors(self.expectations, self.context))

    def test_every_payload_materializes_to_a_schema_valid_payload(self):
        self.assertEqual(
            [], bo.payload_errors(self.expectations, self.context, self.registry)
        )

    def test_links_are_consistent(self):
        self.assertEqual([], bo.link_errors(self.expectations, self.context))

    def test_coverage_is_complete_and_resolvable(self):
        self.assertEqual([], bo.coverage_errors(self.expectations, self.context))
        for q_id in bo.KNOWN_Q:
            self.assertIn(q_id, self.expectations["coverage"])

    def test_inventory_contract_is_a_logical_expectation(self):
        self.assertEqual([], bo.inventory_errors(self.expectations, self.context))
        contract = self.expectations["inventory"]
        self.assertEqual("logical-inventory-expectation", contract["kind"])
        self.assertTrue(contract["no_file_writes"])
        self.assertTrue(contract["content_recipe"]["seed"])
        self.assertEqual([], contract.get("existing_objects", []))

    def test_every_generated_example_matches_the_committed_file(self):
        generated = bo.generated_examples(self.expectations, self.context)
        self.assertTrue(generated)
        for relative, payload in generated.items():
            with self.subTest(example=relative):
                committed = synthetic.load_json(REPO_ROOT / relative)
                self.assertEqual(committed, payload)

    def test_every_generated_example_is_bound_in_the_manifest(self):
        manifest = self.context["manifest"]
        bound = {entry["file"]: entry["schema"] for entry in manifest["examples"]}
        for binding in bo.EXAMPLE_BINDINGS:
            self.assertIn(binding["file"], bound)
            self.assertEqual(binding["schema"], bound[binding["file"]])


class StateCoverageTests(BatchMixin, unittest.TestCase):
    def test_all_five_batch_states_appear(self):
        present = {batch["status"] for batch in self.expectations["batches"]}
        self.assertEqual(set(bo.BATCH_STATES), present)

    def test_all_eight_outcome_states_appear(self):
        present = {outcome["state"] for outcome in self.all_outcomes()}
        self.assertEqual(set(bo.OUTCOME_STATES), present)

    def test_all_nine_reason_codes_appear(self):
        present = {outcome["reason_code"] for outcome in self.all_outcomes()}
        present.discard(None)
        self.assertEqual(set(bo.REASON_CODES), present)

    def test_state_and_reason_mapping_is_exact(self):
        expected = {
            "PENDING": {None},
            "PROCESSING": {None},
            "SORTED": {None},
            "MANUAL_REVIEW": {"NO_SCENARIO", "RULE_CONFLICT"},
            "REQUIRES_DECISION": {"TARGET_OCCUPIED", "MANUAL_REVIEW_NAME_OCCUPIED"},
            "QUARANTINED": {"TECHNICAL_ERROR"},
            "SKIPPED": {"ALREADY_PROCESSING", "SOURCE_CHANGED", "SOURCE_MISSING"},
            "RECOVERY_REQUIRED": {"RECOVERY_REQUIRED"},
        }
        seen = {}
        for outcome in self.all_outcomes():
            seen.setdefault(outcome["state"], set()).add(outcome["reason_code"])
        self.assertEqual(expected, seen)


class CountAndPageTests(BatchMixin, unittest.TestCase):
    def test_the_120_item_batches_page_100_then_20(self):
        for batch_id in ("batch-atlas-direct-fresh", "batch-atlas-previewed-fresh"):
            page1 = self.page(batch_id, 0)
            page2 = self.page(batch_id, 1)
            with self.subTest(batch=batch_id):
                self.assertEqual(120, page1["selected_count"])
                self.assertEqual(100, len(page1["outcomes"]))
                self.assertEqual(20, len(page2["outcomes"]))
                self.assertIsNotNone(page1["next_cursor"])
                self.assertIsNone(page2["next_cursor"])

    def test_page_membership_is_the_frozen_selection(self):
        for batch_id in ("batch-atlas-direct-fresh", "batch-atlas-previewed-fresh"):
            selection = self.context["selections"]["selection-atlas-allmatching-120"]
            rows = self.outcomes(batch_id)
            with self.subTest(batch=batch_id):
                self.assertEqual(selection["member_order"], [row["item_id"] for row in rows])

    def test_completed_count_is_the_first_five_counters(self):
        for batch in self.expectations["batches"]:
            counts = batch["counts"]
            established = sum(counts[field] for field in bo.COUNT_FIELDS[:-1])
            with self.subTest(batch=batch["batch_id"]):
                self.assertEqual(established, batch["completed_count"])

    def test_recovery_is_incomplete_and_not_terminal(self):
        batch = self.batch("batch-atlas-technical")
        self.assertEqual("RECOVERY_REQUIRED", batch["status"])
        self.assertIsNone(batch["finished_at"])
        self.assertGreaterEqual(batch["counts"]["recovery_required"], 1)

    def test_terminal_batches_finish_without_recovery(self):
        for batch in self.expectations["batches"]:
            if batch["status"] in bo.TERMINAL_BATCH_STATES:
                with self.subTest(batch=batch["batch_id"]):
                    self.assertIsNotNone(batch["finished_at"])
                    self.assertEqual(0, batch["counts"]["recovery_required"])
                    self.assertEqual(batch["selected_count"], batch["completed_count"])

    def test_completed_batch_has_only_sorted_outcomes(self):
        for outcome in self.outcomes("batch-atlas-sorted"):
            self.assertEqual("SORTED", outcome["state"])

    def test_completed_with_issues_has_no_pending_work(self):
        for batch_id in (
            "batch-atlas-same-user-session",
            "batch-atlas-hetero",
            "batch-atlas-conflict",
        ):
            states = {outcome["state"] for outcome in self.outcomes(batch_id)}
            with self.subTest(batch=batch_id):
                self.assertNotIn("PENDING", states)
                self.assertNotIn("PROCESSING", states)
                self.assertTrue(states - {"SORTED"})


class PlacementTests(BatchMixin, unittest.TestCase):
    def test_sorted_actual_equals_planned_and_the_rule_literal(self):
        for outcome in self.all_outcomes():
            if outcome["state"] != "SORTED":
                continue
            rule = bo.preview_preflight._rule_entry(self.context["preview"], outcome["matched_rule"])
            expected = bo.preview_preflight._derive_target(
                self.context["preview"], rule, bo._basename(outcome["source"]["relative_path"])
            )
            with self.subTest(item=outcome["item_id"]):
                self.assertEqual(expected, outcome["planned_target"])
                self.assertEqual(outcome["planned_target"], outcome["actual_location"])

    def test_occupied_target_keeps_the_source_and_existing_object(self):
        outcome = self.outcome("batch-atlas-hetero", "preview-atlas-occupied-report")
        self.assertEqual("REQUIRES_DECISION", outcome["state"])
        self.assertEqual("TARGET_OCCUPIED", outcome["reason_code"])
        self.assertEqual(outcome["source"], outcome["actual_location"])
        existing = self.expectations["occupied_targets"][0]
        self.assertEqual(existing["location"], outcome["planned_target"])
        self.assertTrue(existing["unchanged"])

    def test_duplicate_plan_target_has_all_participants_and_no_winner(self):
        group = self.expectations["duplicate_targets"][0]
        participants = [
            self.outcome("batch-atlas-hetero", item_id)
            for item_id in group["participants"]
        ]
        self.assertEqual(2, len(participants))
        for outcome in participants:
            with self.subTest(item=outcome["item_id"]):
                self.assertEqual("REQUIRES_DECISION", outcome["state"])
                self.assertEqual("TARGET_OCCUPIED", outcome["reason_code"])
                self.assertEqual(group["target"], outcome["planned_target"])
                self.assertEqual(outcome["source"], outcome["actual_location"])

    def test_manual_review_keeps_the_flat_unchanged_basename(self):
        for outcome in self.all_outcomes():
            if outcome["state"] != "MANUAL_REVIEW":
                continue
            source_basename = bo._basename(outcome["source"]["relative_path"])
            destination = outcome["actual_location"]
            with self.subTest(item=outcome["item_id"]):
                self.assertIsNone(outcome["planned_target"])
                self.assertTrue(destination["relative_path"].startswith("_manual_review/atlas/"))
                self.assertEqual(source_basename, bo._basename(destination["relative_path"]))

    def test_rule_conflict_is_manual_review_not_quarantine(self):
        outcome = self.outcome("batch-atlas-conflict", "batch-atlas-shared-file")
        self.assertEqual("MANUAL_REVIEW", outcome["state"])
        self.assertEqual("RULE_CONFLICT", outcome["reason_code"])
        self.assertNotIn("quarantine", outcome["actual_location"]["relative_path"])

    def test_manual_review_name_occupied_keeps_the_source(self):
        outcome = self.outcome("batch-atlas-hetero", "preview-atlas-manual-name")
        self.assertEqual("REQUIRES_DECISION", outcome["state"])
        self.assertEqual("MANUAL_REVIEW_NAME_OCCUPIED", outcome["reason_code"])
        self.assertIsNone(outcome["planned_target"])
        self.assertEqual(outcome["source"], outcome["actual_location"])
        existing = self.expectations["manual_review_occupied"][0]
        self.assertTrue(existing["unchanged"])

    def test_confirmed_quarantine_has_a_real_destination(self):
        outcome = self.outcome("batch-atlas-technical", "batch-tech-quarantine")
        self.assertEqual("QUARANTINED", outcome["state"])
        self.assertEqual("TECHNICAL_ERROR", outcome["reason_code"])
        self.assertIsNotNone(outcome["actual_location"])
        self.assertTrue(
            outcome["actual_location"]["relative_path"].startswith("_quarantine/atlas/")
        )
        self.assertNotEqual(outcome["source"], outcome["actual_location"])

    def test_recovery_unknown_has_null_location_and_known_keeps_source(self):
        unknown = self.outcome("batch-atlas-technical", "batch-tech-recovery-unknown")
        known = self.outcome("batch-atlas-technical", "batch-tech-recovery-known")
        self.assertEqual("RECOVERY_REQUIRED", unknown["state"])
        self.assertIsNone(unknown["actual_location"])
        self.assertIsNone(unknown["finished_at"])
        self.assertEqual("RECOVERY_REQUIRED", known["state"])
        self.assertEqual(known["source"], known["actual_location"])
        self.assertIsNone(known["finished_at"])

    def test_skipped_reasons_perform_no_own_mutation(self):
        expected = {
            "batch-tech-skip-claimed": "ALREADY_PROCESSING",
            "batch-tech-skip-changed": "SOURCE_CHANGED",
            "batch-tech-skip-missing": "SOURCE_MISSING",
        }
        for item_id, reason in expected.items():
            outcome = self.outcome("batch-atlas-technical", item_id)
            with self.subTest(item=item_id):
                self.assertEqual("SKIPPED", outcome["state"])
                self.assertEqual(reason, outcome["reason_code"])
                self.assertIsNone(outcome["actual_location"])

    def test_every_outcome_links_to_a_frozen_member(self):
        for batch in self.expectations["batches"]:
            selection = self.context["selections"][bo._selection_id(batch)]
            for outcome in self.outcomes(batch["batch_id"]):
                member = selection["members"][outcome["item_id"]]
                with self.subTest(batch=batch["batch_id"], item=outcome["item_id"]):
                    self.assertEqual(member["item_revision"], outcome["item_revision"])
                    self.assertEqual(member["location"], outcome["source"])

    def test_actor_and_rule_set_are_shared(self):
        for batch in self.expectations["batches"]:
            payload = self.page(batch["batch_id"])
            owner = self.context["actors"][batch["owner"]]
            with self.subTest(batch=batch["batch_id"]):
                self.assertEqual(owner, payload["actor"])
                self.assertEqual(
                    self.context["rule_sets"][batch["rule_set_id"]]["company_id"],
                    payload["company_id"],
                )


class AcceptedPreflightTests(BatchMixin, unittest.TestCase):
    def test_the_three_accepted_preflights_realise_real_batches(self):
        self.assertEqual(3, len(self.expectations["accepted_preflights"]))
        for entry in self.expectations["accepted_preflights"]:
            preflight = self.context["preflight_by_id"][entry["scenario_id"]]
            batch = self.batch(entry["batch_id"])
            with self.subTest(scenario=entry["scenario_id"]):
                self.assertEqual(preflight["expected"]["future_batch_id"], batch["batch_id"])
                self.assertEqual(preflight["selection_id"], bo._selection_id(batch))
                self.assertEqual(preflight["expected"]["rule_set_id"], batch["rule_set_id"])
                self.assertEqual(preflight.get("execution_mode"), batch["execution_mode"])

    def test_previewed_batch_carries_the_accepted_preview(self):
        batch = self.batch("batch-atlas-previewed-fresh")
        self.assertEqual("PREVIEWED", batch["execution_mode"])
        self.assertEqual("preview-atlas-allmatching-120", batch["preview_id"])

    def test_hetero_batch_excludes_not_ready_members(self):
        selection = self.context["selections"]["selection-batch-atlas-hetero"]
        preview_selection = self.context["selections"]["selection-preview-atlas-hetero"]
        self.assertEqual(7, selection["snapshot"]["selected_count"])
        self.assertNotIn("preview-atlas-not-ready", selection["members"])
        self.assertIn("preview-atlas-not-ready", preview_selection["members"])
        self.assertEqual(
            sorted(set(preview_selection["member_order"]) - {"preview-atlas-not-ready"}),
            sorted(selection["member_order"]),
        )

    def test_history_summaries_are_ordered_and_linked(self):
        page = bo.materialize_history_page(self.expectations["history"][0], self.context)
        keyed = [(item["created_at"], item["batch_id"]) for item in page["items"]]
        self.assertEqual(sorted(keyed, reverse=True), keyed)
        for summary in page["items"]:
            batch = self.batch(summary["batch_id"])
            with self.subTest(batch=summary["batch_id"]):
                self.assertEqual(batch["counts"], summary["counts"])
                self.assertEqual(self.context["actors"][batch["owner"]], summary["actor"])
                self.assertEqual(batch["completed_count"], summary["completed_count"])

    def test_every_batch_appears_in_the_history(self):
        page = bo.materialize_history_page(self.expectations["history"][0], self.context)
        self.assertEqual(
            {batch["batch_id"] for batch in self.expectations["batches"]},
            {summary["batch_id"] for summary in page["items"]},
        )


class InventoryTests(BatchMixin, unittest.TestCase):
    def test_no_source_is_left_for_confirmed_moves(self):
        for record in bo.inventory_records(self.expectations, self.context):
            if record["state"] in ("SORTED", "MANUAL_REVIEW", "QUARANTINED"):
                with self.subTest(outcome=record["outcome_id"]):
                    self.assertIs(False, record["source_present_after"])
                    self.assertIs(True, record["destination_present"])
                    self.assertIs(True, record["content_conserved"])

    def test_decisions_and_skips_do_not_claim_a_destination(self):
        for record in bo.inventory_records(self.expectations, self.context):
            if record["state"] in ("REQUIRES_DECISION", "SKIPPED"):
                with self.subTest(outcome=record["outcome_id"]):
                    self.assertIs(False, record["destination_present"])
                    self.assertIsNone(record["content_conserved"])

    def test_only_a_logical_content_tag_is_exposed(self):
        for record in bo.inventory_records(self.expectations, self.context):
            with self.subTest(outcome=record["outcome_id"]):
                self.assertEqual("logical-content-tag", record["checksum_kind"])
                self.assertTrue(record["content_tag"].startswith("lt034a-content-"))

    def test_unknown_recovery_has_unknown_source_presence(self):
        unknown = next(
            record
            for record in bo.inventory_records(self.expectations, self.context)
            if record["outcome_id"].endswith("batch-tech-recovery-unknown")
        )
        known = next(
            record
            for record in bo.inventory_records(self.expectations, self.context)
            if record["outcome_id"].endswith("batch-tech-recovery-known")
        )
        self.assertIsNone(unknown["source_present_after"])
        self.assertIs(True, known["source_present_after"])


class NegativeExpectationTests(BatchMixin, unittest.TestCase):
    def _errors(self, expectations):
        return bo.expectation_errors(expectations, self.context_for(expectations))

    def test_declared_mutations_are_rejected(self):
        self.assertEqual(
            [],
            bo.mutation_errors(self.expectations, self.context, self.registry),
        )

    def test_status_with_recovery_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["batches", 6, "status"], "RUNNING"
        )
        errors = bo.payload_errors(mutated, self.context_for(mutated), self.registry)
        self.assertTrue(any("RECOVERY_REQUIRED" in message for message in errors), errors)

    def test_terminal_batch_without_finish_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["batches", 5, "finished_at"], None
        )
        errors = self._errors(mutated)
        self.assertTrue(any("finished_at" in message for message in errors), errors)

    def test_sorted_target_drift_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["batches", 5, "pages", 0, "rows", 0, "planned_target"],
            {
                "root_id": "root-demo-atlas",
                "relative_path": "Archive/Atlas/Orion_2031/Invoices/Other.pdf",
                "display_path": "DEMO:/SandboxRoot/Archive/Atlas/Orion_2031/Invoices/Other.pdf",
            },
        )
        errors = self._errors(mutated)
        self.assertTrue(any("planned target" in message for message in errors), errors)

    def test_manual_review_target_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["batches", 4, "pages", 0, "rows", 0, "planned_target"],
            {
                "root_id": "root-demo-atlas",
                "relative_path": "Archive/Atlas/Orion_2031/Reports/Report.pdf",
                "display_path": "DEMO:/SandboxRoot/Archive/Atlas/Orion_2031/Reports/Report.pdf",
            },
        )
        errors = self._errors(mutated)
        self.assertTrue(any("manual review" in message for message in errors), errors)

    def test_manual_review_basename_change_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["batches", 4, "pages", 0, "rows", 0, "actual"],
            {
                "root_id": "root-demo-atlas",
                "relative_path": "_manual_review/atlas/shared-file-1.pdf",
                "display_path": "DEMO:/SandboxRoot/_manual_review/atlas/shared-file-1.pdf",
            },
        )
        errors = self._errors(mutated)
        self.assertTrue(any("basename" in message for message in errors), errors)

    def test_duplicate_target_winner_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["batches", 3, "pages", 0, "rows", 5, "state"], "SORTED"
        )
        errors = self._errors(mutated)
        self.assertTrue(any("duplicate" in message.lower() for message in errors), errors)

    def test_page_fullness_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["batches", 0, "pages", 0, "rows", 0, "$repeat_rows", "index_end"],
            99,
        )
        errors = self._errors(mutated)
        self.assertTrue(any("full" in message for message in errors), errors)

    def test_membership_drift_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["batches", 3, "pages", 0, "rows", 0, "item_id"],
            "queue-atlas-ready-0001",
        )
        errors = self._errors(mutated)
        self.assertTrue(any("frozen selection member" in message for message in errors), errors)

    def test_history_order_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["history", 0, "batch_ids", 0],
            "batch-atlas-direct-fresh",
        )
        errors = self._errors(mutated)
        self.assertTrue(any("ordered" in message for message in errors), errors)

    def test_inventory_source_leftover_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["inventory", "state_rules", 2, "source_present_after"],
            True,
        )
        errors = bo.inventory_errors(mutated, self.context_for(mutated))
        self.assertTrue(any("source" in message for message in errors), errors)

    def test_skipped_missing_with_location_is_rejected_by_schema(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["batches", 6, "pages", 0, "rows", 5, "actual"],
            {
                "root_id": "root-demo-atlas",
                "relative_path": "Archive/Atlas/Orion_2031/Reports/batch-tech-skip-missing.pdf",
                "display_path": "DEMO:/SandboxRoot/Archive/Atlas/Orion_2031/Reports/batch-tech-skip-missing.pdf",
            },
        )
        errors = bo.payload_errors(mutated, self.context_for(mutated), self.registry)
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
