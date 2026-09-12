"""Tests for the LT-03.4b operational retry/overlap/restart scenarios.

The scenarios are an *independent* oracle: these tests check that the literal
sequences are internally consistent, schema-valid, traced to the matrix Q ids
and that the committed public examples equal the materialized literals.  No test
matches a rule, executes a batch, writes a file, performs a restart or runs a
concurrency primitive; the materializer only expands the declared literals and
cross-checks them against the referenced LT-03.4a batches and LT-03.3b
preflights/errors.
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
from contractlib import batch_scenarios as bs  # noqa: E402
from contractlib import synthetic  # noqa: E402
from contractlib.search_expectations import allowed_error_codes  # noqa: E402

REPO_ROOT = HERE.parents[1]
CONTRACT = REPO_ROOT / "contracts" / "openapi" / "wiseway-v1.yaml"

_MISSING = object()


class ScenarioMixin:
    @classmethod
    def setUpClass(cls):
        cls.registry = build_registry(load_contract(CONTRACT))
        cls.expectations = bs.load_expectations(REPO_ROOT)
        cls.context = bs.build_context(REPO_ROOT, cls.expectations)

    def context_for(self, expectations):
        return bs.build_context(REPO_ROOT, expectations)

    def scenario(self, scenario_id):
        return self.context["scenarios"][scenario_id]

    def outcome(self, batch_id, item_id):
        return bs.outcome_payload(batch_id, item_id, self.context)

    def mutate(self, expectations, operation, path, value=_MISSING):
        mutated = copy.deepcopy(expectations)
        mutation = {"operation": operation, "path": path}
        if value is not _MISSING:
            mutation["value"] = value
        bs._apply_mutation(mutated, mutation)
        return mutated


class OracleStructureTests(ScenarioMixin, unittest.TestCase):
    def test_expectations_have_no_structural_errors(self):
        self.assertEqual([], bs.expectation_errors(self.expectations, self.context))

    def test_every_payload_materializes_to_a_schema_valid_payload(self):
        self.assertEqual(
            [], bs.payload_errors(self.expectations, self.context, self.registry)
        )

    def test_links_are_consistent(self):
        self.assertEqual([], bs.link_errors(self.expectations, self.context))

    def test_isolated_ids_do_not_collide_with_linked_fixtures(self):
        self.assertEqual([], bs.identity_errors(self.expectations, self.context))

    def test_isolated_batches_obey_the_logical_inventory_contract(self):
        self.assertEqual([], bs.inventory_errors(self.expectations, self.context))
        contract = self.context["batch_expectations"]["inventory"]
        self.assertEqual("logical-inventory-expectation", contract["kind"])
        self.assertTrue(contract["no_file_writes"])

    def test_coverage_is_complete_and_resolvable(self):
        self.assertEqual([], bs.coverage_errors(self.expectations, self.context))
        for q_id in bs.KNOWN_Q:
            self.assertTrue(self.expectations["coverage"].get(q_id), q_id)

    def test_all_categories_are_present(self):
        present = {scenario["category"] for scenario in self.expectations["scenarios"]}
        self.assertEqual(set(bs.CATEGORIES), present)

    def test_every_expected_audit_id_resolves(self):
        for scenario in self.expectations["scenarios"]:
            for audit_id in scenario.get("expected_audit", []):
                with self.subTest(scenario=scenario["scenario_id"], audit=audit_id):
                    self.assertIn(audit_id, self.context["audit"])

    def test_every_generated_example_matches_the_committed_file(self):
        generated = bs.generated_examples(self.expectations, self.context)
        self.assertTrue(generated)
        for relative, payload in generated.items():
            with self.subTest(example=relative):
                committed = synthetic.load_json(REPO_ROOT / relative)
                self.assertEqual(committed, payload)

    def test_every_generated_example_is_bound_in_the_manifest(self):
        manifest = self.context["manifest"]
        bound = {entry["file"]: entry["schema"] for entry in manifest["examples"]}
        for binding in bs.EXAMPLE_BINDINGS:
            self.assertIn(binding["file"], bound)
            self.assertEqual(binding["schema"], bound[binding["file"]])


class IdempotencyTests(ScenarioMixin, unittest.TestCase):
    def test_every_idempotency_key_is_a_uuid(self):
        for scenario in self.expectations["scenarios"]:
            keys = []
            if "idempotency_key" in scenario:
                keys.append(scenario["idempotency_key"])
            for block in ("first", "retry"):
                if block in scenario:
                    keys.append(scenario[block]["idempotency_key"])
            for key in keys:
                with self.subTest(scenario=scenario["scenario_id"], key=key):
                    self.assertRegex(key, bs.UUID_RE)

    def test_replays_return_the_original_batch_without_a_new_attempt(self):
        for scenario_id in ("SCN-IDEM-REPLAY-DIRECT", "SCN-IDEM-REPLAY-PREVIEWED"):
            scenario = self.scenario(scenario_id)
            for replay in scenario["replays"]:
                expected = replay["expected"]
                with self.subTest(scenario=scenario_id, replay=replay["replay_id"]):
                    self.assertEqual(scenario["accepted_batch_id"], expected["batch_id"])
                    self.assertEqual(0, expected["new_attempts"])
                    self.assertEqual(202, expected["http"])

    def test_replays_after_expiry_are_after_the_declared_expiry(self):
        for scenario_id, timing in (
            ("SCN-IDEM-REPLAY-DIRECT", "after_snapshot_expiry"),
            ("SCN-IDEM-REPLAY-PREVIEWED", "after_preview_expiry"),
        ):
            scenario = self.scenario(scenario_id)
            replay = next(r for r in scenario["replays"] if r["timing"] == timing)
            selection = self.context["selections"][scenario["body"]["selection_id"]]
            expiry = selection["snapshot"]["expires_at"]
            if timing == "after_preview_expiry":
                expiry = self.context["preview_expiries"][scenario["body"]["preview_id"]]
            with self.subTest(scenario=scenario_id):
                self.assertGreater(bs._instant(replay["at"]), bs._instant(expiry))

    def test_modified_body_is_rejected_with_the_declared_error(self):
        scenario = self.scenario("SCN-IDEM-MODIFIED-BODY")
        self.assertNotEqual(scenario["original_body"], scenario["modified_body"])
        error = self.context["errors"][scenario["expected"]["error_id"]]
        self.assertEqual("IDEMPOTENCY_KEY_REUSED", error["code"])
        self.assertEqual(409, error["status"])
        self.assertEqual("createSortingBatch", error["operation"])

    def test_another_user_reuses_the_same_key_string_as_a_separate_scope(self):
        scenario = self.scenario("SCN-IDEM-DIFFERENT-USER-SCOPE")
        original = self.context["batch"]["batches"][scenario["original_batch_id"]]
        scoped = self.context["batch"]["batches"][scenario["scoped_batch_id"]]
        self.assertNotEqual(scenario["original_actor"], scenario["scoped_actor"])
        self.assertNotEqual(original["batch_id"], scoped["batch_id"])
        self.assertEqual(scenario["scoped_actor"], scoped["owner"])
        self.assertTrue(scenario["expected"]["separate_scope"])
        self.assertFalse(scenario["expected"]["idempotency_conflict"])

    def test_manual_retry_uses_a_new_key_and_a_new_attempt(self):
        scenario = self.scenario("SCN-MANUAL-RETRY-NEW-KEY")
        self.assertNotEqual(
            scenario["first"]["idempotency_key"], scenario["retry"]["idempotency_key"]
        )
        self.assertEqual([], scenario["first"]["expected"]["attempts"])
        retry_attempts = bs.attempt_ids(
            scenario["retry"]["expected"]["batch_id"], self.context
        )
        self.assertEqual(scenario["retry"]["expected"]["attempts"], retry_attempts)
        self.assertTrue(retry_attempts)

    def test_attempt_ids_are_globally_unique_across_batches(self):
        seen = {}
        for batch_id in self.context["batch"]["batches"]:
            for attempt in bs.attempt_ids(batch_id, self.context):
                with self.subTest(attempt=attempt):
                    self.assertNotIn(attempt, seen)
                seen[attempt] = batch_id


class OverlapTests(ScenarioMixin, unittest.TestCase):
    def test_shared_item_has_the_same_location_and_revision_in_both_selections(self):
        scenario = self.scenario("SCN-OVERLAP-TWO-ACTORS")
        shared = scenario["shared_item_id"]
        winner = self.context["selections"][scenario["winner"]["selection_id"]]
        loser = self.context["selections"][scenario["loser"]["selection_id"]]
        self.assertEqual(
            winner["members"][shared]["location"], loser["members"][shared]["location"]
        )
        self.assertEqual(
            winner["members"][shared]["item_revision"],
            loser["members"][shared]["item_revision"],
        )

    def test_loser_skips_the_claimed_item_without_a_second_move(self):
        scenario = self.scenario("SCN-OVERLAP-TWO-ACTORS")
        outcome = self.outcome(scenario["loser"]["batch_id"], scenario["shared_item_id"])
        self.assertEqual("SKIPPED", outcome["state"])
        self.assertEqual("ALREADY_PROCESSING", outcome["reason_code"])
        self.assertIsNone(outcome["actual_location"])
        self.assertFalse(scenario["expected"]["second_move"])

    def test_claim_does_not_change_the_content_revision(self):
        scenario = self.scenario("SCN-OVERLAP-TWO-ACTORS")
        winner = self.outcome(scenario["winner"]["batch_id"], scenario["shared_item_id"])
        loser = self.outcome(scenario["loser"]["batch_id"], scenario["shared_item_id"])
        selection = self.context["selections"][scenario["winner"]["selection_id"]]
        self.assertEqual(
            selection["members"][scenario["shared_item_id"]]["item_revision"],
            winner["item_revision"],
        )
        self.assertEqual(winner["item_revision"], loser["item_revision"])
        self.assertTrue(scenario["expected"]["content_revision_unchanged_by_claim"])

    def test_independent_safe_items_are_sorted_for_both_actors(self):
        scenario = self.scenario("SCN-OVERLAP-TWO-ACTORS")
        for side, batch_key in (("winner", "winner"), ("loser", "loser")):
            for item_id in scenario["independent_safe_items"][side]:
                outcome = self.outcome(scenario[batch_key]["batch_id"], item_id)
                with self.subTest(side=side, item=item_id):
                    self.assertEqual("SORTED", outcome["state"])

    def test_barrier_orders_the_winner_claim_before_the_loser_attempt(self):
        scenario = self.scenario("SCN-OVERLAP-TWO-ACTORS")
        self.assertLess(
            bs._instant(scenario["winner"]["claim_at"]),
            bs._instant(scenario["loser"]["claim_at"]),
        )
        self.assertEqual("winner_claim", scenario["synchronization"]["before"])
        self.assertEqual("loser_attempt", scenario["synchronization"]["after"])


class SourceChangeTests(ScenarioMixin, unittest.TestCase):
    def test_source_change_before_acceptance_is_a_pre_batch_refusal(self):
        scenario = self.scenario("SCN-SOURCE-CHANGE-BEFORE-AFTER")
        for entry in scenario["before_acceptance"]:
            preflight = self.context["preflight_by_id"][entry["ref"]]
            with self.subTest(preflight=entry["ref"]):
                self.assertFalse(preflight["expected"]["accepted"])
                self.assertEqual(preflight["expected"]["code"], entry["code"])
                self.assertEqual(preflight["expected"]["status"], entry["http"])
                self.assertFalse(entry["batch_created"])
                self.assertFalse(entry["file_operations"])

    def test_source_change_after_acceptance_skips_and_returns_to_waiting_ready(self):
        scenario = self.scenario("SCN-SOURCE-CHANGE-BEFORE-AFTER")
        after = scenario["after_acceptance"]
        outcome = self.outcome(after["batch_id"], after["item_id"])
        self.assertEqual("SKIPPED", outcome["state"])
        self.assertEqual("SOURCE_CHANGED", outcome["reason_code"])
        self.assertIsNone(outcome["actual_location"])
        self.assertEqual("WAITING_READY", after["expected_queue_status"])
        self.assertEqual("none", after["mutation"])


class ContinuationTests(ScenarioMixin, unittest.TestCase):
    def test_logout_reload_keeps_the_original_author_and_batch(self):
        scenario = self.scenario("SCN-LOGOUT-RELOAD-CONTINUE")
        batch = self.context["batch"]["batches"][scenario["accepted_batch_id"]]
        self.assertEqual(scenario["author"], batch["owner"])
        self.assertNotEqual(scenario["author"], scenario["new_viewer"])
        read = next(step for step in scenario["steps"] if step["kind"] == "READ")
        self.assertEqual(scenario["author"], read["expected"]["author"])
        self.assertEqual(200, read["expected"]["http"])

    def test_no_cancel_operation_and_the_viewer_never_becomes_author(self):
        scenario = self.scenario("SCN-LOGOUT-RELOAD-CONTINUE")
        absent = next(
            step for step in scenario["steps"] if step["kind"] == "ABSENT_OPERATION"
        )["expected"]
        self.assertFalse(absent["cancel_operation_available"])
        self.assertFalse(absent["new_viewer_is_author"])
        self.assertFalse(absent["batch_cancelled"])
        self.assertFalse(absent["new_batch_created"])


class LateTargetTests(ScenarioMixin, unittest.TestCase):
    def test_late_target_requires_decision_and_preserves_both_objects(self):
        scenario = self.scenario("SCN-LATE-TARGET-AFTER-PREFLIGHT")
        outcome = self.outcome(scenario["outcome"]["batch_id"], scenario["outcome"]["item_id"])
        self.assertEqual("REQUIRES_DECISION", outcome["state"])
        self.assertEqual("TARGET_OCCUPIED", outcome["reason_code"])
        self.assertEqual(outcome["source"], outcome["actual_location"])
        existing = self.context["occupied_targets"][scenario["existing_object_id"]]
        self.assertTrue(existing["unchanged"])
        self.assertEqual(existing["location"], outcome["planned_target"])


class DuplicateTargetTests(ScenarioMixin, unittest.TestCase):
    def test_reversing_the_input_order_keeps_every_participant_undecided(self):
        scenario = self.scenario("SCN-DUPLICATE-TARGET-REVERSED")
        group = self.context["duplicate_groups"][scenario["group_id"]]
        self.assertEqual(
            list(reversed(scenario["runs"][0]["input_order"])),
            scenario["runs"][1]["input_order"],
        )
        for item_id in group["participants"]:
            outcome = self.outcome(scenario["batch_id"], item_id)
            with self.subTest(item=item_id):
                self.assertEqual("REQUIRES_DECISION", outcome["state"])
                self.assertEqual("TARGET_OCCUPIED", outcome["reason_code"])
                self.assertEqual(outcome["source"], outcome["actual_location"])
                self.assertEqual(group["target"], outcome["planned_target"])
        self.assertIsNone(scenario["expected"]["winner"])

    def test_the_independent_safe_file_still_sorts(self):
        scenario = self.scenario("SCN-DUPLICATE-TARGET-REVERSED")
        outcome = self.outcome(scenario["batch_id"], scenario["independent_safe_file"])
        self.assertEqual("SORTED", outcome["state"])


class RestartTests(ScenarioMixin, unittest.TestCase):
    def test_three_declared_restart_points_with_durable_intent(self):
        scenario = self.scenario("SCN-RESTART-THREE-POINTS")
        self.assertFalse(scenario["live_evidence"])
        self.assertEqual(
            set(bs.RESTART_POINTS), {point["point_id"] for point in scenario["points"]}
        )
        for point in scenario["points"]:
            with self.subTest(point=point["point_id"]):
                self.assertTrue(point["durable_intent"])
                self.assertTrue(
                    all(phase in bs.INTENT_PHASES for phase in point["durable_intent"])
                )
                self.assertTrue(point["expected"]["intent_survives_restart"])
                self.assertFalse(point["expected"]["blind_retry"])

    def test_proven_points_yield_one_result_and_ambiguous_stays_recovery(self):
        scenario = self.scenario("SCN-RESTART-THREE-POINTS")
        points = {point["point_id"]: point for point in scenario["points"]}
        self.assertEqual(1, points["RESTART-BEFORE-MUTATION"]["expected"]["final_results"])
        self.assertEqual(1, points["RESTART-AFTER-PROVEN-COMMIT"]["expected"]["final_results"])
        ambiguous = points["RESTART-AMBIGUOUS"]["expected"]
        self.assertEqual("RECOVERY_REQUIRED", ambiguous["final_results"])
        self.assertTrue(ambiguous["registered_operation_id"])
        self.assertIsNone(ambiguous["finished_at"])
        for item_id in scenario["ambiguous_outcomes"]:
            outcome = self.outcome("batch-atlas-technical", item_id)
            self.assertEqual("RECOVERY_REQUIRED", outcome["state"])


class ContainmentTests(ScenarioMixin, unittest.TestCase):
    def test_before_batch_cases_use_only_declared_error_codes(self):
        scenario = self.scenario("SCN-CONTAINMENT-Q044")
        document = self.context["document"]
        for case in scenario["before_batch"]:
            allowed = allowed_error_codes(
                document, case["operation"], case["expected"]["http"]
            )
            with self.subTest(case=case["case_id"]):
                self.assertIn(case["expected"]["code"], allowed)
                self.assertFalse(case["expected"]["batch_created"])
                self.assertTrue(case["no_outside_access"])
                self.assertTrue(case["request"])

    def test_after_batch_cases_never_access_outside_and_use_outcomes(self):
        scenario = self.scenario("SCN-CONTAINMENT-Q044")
        for case in scenario["after_batch"]:
            outcome_spec = case["expected"]["outcome"]
            outcome = self.outcome(outcome_spec["batch_id"], outcome_spec["item_id"])
            with self.subTest(case=case["case_id"]):
                self.assertEqual(outcome_spec["state"], outcome["state"])
                self.assertEqual(outcome_spec["reason_code"], outcome["reason_code"])
                self.assertFalse(case["expected"]["outside_access"])
                self.assertFalse(case["expected"]["blind_retry"])
                self.assertTrue(case["no_outside_access"])

    def test_an_unknown_recovery_keeps_the_safe_requirement(self):
        scenario = self.scenario("SCN-CONTAINMENT-Q044")
        ambiguous = next(
            case
            for case in scenario["after_batch"]
            if case["case_id"] == "CONT-LINK-REPLACEMENT-AMBIGUOUS"
        )
        self.assertFalse(ambiguous["exact_recovery_available"])
        self.assertEqual(
            "RECOVERY_REQUIRED", ambiguous["expected"]["outcome"]["state"]
        )
        self.assertFalse(ambiguous["expected"]["invented_outcome"])


class AuditTests(ScenarioMixin, unittest.TestCase):
    def test_audit_phase_action_category_and_result_are_declared(self):
        for entry in self.expectations["audit_expectations"]:
            with self.subTest(audit=entry["audit_id"]):
                self.assertIn(entry["phase"], bs.AUDIT_PHASES)
                self.assertIn(entry["action"], bs.AUDIT_ACTIONS)
                self.assertIn(entry["category"], bs.AUDIT_CATEGORIES)
                self.assertIn(entry["result"], bs.AUDIT_RESULTS)

    def test_unique_attempt_phase_keys_prevent_duplicate_events(self):
        keys = [entry["unique_key"] for entry in self.expectations["audit_expectations"]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_file_attempt_events_link_batch_attempt_and_item(self):
        for entry in self.expectations["audit_expectations"]:
            if entry["action"] not in ("FILE_ATTEMPT_STARTED", "FILE_ATTEMPT_FINISHED"):
                continue
            outcome = self.outcome(entry["batch_id"], entry["item_id"])
            with self.subTest(audit=entry["audit_id"]):
                self.assertEqual(outcome["attempt_id"], entry["attempt_id"])
                self.assertEqual(outcome["attempt_id"], entry["operation_id"])

    def test_recovery_event_links_the_source_attempt(self):
        recovery = next(
            entry
            for entry in self.expectations["audit_expectations"]
            if entry["action"] == "RECOVERY_REQUIRED"
        )
        self.assertEqual(recovery["attempt_id"], recovery["source_attempt_id"])
        self.assertEqual("BUSINESS", recovery["category"])


class NegativeExpectationTests(ScenarioMixin, unittest.TestCase):
    def _errors(self, expectations):
        return bs.expectation_errors(expectations, self.context_for(expectations))

    def test_declared_mutations_are_rejected(self):
        self.assertEqual(
            [],
            bs.mutation_errors(self.expectations, self.context, self.registry),
        )

    def test_replay_with_a_new_attempt_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["scenarios", 0, "replays", 1, "expected", "new_attempts"], 1
        )
        errors = self._errors(mutated)
        self.assertTrue(any("attempt" in message for message in errors), errors)

    def test_modified_body_accepted_is_caught(self):
        mutated = self.mutate(self.expectations, "set", ["scenarios", 2, "expected", "http"], 202)
        errors = self._errors(mutated)
        self.assertTrue(any("409" in message for message in errors), errors)

    def test_scope_conflict_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["scenarios", 3, "expected", "idempotency_conflict"], True
        )
        errors = self._errors(mutated)
        self.assertTrue(any("conflict" in message for message in errors), errors)

    def test_retry_reusing_the_key_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["scenarios", 4, "retry", "idempotency_key"],
            "55555555-5555-4555-8555-555555555555",
        )
        errors = self._errors(mutated)
        self.assertTrue(any("new key" in message for message in errors), errors)

    def test_overlap_loser_winning_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["scenarios", 5, "expected", "loser_shared_state"], "SORTED"
        )
        errors = self._errors(mutated)
        self.assertTrue(any("loser" in message for message in errors), errors)

    def test_overlap_double_claim_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["scenarios", 5, "expected", "shared_claim_count"], 2
        )
        errors = self._errors(mutated)
        self.assertTrue(any("claim" in message for message in errors), errors)

    def test_source_change_after_with_location_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["scenarios", 6, "after_acceptance", "actual_location"],
            {
                "root_id": "root-demo-atlas",
                "relative_path": "Archive/Atlas/Orion_2031/Reports/batch-tech-skip-changed.pdf",
                "display_path": "DEMO:/SandboxRoot/Archive/Atlas/Orion_2031/Reports/batch-tech-skip-changed.pdf",
            },
        )
        errors = self._errors(mutated)
        self.assertTrue(any("actual location" in message for message in errors), errors)

    def test_continuation_author_change_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["scenarios", 7, "steps", 1, "expected", "author"], "worker2"
        )
        errors = self._errors(mutated)
        self.assertTrue(any("author" in message for message in errors), errors)

    def test_continuation_cancel_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["scenarios", 7, "steps", 3, "expected", "cancel_operation_available"],
            True,
        )
        errors = self._errors(mutated)
        self.assertTrue(any("cancel" in message for message in errors), errors)

    def test_duplicate_target_winner_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["scenarios", 9, "expected", "winner"], "preview-atlas-invoice-a"
        )
        errors = self._errors(mutated)
        self.assertTrue(any("winner" in message for message in errors), errors)

    def test_restart_blind_retry_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["scenarios", 10, "points", 2, "expected", "blind_retry"], True
        )
        errors = self._errors(mutated)
        self.assertTrue(any("blind retry" in message for message in errors), errors)

    def test_containment_outside_access_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["scenarios", 11, "before_batch", 3, "no_outside_access"], False
        )
        errors = self._errors(mutated)
        self.assertTrue(any("outside" in message for message in errors), errors)

    def test_containment_wrong_error_code_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["scenarios", 11, "before_batch", 0, "expected", "code"], "INVALID_TARGET"
        )
        errors = self._errors(mutated)
        self.assertTrue(any("not declared" in message for message in errors), errors)

    def test_audit_unknown_action_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["audit_expectations", 0, "action"], "BATCH_CANCELLED"
        )
        errors = bs._audit_errors(mutated, self.context_for(mutated))
        self.assertTrue(any("AuditAction" in message for message in errors), errors)

    def test_audit_duplicate_key_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["audit_expectations", 1, "unique_key"],
            "batch-atlas-direct-fresh:accepted",
        )
        errors = bs._audit_errors(mutated, self.context_for(mutated))
        self.assertTrue(any("unique_key" in message for message in errors), errors)

    def test_coverage_gap_is_caught(self):
        mutated = self.mutate(self.expectations, "set", ["coverage", "Q-040"], [])
        errors = bs.coverage_errors(mutated, self.context_for(mutated))
        self.assertTrue(any("Q-040" in message for message in errors), errors)

    def test_invalid_idempotency_key_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["scenarios", 0, "idempotency_key"], "not-a-uuid"
        )
        errors = self._errors(mutated)
        self.assertTrue(any("UUID" in message for message in errors), errors)


if __name__ == "__main__":
    unittest.main()
