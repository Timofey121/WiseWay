"""Tests for the LT-03.1b literal search/facet/auth/error expectations.

The expectations are an *independent* oracle: these tests only check that the
literal data is internally consistent, schema-valid, fully traced to Q ids and
that the committed public examples equal the materialized literals.  No test
computes result membership, ranking or facet counts; the materializer merely
looks items up by the literal ids.
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
from contractlib import search_expectations as se  # noqa: E402
from contractlib import synthetic  # noqa: E402

REPO_ROOT = HERE.parents[1]
CONTRACT = REPO_ROOT / "contracts" / "openapi" / "wiseway-v1.yaml"


class SearchExpectationMixin:
    @classmethod
    def setUpClass(cls):
        cls.registry = build_registry(load_contract(CONTRACT))
        cls.expectations = se.load_expectations(REPO_ROOT)
        cls.context = se.build_context(REPO_ROOT)
        cls.search = cls.expectations["search_scenarios"]
        cls.facets = cls.expectations["facet_scenarios"]
        cls.errors = cls.expectations["error_scenarios"]


class OracleStructureTests(SearchExpectationMixin, unittest.TestCase):
    def test_expectations_have_no_structural_errors(self):
        self.assertEqual([], se.expectation_errors(self.expectations, self.context))

    def test_every_search_response_is_schema_valid(self):
        for scenario in self.search:
            with self.subTest(scenario=scenario["scenario_id"]):
                payload = se.materialize_search_response(
                    self.expectations, scenario, self.context
                )
                errors, semantic = validate_fixture(
                    self.registry, se.SEARCH_SCHEMA, payload
                )
                self.assertEqual([], errors, errors)
                self.assertEqual([], semantic, semantic)

    def test_every_facet_response_is_schema_valid(self):
        for scenario in self.facets:
            with self.subTest(scenario=scenario["scenario_id"]):
                payload = se.materialize_facet_response(
                    self.expectations, scenario, self.context
                )
                errors, semantic = validate_fixture(
                    self.registry, se.FACET_SCHEMA, payload
                )
                self.assertEqual([], errors, errors)
                self.assertEqual([], semantic, semantic)

    def test_every_error_response_is_schema_valid(self):
        for scenario in self.errors:
            with self.subTest(scenario=scenario["scenario_id"]):
                payload = se.materialize_error_response(scenario)
                errors, semantic = validate_fixture(
                    self.registry, se.ERROR_SCHEMA, payload
                )
                self.assertEqual([], errors, errors)
                self.assertEqual([], semantic, semantic)

    def test_tie_profile_inputs_are_schema_valid_search_items(self):
        for profile in self.expectations["sort_profiles"]:
            for entry in profile["inputs"]:
                with self.subTest(item=entry["item_id"]):
                    errors, semantic = validate_fixture(
                        self.registry, se.SEARCH_ITEM, entry
                    )
                    self.assertEqual([], errors, errors)
                    self.assertEqual([], semantic, semantic)

    def test_response_items_follow_the_literal_ordered_ids(self):
        for scenario in self.search:
            with self.subTest(scenario=scenario["scenario_id"]):
                payload = se.materialize_search_response(
                    self.expectations, scenario, self.context
                )
                self.assertEqual(
                    scenario["expected"]["item_ids"],
                    [item["item_id"] for item in payload["items"]],
                )
                self.assertEqual(
                    scenario["expected"]["returned_count"], len(payload["items"])
                )

    def test_selected_markers_expand_from_the_literal_ids(self):
        for scenario in self.search:
            payload = se.materialize_search_response(
                self.expectations, scenario, self.context
            )
            self.assertEqual(
                scenario["request"]["selected_marker_ids"],
                [marker["marker_id"] for marker in payload["selected_markers"]],
            )

    def test_ranking_scenarios_expose_manual_numeric_scores(self):
        ranking = {
            scenario["scenario_id"]: scenario
            for scenario in self.search
            if scenario.get("scores")
        }
        self.assertEqual(
            {"file-atlas-q009-space": 10, "file-atlas-q009-metrics": 5,
             "file-atlas-q009-backslash": 2, "file-atlas-q009-slash": 2},
            {key: ranking["SRCH-Q009-RANKING"]["scores"][key]
             for key in ("file-atlas-q009-space", "file-atlas-q009-metrics",
                         "file-atlas-q009-backslash", "file-atlas-q009-slash")},
        )
        self.assertEqual(
            {"file-atlas-q008-cross-field": 4},
            ranking["SRCH-Q011-RANK-PHRASE-CROSS"]["scores"],
        )
        self.assertEqual(20, ranking["SRCH-Q008-PHRASE"]["scores"]["file-nova-q008-atlas-main"])
        self.assertEqual(
            10, ranking["SRCH-Q011-RANK-FULL"]["scores"]["file-nova-q007-both"]
        )
        self.assertEqual(
            5, ranking["SRCH-Q011-RANK-PREFIX"]["scores"]["file-nova-q007-both"]
        )

    def test_unrecognized_option_is_last_when_present(self):
        for scenario in self.search:
            facet = scenario["expected"]["next_facet"]
            if not facet:
                continue
            kinds = [
                self.context["catalog"][option["marker_id"]]["kind"]
                for option in facet["options"]
            ]
            if "UNRECOGNIZED" in kinds:
                self.assertEqual("UNRECOGNIZED", kinds[-1], scenario["scenario_id"])
        for scenario in self.facets:
            kinds = [
                self.context["catalog"][option["marker_id"]]["kind"]
                for option in scenario["expected"]["options"]
            ]
            if "UNRECOGNIZED" in kinds:
                self.assertEqual("UNRECOGNIZED", kinds[-1], scenario["scenario_id"])


class AcceptanceTraceTests(SearchExpectationMixin, unittest.TestCase):
    def test_every_required_q_is_covered_by_finite_scenarios(self):
        coverage = self.expectations["coverage"]
        for q in se.KNOWN_Q:
            with self.subTest(q=q):
                self.assertTrue(coverage.get(q), f"{q} has no scenario ids")
                for scenario_id in coverage[q]:
                    self.assertTrue(scenario_id)

    def test_every_scenario_has_parameters_and_manual_reason(self):
        groups = (
            self.search
            + self.facets
            + self.expectations["auth_scenarios"]
            + self.errors
            + self.expectations["race_scenarios"]
            + self.expectations["lifecycle_scenarios"]
            + self.expectations["format_samples"]
        )
        for scenario in groups:
            with self.subTest(scenario=scenario["scenario_id"]):
                self.assertTrue(scenario["parameters"])
                self.assertTrue(scenario["reason"])

    def test_n10_and_n100_are_exact_l_plus_three(self):
        by_id = {scenario["scenario_id"]: scenario for scenario in self.search}
        n10 = by_id["SRCH-Q013-N10"]["expected"]
        self.assertEqual(13, n10["total"])
        self.assertEqual(10, n10["returned_count"])
        self.assertEqual(10, n10["result_limit"])
        self.assertTrue(n10["limited"])
        n100 = by_id["SRCH-Q013-N100"]["expected"]
        self.assertEqual(103, n100["total"])
        self.assertEqual(100, n100["returned_count"])
        self.assertEqual(100, n100["result_limit"])
        self.assertTrue(n100["limited"])

    def test_idle_scenarios_for_both_roots(self):
        by_id = {scenario["scenario_id"]: scenario for scenario in self.search}
        for scenario_id in ("SRCH-Q004-IDLE-ATLAS", "SRCH-Q004-IDLE-NOVA"):
            expected = by_id[scenario_id]["expected"]
            self.assertEqual("IDLE", expected["mode"])
            self.assertIsNone(expected["total"])
            self.assertEqual([], expected["item_ids"])
            self.assertEqual("level-section", expected["next_facet"]["level_id"])
            self.assertTrue(expected["next_facet"]["options"])

    def test_token_separators_cover_positive_and_negative_cases(self):
        by_id = {scenario["scenario_id"]: scenario for scenario in self.search}
        boundaries = by_id["SRCH-Q009-BOUNDARIES"]["expected"]["item_ids"]
        self.assertEqual(8, len(boundaries))
        for item_id in (
            "file-atlas-q009-symmetry",
            "file-atlas-q009-internal",
            "file-atlas-q009-preceded-letter",
            "file-atlas-q009-typo",
        ):
            self.assertNotIn(item_id, boundaries)

    def test_phrase_negatives_are_not_in_the_phrase_result(self):
        by_id = {scenario["scenario_id"]: scenario for scenario in self.search}
        items = by_id["SRCH-Q008-PHRASE"]["expected"]["item_ids"]
        self.assertEqual(
            ["file-nova-q008-mixed", "file-nova-q008-atlas-main"], items
        )
        for item_id in (
            "file-nova-q008-inserted",
            "file-nova-q008-prefix",
            "file-nova-q008-reversed",
        ):
            self.assertNotIn(item_id, items)
        cross = by_id["SRCH-Q008-PHRASE-CROSS-FIELD"]["expected"]["item_ids"]
        self.assertEqual(["file-atlas-rank-phrase"], cross)
        self.assertNotIn("file-atlas-q008-cross-field", cross)

    def test_content_old_path_and_service_exclusions_are_zero(self):
        by_id = {scenario["scenario_id"]: scenario for scenario in self.search}
        for scenario_id in (
            "SRCH-Q014-CONTENT-ONLY",
            "SRCH-Q014-OLD-PATH",
            "SRCH-Q014-SERVICE-INCOMING",
            "SRCH-Q014-SERVICE-QUARANTINE",
            "SRCH-Q014-SERVICE-TMP",
        ):
            expected = by_id[scenario_id]["expected"]
            self.assertEqual(0, expected["total"], scenario_id)
            self.assertEqual([], expected["item_ids"], scenario_id)
        current = by_id["SRCH-Q014-CURRENT-CONTROL"]["expected"]["item_ids"]
        self.assertEqual(["file-atlas-old-path"], current)

    def test_four_structure_issues_and_unrecognized_terminal_are_covered(self):
        by_id = {scenario["scenario_id"]: scenario for scenario in self.search}
        for scenario_id in (
            "SRCH-Q012-ISSUE-UNEXPECTED-DEPTH",
            "SRCH-Q012-ISSUE-INVALID-VALUE",
            "SRCH-Q012-ISSUE-INVALID-COMPOSITE",
            "SRCH-Q012-ISSUE-MISSING-AREA",
        ):
            self.assertEqual(1, by_id[scenario_id]["expected"]["total"], scenario_id)
        terminal = by_id["SRCH-Q012-UNRECOGNIZED-TERMINAL"]
        self.assertEqual(["file-atlas-issue-invalid-value"], terminal["expected"]["item_ids"])
        self.assertIsNone(terminal["expected"]["next_facet"])

    def test_manual_sort_directions_are_declared(self):
        fields = {
            (scenario["request"]["sort"]["field"], scenario["request"]["sort"]["direction"])
            for scenario in self.search
        }
        for pair in (
            ("NAME", "ASC"), ("NAME", "DESC"),
            ("SIZE", "ASC"), ("SIZE", "DESC"),
            ("MODIFIED_AT", "ASC"), ("MODIFIED_AT", "DESC"),
            ("PATH", "ASC"), ("PATH", "DESC"),
        ):
            self.assertIn(pair, fields)

    def test_tie_break_natural_and_raw_are_exercised(self):
        by_id = {scenario["scenario_id"]: scenario for scenario in self.search}
        natural = by_id["SRCH-Q011-TIE-NATURAL"]["expected"]["item_ids"]
        self.assertEqual(
            [
                "file-atlas-natural-2",
                "file-atlas-natural-10",
                "file-atlas-tie-a",
                "file-atlas-tie-b",
            ],
            natural,
        )
        raw = by_id["SRCH-Q011-TIE-RAW"]["expected"]["item_ids"]
        self.assertEqual(
            ["file-atlas-tie-raw-note-upper", "file-atlas-tie-raw-note-lower"], raw
        )

    def test_error_status_code_pairs_are_exact(self):
        pairs = {
            scenario["scenario_id"]: (scenario["status"], scenario["code"])
            for scenario in self.errors
        }
        expected = {
            "AUTH-Q001-UNAUTHENTICATED": (401, "UNAUTHENTICATED"),
            "AUTH-Q001-LOGIN-FAILED": (401, "LOGIN_FAILED"),
            "AUTH-Q002-EXPIRY": (401, "UNAUTHENTICATED"),
            "AUTH-Q002-BLOCK": (401, "UNAUTHENTICATED"),
            "AUTH-Q003-SEARCH-503": (503, "SEARCH_UNAVAILABLE"),
            "AUTH-Q003-INTERNAL-500": (500, "INTERNAL_ERROR"),
            "SRCH-Q010-INVALID-QUOTE": (400, "INVALID_QUERY"),
            "SRCH-Q010-LENGTH": (422, "VALIDATION_ERROR"),
            "SRCH-Q010-INVALID-MARKER": (422, "INVALID_MARKER_SELECTION"),
            "SRCH-Q010-SCHEMA-CHANGED": (409, "SCHEMA_VERSION_CHANGED"),
            "SRCH-Q010-ROOT-NOT-READY": (409, "ROOT_NOT_READY"),
            "CONTRACT-Q043-CSRF": (403, "CSRF_FAILED"),
            "CONTRACT-Q043-FORBIDDEN": (403, "FORBIDDEN"),
            "CONTRACT-Q043-RATE-LIMITED": (429, "RATE_LIMITED"),
        }
        self.assertEqual(expected, pairs)
        for scenario in self.errors:
            self.assertIsNone(scenario["operation_id"])
            payload = se.materialize_error_response(scenario)
            self.assertEqual(scenario["request_id"], payload["error"]["request_id"])
            self.assertIsNone(payload["error"]["operation_id"])

    def test_error_codes_follow_the_operation_response_schema(self):
        document = self.context["document"]
        for scenario in self.errors:
            allowed = se.allowed_error_codes(
                document, scenario["operation"], scenario["status"]
            )
            self.assertIn(scenario["code"], allowed, scenario["scenario_id"])
        # searchFiles 403 declares only FORBIDDEN; the mutation 403 allows CSRF.
        self.assertEqual(
            {"FORBIDDEN"}, se.allowed_error_codes(document, "searchFiles", 403)
        )
        self.assertIn(
            "CSRF_FAILED", se.allowed_error_codes(document, "logout", 403)
        )

    def test_error_scenarios_carry_concrete_preconditions(self):
        for scenario in self.errors:
            with self.subTest(scenario=scenario["scenario_id"]):
                self.assertTrue(scenario["precondition"])
        csrf = next(s for s in self.errors if s["scenario_id"] == "CONTRACT-Q043-CSRF")
        self.assertEqual("logout", csrf["operation"])
        self.assertIn("X-CSRF-Token", csrf["request_headers"])
        forbidden = next(
            s for s in self.errors if s["scenario_id"] == "CONTRACT-Q043-FORBIDDEN"
        )
        self.assertEqual("login", forbidden["operation"])
        self.assertIn("Origin", forbidden["request_headers"])

    def test_freshness_profiles_cover_current_updating_stale(self):
        profiles = self.expectations["constants"]["freshness_profiles"]
        self.assertEqual({"CURRENT", "UPDATING", "STALE"}, set(profiles))
        for profile in profiles.values():
            self.assertIn(profile["status"], {"CURRENT", "UPDATING", "STALE"})

    def test_previous_generation_available_during_update_and_stale(self):
        by_id = {scenario["scenario_id"]: scenario for scenario in self.search}
        base = by_id["SRCH-Q011-RANK-FULL"]["expected"]
        for scenario_id, profile in (
            ("SRCH-Q011-FRESHNESS-UPDATING", "UPDATING"),
            ("SRCH-Q003-FRESHNESS-STALE", "STALE"),
        ):
            scenario = by_id[scenario_id]
            self.assertEqual(profile, scenario["freshness_profile"])
            self.assertEqual(base["item_ids"], scenario["expected"]["item_ids"])
            self.assertEqual(base["total"], scenario["expected"]["total"])
            payload = se.materialize_search_response(
                self.expectations, scenario, self.context
            )
            self.assertEqual(profile, payload["freshness"]["status"])
            self.assertEqual(len(base["item_ids"]), len(payload["items"]))

    def test_item_id_tie_profile_is_stand_alone_and_ordered(self):
        profiles = self.expectations["sort_profiles"]
        self.assertEqual(1, len(profiles))
        profile = profiles[0]
        self.assertEqual("tie_profile", profile["kind"])
        self.assertTrue(profile["standalone"])
        inputs = profile["inputs"]
        self.assertEqual(2, len(inputs))
        keys = {
            (entry["location"]["display_path"], entry["location"]["relative_path"], entry["filename"])
            for entry in inputs
        }
        self.assertEqual(1, len(keys))
        self.assertEqual(
            sorted(entry["item_id"] for entry in inputs),
            profile["expected_item_ids"],
        )
        self.assertNotIn(
            profile["expected_item_ids"][0],
            {item["item_id"] for item in self.context["inventory"].values()},
        )

    def test_races_pick_the_latest_request_state_id(self):
        for scenario in self.expectations["race_scenarios"]:
            with self.subTest(scenario=scenario["scenario_id"]):
                accepted = scenario["accepted"]
                send_ids = [send["request_state_id"] for send in scenario["sends"]]
                self.assertEqual(send_ids[-1], accepted)
                self.assertNotIn(accepted, scenario["stale_ignored"])

    def test_lifecycle_stages_are_traced_to_the_fixture(self):
        for scenario in self.expectations["lifecycle_scenarios"]:
            state = self.context["lifecycle"][scenario["stage"]]
            self.assertEqual(state["item_id"], scenario["item_id"])
        rename = next(
            s for s in self.expectations["lifecycle_scenarios"] if s["stage"] == "rename"
        )
        self.assertIn("old-name", rename["before_path"])
        self.assertIn("new-name", rename["after_path"])
        delete = next(
            s for s in self.expectations["lifecycle_scenarios"] if s["stage"] == "delete"
        )
        self.assertIsNone(delete["after_path"])
        self.assertEqual([], delete["after_match_item_ids"])

    def test_format_samples_are_literal_ui_values(self):
        by_kind = {sample["kind"]: sample for sample in self.expectations["format_samples"]}
        self.assertIn({"bytes": 0, "expected": "0 B"}, by_kind["size"]["cases"])
        self.assertIn({"bytes": 1500, "expected": "1.5 KB"}, by_kind["size"]["cases"])
        self.assertIn(
            {"instant": "2031-05-10T09:30:00Z", "timezone": "Europe/Moscow",
             "expected": "10.05.2031 12:30"},
            by_kind["date"]["cases"],
        )
        for case in by_kind["display_path"]["cases"]:
            item = self.context["inventory"][case["item_id"]]
            self.assertEqual(item["location"]["display_path"], case["expected_display_path"])


class GeneratedExampleTests(SearchExpectationMixin, unittest.TestCase):
    def test_generated_examples_match_committed_files(self):
        generated = se.generated_examples(self.expectations, self.context)
        self.assertEqual(17, len(generated))
        for relative, payload in generated.items():
            with self.subTest(file=relative):
                committed = synthetic.load_json(REPO_ROOT / relative)
                self.assertEqual(committed, payload)

    def test_every_generated_example_is_bound_in_the_manifest(self):
        manifest = self.context["manifest"]
        bound = {entry["file"]: entry["schema"] for entry in manifest["examples"]}
        for binding in se.EXAMPLE_BINDINGS:
            self.assertIn(binding["file"], bound)
            self.assertEqual(binding["schema"], bound[binding["file"]])


class NegativeExpectationTests(SearchExpectationMixin, unittest.TestCase):
    def test_mutated_returned_count_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        expectations["search_scenarios"][0]["expected"]["returned_count"] = 5
        errors = se.expectation_errors(expectations, self.context)
        self.assertTrue(any("returned_count" in message for message in errors), errors)

    def test_mutated_total_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        scenario = next(s for s in expectations["search_scenarios"] if s["expected"]["mode"] == "RESULTS")
        scenario["expected"]["total"] = scenario["expected"]["total"] + 1
        errors = se.expectation_errors(expectations, self.context)
        self.assertTrue(any("limited" in message or "returned_count" in message for message in errors), errors)

    def test_mutated_order_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        scenario = next(
            s
            for s in expectations["search_scenarios"]
            if s.get("scores") and len(set(s["scores"].values())) > 1
        )
        scenario["expected"]["item_ids"] = list(reversed(scenario["expected"]["item_ids"]))
        errors = se.expectation_errors(expectations, self.context)
        self.assertTrue(any("non-increasing" in message for message in errors), errors)

    def test_mutated_item_link_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        scenario = next(s for s in expectations["search_scenarios"] if s["expected"]["item_ids"])
        scenario["expected"]["item_ids"][0] = "file-does-not-exist"
        errors = se.expectation_errors(expectations, self.context)
        self.assertTrue(any("unknown item_id" in message for message in errors), errors)

    def test_mutated_facet_count_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        facet = expectations["facet_scenarios"][0]
        facet["expected"]["options"][0]["count"] = 0
        errors = se.expectation_errors(expectations, self.context)
        self.assertTrue(any("count must be >= 1" in message for message in errors), errors)

    def test_mutated_coverage_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        expectations["coverage"]["Q-007"] = []
        errors = se.expectation_errors(expectations, self.context)
        self.assertTrue(any("Q-007" in message for message in errors), errors)

    def test_mutated_error_code_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        expectations["error_scenarios"][0]["code"] = "NOT_A_CODE"
        errors = se.expectation_errors(expectations, self.context)
        self.assertTrue(any("unknown error code" in message for message in errors), errors)

    def test_broken_marker_chain_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        scenario = next(s for s in expectations["search_scenarios"] if len(s["request"]["selected_marker_ids"]) >= 2)
        scenario["request"]["selected_marker_ids"] = list(reversed(scenario["request"]["selected_marker_ids"]))
        errors = se.expectation_errors(expectations, self.context)
        self.assertTrue(any("chain" in message for message in errors), errors)

    def test_missing_reason_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        expectations["search_scenarios"][0]["reason"] = ""
        errors = se.expectation_errors(expectations, self.context)
        self.assertTrue(any("reason" in message for message in errors), errors)

    def test_wrong_operation_error_code_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        scenario = next(
            s for s in expectations["error_scenarios"] if s["scenario_id"] == "CONTRACT-Q043-CSRF"
        )
        scenario["operation"] = "searchFiles"  # 403 there declares only FORBIDDEN
        errors = se.expectation_errors(expectations, self.context)
        self.assertTrue(
            any("not declared by operation" in message for message in errors), errors
        )

    def test_unrecognized_item_marker_is_caught(self):
        context = copy.deepcopy(self.context)
        item = context["inventory"]["file-atlas-issue-invalid-value"]
        terminal = next(
            entry
            for entry in context["catalog"].values()
            if entry["kind"] == "UNRECOGNIZED"
            and entry["level_id"] == "level-category"
        )
        item["markers"] = item["markers"] + [synthetic.marker_payload(terminal)]
        errors = se.expectation_errors(self.expectations, context)
        self.assertTrue(
            any("non-VALUE marker" in message for message in errors), errors
        )
        self.assertTrue(synthetic.path_marker_errors(item), "path_marker_errors missed it")

    def test_tie_profile_order_mutation_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        profile = expectations["sort_profiles"][0]
        profile["expected_item_ids"] = list(reversed(profile["expected_item_ids"]))
        errors = se.expectation_errors(expectations, self.context)
        self.assertTrue(
            any("item_id ASC" in message for message in errors), errors
        )


class CorpusUnrecognizedTests(SearchExpectationMixin, unittest.TestCase):
    def test_issue_items_carry_only_recognized_value_parents(self):
        cases = {
            "file-atlas-issue-invalid-value": "level-category",
            "file-atlas-issue-invalid-composite": "level-project",
            "file-nova-issue-missing-area": "level-area",
        }
        for item_id, level_id in cases.items():
            item = self.context["inventory"][item_id]
            self.assertEqual("UNRECOGNIZED", item["structure_status"], item_id)
            self.assertEqual(level_id, item["structure_issue"]["level_id"], item_id)
            self.assertTrue(item["markers"], item_id)
            for marker in item["markers"]:
                self.assertEqual("VALUE", marker["kind"], item_id)
                self.assertIsNotNone(marker["raw_value"], item_id)
            self.assertEqual([], synthetic.path_marker_errors(item), item_id)

    def test_catalog_terminal_is_not_attached_to_any_item(self):
        catalog = self.context["catalog"]
        terminals = {
            marker_id
            for marker_id, entry in catalog.items()
            if entry["kind"] == "UNRECOGNIZED"
        }
        self.assertTrue(terminals)
        attached = {
            marker["marker_id"]
            for item in self.context["inventory"].values()
            for marker in item["markers"]
        }
        self.assertEqual(set(), terminals & attached)

    def test_unrecognized_facet_option_is_literally_linked_to_the_first_issue(self):
        scenario = next(
            s
            for s in self.facets
            if s["scenario_id"] == "FACET-Q012-ATLAS-ORION-CATEGORY"
        )
        sources = scenario["expected"]["unrecognized_sources"]
        self.assertEqual(1, len(sources))
        source = sources[0]
        option = next(
            o
            for o in scenario["expected"]["options"]
            if o["marker_id"] == source["marker_id"]
        )
        self.assertEqual(1, option["count"])
        item = self.context["inventory"][source["item_id"]]
        self.assertEqual("UNRECOGNIZED", item["structure_status"])
        self.assertEqual(source["issue_code"], item["structure_issue"]["code"])
        self.assertEqual(source["issue_level_id"], item["structure_issue"]["level_id"])
        self.assertEqual(
            source["issue_level_id"], self.context["catalog"][source["marker_id"]]["level_id"]
        )


if __name__ == "__main__":
    unittest.main()
