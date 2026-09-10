"""Tests for the LT-03.1a synthetic metadata corpus and public API examples.

The corpus is an independent expectation source: these tests assert the finite
inventory, the two disjoint logical roots, stable marker/ID uniqueness, the
large regular branch, the four structural issue kinds, file-type coverage and
the explicit controls/lifecycle/search-input scaffolding that LT-03.1b will
consume.  They never call a search or matcher implementation.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from contractlib import build_registry, load_contract, validate_fixture  # noqa: E402
from contractlib import synthetic  # noqa: E402

REPO_ROOT = HERE.parents[1]
CONTRACT = REPO_ROOT / "contracts" / "openapi" / "wiseway-v1.yaml"
SEARCH_ITEM = "#/components/schemas/SearchItem"


class CorpusFixtureMixin:
    @classmethod
    def setUpClass(cls):
        cls.manifest = synthetic.load_manifest(synthetic.manifest_path(REPO_ROOT))
        cls.corpus = synthetic.load_corpus(cls.manifest, REPO_ROOT)
        cls.materialized = synthetic.materialize(cls.corpus)
        cls.lifecycle = synthetic.materialize_lifecycle(cls.corpus)
        cls.registry = build_registry(load_contract(CONTRACT))


class ManifestTests(CorpusFixtureMixin, unittest.TestCase):
    def test_manifest_is_versioned_seeded_and_has_a_checksum_method(self):
        self.assertEqual("wiseway-synthetic-metadata", self.manifest["fixture_set"])
        self.assertTrue(self.manifest["version"])
        self.assertTrue(self.manifest["seed"])
        self.assertEqual("sha256", self.manifest["checksum"]["algorithm"])
        self.assertIn("corpus=", self.manifest["checksum"]["method"])
        self.assertIn("json.dumps", self.manifest["checksum"]["canonicalization"])

    def test_checksum_is_portable_across_line_endings_and_key_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            text = json.dumps({"b": 2, "a": ["x", "y"]}, indent=2, ensure_ascii=False)
            lf = tmp / "lf.json"
            crlf = tmp / "crlf.json"
            reordered = tmp / "reordered.json"
            lf.write_bytes(text.encode("utf-8"))
            crlf.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
            reordered.write_bytes(
                json.dumps({"a": ["x", "y"], "b": 2}, indent=4, ensure_ascii=False).encode("utf-8")
            )
            self.assertNotEqual(lf.read_bytes(), crlf.read_bytes())
            self.assertEqual(synthetic.content_hash(lf), synthetic.content_hash(crlf))
            self.assertEqual(synthetic.content_hash(lf), synthetic.content_hash(reordered))

    def test_checksums_match_recomputation(self):
        expected = synthetic.compute_checksums(self.manifest, REPO_ROOT)
        declared = self.manifest["checksum"]
        self.assertEqual(expected["corpus"], declared["corpus"])
        self.assertEqual(expected["combined"], declared["combined"])
        self.assertEqual(expected["examples"], declared["examples"])

    def test_checksum_is_deterministic(self):
        first = synthetic.compute_checksums(self.manifest, REPO_ROOT)
        second = synthetic.compute_checksums(self.manifest, REPO_ROOT)
        self.assertEqual(first, second)

    def test_every_manifest_example_validates_against_its_canonical_schema(self):
        for entry in self.manifest["examples"]:
            with self.subTest(example=entry["id"]):
                value = synthetic.load_json(REPO_ROOT / entry["file"])
                schema_errors, semantic = validate_fixture(self.registry, entry["schema"], value)
                self.assertEqual([], schema_errors, schema_errors)
                self.assertEqual([], semantic, semantic)

    def test_every_example_is_bound_to_a_canonical_component_pointer(self):
        for entry in self.manifest["examples"]:
            self.assertTrue(entry["schema"].startswith("#/components/schemas/"))

    def test_auth_examples_cover_two_workers_and_an_admin_without_real_secrets(self):
        roles = [
            synthetic.load_json(REPO_ROOT / entry["file"])["role"]
            for entry in self.manifest["examples"]
            if entry["id"].startswith("auth-actor")
        ]
        self.assertEqual(["WORKER", "WORKER", "ADMIN"], roles)
        for entry in self.manifest["examples"]:
            if entry["id"].startswith("auth-session"):
                value = synthetic.load_json(REPO_ROOT / entry["file"])
                self.assertIn("inert", value["csrf_token"])

    def test_config_profiles_cover_n100_and_n10(self):
        limits = sorted(
            synthetic.load_json(REPO_ROOT / entry["file"])["search_result_limit"]
            for entry in self.manifest["examples"]
            if entry["id"].startswith("config-")
        )
        self.assertEqual([10, 100], limits)

    def test_roots_and_companies_cover_the_empty_cases(self):
        by_id = {entry["id"]: entry for entry in self.manifest["examples"]}
        self.assertEqual(
            [], synthetic.load_json(REPO_ROOT / by_id["roots-empty"]["file"])["items"]
        )
        self.assertEqual(
            [], synthetic.load_json(REPO_ROOT / by_id["companies-empty"]["file"])["items"]
        )
        self.assertEqual(
            2, len(synthetic.load_json(REPO_ROOT / by_id["roots-two"]["file"])["items"])
        )
        self.assertEqual(
            2,
            len(synthetic.load_json(REPO_ROOT / by_id["companies-atlas-nova"]["file"])["items"]),
        )


class CorpusStructureTests(CorpusFixtureMixin, unittest.TestCase):
    def test_corpus_has_no_integrity_violations(self):
        self.assertEqual([], synthetic.integrity_errors(self.corpus, self.materialized))

    def test_exactly_two_disjoint_logical_roots(self):
        root_ids = [root["root_id"] for root in self.corpus["roots"]]
        self.assertEqual(2, len(root_ids))
        by_root = {root_id: set() for root_id in root_ids}
        for item in self.materialized["files"]:
            by_root[item["location"]["root_id"]].add(item["item_id"])
        for root_id, ids in by_root.items():
            self.assertTrue(ids, root_id)
        self.assertEqual(set(), by_root[root_ids[0]] & by_root[root_ids[1]])

    def test_roots_use_different_schema_depth_and_values(self):
        schema_roots = self.corpus["schema"]["roots"]
        atlas = schema_roots["root-demo-atlas"]["levels"]
        nova = schema_roots["root-demo-nova"]["levels"]
        self.assertIn("level-subcategory", atlas)
        self.assertNotIn("level-area", atlas)
        self.assertIn("level-area", nova)
        self.assertNotEqual(atlas, nova)

    def test_item_ids_are_unique_and_marker_ids_stable(self):
        ids = [item["item_id"] for item in self.materialized["files"]]
        ids += [item["item_id"] for item in self.materialized["service_objects"]]
        self.assertEqual(len(ids), len(set(ids)))
        catalog = synthetic.marker_index(self.corpus)
        identities = {}
        for marker in catalog.values():
            key = (
                marker["root_id"],
                tuple((parent["level_id"], parent["raw_value"]) for parent in marker["parents"]),
                marker["level_id"],
                marker["raw_value"],
                marker["kind"],
            )
            self.assertNotIn(key, identities, key)
            identities[key] = marker["marker_id"]

    def test_marker_id_is_unique_per_root_and_ancestry(self):
        catalog = synthetic.marker_index(self.corpus)
        # Same raw value in different roots must not share a marker id.
        sections = {
            marker["root_id"]: marker["marker_id"]
            for marker in catalog.values()
            if marker["level_id"] == "level-section"
        }
        self.assertEqual(2, len(sections))
        self.assertEqual(2, len(set(sections.values())))
        # Same raw value under different ancestor chains must not share an id.
        reports = {
            tuple(
                (parent["level_id"], parent["raw_value"]) for parent in marker["parents"]
            ): marker["marker_id"]
            for marker in catalog.values()
            if marker["level_id"] == "level-category" and marker["raw_value"] == "Reports"
        }
        self.assertGreaterEqual(len(reports), 2)
        self.assertEqual(len(reports), len(set(reports.values())))

    def test_raw_case_variants_are_distinct_markers(self):
        catalog = synthetic.marker_index(self.corpus)
        company = {
            marker["raw_value"]: marker["marker_id"]
            for marker in catalog.values()
            if marker["level_id"] == "level-company" and marker["raw_value"]
        }
        self.assertIn("Atlas", company)
        self.assertIn("ATLAS", company)
        self.assertNotEqual(company["Atlas"], company["ATLAS"])

    def test_every_value_marker_is_used_by_a_corpus_file(self):
        catalog = synthetic.marker_index(self.corpus)
        used = {
            marker["marker_id"]
            for item in self.materialized["files"]
            for marker in item["markers"]
        }
        unused = [
            marker["marker_id"]
            for marker in catalog.values()
            if marker["kind"] == "VALUE" and marker["marker_id"] not in used
        ]
        self.assertEqual([], unused)

    def test_every_recognized_marker_matches_its_path_segments(self):
        files = self.materialized["files"]
        self.assertEqual(164, len(files))
        for item in files:
            with self.subTest(item=item["item_id"]):
                self.assertEqual([], synthetic.path_marker_errors(item), item["item_id"])
        scanned = 0
        for stage, payload in self.lifecycle.items():
            for side in ("before", "after"):
                state = payload[side]
                if state is None:
                    continue
                scanned += 1
                with self.subTest(stage=stage, side=side):
                    self.assertEqual(
                        [], synthetic.path_marker_errors(state, label=f"{stage}.{side}")
                    )
        self.assertEqual(8, scanned)

    def test_inventory_excludes_service_objects(self):
        inventory_ids = {item["item_id"] for item in self.materialized["files"]}
        service_ids = {item["item_id"] for item in self.materialized["service_objects"]}
        self.assertTrue(service_ids)
        self.assertEqual(set(), inventory_ids & service_ids)
        inventory_paths = {
            item["location"]["relative_path"] for item in self.materialized["files"]
        }
        for service in self.materialized["service_objects"]:
            self.assertNotIn(service["location"]["relative_path"], inventory_paths)

    def test_large_branch_has_103_files(self):
        cohort = next(
            item for item in self.corpus["cohorts"] if item["cohort_id"] == "atlas-orion-reports-103"
        )
        self.assertEqual(103, cohort["count"])
        members = [
            item
            for item in self.materialized["files"]
            if item["item_id"].startswith("file-atlas-orion-report-")
        ]
        self.assertEqual(103, len(members))
        self.assertGreater(103, 100)

    def test_four_structure_issue_kinds_with_first_deviation(self):
        codes = {}
        for item in self.materialized["files"]:
            if item["structure_status"] == "UNRECOGNIZED":
                issue = item["structure_issue"]
                codes.setdefault(issue["code"], []).append(item)
        self.assertEqual(
            set(synthetic.STRUCTURE_ISSUE_CODES), set(codes), sorted(codes)
        )
        for code, items in codes.items():
            for item in items:
                self.assertTrue(item["structure_issue"]["level_name"])
                self.assertTrue(item["structure_issue"]["message"])
                levels = self.corpus["schema"]["roots"][item["location"]["root_id"]]["levels"]
                marker_levels = [marker["level_id"] for marker in item["markers"]]
                self.assertEqual(levels[: len(marker_levels)], marker_levels)

    def test_file_type_and_name_coverage(self):
        filenames = {item["filename"] for item in self.materialized["files"]}
        extensions = {item["extension"] for item in self.materialized["files"]}
        self.assertTrue({".env", "name.", "README", "archive.tar.gz"} <= filenames)
        self.assertTrue({".pdf", ".xlsx", ".docx", ".pptx", ".png", ""} <= extensions)
        self.assertIn(".TXT", extensions)
        self.assertTrue(any(item["size_bytes"] == 0 for item in self.materialized["files"]))

    def test_content_only_and_old_path_controls_reference_real_files(self):
        known = {item["item_id"] for item in self.materialized["files"]}
        content = self.corpus["controls"]["content_only"][0]
        old_path = self.corpus["controls"]["old_path"][0]
        self.assertIn(content["item_id"], known)
        self.assertIn(old_path["item_id"], known)
        current = next(
            item for item in self.materialized["files"] if item["item_id"] == old_path["item_id"]
        )
        self.assertEqual(
            current["location"]["relative_path"], old_path["current_relative_path"]
        )
        self.assertNotEqual(
            old_path["current_relative_path"], old_path["old_relative_path"]
        )

    def test_lifecycle_stages_are_present_and_consistent(self):
        self.assertEqual(
            set(synthetic.REQUIRED_LIFECYCLE_STAGES), set(self.lifecycle)
        )
        create = self.lifecycle["create"]
        self.assertIsNone(create["before"])
        self.assertIsNotNone(create["after"])
        delete = self.lifecycle["delete"]
        self.assertIsNotNone(delete["before"])
        self.assertIsNone(delete["after"])
        rename = self.lifecycle["rename"]
        self.assertNotEqual(
            rename["before"]["location"]["relative_path"],
            rename["after"]["location"]["relative_path"],
        )
        self.assertEqual(rename["before"]["item_id"], rename["after"]["item_id"])

    def test_prepared_search_inputs_reference_existing_items(self):
        known = {item["item_id"] for item in self.materialized["files"]}
        inputs = self.corpus["search_inputs"]
        self.assertIn(inputs["q007_and"]["matching_item_ids"][0], known)
        self.assertIn(inputs["q008_phrase"]["matching_item_ids"][0], known)
        for item_id in inputs["q009_boundaries"]["matching_item_ids"]:
            self.assertIn(item_id, known)
        for separator, item_id in inputs["q009_boundaries"]["separators"].items():
            self.assertIn(item_id, known, separator)
        for group in ("numeric", "russian", "ties"):
            for item_id in inputs["natural_order"][group]:
                self.assertIn(item_id, known, group)

    def test_natural_order_lists_are_unordered_candidates(self):
        natural = self.corpus["search_inputs"]["natural_order"]
        self.assertIs(False, natural["ordered"])
        self.assertIn("unordered", natural["note"].lower())

    def test_q009_backslash_separator_uses_display_path_without_changing_relative_path(self):
        backslash = next(
            item
            for item in self.materialized["files"]
            if item["item_id"] == "file-atlas-q009-backslash"
        )
        self.assertIn("\\met\\", backslash["location"]["display_path"])
        self.assertNotIn("\\", backslash["location"]["relative_path"])
        self.assertIn("/", backslash["location"]["relative_path"])


class MaterializationTests(CorpusFixtureMixin, unittest.TestCase):
    def test_materialization_is_deterministic_and_python_free_json(self):
        first = synthetic.materialize(self.corpus)
        second = synthetic.materialize(self.corpus)
        self.assertEqual(first, second)
        serialized = json.dumps(first, ensure_ascii=False, sort_keys=True)
        self.assertIn('"item_id"', serialized)

    def test_every_corpus_file_is_a_schema_valid_search_item(self):
        for item in self.materialized["files"] + self.materialized["service_objects"]:
            with self.subTest(item=item["item_id"]):
                schema_errors, semantic = validate_fixture(self.registry, SEARCH_ITEM, item)
                self.assertEqual([], schema_errors, schema_errors)
                self.assertEqual([], semantic, semantic)

    def test_all_lifecycle_payloads_are_schema_valid_search_items(self):
        count = 0
        for stage, payload in self.lifecycle.items():
            for side in ("before", "after"):
                state = payload[side]
                if state is None:
                    continue
                count += 1
                with self.subTest(stage=stage, side=side):
                    schema_errors, semantic = validate_fixture(self.registry, SEARCH_ITEM, state)
                    self.assertEqual([], schema_errors, f"{stage}.{side}: {schema_errors}")
                    self.assertEqual([], semantic, f"{stage}.{side}: {semantic}")
        self.assertEqual(8, count)

    def test_documented_preparation_command_materializes_the_same_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "inventory.json"
            exit_code = synthetic._main(
                [
                    "--manifest",
                    str(synthetic.manifest_path(REPO_ROOT)),
                    "--write",
                    str(target),
                ]
            )
            self.assertEqual(0, exit_code)
            written = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(len(self.materialized["files"]), len(written["files"]))
        self.assertEqual(
            self.materialized["files"][0]["item_id"], written["files"][0]["item_id"]
        )


class NegativeFixtureTests(CorpusFixtureMixin, unittest.TestCase):
    def test_corrupted_public_example_is_rejected_by_schema(self):
        session = synthetic.load_json(
            REPO_ROOT / "contracts/examples/auth/session-worker-one.json"
        )
        del session["csrf_token"]
        schema_errors, semantic = validate_fixture(
            self.registry, "#/components/schemas/Session", session
        )
        self.assertTrue(schema_errors, "missing required csrf_token was accepted")
        self.assertEqual([], semantic)

    def test_corrupted_corpus_duplicate_item_id_is_rejected(self):
        corpus = copy.deepcopy(self.corpus)
        corpus["files"][1]["item_id"] = corpus["files"][0]["item_id"]
        errors = synthetic.integrity_errors(corpus)
        self.assertTrue(
            any("not unique" in message for message in errors), errors
        )

    def test_corrupted_corpus_missing_structure_issue_is_rejected(self):
        corpus = copy.deepcopy(self.corpus)
        for record in corpus["files"]:
            if record.get("structure_status") == "UNRECOGNIZED":
                del record["structure_issue"]
                break
        errors = synthetic.integrity_errors(corpus)
        self.assertTrue(
            any("structure_issue" in message for message in errors), errors
        )

    def test_corrupted_corpus_service_leak_is_rejected(self):
        corpus = copy.deepcopy(self.corpus)
        corpus["service_objects"][0]["item_id"] = corpus["files"][0]["item_id"]
        errors = synthetic.integrity_errors(corpus)
        self.assertTrue(
            any("leaks into the inventory" in message for message in errors), errors
        )

    def test_dangling_marker_context_is_reported_gracefully(self):
        corpus = copy.deepcopy(self.corpus)
        corpus["files"][0]["marker_context"] = "does-not-exist"
        errors = synthetic.integrity_errors(corpus)
        self.assertTrue(
            any("unknown marker_context" in message for message in errors), errors
        )

    def test_duplicate_marker_context_id_is_reported(self):
        corpus = copy.deepcopy(self.corpus)
        contexts = corpus["marker_model"]["contexts"]
        contexts[1]["context_id"] = contexts[0]["context_id"]
        errors = synthetic.integrity_errors(corpus)
        self.assertTrue(
            any("duplicate context_id" in message for message in errors), errors
        )

    def test_duplicate_context_path_is_reported(self):
        corpus = copy.deepcopy(self.corpus)
        contexts = corpus["marker_model"]["contexts"]
        clone = copy.deepcopy(contexts[0])
        clone["context_id"] = "duplicate-path"
        contexts.append(clone)
        errors = synthetic.integrity_errors(corpus)
        self.assertTrue(
            any("duplicate context path" in message for message in errors), errors
        )

    def test_duplicate_marker_value_id_is_reported(self):
        corpus = copy.deepcopy(self.corpus)
        values = corpus["marker_model"]["values"]
        values[1]["value_id"] = values[0]["value_id"]
        errors = synthetic.integrity_errors(corpus)
        self.assertTrue(
            any("duplicate value_id" in message for message in errors), errors
        )

    def test_single_path_raw_case_mutation_is_caught(self):
        corpus = copy.deepcopy(self.corpus)
        for record in corpus["files"]:
            if record["item_id"] == "file-atlas-rawcase-polaris-lower":
                record["relative_path"] = record["relative_path"].replace("/Data/", "/data/")
                break
        errors = synthetic.integrity_errors(corpus)
        self.assertTrue(
            any("does not match path segment" in message for message in errors), errors
        )

    def test_context_deeper_than_declared_schema_is_reported(self):
        corpus = copy.deepcopy(self.corpus)
        for context in corpus["marker_model"]["contexts"]:
            if context["context_id"] == "atlas-archive-atlas-orion-reports-text":
                context["path"] = context["path"] + ["data"]
                break
        errors = synthetic.integrity_errors(corpus)
        self.assertTrue(
            any("deeper than the declared schema" in message for message in errors), errors
        )

    def test_conflicting_marker_id_identity_is_rejected_before_dict_collapse(self):
        # Two distinct ancestor chains whose hyphen-joined value ids collide.
        corpus = {
            "marker_model": {
                "levels": {"level-a": "A", "level-b": "B"},
                "values": [
                    {"value_id": "a-b", "level_id": "level-a", "raw_value": "AB",
                     "display_value": "AB", "kind": "VALUE"},
                    {"value_id": "c", "level_id": "level-b", "raw_value": "C",
                     "display_value": "C", "kind": "VALUE"},
                    {"value_id": "a", "level_id": "level-a", "raw_value": "A",
                     "display_value": "A", "kind": "VALUE"},
                    {"value_id": "b-c", "level_id": "level-b", "raw_value": "BC",
                     "display_value": "BC", "kind": "VALUE"},
                ],
                "contexts": [
                    {"context_id": "ctx1", "root_id": "root-x", "path": ["a-b", "c"]},
                    {"context_id": "ctx2", "root_id": "root-x", "path": ["a", "b-c"]},
                ],
            },
            "roots": [{"root_id": "root-x"}],
            "schema": {"roots": {"root-x": {"levels": ["level-a", "level-b"]}}},
        }
        with self.assertRaises(synthetic.MarkerModelError):
            synthetic.build_marker_catalog(corpus)

    def test_run_checks_reports_the_fixture_checks(self):
        from contractlib import run_checks

        document = load_contract(CONTRACT)
        report = run_checks(document, repo_root=REPO_ROOT)
        passed = {check.check_id for check in report.checks if check.passed}
        self.assertIn("FIX-EX-001", passed)
        self.assertIn("FIX-EX-002", passed)
        self.assertIn("FIX-CORPUS-001", passed)
        self.assertIn("FIX-CHK-001", passed)
        self.assertIn("FIX-SRCH-001", passed)
        self.assertIn("FIX-SRCH-002", passed)
        self.assertIn("FIX-RULE-001", passed)
        self.assertIn("FIX-RULE-002", passed)
        self.assertEqual(49, report.fixtures_validated)
        self.assertEqual(164, report.corpus_files)
        self.assertEqual(8, report.lifecycle_fixtures)
        self.assertEqual(51, report.search_scenarios)
        self.assertEqual(6, report.facet_scenarios)
        self.assertEqual(14, report.error_scenarios)
        self.assertEqual(3, report.race_scenarios)
        self.assertEqual(3, report.format_samples)
        self.assertEqual(26, report.rule_scenarios)
        self.assertEqual(8, report.target_scenarios)
        self.assertEqual(17, report.invalid_rule_cases)


if __name__ == "__main__":
    unittest.main()
