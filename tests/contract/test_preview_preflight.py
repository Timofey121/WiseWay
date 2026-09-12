"""Tests for the LT-03.3b literal preview and preflight expectations.

The expectations are an *independent* oracle: these tests check that the literal
data is internally consistent, schema-valid, fully traced to Q ids and that the
committed public examples equal the materialized literals.  No test matches a
rule, resolves a priority, derives a target name, counts a page or decides a
preflight; the materializer only expands already-declared literal ids and
cross-checks the declared values against the frozen selection membership.
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from contractlib import build_registry, load_contract, validate_fixture  # noqa: E402
from contractlib import preview_preflight as pp  # noqa: E402
from contractlib import synthetic  # noqa: E402
from contractlib.schemas import validate_value  # noqa: E402

REPO_ROOT = HERE.parents[1]
CONTRACT = REPO_ROOT / "contracts" / "openapi" / "wiseway-v1.yaml"


class PreviewMixin:
    @classmethod
    def setUpClass(cls):
        cls.registry = build_registry(load_contract(CONTRACT))
        cls.expectations = pp.load_expectations(REPO_ROOT)
        cls.context = pp.build_context(REPO_ROOT, cls.expectations)

    def context_for(self, expectations):
        return pp.build_context(REPO_ROOT, expectations)

    def preview(self, page_id):
        return pp.materialize_preview(self.context["preview_pages"][page_id], self.context)

    def all_rows(self, preview_id):
        rows = []
        for page in self.context["preview_groups"][preview_id]:
            rows.extend(pp.materialize_preview(page, self.context)["rows"])
        return rows

    def mutate(self, expectations, operation, path, value=None):
        mutated = copy.deepcopy(expectations)
        mutation = {"operation": operation, "path": path}
        if value is not None:
            mutation["value"] = value
        pp._apply_mutation(mutated, mutation)
        return mutated


class OracleStructureTests(PreviewMixin, unittest.TestCase):
    def test_expectations_have_no_structural_errors(self):
        self.assertEqual([], pp.expectation_errors(self.expectations, self.context))

    def test_every_payload_materializes_to_a_schema_valid_payload(self):
        self.assertEqual(
            [],
            pp.payload_errors(self.expectations, self.context, self.registry),
        )

    def test_preflight_requests_are_schema_valid(self):
        self.assertEqual(
            [],
            pp.request_schema_errors(self.expectations, self.context, self.registry),
        )

    def test_invalid_requests_are_schema_classified(self):
        self.assertEqual(
            [], pp.schema_rejection_errors(self.expectations, self.registry)
        )
        for entry in self.expectations["invalid_requests"]:
            with self.subTest(entry=entry["request_id"]):
                value = pp.materialize_invalid_request(entry)
                errors = validate_value(self.registry, entry["schema"], value)
                self.assertEqual(entry["schema_rejected"], bool(errors))

    def test_declared_mutations_are_rejected(self):
        self.assertEqual(
            [],
            pp.mutation_errors(self.expectations, self.context, self.registry),
        )

    def test_links_are_consistent(self):
        self.assertEqual([], pp.link_errors(self.expectations, self.context))

    def test_coverage_is_complete_and_resolvable(self):
        self.assertEqual([], pp.coverage_errors(self.expectations, self.context))
        for q_id in pp.KNOWN_Q:
            self.assertIn(q_id, self.expectations["coverage"])

    def test_every_generated_example_matches_the_committed_file(self):
        generated = pp.generated_examples(self.expectations, self.context)
        self.assertTrue(generated)
        for relative, payload in generated.items():
            with self.subTest(example=relative):
                committed = synthetic.load_json(REPO_ROOT / relative)
                self.assertEqual(committed, payload)

    def test_every_generated_example_is_bound_in_the_manifest(self):
        manifest = self.context["manifest"]
        bound = {entry["file"]: entry["schema"] for entry in manifest["examples"]}
        for binding in pp.EXAMPLE_BINDINGS:
            self.assertIn(binding["file"], bound)
            self.assertEqual(binding["schema"], bound[binding["file"]])


class PredictionCoverageTests(PreviewMixin, unittest.TestCase):
    def test_all_four_prediction_kinds_appear(self):
        present = {
            row["predicted_state"]
            for entry in self.expectations["previews"]
            for row in pp.materialize_preview(entry, self.context)["rows"]
        }
        self.assertEqual(set(pp.PREDICTIONS), present)

    def test_all_three_collision_kinds_appear(self):
        present = {
            row["collision"]["kind"]
            for entry in self.expectations["previews"]
            for row in pp.materialize_preview(entry, self.context)["rows"]
            if isinstance(row.get("collision"), dict)
        }
        self.assertEqual(set(pp.COLLISION_KINDS), present)

    def test_no_scenario_has_empty_matched_rules(self):
        rows = [
            row
            for entry in self.expectations["previews"]
            for row in pp.materialize_preview(entry, self.context)["rows"]
            if row["reason_code"] == "NO_SCENARIO"
        ]
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(row=row["item_id"]):
                self.assertEqual([], row["matched_rules"])
                self.assertIsNone(row["selected_rule"])
                self.assertIsNone(row["target"])

    def test_rule_conflict_has_two_matches_and_no_winner(self):
        row = self.all_rows("preview-atlas-conflict")[0]
        self.assertEqual("WILL_MANUAL_REVIEW", row["predicted_state"])
        self.assertEqual("RULE_CONFLICT", row["reason_code"])
        self.assertGreaterEqual(len(row["matched_rules"]), 2)
        self.assertIsNone(row["selected_rule"])
        self.assertIsNone(row["target"])

    def test_selected_rule_is_the_minimum_priority_match(self):
        row = self.all_rows("preview-atlas-hetero")[0]
        self.assertEqual("rule-atlas-invoices-invoice", row["selected_rule"]["rule_id"])
        priorities = [
            pp._rule_entry(self.context, reference)["priority"]
            for reference in row["matched_rules"]
        ]
        self.assertEqual(min(priorities), 10)
        self.assertGreater(max(priorities), min(priorities))

    def test_existing_target_carries_the_occupying_metadata(self):
        row = next(
            r for r in self.all_rows("preview-atlas-hetero")
            if r["item_id"] == "preview-atlas-occupied-report"
        )
        collision = row["collision"]
        self.assertEqual("EXISTING_TARGET", collision["kind"])
        self.assertIsNotNone(collision["existing_target_metadata"])
        self.assertEqual(row["target"], collision["existing_target_metadata"]["location"])
        self.assertEqual([], collision["conflicting_item_ids"])

    def test_duplicate_plan_target_lists_every_participant(self):
        rows = [
            r for r in self.all_rows("preview-atlas-hetero")
            if isinstance(r.get("collision"), dict)
            and r["collision"]["kind"] == "DUPLICATE_PLAN_TARGET"
        ]
        self.assertEqual(2, len(rows))
        ids = sorted(row["item_id"] for row in rows)
        for row in rows:
            with self.subTest(row=row["item_id"]):
                self.assertEqual(ids, sorted(row["collision"]["conflicting_item_ids"]))
                self.assertIsNone(row["collision"]["existing_target_metadata"])
                self.assertEqual(rows[0]["target"], row["target"])

    def test_manual_review_name_has_no_target(self):
        row = next(
            r for r in self.all_rows("preview-atlas-hetero")
            if r["item_id"] == "preview-atlas-manual-name"
        )
        self.assertEqual("MANUAL_REVIEW_NAME", row["collision"]["kind"])
        self.assertIsNone(row["target"])
        self.assertIsNotNone(row["collision"]["existing_target_metadata"])

    def test_not_ready_has_null_target(self):
        row = next(
            r for r in self.all_rows("preview-atlas-hetero")
            if r["item_id"] == "preview-atlas-not-ready"
        )
        self.assertEqual("NOT_READY", row["predicted_state"])
        self.assertIsNone(row["target"])
        self.assertIsNone(row["collision"])


class PreviewBindingTests(PreviewMixin, unittest.TestCase):
    def test_total_equals_the_frozen_selection_count(self):
        for preview_id, pages in self.context["preview_groups"].items():
            selection = self.context["selections"][pages[0]["selection_id"]]
            with self.subTest(preview=preview_id):
                self.assertEqual(
                    selection["snapshot"]["selected_count"], pages[0]["total"]
                )

    def test_rows_keep_the_frozen_revisions_and_sources(self):
        for preview_id in self.context["preview_groups"]:
            selection = self.context["selections"][
                self.context["preview_groups"][preview_id][0]["selection_id"]
            ]
            for row in self.all_rows(preview_id):
                member = selection["members"][row["item_id"]]
                with self.subTest(preview=preview_id, row=row["item_id"]):
                    self.assertEqual(member["item_revision"], row["item_revision"])
                    self.assertEqual(member["location"], row["source"])
                    self.assertEqual(member["filename"], row["filename"])

    def test_rows_cover_exactly_the_selection_membership(self):
        for preview_id in self.context["preview_groups"]:
            selection = self.context["selections"][
                self.context["preview_groups"][preview_id][0]["selection_id"]
            ]
            with self.subTest(preview=preview_id):
                self.assertEqual(
                    sorted(selection["member_order"]),
                    sorted(row["item_id"] for row in self.all_rows(preview_id)),
                )

    def test_120_preview_pages_at_the_limit(self):
        page1 = self.preview("preview-atlas-allmatching-120-page1")
        page2 = self.preview("preview-atlas-allmatching-120-page2")
        self.assertEqual(120, page1["total"])
        self.assertEqual(100, len(page1["rows"]))
        self.assertEqual(20, len(page2["rows"]))
        self.assertIsNotNone(page1["next_cursor"])
        self.assertIsNone(page2["next_cursor"])

    def test_explicit_one_and_multiple_totals(self):
        self.assertEqual(1, self.preview("preview-atlas-explicit-one")["total"])
        self.assertEqual(
            1, len(self.preview("preview-atlas-explicit-one")["rows"])
        )
        self.assertEqual(
            3, self.preview("preview-atlas-explicit-multiple")["total"]
        )
        self.assertEqual(
            3, len(self.preview("preview-atlas-explicit-multiple")["rows"])
        )

    def test_preview_ttl_does_not_outlive_the_selection(self):
        for preview_id, pages in self.context["preview_groups"].items():
            selection = self.context["selections"][pages[0]["selection_id"]]
            with self.subTest(preview=preview_id):
                self.assertLessEqual(
                    pp._instant(pages[0]["expires_at"]),
                    pp._instant(selection["snapshot"]["expires_at"]),
                )

    def test_preview_references_are_published_and_not_null(self):
        for entry in self.expectations["previews"]:
            payload = pp.materialize_preview(entry, self.context)
            for row in payload["rows"]:
                for reference in list(row["matched_rules"]) + (
                    [row["selected_rule"]] if row["selected_rule"] else []
                ):
                    with self.subTest(page=entry["page_id"], rule=reference["rule_id"]):
                        self.assertIsNotNone(reference["version_id"])

    def test_published_preview_uses_the_accepted_rule_set(self):
        page = self.preview("preview-atlas-allmatching-120-page1")
        self.assertEqual("rule-set-atlas-published", page["rule_set"]["rule_set_id"])
        self.assertEqual(
            "company-demo-atlas", page["rule_set"]["company_id"]
        )
        self.assertEqual(
            [{"dictionary_id": "dictionary-atlas-general", "version_id": "version-atlas-general-v1"},
             {"dictionary_id": "dictionary-atlas-invoices", "version_id": "version-atlas-invoices-v1"}],
            page["rule_set"]["members"],
        )

    def test_rule_set_consistency_across_previews(self):
        seen = {}
        for entry in self.expectations["previews"]:
            payload = pp.materialize_preview(entry, self.context)
            rule_set = payload["rule_set"]
            signature = (
                rule_set["company_id"],
                tuple((m["dictionary_id"], m["version_id"]) for m in rule_set["members"]),
            )
            seen.setdefault(rule_set["rule_set_id"], set()).add(signature)
        for rule_set_id, signatures in seen.items():
            with self.subTest(rule_set=rule_set_id):
                self.assertEqual(1, len(signatures))


class PreflightTests(PreviewMixin, unittest.TestCase):
    def test_accepted_scenarios_create_no_batch_payload(self):
        accepted = [
            entry for entry in self.expectations["preflight"]
            if entry["expected"]["accepted"]
        ]
        self.assertTrue(accepted)
        for entry in accepted:
            with self.subTest(scenario=entry["scenario_id"]):
                self.assertEqual(202, entry["expected"]["status"])
                self.assertIsNone(entry["expected"]["code"])
                self.assertTrue(entry["expected"]["batch_created"])
                self.assertFalse(entry["expected"]["file_operations"])
                self.assertTrue(entry["expected"]["future_batch_id"])
                self.assertNotIn("batch", entry)
                self.assertIsNone(entry["error_id"])

    def test_direct_source_change_is_selection_changed(self):
        entry = next(
            e for e in self.expectations["preflight"]
            if e["scenario_id"] == "PF-DIRECT-SOURCE-CHANGED"
        )
        self.assertEqual("DIRECT", entry["execution_mode"])
        self.assertEqual("SELECTION_CHANGED", entry["expected"]["code"])
        self.assertEqual(409, entry["expected"]["status"])
        self.assertFalse(entry["expected"]["batch_created"])
        self.assertFalse(entry["expected"]["file_operations"])

    def test_previewed_stale_causes_are_stale_preview(self):
        stale = [
            e for e in self.expectations["preflight"]
            if e["expected"].get("code") == "STALE_PREVIEW"
        ]
        self.assertEqual(
            {"source_changed", "rules_changed", "target_changed", "preview_ttl"},
            {entry["cause"] for entry in stale},
        )
        for entry in stale:
            with self.subTest(scenario=entry["scenario_id"]):
                self.assertEqual("PREVIEWED", entry["execution_mode"])

    def test_expired_selection_is_selection_expired(self):
        expired = [
            e for e in self.expectations["preflight"]
            if e["expected"].get("code") == "SELECTION_EXPIRED"
        ]
        self.assertTrue(expired)
        for entry in expired:
            with self.subTest(scenario=entry["scenario_id"]):
                self.assertTrue((entry.get("expired") or {}).get("selection"))

    def test_invalid_state_covers_pairing_and_company(self):
        invalid = [
            e for e in self.expectations["preflight"]
            if e["expected"].get("code") == "INVALID_STATE"
        ]
        self.assertTrue(any(e.get("pairing_mismatch") for e in invalid))
        self.assertTrue(any(e.get("company_mismatch") for e in invalid))

    def test_unknown_and_forbidden_use_real_operations(self):
        for scenario_id, code, status in (
            ("PF-NOT-FOUND-SELECTION", "NOT_FOUND", 404),
            ("PF-NOT-FOUND-PREVIEW", "NOT_FOUND", 404),
            ("PF-FORBIDDEN-OTHER-USER", "FORBIDDEN", 403),
        ):
            entry = next(
                e for e in self.expectations["preflight"]
                if e["scenario_id"] == scenario_id
            )
            with self.subTest(scenario=scenario_id):
                self.assertEqual(code, entry["expected"]["code"])
                self.assertEqual(status, entry["expected"]["status"])
                self.assertFalse(entry["expected"]["batch_created"])

    def test_same_user_new_session_is_allowed(self):
        entry = next(
            e for e in self.expectations["preflight"]
            if e["scenario_id"] == "PF-SAME-USER-NEW-SESSION"
        )
        self.assertTrue(entry["new_session"])
        self.assertTrue(entry["expected"]["accepted"])
        self.assertEqual(entry["owner"], entry["requesting_actor"])

    def test_every_rejection_has_request_precondition_and_error(self):
        for entry in self.expectations["preflight"]:
            if entry["expected"]["accepted"]:
                continue
            with self.subTest(scenario=entry["scenario_id"]):
                self.assertTrue(entry["precondition"])
                self.assertTrue(entry["reason"])
                self.assertIsNotNone(entry["error_id"])
                self.assertFalse(entry["expected"]["batch_created"])
                self.assertFalse(entry["expected"]["file_operations"])
                self.assertNotIn("batch", entry)
                request = pp.materialize_request(entry)
                self.assertEqual(entry["selection_id"], request["selection_id"])

    def test_error_codes_match_their_operation(self):
        from contractlib.search_expectations import allowed_error_codes

        for entry in self.expectations["preflight"]:
            expected = entry["expected"]
            if expected["accepted"]:
                continue
            with self.subTest(scenario=entry["scenario_id"]):
                allowed = allowed_error_codes(
                    self.context["document"], entry["operation"], expected["status"]
                )
                self.assertIn(expected["code"], allowed)

    def test_post_acceptance_outcomes_are_per_file(self):
        for entry in self.expectations["post_acceptance"]:
            with self.subTest(outcome=entry["outcome_id"]):
                self.assertTrue(entry["batch_created"])
                self.assertFalse(entry["global_refusal"])
                self.assertLess(entry["http_status"], 400)
                self.assertIn(
                    entry["reason_code"],
                    {"SOURCE_CHANGED", "ALREADY_PROCESSING", "TARGET_OCCUPIED", "MANUAL_REVIEW_NAME_OCCUPIED"},
                )

    def test_source_change_and_claim_overlap_are_not_global_refusals(self):
        by_id = {e["outcome_id"]: e for e in self.expectations["post_acceptance"]}
        source = by_id["PF-POST-SOURCE-CHANGED"]
        claim = by_id["PF-POST-CLAIM-OVERLAP"]
        self.assertEqual("SOURCE_CHANGED", source["reason_code"])
        self.assertTrue(source["returns_to_waiting_ready"])
        self.assertEqual("ALREADY_PROCESSING", claim["reason_code"])
        self.assertTrue(claim["other_items_continue"])
        self.assertFalse(source["global_refusal"])
        self.assertFalse(claim["global_refusal"])


class NegativeExpectationTests(PreviewMixin, unittest.TestCase):
    def _errors(self, expectations):
        return pp.expectation_errors(expectations, self.context_for(expectations))

    def test_wrong_preview_total_is_caught(self):
        mutated = self.mutate(self.expectations, "set", ["previews", 0, "total"], 119)
        errors = self._errors(mutated)
        self.assertTrue(any("total" in message for message in errors), errors)

    def test_preview_ttl_beyond_selection_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["previews", 0, "expires_at"], "2031-05-10T09:40:00Z"
        )
        errors = self._errors(mutated)
        self.assertTrue(any("expires_at" in message for message in errors), errors)

    def test_selection_count_drift_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["selections", 3, "snapshot", "selected_count"], 7
        )
        errors = self._errors(mutated)
        self.assertTrue(any("selected_count" in message for message in errors), errors)

    def test_row_revision_drift_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["previews", 0, "rows", "$repeat_rows", "item_revision"],
            99,
        )
        errors = self._errors(mutated)
        self.assertTrue(any("revision" in message for message in errors), errors)

    def test_non_minimum_selected_rule_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["previews", 4, "rows", 0, "selected_rule"],
            {
                "dictionary_id": "dictionary-atlas-invoices",
                "version_id": "version-atlas-invoices-v1",
                "rule_id": "rule-atlas-invoices-upper",
            },
        )
        errors = self._errors(mutated)
        self.assertTrue(any("minimum-priority" in message for message in errors), errors)

    def test_no_scenario_with_a_match_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["previews", 4, "rows", 2, "matched_rules"],
            [
                {
                    "dictionary_id": "dictionary-atlas-general",
                    "version_id": "version-atlas-general-v1",
                    "rule_id": "rule-atlas-general-readme",
                }
            ],
        )
        errors = self._errors(mutated)
        self.assertTrue(any("NO_SCENARIO" in message for message in errors), errors)

    def test_existing_target_without_metadata_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "remove",
            ["previews", 4, "rows", 3, "collision", "existing_target_metadata"],
        )
        errors = self._errors(mutated)
        self.assertTrue(any("existing_target_metadata" in message for message in errors), errors)

    def test_duplicate_target_with_incomplete_participants_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["previews", 4, "rows", 4, "collision", "conflicting_item_ids"],
            ["preview-atlas-invoice-a"],
        )
        errors = self._errors(mutated)
        self.assertTrue(any("participant" in message.lower() for message in errors), errors)

    def test_accepted_scenario_with_error_code_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["preflight", 0, "expected", "code"], "STALE_PREVIEW"
        )
        errors = self._errors(mutated)
        self.assertTrue(any("error code" in message for message in errors), errors)

    def test_direct_source_change_as_stale_preview_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["preflight", 3, "expected", "code"], "STALE_PREVIEW"
        )
        errors = self._errors(mutated)
        self.assertTrue(any("STALE_PREVIEW" in message for message in errors), errors)

    def test_wrong_invalid_request_classification_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["invalid_requests", 1, "schema_rejected"], False
        )
        errors = pp.schema_rejection_errors(mutated, self.registry)
        self.assertTrue(errors)

    def test_reference_outside_the_rule_set_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["previews", 4, "rows", 0, "matched_rules", 0, "version_id"],
            "version-nova-general-v1",
        )
        errors = self._errors(mutated)
        self.assertTrue(any("RuleSet" in message for message in errors), errors)

    def test_undefined_rule_reference_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["previews", 4, "rows", 1, "matched_rules", 0, "rule_id"],
            "rule-does-not-exist",
        )
        errors = self._errors(mutated)
        self.assertTrue(any("undefined rule" in message for message in errors), errors)

    def test_collision_source_mismatch_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["previews", 4, "rows", 3, "collision", "source_metadata", "filename"],
            "other.pdf",
        )
        errors = self._errors(mutated)
        self.assertTrue(any("source filename" in message for message in errors), errors)

    def test_relabelled_direct_with_preview_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["preflight", 1, "execution_mode"], "DIRECT"
        )
        errors = self._errors(mutated)
        self.assertTrue(any("DIRECT" in message for message in errors), errors)

    def test_invalid_state_without_a_mismatch_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["preflight", 12, "company_mismatch"], False
        )
        errors = self._errors(mutated)
        self.assertTrue(any("INVALID_STATE" in message for message in errors), errors)

    def test_missing_precondition_is_caught(self):
        mutated = self.mutate(
            self.expectations, "remove", ["preflight", 3, "precondition"]
        )
        errors = self._errors(mutated)
        self.assertTrue(any("precondition" in message for message in errors), errors)


if __name__ == "__main__":
    unittest.main()
