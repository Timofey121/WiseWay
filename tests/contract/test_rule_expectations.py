"""Tests for the LT-03.2a literal rule/target expectations.

The expectations are an *independent* oracle: these tests only check that the
literal data is internally consistent, schema-valid, fully traced to Q ids and
that the committed public examples equal the materialized literals.  No test
matches a mask, picks a winning priority, resolves a conflict or derives a
target name; the materializer merely looks the already-declared rules up by
their literal ids.
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
from contractlib import rule_expectations as re  # noqa: E402
from contractlib import synthetic  # noqa: E402
from contractlib.schemas import validate_value  # noqa: E402

REPO_ROOT = HERE.parents[1]
CONTRACT = REPO_ROOT / "contracts" / "openapi" / "wiseway-v1.yaml"


class RuleExpectationMixin:
    @classmethod
    def setUpClass(cls):
        cls.registry = build_registry(load_contract(CONTRACT))
        cls.expectations = re.load_expectations(REPO_ROOT)
        cls.context = re.build_context(REPO_ROOT, cls.expectations)
        cls.rules = cls.expectations["rule_scenarios"]
        cls.targets = cls.expectations["target_scenarios"]
        cls.invalid = cls.expectations["invalid_rule_cases"]

    def context_for(self, expectations):
        return re.build_context(REPO_ROOT, expectations)


class OracleStructureTests(RuleExpectationMixin, unittest.TestCase):
    def test_expectations_have_no_structural_errors(self):
        self.assertEqual([], re.expectation_errors(self.expectations, self.context))

    def test_schema_rejection_classification_is_correct(self):
        self.assertEqual([], re.schema_rejection_errors(self.expectations, self.registry))
        for case in self.invalid:
            with self.subTest(case=case["case_id"]):
                rule = re.materialize_rule(case["rule"], self.context)
                errors = validate_value(self.registry, re.RULE_SCHEMA, rule)
                self.assertEqual(case["schema_rejected"], bool(errors))

    def test_every_rule_scenario_materializes_to_a_schema_valid_plan_row(self):
        for scenario in self.rules:
            with self.subTest(scenario=scenario["scenario_id"]):
                payload = re.materialize_plan_row(scenario, self.context)
                schema_errors, semantic = validate_fixture(
                    self.registry, re.PLAN_ROW_SCHEMA, payload
                )
                self.assertEqual([], schema_errors, schema_errors)
                self.assertEqual([], semantic, semantic)

    def test_every_target_directory_and_version_is_schema_valid(self):
        for target in self.expectations["target_directories"]:
            with self.subTest(target=target["target_id"]):
                payload = re.materialize_target_directory(target, self.context)
                schema_errors, semantic = validate_fixture(
                    self.registry, re.TARGET_DIRECTORY_SCHEMA, payload
                )
                self.assertEqual([], schema_errors, schema_errors)
                self.assertEqual([], semantic, semantic)
        for version in self.expectations["versions"]:
            with self.subTest(version=version["version_id"]):
                payload = re.materialize_version(version, self.context)
                schema_errors, semantic = validate_fixture(
                    self.registry, re.DICTIONARY_VERSION_SCHEMA, payload
                )
                self.assertEqual([], schema_errors, schema_errors)
                self.assertEqual([], semantic, semantic)

    def test_typed_rule_roundtrip_preserves_all_fields(self):
        seen = 0
        for version in self.expectations["versions"]:
            for rule_entry in version["rules"]:
                seen += 1
                with self.subTest(rule=rule_entry["rule_id"]):
                    rule = re.materialize_rule(rule_entry, self.context)
                    self.assertEqual(
                        {
                            "rule_id",
                            "priority",
                            "match_field",
                            "mask",
                            "target",
                            "target_stem",
                        },
                        set(rule),
                    )
                    self.assertEqual(
                        {"root_id", "relative_directory"}, set(rule["target"])
                    )
                    errors, semantic = validate_fixture(
                        self.registry, re.RULE_SCHEMA, rule
                    )
                    self.assertEqual([], errors, errors)
                    self.assertEqual([], semantic, semantic)
                    self.assertEqual(rule, json.loads(json.dumps(rule)))
        self.assertGreater(seen, 0)


class AcceptanceTraceTests(RuleExpectationMixin, unittest.TestCase):
    def test_two_companies_and_the_exact_auth_actors(self):
        company_ids = {c["company_id"] for c in self.expectations["companies"]}
        self.assertEqual({"company-demo-atlas", "company-demo-nova"}, company_ids)
        self.assertEqual(
            {
                "user-demo-worker-1",
                "user-demo-worker-2",
                "user-demo-admin-1",
            },
            set(self.context["actors"]),
        )
        for alias, actor_id in self.expectations["actors"].items():
            self.assertIn(actor_id, self.context["actors"], alias)
        self.assertEqual("user-demo-worker-1", self.expectations["actors"]["worker-one"])
        self.assertEqual("user-demo-worker-2", self.expectations["actors"]["worker-two"])

    def test_public_dictionary_history_counts_only_published_versions(self):
        """``versions_count`` is the live timeline, never the scenario universe."""
        published_ids = {
            version["version_id"]
            for version in self.expectations["versions"]
            if version.get("role") == "published"
        }
        self.assertTrue(published_ids)
        for dictionary in self.expectations["dictionaries"]:
            with self.subTest(dictionary=dictionary["dictionary_id"]):
                live = re.published_versions(
                    self.expectations, dictionary["dictionary_id"]
                )
                self.assertTrue(live)
                self.assertTrue(
                    all(version["role"] == "published" for version in live)
                )
                payload = re.materialize_dictionary(dictionary, self.context)
                self.assertEqual(len(live), payload["versions_count"])
                self.assertEqual(
                    dictionary["active_version_id"], payload["active_version_id"]
                )
                self.assertIn(dictionary["active_version_id"], published_ids)
        # Scenario versions stay isolated from the live timeline.
        scenario_ids = {
            version["version_id"]
            for version in self.expectations["versions"]
            if version.get("role") == "scenario"
        }
        self.assertTrue(scenario_ids)
        self.assertEqual(set(), scenario_ids & published_ids)
        for dictionary in self.expectations["dictionaries"]:
            live_ids = {
                version["version_id"]
                for version in re.published_versions(
                    self.expectations, dictionary["dictionary_id"]
                )
            }
            self.assertEqual(set(), live_ids & scenario_ids)

    def test_at_least_two_dictionaries_of_one_company_and_full_published_rule_sets(self):
        dictionaries = self.expectations["dictionaries"]
        self.assertGreaterEqual(len(dictionaries), 2)
        atlas = [d for d in dictionaries if d["company_id"] == "company-demo-atlas"]
        self.assertGreaterEqual(len(atlas), 2)
        for rule_set in self.expectations["rule_sets"]:
            if rule_set["role"] != "published":
                continue
            with self.subTest(rule_set=rule_set["rule_set_id"]):
                active = sorted(
                    (d["dictionary_id"], d["active_version_id"])
                    for d in dictionaries
                    if d["company_id"] == rule_set["company_id"]
                )
                self.assertEqual(
                    active,
                    sorted(
                        (m["dictionary_id"], m["version_id"])
                        for m in rule_set["members"]
                    ),
                )

    def test_every_rule_reference_resolves_to_a_complete_definition(self):
        versions = self.context["versions"]
        for scenario in self.rules:
            references = list(scenario["expected"]["matched_rule_refs"])
            if scenario["expected"]["selected_rule"]:
                references.append(scenario["expected"]["selected_rule"])
            for reference in references:
                with self.subTest(
                    scenario=scenario["scenario_id"], rule=reference["rule_id"]
                ):
                    version = versions[reference["version_id"]]
                    self.assertEqual(reference["dictionary_id"], version["dictionary_id"])
                    self.assertIn(
                        reference["rule_id"],
                        [rule["rule_id"] for rule in version["rules"]],
                    )

    def test_suffix_rules_cover_archive_env_readme_namedot_and_txt(self):
        by_id = {s["scenario_id"]: s for s in self.rules}
        expected = {
            "RULE-Q015-ARCHIVE-GZ": ("Archive.gz", "Archive", ".gz"),
            "RULE-Q015-ENV-NO-SUFFIX": ("EnvFile", "EnvFile", ""),
            "RULE-Q015-README-NO-SUFFIX": ("Readme", "Readme", ""),
            "RULE-Q015-NAMEDOT-NO-SUFFIX": ("Named", "Named", ""),
            "RULE-Q015-UPPER-TXT-SMALLER-WINS": ("Invoice.TXT", "Invoice", ".TXT"),
            "RULE-Q015-DOTTED-STEM-LAST-SUFFIX": (
                "Final.Report.pdf",
                "Final.Report",
                ".pdf",
            ),
        }
        for scenario_id, (basename, stem, suffix) in expected.items():
            result = by_id[scenario_id]["expected"]
            self.assertEqual(basename, result["target_basename"], scenario_id)
            self.assertEqual(stem, result["final_stem"], scenario_id)
            self.assertEqual(suffix, result["suffix"], scenario_id)

    def test_basename_does_not_fall_back_to_the_relative_path(self):
        scenario = next(
            s for s in self.rules if s["scenario_id"] == "RULE-Q015-BASENAME-NO-FALLBACK"
        )
        matched = scenario["expected"]["matched_rule_refs"]
        self.assertEqual(1, len(matched))
        self.assertEqual("rule-atlas-nofb-relative", matched[0]["rule_id"])
        self.assertEqual("RELATIVE_PATH", self._rule_field(matched[0]))

    def test_whole_field_requires_stars_for_substrings(self):
        by_id = {s["scenario_id"]: s for s in self.rules}
        exact = by_id["RULE-Q015-WHOLE-EXACT-MATCH"]["expected"]
        substring = by_id["RULE-Q015-SUBSTRING-NEEDS-STARS"]["expected"]
        self.assertEqual("WILL_MOVE", exact["predicted_state"])
        self.assertEqual("NO_SCENARIO", substring["reason_code"])

    def test_star_zero_multi_cross_slash_and_question(self):
        by_id = {s["scenario_id"]: s for s in self.rules}
        for scenario_id in ("RULE-Q015-STAR-ZERO", "RULE-Q015-STAR-MULTI"):
            self.assertEqual(
                "WILL_MOVE", by_id[scenario_id]["expected"]["predicted_state"]
            )
        cross = by_id["RULE-Q015-STAR-CROSS-SLASH"]
        self.assertEqual("WILL_MOVE", cross["expected"]["predicted_state"])
        # The mask must cover the basename too; a trailing-only mask cannot.
        cross_mask = self._rule_mask(cross["expected"]["selected_rule"])
        self.assertTrue(cross_mask.endswith("/*"), cross_mask)
        trailing = by_id["RULE-Q015-STAR-CROSS-SLASH-TRAILING-NO-MATCH"]
        self.assertEqual("NO_SCENARIO", trailing["expected"]["reason_code"])
        trailing_version = next(
            version
            for version in self.expectations["versions"]
            if version["version_id"] == "version-atlas-star-cross-slash-neg-v1"
        )
        trailing_mask = trailing_version["rules"][0]["mask"]
        self.assertFalse(trailing_mask.endswith("/*"), trailing_mask)
        self.assertEqual(
            "WILL_MOVE", by_id["RULE-Q015-QUESTION-ONE"]["expected"]["predicted_state"]
        )
        for scenario_id in ("RULE-Q015-QUESTION-ZERO", "RULE-Q015-QUESTION-TWO"):
            self.assertEqual(
                "NO_SCENARIO", by_id[scenario_id]["expected"]["reason_code"]
            )

    def test_slash_normalization_and_casefold_without_nfc(self):
        by_id = {s["scenario_id"]: s for s in self.rules}
        slash = by_id["RULE-Q015-SLASH-VARIANTS"]
        slash_mask = self._rule_mask(slash["expected"]["selected_rule"])
        self.assertIn("\\", slash_mask)
        self.assertEqual("WILL_MOVE", slash["expected"]["predicted_state"])
        self.assertEqual(
            "WILL_MOVE",
            by_id["RULE-Q015-CASEFOLD-MATCH"]["expected"]["predicted_state"],
        )
        self.assertEqual(
            "NO_SCENARIO", by_id["RULE-Q015-CASEFOLD-NO-NFC"]["expected"]["reason_code"]
        )

    def test_priority_one_and_one_thousand_with_smaller_winning(self):
        scenario = next(
            s for s in self.rules if s["scenario_id"] == "RULE-Q015-PRIORITY-1-1000"
        )
        matched = scenario["expected"]["matched_rule_refs"]
        self.assertEqual(
            {"rule-atlas-priority-1", "rule-atlas-priority-1000"},
            {ref["rule_id"] for ref in matched},
        )
        self.assertEqual("rule-atlas-priority-1", scenario["expected"]["selected_rule"]["rule_id"])

    def test_equal_priority_same_target_is_stable_and_different_target_conflicts(self):
        by_id = {s["scenario_id"]: s for s in self.rules}
        same = by_id["RULE-Q018-EQ-SAME-TARGET"]["expected"]
        self.assertIsNone(same["reason_code"])
        self.assertIsNotNone(same["selected_rule"])
        self.assertEqual(
            "dictionary-atlas-general", same["selected_rule"]["dictionary_id"]
        )
        diff = by_id["RULE-Q018-EQ-DIFF-TARGET-CONFLICT"]["expected"]
        self.assertEqual("RULE_CONFLICT", diff["reason_code"])
        self.assertIsNone(diff["selected_rule"])
        self.assertIsNone(diff["target"])
        self.assertGreaterEqual(len(diff["matched_rule_refs"]), 2)

    def test_target_resolver_oracles_are_resolved_or_declared_rejections(self):
        for scenario in self.targets:
            with self.subTest(scenario=scenario["scenario_id"]):
                expected = scenario["expected"]
                if expected["outcome"] == "RESOLVED":
                    target = self.context["targets"][expected["target_id"]]
                    self.assertEqual(scenario["company_id"], target["company_id"])
                    self.assertEqual(
                        self.context["prefix"] + "/" + target["relative_directory"],
                        scenario["request"]["display_path"],
                    )
                else:
                    allowed = re.allowed_error_codes(
                        self.context["document"],
                        re.RESOLVE_OPERATION,
                        expected["status"],
                    )
                    self.assertIn(expected["code"], allowed)
        codes = {s["expected"].get("code") for s in self.targets}
        self.assertIn("INVALID_TARGET", codes)
        self.assertIn("PATH_OUTSIDE_ROOT", codes)
        self.assertIn("VALIDATION_ERROR", codes)

    def test_invalid_masks_and_bounds_are_classified(self):
        by_id = {c["case_id"]: c for c in self.invalid}
        for case_id in (
            "RULE-INVALID-MASK-DOUBLE-STAR",
            "RULE-INVALID-MASK-REGEX",
            "RULE-INVALID-MASK-HIDDEN-OR",
            "RULE-INVALID-MASK-ESCAPED-WILDCARD",
            "RULE-INVALID-PRIORITY-ZERO",
            "RULE-INVALID-PRIORITY-1001",
            "RULE-INVALID-STEM-LENGTH",
            "RULE-INVALID-STEM-EMPTY",
            "RULE-INVALID-TARGET-MISSING-DIR",
            "RULE-INVALID-TARGET-OTHER-COMPANY",
        ):
            self.assertIn(case_id, by_id)
        self.assertTrue(by_id["RULE-INVALID-MASK-DOUBLE-STAR"]["schema_rejected"])
        self.assertFalse(by_id["RULE-INVALID-MASK-REGEX"]["schema_rejected"])
        self.assertFalse(by_id["RULE-INVALID-TARGET-MISSING-DIR"]["schema_rejected"])
        for case in self.invalid:
            allowed = re.allowed_error_codes(
                self.context["document"],
                case["operation"],
                case["expected"]["status"],
            )
            self.assertIn(case["expected"]["code"], allowed, case["case_id"])

    def test_every_required_q_is_covered(self):
        coverage = self.expectations["coverage"]
        for q in re.KNOWN_Q:
            with self.subTest(q=q):
                self.assertTrue(coverage.get(q), q)

    def _rule_field(self, reference):
        return self._rule(reference)["match_field"]

    def _rule_mask(self, reference):
        return self._rule(reference)["mask"]

    def _rule(self, reference):
        return re._rule_entry(self.context["versions"], reference)


class GeneratedExampleTests(RuleExpectationMixin, unittest.TestCase):
    def test_generated_examples_match_committed_files(self):
        generated = re.generated_examples(self.expectations, self.context)
        self.assertEqual(17, len(generated))
        for relative, payload in generated.items():
            with self.subTest(file=relative):
                committed = synthetic.load_json(REPO_ROOT / relative)
                self.assertEqual(committed, payload)

    def test_every_generated_example_is_bound_in_the_manifest(self):
        manifest = self.context["manifest"]
        bound = {entry["file"]: entry["schema"] for entry in manifest["examples"]}
        for binding in re.EXAMPLE_BINDINGS:
            self.assertIn(binding["file"], bound)
            self.assertEqual(binding["schema"], bound[binding["file"]])


class NegativeExpectationTests(RuleExpectationMixin, unittest.TestCase):
    def _errors(self, expectations):
        return re.expectation_errors(expectations, self.context_for(expectations))

    def test_undefined_rule_reference_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        expectations["rule_scenarios"][0]["expected"]["matched_rule_refs"][0][
            "rule_id"
        ] = "rule-does-not-exist"
        errors = self._errors(expectations)
        self.assertTrue(any("undefined rule reference" in m for m in errors), errors)

    def test_reference_outside_rule_set_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        expectations["rule_scenarios"][0]["expected"]["matched_rule_refs"][0][
            "dictionary_id"
        ] = "dictionary-nova-general"
        errors = self._errors(expectations)
        self.assertTrue(any("not a member of the rule set" in m for m in errors), errors)

    def test_selected_rule_outside_matched_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        scenario = next(
            s for s in expectations["rule_scenarios"] if len(s["expected"]["matched_rule_refs"]) >= 2
        )
        scenario["expected"]["selected_rule"] = scenario["expected"]["matched_rule_refs"][-1]
        scenario["expected"]["matched_rule_refs"] = [
            scenario["expected"]["matched_rule_refs"][0]
        ]
        errors = self._errors(expectations)
        self.assertTrue(
            any("selected_rule is not one of matched_rule_refs" in m for m in errors),
            errors,
        )

    def test_conflict_with_one_match_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        scenario = next(
            s
            for s in expectations["rule_scenarios"]
            if s["scenario_id"] == "RULE-Q018-EQ-DIFF-TARGET-CONFLICT"
        )
        scenario["expected"]["matched_rule_refs"] = [
            scenario["expected"]["matched_rule_refs"][0]
        ]
        errors = self._errors(expectations)
        self.assertTrue(any("at least two matches" in m for m in errors), errors)

    def test_same_target_scenario_with_split_targets_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        version = next(
            v
            for v in expectations["versions"]
            if v["version_id"] == "version-atlas-eq-same-invoices-v1"
        )
        version["rules"][0]["target_id"] = "target-atlas-invoices"
        errors = self._errors(expectations)
        self.assertTrue(
            any("must share one final target" in m for m in errors), errors
        )

    def test_stem_suffix_mismatch_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        scenario = next(
            s for s in expectations["rule_scenarios"] if s["expected"]["target"]
        )
        scenario["expected"]["target_basename"] = "Wrong"
        errors = self._errors(expectations)
        self.assertTrue(
            any("target_basename" in m or "final_stem" in m for m in errors), errors
        )

    def test_target_outside_allowlist_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        scenario = next(
            s for s in expectations["rule_scenarios"] if s["expected"]["target"]
        )
        scenario["expected"]["target"]["relative_path"] = (
            "Archive/Atlas/Orion_2031/NoSuchDir/Report.pdf"
        )
        errors = self._errors(expectations)
        self.assertTrue(
            any("not an allowlisted directory" in m for m in errors), errors
        )

    def test_wrong_operation_error_code_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        case = expectations["invalid_rule_cases"][0]
        case["operation"] = "searchFiles"
        case["expected"] = {"status": 422, "code": "INVALID_TARGET"}
        errors = self._errors(expectations)
        self.assertTrue(
            any("is not declared by" in m for m in errors), errors
        )

    def test_missing_reason_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        expectations["rule_scenarios"][0]["reason"] = ""
        errors = self._errors(expectations)
        self.assertTrue(any("reason" in m for m in errors), errors)

    def test_scenario_version_in_published_rule_set_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        rule_set = next(
            r for r in expectations["rule_sets"] if r["rule_set_id"] == "rule-set-atlas-published"
        )
        rule_set["members"][0]["version_id"] = "version-atlas-no-fallback-v1"
        errors = self._errors(expectations)
        self.assertTrue(
            any("must reference published versions" in m for m in errors), errors
        )

    def test_unknown_version_role_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        expectations["versions"][0]["role"] = "draft"
        errors = self._errors(expectations)
        self.assertTrue(any("unknown role" in m for m in errors), errors)

    def test_company_incoming_source_ids_mismatch_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        expectations["companies"][0]["incoming_source_ids"] = ["incoming-wrong"]
        errors = self._errors(expectations)
        self.assertTrue(
            any("incoming_source_ids" in m for m in errors), errors
        )

    def test_duplicate_rule_id_in_version_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        version = expectations["versions"][0]
        version["rules"][1]["rule_id"] = version["rules"][0]["rule_id"]
        errors = self._errors(expectations)
        self.assertTrue(any("repeats rule_id" in m for m in errors), errors)

    def test_missing_coverage_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        expectations["coverage"]["Q-018"] = []
        errors = self._errors(expectations)
        self.assertTrue(any("Q-018" in m for m in errors), errors)

    def test_wrong_schema_rejection_classification_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        case = next(
            c for c in expectations["invalid_rule_cases"] if c["case_id"] == "RULE-INVALID-MASK-DOUBLE-STAR"
        )
        case["schema_rejected"] = False
        errors = re.schema_rejection_errors(expectations, self.registry)
        self.assertTrue(
            any("declared schema-valid" in m for m in errors), errors
        )


if __name__ == "__main__":
    unittest.main()
