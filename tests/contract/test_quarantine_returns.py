"""Tests for the LT-03.5a quarantine/return lifecycle oracle.

The fixture is an *independent* oracle: these tests check that the confirmed
quarantine record is derived from the actual LT-03.4a ``QUARANTINED`` outcome,
that the same batch's ``RECOVERY_REQUIRED`` outcomes never enter the confirmed
quarantine list, that the return success/conflicts/replays are internally
consistent, schema-valid and traced to the matrix Q ids, and that the committed
public examples equal the materialized literals.  No test executes a return,
writes a file, starts sorting, stores an idempotency key or records an audit
event; the materializer only expands the declared literals and cross-checks them
against the linked LT-03.4a batch outcomes.
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
from contractlib import quarantine_returns as qr  # noqa: E402
from contractlib import synthetic  # noqa: E402
from contractlib.search_expectations import allowed_error_codes  # noqa: E402

REPO_ROOT = HERE.parents[1]
CONTRACT = REPO_ROOT / "contracts" / "openapi" / "wiseway-v1.yaml"

_MISSING = object()


class QuarantineMixin:
    @classmethod
    def setUpClass(cls):
        cls.registry = build_registry(load_contract(CONTRACT))
        cls.expectations = qr.load_expectations(REPO_ROOT)
        cls.context = qr.build_context(REPO_ROOT, cls.expectations)

    def context_for(self, expectations):
        return qr.build_context(REPO_ROOT, expectations)

    def scenario(self, scenario_id):
        return self.context["scenarios"][scenario_id]

    def state(self, state_id):
        return self.context["states"][state_id]

    def item(self, state_id):
        return qr.materialize_quarantine_item(self.state(state_id), self.context)

    def outcome(self, batch_id, item_id):
        return self.context["outcomes"][(batch_id, item_id)]

    def mutate(self, expectations, operation, path, value=_MISSING):
        mutated = copy.deepcopy(expectations)
        mutation = {"operation": operation, "path": path}
        if value is not _MISSING:
            mutation["value"] = value
        bs._apply_mutation(mutated, mutation)
        return mutated


class OracleStructureTests(QuarantineMixin, unittest.TestCase):
    def test_expectations_have_no_structural_errors(self):
        self.assertEqual([], qr.expectation_errors(self.expectations, self.context))

    def test_every_payload_materializes_to_a_schema_valid_payload(self):
        self.assertEqual(
            [], qr.payload_errors(self.expectations, self.context, self.registry)
        )

    def test_requests_are_schema_classified(self):
        self.assertEqual(
            [], qr.schema_rejection_errors(self.expectations, self.registry)
        )

    def test_links_are_consistent(self):
        self.assertEqual([], qr.link_errors(self.expectations, self.context))

    def test_coverage_is_complete_and_resolvable(self):
        self.assertEqual(
            [], qr.coverage_errors(self.expectations, self.context)
        )
        for q_id in qr.KNOWN_Q:
            self.assertTrue(self.expectations["coverage"].get(q_id), q_id)

    def test_all_categories_are_present(self):
        present = {scenario["category"] for scenario in self.expectations["scenarios"]}
        self.assertEqual(set(qr.CATEGORIES), present)

    def test_every_generated_example_matches_the_committed_file(self):
        generated = qr.generated_examples(self.expectations, self.context)
        self.assertTrue(generated)
        for relative, payload in generated.items():
            with self.subTest(example=relative):
                committed = synthetic.load_json(REPO_ROOT / relative)
                self.assertEqual(committed, payload)

    def test_every_generated_example_is_bound_in_the_manifest(self):
        manifest = self.context["manifest"]
        bound = {entry["file"]: entry["schema"] for entry in manifest["examples"]}
        for binding in qr.EXAMPLE_BINDINGS:
            self.assertIn(binding["file"], bound)
            self.assertEqual(binding["schema"], bound[binding["file"]])


class QuarantineRecordTests(QuarantineMixin, unittest.TestCase):
    def test_confirmed_record_matches_the_actual_batch_outcome(self):
        item = self.item("QR-STATE-CONFIRMED")
        outcome = self.outcome("batch-atlas-technical", "batch-tech-quarantine")
        self.assertEqual(outcome["item_id"], item["item_id"])
        self.assertEqual(outcome["attempt_id"], item["source_attempt_id"])
        self.assertEqual(outcome["actual_location"], item["location"])
        self.assertEqual(outcome["source"], item["original_location"])
        self.assertEqual(outcome["reason_code"], item["reason_code"])
        self.assertEqual(
            qr._basename(outcome["source"]["relative_path"]), item["filename"]
        )
        self.assertTrue(item["can_return"])
        self.assertIsNone(item["recovery_operation_id"])

    def test_prior_batch_is_the_immutable_recovery_required_batch(self):
        self.assertEqual([], qr._prior_batch_errors(self.expectations, self.context))
        batch = self.context["batch"]["batches"]["batch-atlas-technical"]
        self.assertEqual("RECOVERY_REQUIRED", batch["status"])
        self.assertIsNone(batch["finished_at"])

    def test_recovery_outcomes_are_not_in_the_confirmed_quarantine_list(self):
        self.assertEqual(
            [], qr._quarantine_list_errors(self.expectations, self.context)
        )
        page_ids = [
            item["item_id"]
            for item in qr.materialize_quarantine_page(
                self.expectations, self.context
            )["items"]
        ]
        self.assertEqual(["batch-tech-quarantine"], page_ids)
        for recovery in self.expectations["recovery_outcomes"]:
            self.assertNotIn(recovery["item_id"], page_ids)

    def test_ambiguous_record_is_can_return_false_with_registered_operation(self):
        item = self.item("QR-STATE-AMBIGUOUS")
        self.assertFalse(item["can_return"])
        self.assertEqual(
            "return-atlas-batch-tech-quarantine-recovery",
            item["recovery_operation_id"],
        )
        self.assertFalse(self.state("QR-STATE-AMBIGUOUS")["returned"])

    def test_record_time_matches_the_confirmed_outcome(self):
        outcome = self.outcome("batch-atlas-technical", "batch-tech-quarantine")
        for state_id in ("QR-STATE-CONFIRMED", "QR-STATE-AMBIGUOUS"):
            with self.subTest(state=state_id):
                self.assertEqual(
                    qr._instant(outcome["finished_at"]),
                    qr._instant(self.state(state_id)["quarantined_at"]),
                )

    def test_logical_return_inventory_is_an_expectation(self):
        self.assertEqual([], qr._inventory_errors(self.expectations, self.context))
        inventory = self.expectations["return_inventory"]
        self.assertEqual("logical-inventory-expectation", inventory["kind"])
        self.assertTrue(inventory["no_file_writes"])
        self.assertFalse(inventory["success"]["source_quarantine_present_after"])
        self.assertTrue(inventory["success"]["original_present_after"])
        self.assertTrue(inventory["success"]["content_conserved"])
        self.assertIsNone(inventory["ambiguous"]["original_present_after"])
        self.assertIsNone(inventory["ambiguous"]["source_quarantine_present_after"])


class ReturnSuccessTests(QuarantineMixin, unittest.TestCase):
    def test_success_is_waiting_ready_without_autosort(self):
        scenario = self.scenario("QR-RETURN-SUCCESS")
        expected = scenario["expected"]
        self.assertEqual(200, expected["http"])
        self.assertEqual("RETURN", expected["result"])
        self.assertEqual("WAITING_READY", expected["item_status"])
        self.assertFalse(expected["selectable"])
        self.assertIsNone(expected["active_attempt_id"])
        self.assertIsNone(expected["reason_code"])
        self.assertTrue(expected["no_autosort"])
        self.assertFalse(expected["new_batch"])
        self.assertFalse(expected["new_attempt"])
        self.assertFalse(expected["second_move"])

    def test_returned_item_keeps_the_original_source_and_filename(self):
        response = qr.materialize_return_response(
            self.scenario("QR-RETURN-SUCCESS"), self.context
        )
        item = response["item"]
        outcome = self.outcome("batch-atlas-technical", "batch-tech-quarantine")
        self.assertEqual(outcome["source"], item["source"])
        self.assertEqual("batch-tech-quarantine.tar.gz", item["filename"])
        self.assertEqual(
            qr._basename(item["source"]["relative_path"]), item["filename"]
        )
        self.assertGreater(item["item_revision"], outcome["item_revision"])
        self.assertEqual(
            "return-atlas-batch-tech-quarantine", response["return_operation_id"]
        )

    def test_returned_item_uses_the_company_incoming_source_identity(self):
        response = qr.materialize_return_response(
            self.scenario("QR-RETURN-SUCCESS"), self.context
        )
        item = response["item"]
        company = self.expectations["companies"]["atlas"]
        self.assertEqual(company["company_id"], item["company_id"])
        self.assertEqual(company["incoming_source_id"], item["incoming_source_id"])
        self.assertEqual(company["source_name"], item["source_name"])


class ConflictTests(QuarantineMixin, unittest.TestCase):
    def test_empty_and_long_comments_are_schema_invalid(self):
        for scenario_id in ("QR-COMMENT-EMPTY", "QR-COMMENT-LONG"):
            scenario = self.scenario(scenario_id)
            with self.subTest(scenario=scenario_id):
                self.assertTrue(scenario["schema_rejected"])
                self.assertEqual(422, scenario["expected"]["http"])
                self.assertEqual("VALIDATION_ERROR", scenario["expected"]["code"])
                self.assertFalse(scenario["expected"]["mutates"])
        lengths = [
            len(self.scenario(sid)["body"]["comment"])
            for sid in ("QR-COMMENT-EMPTY", "QR-COMMENT-LONG")
        ]
        self.assertEqual([0, 501], lengths)

    def test_stale_revision_is_a_version_conflict(self):
        scenario = self.scenario("QR-STALE-REVISION")
        self.assertNotEqual(
            scenario["body"]["expected_revision"],
            self.state("QR-STATE-CONFIRMED")["revision"],
        )
        self.assertEqual(409, scenario["expected"]["http"])
        self.assertEqual(
            "QUARANTINE_VERSION_CONFLICT", scenario["expected"]["code"]
        )
        self.assertFalse(scenario["expected"]["mutates"])

    def test_occupied_original_path_preserves_everything(self):
        scenario = self.scenario("QR-ORIGINAL-PATH-OCCUPIED")
        occupied = self.context["occupied"][scenario["occupied_object"]]
        item = self.item("QR-STATE-CONFIRMED")
        self.assertEqual(item["original_location"], occupied["location"])
        self.assertTrue(occupied["unchanged"])
        self.assertEqual(409, scenario["expected"]["http"])
        self.assertEqual("ORIGINAL_PATH_OCCUPIED", scenario["expected"]["code"])
        self.assertFalse(scenario["expected"]["new_move"])

    def test_unknown_id_is_not_found(self):
        scenario = self.scenario("QR-UNKNOWN-ID")
        self.assertNotIn(scenario["unknown_quarantine_id"], self.context["quarantine_ids"])
        self.assertEqual(404, scenario["expected"]["http"])
        self.assertEqual("NOT_FOUND", scenario["expected"]["code"])

    def test_already_returned_with_a_new_key_is_invalid_state(self):
        scenario = self.scenario("QR-ALREADY-RETURNED-NEW-KEY")
        self.assertEqual("RETURNED", scenario["precondition"])
        self.assertEqual(409, scenario["expected"]["http"])
        self.assertEqual("INVALID_STATE", scenario["expected"]["code"])
        self.assertFalse(scenario["expected"]["second_return"])

    def test_ambiguous_return_registers_a_recovery_operation(self):
        scenario = self.scenario("QR-RECOVERY-AMBIGUOUS")
        expected = scenario["expected"]
        state = self.state(scenario["record_state"])
        self.assertEqual(409, expected["http"])
        self.assertEqual("RECOVERY_REQUIRED", expected["code"])
        self.assertIsNotNone(expected["operation_id"])
        self.assertEqual(state["recovery_operation_id"], expected["operation_id"])
        self.assertFalse(expected["can_return"])
        self.assertFalse(expected["produced_item"])
        self.assertIsNone(expected["actual_placement"])

    def test_conflict_codes_are_declared_by_the_return_operation(self):
        for scenario in self.expectations["scenarios"]:
            if scenario["category"] == "CAN_RETURN_STABILITY":
                continue
            if scenario["expected"].get("result") != "ERROR":
                continue
            allowed = allowed_error_codes(
                self.context["document"], qr.RETURN_OPERATION, scenario["expected"]["http"]
            )
            with self.subTest(scenario=scenario["scenario_id"]):
                self.assertIn(scenario["expected"]["code"], allowed)


class IdempotencyTests(QuarantineMixin, unittest.TestCase):
    def test_every_return_key_is_a_uuid(self):
        for scenario in self.expectations["scenarios"]:
            with self.subTest(scenario=scenario["scenario_id"]):
                self.assertRegex(scenario["idempotency_key"], qr.UUID_RE)

    def test_replays_reuse_key_body_and_user_without_a_second_move(self):
        self.assertEqual([], [
            error
            for replay in self.expectations["replays"]
            for error in qr._replay_errors(replay, self.context)
        ])
        for replay in self.expectations["replays"]:
            original = self.scenario(replay["of"])
            with self.subTest(replay=replay["replay_id"]):
                self.assertTrue(replay["same_key"])
                self.assertTrue(replay["same_user"])
                self.assertTrue(replay["same_body"])
                self.assertEqual(original["idempotency_key"], original["idempotency_key"])
                self.assertGreater(
                    replay["record_revision_after"],
                    original["body"]["expected_revision"],
                )
                self.assertFalse(replay["expected"]["new_move"])
                self.assertFalse(replay["expected"]["new_attempt"])
                self.assertFalse(replay["expected"]["new_event"])

    def test_success_replay_returns_the_original_operation(self):
        replay = next(r for r in self.expectations["replays"] if r["replay_id"] == "QR-REPLAY-SUCCESS")
        original = self.scenario("QR-RETURN-SUCCESS")
        self.assertEqual(200, replay["expected"]["http"])
        self.assertEqual(
            original["expected"]["return_operation_id"],
            replay["expected"]["return_operation_id"],
        )

    def test_recovery_replay_returns_the_registered_operation(self):
        replay = next(r for r in self.expectations["replays"] if r["replay_id"] == "QR-REPLAY-RECOVERY")
        original = self.scenario("QR-RECOVERY-AMBIGUOUS")
        self.assertEqual(409, replay["expected"]["http"])
        self.assertEqual("RECOVERY_REQUIRED", replay["expected"]["code"])
        self.assertEqual(
            original["expected"]["operation_id"], replay["expected"]["operation_id"]
        )

    def test_reused_key_with_a_different_body_is_a_key_conflict(self):
        scenario = self.scenario("QR-KEY-REUSED-DIFFERENT-BODY")
        original = self.scenario(scenario["replay_of"])
        self.assertEqual(original["idempotency_key"], scenario["idempotency_key"])
        self.assertNotEqual(original["body"], scenario["body"])
        self.assertEqual(409, scenario["expected"]["http"])
        self.assertEqual("IDEMPOTENCY_KEY_REUSED", scenario["expected"]["code"])
        self.assertTrue(scenario["expected"]["idempotency_conflict"])

    def test_another_user_reuses_the_key_string_as_a_separate_scope(self):
        scenario = self.scenario("QR-USER-SCOPE-NEW-OPERATION")
        original = self.scenario(scenario["original_scenario"])
        self.assertEqual(original["idempotency_key"], scenario["idempotency_key"])
        self.assertNotEqual(scenario["original_actor"], scenario["scoped_actor"])
        self.assertTrue(scenario["expected"]["separate_scope"])
        self.assertFalse(scenario["expected"]["idempotency_conflict"])
        self.assertNotEqual("IDEMPOTENCY_KEY_REUSED", scenario["expected"]["code"])


class CanReturnTests(QuarantineMixin, unittest.TestCase):
    def test_can_return_is_a_stability_flag_not_a_permission(self):
        scenario = self.scenario("QR-CAN-RETURN-STABILITY")
        expected = scenario["expected"]
        state = self.state(scenario["record_state"])
        self.assertFalse(expected["can_return"])
        self.assertEqual(state["recovery_operation_id"], expected["recovery_operation_id"])
        self.assertFalse(expected["permission_based"])
        self.assertFalse(expected["role_based"])
        # The semantic validator enforces the OAS stability coupling.
        self.assertEqual(
            [],
            qr.validate_fixture(
                self.registry,
                qr.QUARANTINE_ITEM_SCHEMA,
                self.item("QR-STATE-AMBIGUOUS"),
            )[1],
        )

    def test_returnable_record_has_no_recovery_operation(self):
        item = self.item("QR-STATE-CONFIRMED")
        self.assertTrue(item["can_return"])
        self.assertIsNone(item["recovery_operation_id"])


class AuditTests(QuarantineMixin, unittest.TestCase):
    def test_audit_descriptors_are_valid_and_unique(self):
        self.assertEqual([], qr._audit_errors(self.expectations, self.context))
        keys = [entry["unique_key"] for entry in self.expectations["audit_expectations"]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_audit_descriptors_are_not_measured_evidence(self):
        for entry in self.expectations["audit_expectations"]:
            with self.subTest(audit=entry["audit_id"]):
                self.assertIs(False, entry["evidence"])

    def test_return_event_links_operation_and_source_attempt(self):
        entry = next(
            e
            for e in self.expectations["audit_expectations"]
            if e["action"] == "QUARANTINE_RETURNED"
        )
        item = self.item("QR-STATE-CONFIRMED")
        self.assertEqual("return-atlas-batch-tech-quarantine", entry["operation_id"])
        self.assertEqual(item["source_attempt_id"], entry["source_attempt_id"])
        self.assertEqual("BUSINESS", entry["category"])
        self.assertEqual("SUCCESS", entry["result"])

    def test_recovery_event_links_the_registered_operation(self):
        entry = next(
            e
            for e in self.expectations["audit_expectations"]
            if e["action"] == "RECOVERY_REQUIRED"
        )
        state = self.state(entry["record_state"])
        self.assertEqual(state["recovery_operation_id"], entry["operation_id"])
        self.assertEqual("ISSUE", entry["result"])
        self.assertIsNone(entry["target"])


class NegativeExpectationTests(QuarantineMixin, unittest.TestCase):
    def _errors(self, expectations):
        return qr.expectation_errors(expectations, self.context_for(expectations))

    def test_declared_mutations_are_rejected(self):
        self.assertEqual(
            [],
            qr.mutation_errors(self.expectations, self.context, self.registry),
        )

    def test_revision_drift_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["scenarios", 0, "body", "expected_revision"], 0
        )
        self.assertTrue(self._errors(mutated))

    def test_success_status_drift_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["scenarios", 0, "expected", "item_status"], "READY"
        )
        self.assertTrue(
            any("WAITING_READY" in message for message in self._errors(mutated))
        )

    def test_autosort_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["scenarios", 0, "expected", "no_autosort"], False
        )
        self.assertTrue(
            any("auto-starts sorting" in message for message in self._errors(mutated))
        )

    def test_second_move_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["replays", 0, "expected", "new_move"], True
        )
        self.assertTrue(any("second move" in message for message in self._errors(mutated)))

    def test_recovery_without_operation_id_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["scenarios", 7, "expected", "operation_id"], None
        )
        self.assertTrue(self._errors(mutated))

    def test_ambiguous_can_return_true_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["quarantine_states", 1, "can_return"], True
        )
        self.assertTrue(self._errors(mutated))

    def test_user_scope_conflict_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["scenarios", 9, "expected", "idempotency_conflict"],
            True,
        )
        self.assertTrue(
            any("conflict" in message for message in self._errors(mutated))
        )

    def test_recovery_outcome_listed_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "append",
            ["confirmed_outcomes"],
            {"batch_id": "batch-atlas-technical", "item_id": "batch-tech-recovery-unknown"},
        )
        errors = qr._quarantine_list_errors(mutated, self.context_for(mutated))
        self.assertTrue(errors)

    def test_inventory_quarantine_leftover_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["return_inventory", "success", "source_quarantine_present_after"],
            True,
        )
        errors = qr._inventory_errors(mutated, self.context_for(mutated))
        self.assertTrue(errors)

    def test_valid_comment_on_a_schema_invalid_scenario_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["scenarios", 1, "body", "comment"], "valid"
        )
        errors = qr.schema_rejection_errors(mutated, self.registry)
        self.assertTrue(any("schema rejection" in message for message in errors), errors)

    def test_empty_comment_on_a_valid_scenario_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["scenarios", 0, "body", "comment"], ""
        )
        errors = qr.payload_errors(mutated, self.context_for(mutated), self.registry)
        self.assertTrue(errors)

    def test_link_placement_drift_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["links", 1, "target", "path"], ["source"]
        )
        errors = qr.link_errors(mutated, self.context_for(mutated))
        self.assertTrue(errors)

    def test_audit_operation_drift_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["audit_expectations", 0, "operation_id"], None
        )
        errors = qr._audit_errors(mutated, self.context_for(mutated))
        self.assertTrue(any("return_operation_id" in message for message in errors), errors)

    def test_coverage_gap_is_caught(self):
        mutated = self.mutate(self.expectations, "set", ["coverage", "Q-038"], [])
        errors = qr.coverage_errors(mutated, self.context_for(mutated))
        self.assertTrue(any("Q-038" in message for message in errors), errors)

    def test_invalid_uuid_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["scenarios", 0, "idempotency_key"], "not-a-uuid"
        )
        self.assertTrue(any("UUID" in message for message in self._errors(mutated)))


if __name__ == "__main__":
    unittest.main()
