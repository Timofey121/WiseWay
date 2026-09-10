"""Tests for the LT-03.3a literal queue/readiness/selection expectations.

The expectations are an *independent* oracle: these tests check that the literal
data is internally consistent, schema-valid, fully traced to Q ids and that the
committed public examples equal the materialized literals.  No test filters a
queue, detects readiness, counts a page, selects a winner or freezes membership
by algorithm; the materializer only expands already-declared literal ids and
cross-checks the declared values.
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from contractlib import build_registry, load_contract, validate_fixture  # noqa: E402
from contractlib import queue_selections as qs  # noqa: E402
from contractlib import synthetic  # noqa: E402
from contractlib.schemas import validate_value  # noqa: E402
from contractlib.semantic import queue_response_errors  # noqa: E402

REPO_ROOT = HERE.parents[1]
CONTRACT = REPO_ROOT / "contracts" / "openapi" / "wiseway-v1.yaml"


class QueueMixin:
    @classmethod
    def setUpClass(cls):
        cls.registry = build_registry(load_contract(CONTRACT))
        cls.expectations = qs.load_expectations(REPO_ROOT)
        cls.context = qs.build_context(REPO_ROOT, cls.expectations)
        cls.profiles = cls.expectations["profiles"]
        cls.scenarios = cls.expectations["selection_scenarios"]

    def context_for(self, expectations):
        return qs.build_context(REPO_ROOT, expectations)

    def profile(self, profile_id):
        return self.context["profiles"][profile_id]

    def query(self, profile_id, query_id):
        return self.context["queries"][profile_id][query_id]

    def mutate(self, reference, operation, path, value=None):
        payload = copy.deepcopy(qs._base_payload(reference, self.expectations, self.context))
        mutation = {"operation": operation, "path": path}
        if value is not None:
            mutation["value"] = value
        qs._apply_mutation(payload, mutation)
        return payload


class OracleStructureTests(QueueMixin, unittest.TestCase):
    def test_expectations_have_no_structural_errors(self):
        self.assertEqual([], qs.expectation_errors(self.expectations, self.context))

    def test_every_payload_materializes_to_a_schema_valid_payload(self):
        self.assertEqual(
            [],
            qs.payload_errors(self.expectations, self.context, self.registry),
        )

    def test_invalid_requests_are_schema_classified(self):
        self.assertEqual(
            [],
            qs.schema_rejection_errors(self.expectations, self.registry),
        )
        for entry in self.expectations["invalid_requests"]:
            with self.subTest(entry=entry["request_id"]):
                value = qs.materialize_invalid_request(entry)
                errors = validate_value(self.registry, entry["schema"], value)
                self.assertEqual(entry["schema_rejected"], bool(errors))

    def test_error_codes_belong_to_their_operation(self):
        self.assertEqual(
            [], qs.error_operation_errors(self.expectations, self.context)
        )

    def test_declared_mutations_are_rejected(self):
        self.assertEqual([], qs.mutation_errors(self.expectations, self.context))

    def test_coverage_is_complete_and_resolvable(self):
        self.assertEqual([], qs.coverage_errors(self.expectations))
        for q_id in qs.KNOWN_Q:
            self.assertIn(q_id, self.expectations["coverage"])

    def test_rule_set_identity_matches_accepted_lifecycle(self):
        self.assertEqual(
            [], qs.rule_set_identity_errors(self.expectations, self.context)
        )
        ours = self.expectations["rule_set"]
        reference = self.context["reference_rule_set"]
        self.assertEqual("rule-set-atlas-published", ours["rule_set_id"])
        self.assertEqual(reference["members"], ours["members"])

    def test_every_generated_example_matches_the_committed_file(self):
        generated = qs.generated_examples(self.expectations, self.context)
        self.assertTrue(generated)
        for relative, payload in generated.items():
            with self.subTest(example=relative):
                committed = synthetic.load_json(REPO_ROOT / relative)
                self.assertEqual(committed, payload)

    def test_every_generated_example_is_bound_in_the_manifest(self):
        manifest = self.context["manifest"]
        bound = {entry["file"]: entry["schema"] for entry in manifest["examples"]}
        for binding in qs.EXAMPLE_BINDINGS:
            self.assertIn(binding["file"], bound)
            self.assertEqual(binding["schema"], bound[binding["file"]])


class ProfileTests(QueueMixin, unittest.TestCase):
    def test_ready_profiles_cover_zero_120_and_1001(self):
        ready_counts = {
            profile["profile_id"]: {
                entry["status"]: entry["count"] for entry in profile["status_counts"]
            }.get("READY", 0)
            for profile in self.profiles
        }
        self.assertEqual(0, ready_counts["QUEUE-Q024-READY-0"])
        self.assertEqual(120, ready_counts["QUEUE-Q022-READY-120"])
        self.assertEqual(1001, ready_counts["QUEUE-Q024-READY-1001"])

    def test_company_counters_distinguish_filtered_counts(self):
        profile = self.profile("QUEUE-Q022-READY-120")
        ready_query = self.query("QUEUE-Q022-READY-120", "Q-Q024-READY-PAGE1")
        all_active = self.query("QUEUE-Q022-READY-120", "Q-Q022-ALL-ACTIVE")
        self.assertEqual(120, ready_query["matching_count"])
        self.assertEqual(120, ready_query["eligible_count"])
        self.assertEqual(130, all_active["matching_count"])
        self.assertEqual(121, all_active["eligible_count"])
        declared = {
            entry["status"]: entry["count"] for entry in profile["status_counts"]
        }
        self.assertEqual(120, declared["READY"])
        self.assertEqual(profile["counters"]["ready"], declared["READY"])
        self.assertEqual(profile["counters"]["processing"], declared["PROCESSING"])
        self.assertEqual(
            profile["counters"]["attention"],
            declared["REQUIRES_DECISION"] + declared["RECOVERY_REQUIRED"],
        )

    def test_ready_page_is_capped_and_total_is_larger(self):
        profile = self.profile("QUEUE-Q022-READY-120")
        query = self.query("QUEUE-Q022-READY-120", "Q-Q024-READY-PAGE1")
        response = qs.materialize_queue_response(profile, query, self.context)
        self.assertEqual(100, len(response["items"]))
        self.assertEqual(120, response["matching_count"])
        self.assertIsNotNone(response["next_cursor"])

    def test_missing_is_excluded_from_default_queue(self):
        profile = self.profile("QUEUE-Q022-READY-120")
        default = qs.materialize_queue_response(
            profile, self.query("QUEUE-Q022-READY-120", "Q-Q022-ALL-ACTIVE"), self.context
        )
        explicit = qs.materialize_queue_response(
            profile,
            self.query("QUEUE-Q022-READY-120", "Q-Q022-MISSING-EXPLICIT"),
            self.context,
        )
        self.assertNotIn("MISSING", {item["status"] for item in default["items"]})
        self.assertIn("MISSING", {item["status"] for item in explicit["items"]})

    def test_selectable_matches_ready_or_stable_decision_without_claim(self):
        for profile in self.profiles:
            stability = qs._stability_map(profile, self.context)
            for item in qs.materialize_membership(profile, self.context):
                expected = (
                    item["status"] in qs.SELECTABLE_STATES
                    and stability[item["item_id"]]
                    and item["active_attempt_id"] is None
                )
                with self.subTest(item=item["item_id"]):
                    self.assertEqual(expected, item["selectable"])
        # The claimed REQUIRES_DECISION item is explicitly not selectable.
        membership = {
            item["item_id"]: item
            for item in qs.materialize_membership(
                self.profile("QUEUE-Q022-READY-120"), self.context
            )
        }
        claimed = membership["queue-atlas-decision-claimed-01"]
        self.assertEqual("REQUIRES_DECISION", claimed["status"])
        self.assertIsNotNone(claimed["active_attempt_id"])
        self.assertFalse(claimed["selectable"])

    def test_unstable_decision_without_claim_is_not_selectable(self):
        profile = self.profile("QUEUE-Q022-DECISION-STABILITY")
        stability = qs._stability_map(profile, self.context)
        membership = {
            item["item_id"]: item
            for item in qs.materialize_membership(profile, self.context)
        }
        unstable = membership["queue-atlas-stability-decision-unstable-01"]
        self.assertEqual("REQUIRES_DECISION", unstable["status"])
        self.assertIsNone(unstable["active_attempt_id"])
        self.assertFalse(stability[unstable["item_id"]])
        self.assertFalse(unstable["selectable"])
        stable_decision = membership["queue-atlas-stability-decision-stable-01"]
        self.assertEqual("REQUIRES_DECISION", stable_decision["status"])
        self.assertIsNone(stable_decision["active_attempt_id"])
        self.assertTrue(stable_decision["selectable"])

    def test_shared_validator_accepts_unstable_false_and_rejects_unsound_true(self):
        profile = self.profile("QUEUE-Q022-DECISION-STABILITY")
        query = self.query("QUEUE-Q022-DECISION-STABILITY", "Q-Q022-STABILITY-ACTIVE")
        response = qs.materialize_queue_response(profile, query, self.context)
        self.assertEqual([], queue_response_errors(response))
        # selectable=false for an unstable REQUIRES_DECISION item without a claim
        # is schema-valid and accepted by the shared semantic validator.
        unstable = next(
            item
            for item in response["items"]
            if item["item_id"] == "queue-atlas-stability-decision-unstable-01"
        )
        self.assertFalse(unstable["selectable"])
        self.assertEqual("REQUIRES_DECISION", unstable["status"])
        self.assertIsNone(unstable["active_attempt_id"])
        errors, _semantic = validate_fixture(
            self.registry, qs.QUEUE_RESPONSE_SCHEMA, response
        )
        self.assertEqual([], errors)
        # selectable=true on a disallowed state is rejected.
        disallowed = copy.deepcopy(response)
        disallowed["items"][2]["status"] = "PROCESSING"
        disallowed["items"][2]["selectable"] = True
        self.assertTrue(queue_response_errors(disallowed))
        # selectable=true with an active claim is rejected.
        claimed = copy.deepcopy(response)
        claimed["items"][0]["active_attempt_id"] = "attempt-atlas-unexpected-01"
        self.assertTrue(queue_response_errors(claimed))
        # An explicit stable READY/REQUIRES_DECISION without a claim stays accepted.
        self.assertTrue(response["items"][0]["selectable"])
        self.assertTrue(response["items"][1]["selectable"])
        self.assertEqual([], queue_response_errors(response))

    def test_attention_counts_only_two_states(self):
        profile = self.profile("QUEUE-Q022-READY-120")
        declared = {
            entry["status"]: entry["count"] for entry in profile["status_counts"]
        }
        self.assertEqual(
            profile["counters"]["attention"],
            declared["REQUIRES_DECISION"] + declared["RECOVERY_REQUIRED"],
        )
        self.assertNotEqual(
            profile["counters"]["attention"],
            declared["REQUIRES_DECISION"] + declared["RECOVERY_REQUIRED"] + 1,
        )


class SelectionTests(QueueMixin, unittest.TestCase):
    def test_explicit_membership_is_literal_and_off_page(self):
        scenario = next(
            s for s in self.scenarios if s["scenario_id"] == "SEL-Q024-EXPLICIT-MULTIPLE-OFFPAGE"
        )
        members = qs.materialize_selection_members(scenario, self.context)
        member_ids = [member["item_id"] for member in members]
        self.assertEqual(
            ["queue-atlas-ready-0001", "queue-atlas-ready-0101", "queue-atlas-ready-0120"],
            member_ids,
        )
        page = qs.materialize_queue_response(
            self.profile(scenario["profile_id"]),
            self.query(scenario["profile_id"], "Q-Q024-READY-PAGE1"),
            self.context,
        )
        page_ids = {item["item_id"] for item in page["items"]}
        self.assertNotIn("queue-atlas-ready-0101", page_ids)
        self.assertNotIn("queue-atlas-ready-0120", page_ids)
        self.assertIn("queue-atlas-ready-0101", member_ids)

    def test_all_matching_membership_equals_eligible_set(self):
        scenario = next(
            s for s in self.scenarios if s["scenario_id"] == "SEL-Q024-ALL-MATCHING-120"
        )
        members = qs.materialize_selection_members(scenario, self.context)
        self.assertEqual(120, len(members))
        eligible = qs.materialize_members(
            self.query("QUEUE-Q022-READY-120", "Q-Q024-READY-PAGE1")["eligible_ids"],
            self.context["groups"]["QUEUE-Q022-READY-120"],
        )
        self.assertEqual(
            [member["item_id"] for member in eligible],
            [member["item_id"] for member in members],
        )
        self.assertEqual(120, scenario["expected"]["selected_count"])

    def test_snapshot_ttl_is_five_minutes(self):
        for scenario in self.scenarios:
            with self.subTest(scenario=scenario["scenario_id"]):
                snapshot = qs.materialize_selection_snapshot(scenario, self.context)
                self.assertEqual(
                    300,
                    qs._ttl_seconds(snapshot["created_at"], snapshot["expires_at"]),
                )

    def test_zero_eligible_is_empty_selection(self):
        entry = next(
            e for e in self.expectations["selection_errors"] if e["error_id"] == "SEL-ERR-EMPTY"
        )
        self.assertEqual(422, entry["status"])
        self.assertEqual("EMPTY_SELECTION", entry["code"])
        self.assertEqual(0, entry["eligible_count"])
        self.assertFalse(entry["snapshot_created"])

    def test_over_limit_is_batch_limit_exceeded_without_truncation(self):
        entry = next(
            e for e in self.expectations["selection_errors"] if e["error_id"] == "SEL-ERR-LIMIT"
        )
        self.assertEqual(422, entry["status"])
        self.assertEqual("BATCH_LIMIT_EXCEEDED", entry["code"])
        self.assertEqual(1001, entry["eligible_count"])
        self.assertIsNone(entry["selected_count"])
        self.assertFalse(entry["truncated"])
        self.assertFalse(entry["snapshot_created"])

    def test_count_mismatch_is_selection_changed_before_creation(self):
        entry = next(
            e for e in self.expectations["selection_errors"] if e["error_id"] == "SEL-ERR-CHANGED"
        )
        self.assertEqual(409, entry["status"])
        self.assertEqual("SELECTION_CHANGED", entry["code"])
        self.assertEqual(119, entry["expected_eligible_count"])
        self.assertEqual(120, entry["eligible_count"])
        self.assertFalse(entry["snapshot_created"])

    def test_late_arrival_and_filter_switch_do_not_change_snapshot(self):
        self.assertEqual([], qs.expectation_errors(self.expectations, self.context))
        late = next(
            s for s in self.expectations["sequences"] if s["sequence_id"] == "SEL-Q025-LATE-ARRIVAL"
        )
        switch = next(
            s for s in self.expectations["sequences"] if s["sequence_id"] == "SEL-Q025-FILTER-SWITCH"
        )
        self.assertFalse(late["steps"][2]["new_item_included"])
        self.assertFalse(switch["steps"][2]["membership_rebuilt"])

    def test_same_user_allowed_and_other_user_forbidden(self):
        same = next(
            o for o in self.expectations["ownership"] if o["scenario_id"] == "SEL-OWN-SAME-USER-NEW-SESSION"
        )
        other = next(
            o for o in self.expectations["ownership"] if o["scenario_id"] == "SEL-OWN-OTHER-USER"
        )
        self.assertTrue(same["expected"]["allowed"])
        self.assertEqual(same["owner"], same["requesting_actor"])
        self.assertFalse(other["expected"]["allowed"])
        self.assertNotEqual(other["owner"], other["requesting_actor"])
        self.assertEqual("FORBIDDEN", other["expected"]["code"])

    def test_expired_errors_use_real_preview_and_batch_operations(self):
        expired = [
            e
            for e in self.expectations["selection_errors"]
            if e["code"] == "SELECTION_EXPIRED"
        ]
        self.assertEqual(
            {"createSortingPreview", "createSortingBatch"},
            {entry["operation"] for entry in expired},
        )


class ReadinessTests(QueueMixin, unittest.TestCase):
    def test_readiness_sequences_follow_observation_criteria(self):
        self.assertEqual([], qs.expectation_errors(self.expectations, self.context))
        by_id = {item["item_id"]: item for item in self.expectations["readiness"]["items"]}
        stable = by_id["queue-atlas-readiness-stable"]
        self.assertEqual("READY", stable["expected_status"])
        first, second = stable["observations"]
        self.assertEqual(first["size_bytes"], second["size_bytes"])
        self.assertEqual(first["modified_at"], second["modified_at"])
        self.assertGreaterEqual(
            qs._seconds_between(first["observed_at"], second["observed_at"]), 5
        )
        self.assertFalse(any(o["unfinished"] for o in stable["observations"]))
        for item_id in ("queue-atlas-readiness-changed", "queue-atlas-readiness-renamed"):
            with self.subTest(item=item_id):
                item = by_id[item_id]
                self.assertEqual("WAITING_READY", item["expected_status"])
                self.assertGreater(
                    item["expected_content_revision"], item["content_revision_before"]
                )
        claimed = by_id["queue-atlas-readiness-claimed"]
        self.assertEqual("PROCESSING", claimed["expected_status"])
        self.assertEqual(
            claimed["content_revision_before"], claimed["expected_content_revision"]
        )


class NegativeExpectationTests(QueueMixin, unittest.TestCase):
    def _errors(self, expectations):
        return qs.expectation_errors(expectations, self.context_for(expectations))

    def test_ready_status_count_mismatch_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        profile = next(p for p in expectations["profiles"] if p["profile_id"] == "QUEUE-Q022-READY-120")
        profile["status_counts"][2]["count"] = 119
        errors = self._errors(expectations)
        self.assertTrue(any("status_counts" in message for message in errors), errors)

    def test_attention_with_extra_state_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        profile = next(p for p in expectations["profiles"] if p["profile_id"] == "QUEUE-Q022-READY-120")
        profile["counters"]["attention"] = 4
        errors = self._errors(expectations)
        self.assertTrue(any("attention" in message for message in errors), errors)

    def test_ready_page_capped_at_wrong_size_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        profile = next(p for p in expectations["profiles"] if p["profile_id"] == "QUEUE-Q022-READY-120")
        profile["queries"][0]["page_ids"]["groups"][0]["index_end"] = 99
        errors = self._errors(expectations)
        self.assertTrue(any("page has" in message for message in errors), errors)

    def test_unstable_decision_marked_selectable_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        profile = next(
            p
            for p in expectations["profiles"]
            if p["profile_id"] == "QUEUE-Q022-DECISION-STABILITY"
        )
        unstable = next(
            group
            for group in profile["groups"]
            if group["group"] == "stability-decision-unstable-1"
        )
        unstable["selectable"] = True
        errors = self._errors(expectations)
        self.assertTrue(any("selectable" in message for message in errors), errors)

    def test_group_without_explicit_stability_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        profile = next(
            p
            for p in expectations["profiles"]
            if p["profile_id"] == "QUEUE-Q022-DECISION-STABILITY"
        )
        profile["groups"][0].pop("stable")
        errors = self._errors(expectations)
        self.assertTrue(any("stable metadata" in message for message in errors), errors)

    def test_missing_in_default_queue_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        profile = next(p for p in expectations["profiles"] if p["profile_id"] == "QUEUE-Q022-READY-120")
        profile["queries"][1]["page_ids"]["groups"] = [
            {"group": "missing-2", "index_start": 1, "index_end": 2}
        ]
        errors = self._errors(expectations)
        self.assertTrue(any("MISSING" in message for message in errors), errors)

    def test_selection_count_mismatch_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        scenario = next(
            s for s in expectations["selection_scenarios"] if s["scenario_id"] == "SEL-Q024-ALL-MATCHING-120"
        )
        scenario["expected"]["selected_count"] = 119
        errors = self._errors(expectations)
        self.assertTrue(any("selected_count" in message for message in errors), errors)

    def test_selection_company_mismatch_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        scenario = next(
            s for s in expectations["selection_scenarios"] if s["scenario_id"] == "SEL-Q024-EXPLICIT-ONE"
        )
        scenario["expected"]["company_id"] = "company-demo-nova"
        errors = self._errors(expectations)
        self.assertTrue(any("company" in message for message in errors), errors)

    def test_unknown_member_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        scenario = next(
            s for s in expectations["selection_scenarios"] if s["scenario_id"] == "SEL-Q024-EXPLICIT-ONE"
        )
        scenario["members"]["explicit"] = [
            {"item_id": "queue-atlas-ready-9999", "item_revision": 1}
        ]
        errors = self._errors(expectations)
        self.assertTrue(any("not in the queue profile" in message for message in errors), errors)

    def test_member_revision_mismatch_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        scenario = next(
            s for s in expectations["selection_scenarios"] if s["scenario_id"] == "SEL-Q024-EXPLICIT-ONE"
        )
        scenario["members"]["explicit"] = [
            {"item_id": "queue-atlas-ready-0001", "item_revision": 99}
        ]
        errors = self._errors(expectations)
        self.assertTrue(any("revision" in message for message in errors), errors)

    def test_readiness_short_interval_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        item = next(
            i for i in expectations["readiness"]["items"] if i["item_id"] == "queue-atlas-readiness-stable"
        )
        item["observations"][1]["observed_at"] = "2031-05-10T09:00:03Z"
        errors = self._errors(expectations)
        self.assertTrue(any("5 seconds" in message for message in errors), errors)

    def test_readiness_unfinished_marker_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        item = next(
            i for i in expectations["readiness"]["items"] if i["item_id"] == "queue-atlas-readiness-stable"
        )
        item["observations"][1]["unfinished"] = True
        errors = self._errors(expectations)
        self.assertTrue(any("unfinished" in message for message in errors), errors)

    def test_link_generation_mismatch_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        scenario = next(
            s for s in expectations["selection_scenarios"] if s["scenario_id"] == "SEL-Q024-EXPLICIT-ONE"
        )
        scenario["expected"]["queue_generation"] = "queue-generation-atlas-0"
        errors = self._errors(expectations)
        self.assertTrue(any("GENERATION" in message or "!=" in message for message in errors), errors)

    def test_rule_set_identity_drift_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        expectations["rule_set"]["members"] = [
            {"dictionary_id": "dictionary-atlas-general", "version_id": "version-atlas-general-v2"}
        ]
        errors = self._errors(expectations)
        self.assertTrue(any("RuleSet" in message for message in errors), errors)


class MutationHelperTests(QueueMixin, unittest.TestCase):
    def test_queue_response_counters_mutation_is_rejected(self):
        mutated = self.mutate(
            "queue:QUEUE-Q022-READY-120:Q-Q024-READY-PAGE1", "set", ["counters", "ready"], 119
        )
        self.assertTrue(queue_response_errors(mutated))

    def test_queue_response_selectable_claim_mutation_is_rejected(self):
        mutated = self.mutate(
            "queue:QUEUE-Q022-READY-120:Q-Q024-READY-PAGE1",
            "set",
            ["items", 0, "active_attempt_id"],
            "attempt-atlas-unexpected-01",
        )
        self.assertTrue(queue_response_errors(mutated))

    def test_queue_response_payload_remains_schema_valid_after_item_mutation(self):
        mutated = self.mutate(
            "queue:QUEUE-Q022-READY-120:Q-Q024-READY-PAGE1",
            "set",
            ["items", 0, "filename"],
            "Atlas-Report-0001-renamed.pdf",
        )
        errors, _semantic = validate_fixture(
            self.registry, qs.QUEUE_RESPONSE_SCHEMA, mutated
        )
        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
