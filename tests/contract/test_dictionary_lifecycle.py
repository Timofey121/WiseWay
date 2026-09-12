"""Tests for the LT-03.2b literal dictionary lifecycle expectations.

The expectations are an *independent* oracle: these tests check that the literal
data is internally consistent, schema-valid, fully traced to Q ids and that the
committed public examples equal the materialized literals.  No test matches a
mask, picks a winning priority, derives a target name, bumps a revision or
recomputes a count; the materializer only looks the already-declared values up by
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
from contractlib import dictionary_lifecycle as dl  # noqa: E402
from contractlib import synthetic  # noqa: E402
from contractlib.schemas import validate_value  # noqa: E402

REPO_ROOT = HERE.parents[1]
CONTRACT = REPO_ROOT / "contracts" / "openapi" / "wiseway-v1.yaml"


class LifecycleMixin:
    @classmethod
    def setUpClass(cls):
        cls.registry = build_registry(load_contract(CONTRACT))
        cls.expectations = dl.load_expectations(REPO_ROOT)
        cls.context = dl.build_context(REPO_ROOT, cls.expectations)
        cls.timeline = cls.expectations["timeline"]
        cls.failures = cls.expectations["failures"]
        cls.simulations = cls.expectations["simulations"]

    def context_for(self, expectations):
        return dl.build_context(REPO_ROOT, expectations)

    def sim(self, page_id):
        return self.context["simulations"][page_id]

    def failure(self, failure_id):
        return self.context["failures"][failure_id]


class OracleStructureTests(LifecycleMixin, unittest.TestCase):
    def test_expectations_have_no_structural_errors(self):
        self.assertEqual([], dl.expectation_errors(self.expectations, self.context))

    def test_every_declared_request_is_schema_classified(self):
        self.assertEqual(
            [],
            dl.request_rejection_errors(self.expectations, self.context, self.registry),
        )

    def test_every_payload_materializes_to_a_schema_valid_response(self):
        for state in self.expectations["states"]:
            with self.subTest(state=state["state_id"]):
                payload = dl.materialize_dictionary(state, self.context)
                errors, semantic = validate_fixture(
                    self.registry, dl.DICTIONARY_SCHEMA, payload
                )
                self.assertEqual([], errors, errors)
                self.assertEqual([], semantic, semantic)
        for version in self.expectations["versions"]:
            with self.subTest(version=version["version_id"]):
                payload = dl.materialize_version(
                    self.context["versions"][version["version_id"]], self.context
                )
                errors, semantic = validate_fixture(
                    self.registry, dl.DICTIONARY_VERSION_SCHEMA, payload
                )
                self.assertEqual([], errors, errors)
                self.assertEqual([], semantic, semantic)
        for page in self.expectations["simulations"]:
            with self.subTest(simulation=page["page_id"]):
                payload = dl.materialize_simulation(page, self.context)
                errors, semantic = validate_fixture(
                    self.registry, dl.SIMULATION_SCHEMA, payload
                )
                self.assertEqual([], errors, errors)
                self.assertEqual([], semantic, semantic)
        for publish in self.expectations["publishes"]:
            with self.subTest(publish=publish["publish_id"]):
                payload = dl.materialize_publish(publish, self.context)
                errors, semantic = validate_fixture(
                    self.registry, dl.PUBLISH_SCHEMA, payload
                )
                self.assertEqual([], errors, errors)
                self.assertEqual([], semantic, semantic)
        for page in self.expectations["version_pages"]:
            with self.subTest(page=page["page_id"]):
                payload = dl.materialize_page_versions(page, self.context)
                errors, semantic = validate_fixture(
                    self.registry, dl.PAGE_VERSION_SCHEMA, payload
                )
                self.assertEqual([], errors, errors)
                self.assertEqual([], semantic, semantic)
        for failure in self.expectations["failures"]:
            with self.subTest(failure=failure["failure_id"]):
                payload = dl.materialize_error(failure)
                errors, semantic = validate_fixture(
                    self.registry, dl.ERROR_SCHEMA, payload
                )
                self.assertEqual([], errors, errors)
                self.assertEqual([], semantic, semantic)

    def test_typed_rule_roundtrip_preserves_all_fields(self):
        seen = 0
        for version in self.expectations["versions"]:
            for rule_entry in version["rules"]:
                seen += 1
                with self.subTest(rule=rule_entry["rule_id"]):
                    rule = dl.materialize_rule(rule_entry, self.context)
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
                        self.registry, "#/components/schemas/Rule", rule
                    )
                    self.assertEqual([], errors, errors)
                    self.assertEqual([], semantic, semantic)
                    self.assertEqual(rule, json.loads(json.dumps(rule)))
        self.assertGreater(seen, 0)


class AcceptanceTraceTests(LifecycleMixin, unittest.TestCase):
    def test_create_revision_zero_and_save_increments_by_one(self):
        create = next(s for s in self.timeline if s["step_id"] == "create-atlas-cleanup")
        self.assertEqual(0, create["expected"]["draft_revision"])
        created = dl.materialize_dictionary(
            self.context["states"]["state-atlas-cleanup-created"], self.context
        )
        self.assertEqual(0, created["draft"]["draft_revision"])
        self.assertEqual([], created["draft"]["rules"])
        self.assertIsNone(created["active_version_id"])
        self.assertEqual(0, created["versions_count"])

        save = next(s for s in self.timeline if s["step_id"] == "save-atlas-cleanup")
        self.assertEqual(1, save["expected"]["draft_revision"])
        saved = dl.materialize_dictionary(
            self.context["states"]["state-atlas-cleanup-saved"], self.context
        )
        self.assertEqual(1, saved["draft"]["draft_revision"])
        self.assertEqual(1, len(saved["draft"]["rules"]))

    def test_shared_stale_revision_rejects_second_actor_without_write(self):
        failure = self.failure("save-stale-revision-worker-two")
        self.assertEqual("replaceDictionaryDraft", failure["operation"])
        self.assertEqual("worker-two", failure["actor"])
        self.assertFalse(failure["mutates"])
        self.assertEqual(failure["before_state"], failure["after_state"])
        self.assertEqual(409, failure["expected"]["status"])
        self.assertEqual("DRAFT_VERSION_CONFLICT", failure["expected"]["code"])
        self.assertEqual(1, failure["request"]["expected_draft_revision"])

    def test_name_conflict_trim_casefold_and_no_cross_company_conflict(self):
        failure = self.failure("create-name-conflict-trim-casefold")
        name = failure["request"]["name"]
        self.assertEqual("счета atlas", name.strip().casefold())
        existing = self.context["dictionaries"]["dictionary-atlas-invoices"]
        self.assertEqual("счета atlas", existing["name"].strip().casefold())
        self.assertEqual(409, failure["expected"]["status"])
        self.assertEqual("DICTIONARY_NAME_CONFLICT", failure["expected"]["code"])
        # The same name in another company is allowed (timeline create-nova-scope).
        nova = next(s for s in self.timeline if s["step_id"] == "create-nova-scope")
        self.assertEqual("company-demo-nova", nova["company_id"])
        self.assertEqual(201, nova["expected"]["status"])
        created = dl.materialize_dictionary(
            self.context["states"]["state-nova-scope-created"], self.context
        )
        self.assertEqual("Счета Atlas", created["name"])
        self.assertEqual("company-demo-nova", created["company_id"])

    def test_simulation_replaces_only_its_own_version_over_all_ready(self):
        page = self.sim("page-atlas-full-1")
        simulation = dl.materialize_simulation(page, self.context)
        base = {
            member["dictionary_id"]: member["version_id"]
            for member in simulation["base_rule_set"]["members"]
        }
        # The base RuleSet is the set currently being replaced: the candidate
        # dictionary's previous active version, not the not-yet-published candidate.
        self.assertEqual("version-atlas-general-v1", base["dictionary-atlas-general"])
        self.assertEqual("version-atlas-invoices-v1", base["dictionary-atlas-invoices"])
        self.assertEqual("version-atlas-general-v2", page["candidate_version_id"])
        published = dl.materialize_rule_set(
            self.context["rule_sets"]["rule-set-atlas-v2"], self.context
        )
        result = {
            member["dictionary_id"]: member["version_id"]
            for member in published["members"]
        }
        self.assertEqual("version-atlas-general-v2", result["dictionary-atlas-general"])
        self.assertEqual(base["dictionary-atlas-invoices"], result["dictionary-atlas-invoices"])
        # The full READY set, not a page/filter subset.
        ready = self.context["ready_sets"]["ready-atlas-full"]["members"]
        self.assertEqual(len(ready), simulation["total"])
        page_ids = {
            row["item_id"]
            for entry in self.simulations
            if entry["simulation_id"] == page["simulation_id"]
            for row in entry["rows"]
        }
        self.assertEqual({member["item_id"] for member in ready}, page_ids)
        hidden = [m for m in ready if not m["queue_visible"] or not m["filter_matches"]]
        self.assertTrue(hidden)
        for member in hidden:
            self.assertIn(member["item_id"], page_ids)
        # An item matched by another dictionary is still covered.
        invoice_row = next(
            row
            for row in simulation["rows"]
            if row["item_id"] == "ready-item-atlas-invoice"
        )
        self.assertEqual(
            "dictionary-atlas-invoices",
            invoice_row["selected_rule"]["dictionary_id"],
        )

    def test_invoices_publish_has_its_own_save_and_previous_active_base(self):
        save = next(
            s for s in self.timeline if s["step_id"] == "save-atlas-invoices-v2"
        )
        self.assertEqual(1, save["request"]["expected_draft_revision"])
        self.assertEqual(2, save["expected"]["draft_revision"])
        draft = dl.materialize_dictionary(
            self.context["states"]["state-atlas-invoices-draft-v2"], self.context
        )
        version = dl.materialize_version(
            self.context["versions"]["version-atlas-invoices-v2"], self.context
        )
        self.assertEqual(
            [rule["rule_id"] for rule in version["rules"]],
            [rule["rule_id"] for rule in draft["draft"]["rules"]],
        )
        self.assertEqual(2, draft["draft"]["draft_revision"])
        self.assertEqual("version-atlas-invoices-v1", draft["active_version_id"])
        simulation = dl.materialize_simulation(
            self.sim("page-atlas-invoices-v2"), self.context
        )
        base = {
            member["dictionary_id"]: member["version_id"]
            for member in simulation["base_rule_set"]["members"]
        }
        self.assertEqual("version-atlas-invoices-v1", base["dictionary-atlas-invoices"])
        self.assertEqual(
            "version-atlas-invoices-v2", self.sim("page-atlas-invoices-v2")["candidate_version_id"]
        )
        published = self.context["publishes"]["publish-atlas-invoices-v2"]
        payload = dl.materialize_publish(published, self.context)
        self.assertEqual(
            [rule["rule_id"] for rule in version["rules"]],
            [rule["rule_id"] for rule in payload["published_version"]["rules"]],
        )
        self.assertEqual(
            [rule["rule_id"] for rule in version["rules"]],
            [rule["rule_id"] for rule in payload["dictionary"]["draft"]["rules"]],
        )

    def test_every_publish_comment_and_draft_match_the_published_version(self):
        for publish in self.expectations["publishes"]:
            with self.subTest(publish=publish["publish_id"]):
                version = self.context["versions"][publish["published_version_id"]]
                self.assertEqual(
                    publish["request"]["comment"], version["comment"], publish["publish_id"]
                )
                after = dl.materialize_dictionary(
                    self.context["states"][publish["after_state"]], self.context
                )
                self.assertEqual(
                    [rule["rule_id"] for rule in version["rules"]],
                    [rule["rule_id"] for rule in after["draft"]["rules"]],
                )
                self.assertEqual(version["version_id"], after["active_version_id"])

    def test_simulation_counts_and_pages_are_explicit(self):
        page1 = self.sim("page-atlas-full-1")
        page2 = self.sim("page-atlas-full-2")
        sim1 = dl.materialize_simulation(page1, self.context)
        sim2 = dl.materialize_simulation(page2, self.context)
        self.assertEqual(sim1["counts"], sim2["counts"])
        self.assertEqual(sim1["total"], sim2["total"])
        counts = sim1["counts"]
        self.assertEqual(
            sim1["total"],
            counts["will_move"]
            + counts["will_manual_review"]
            + counts["requires_decision"]
            + counts["not_ready"],
        )
        self.assertEqual(1, counts["no_scenario"])
        self.assertEqual(0, counts["rule_conflicts"])
        self.assertEqual("cursor-simulation-atlas-full-page2", sim1["next_cursor"])
        self.assertIsNone(sim2["next_cursor"])

    def test_empty_ready_set_warns_and_proves_no_coverage(self):
        page = self.sim("page-atlas-empty")
        simulation = dl.materialize_simulation(page, self.context)
        self.assertEqual(0, simulation["total"])
        self.assertEqual([], simulation["rows"])
        self.assertIn("EMPTY_READY_SET", simulation["warnings"])
        self.assertEqual(
            {"will_move": 0, "will_manual_review": 0, "requires_decision": 0,
             "not_ready": 0, "rule_conflicts": 0, "no_scenario": 0},
            simulation["counts"],
        )

    def test_conflict_blocks_same_target_does_not_and_occupied_does_not(self):
        conflict = dl.materialize_simulation(self.sim("page-atlas-conflict"), self.context)
        self.assertEqual(1, conflict["counts"]["rule_conflicts"])
        row = conflict["rows"][0]
        self.assertEqual("RULE_CONFLICT", row["reason_code"])
        self.assertIsNone(row["selected_rule"])
        self.assertEqual(2, len(row["matched_rules"]))

        same = dl.materialize_simulation(
            self.sim("page-atlas-same-target"), self.context
        )
        self.assertEqual(0, same["counts"]["rule_conflicts"])
        self.assertIsNotNone(same["rows"][0]["selected_rule"])
        self.assertEqual("rule-atlas-same-a", same["rows"][0]["selected_rule"]["rule_id"])
        self.assertEqual(
            same["rows"][0]["target"]["relative_path"].rsplit("/", 1)[-1],
            "SameName.pdf",
        )

        full = dl.materialize_simulation(self.sim("page-atlas-full-1"), self.context)
        occupied = next(
            entry
            for entry in self.expectations["simulations"]
            if entry["page_id"] == "page-atlas-full-2"
        )
        occupied_row = next(
            row for row in occupied["rows"] if row["item_id"] == "ready-item-atlas-occupied"
        )
        self.assertEqual("REQUIRES_DECISION", occupied_row["predicted_state"])
        self.assertEqual("TARGET_OCCUPIED", occupied_row["reason_code"])
        self.assertEqual(1, full["counts"]["requires_decision"])
        # The occupied target is not a rule conflict, so publication is allowed.
        publish = next(
            s for s in self.timeline if s["step_id"] == "publish-atlas-general-v2"
        )
        self.assertEqual(201, publish["expected"]["status"])

    def test_no_scenario_ack_and_comment_bounds(self):
        no_ack = self.failure("publish-no-scenario-no-ack")
        self.assertEqual(409, no_ack["expected"]["status"])
        self.assertEqual("NO_SCENARIO_ACK_REQUIRED", no_ack["expected"]["code"])
        self.assertFalse(no_ack["request"]["acknowledge_no_scenario"])
        self.assertEqual(
            "simulation-atlas-general-v2-full", no_ack["request"]["simulation_id"]
        )
        for failure_id in ("publish-comment-empty", "publish-comment-too-long"):
            failure = self.failure(failure_id)
            self.assertTrue(failure["schema_rejected"])
            self.assertEqual(422, failure["expected"]["status"])
            self.assertEqual("VALIDATION_ERROR", failure["expected"]["code"])
        empty = self.failure("publish-comment-empty")
        self.assertEqual("", empty["request"]["comment"])
        too_long = self.failure("publish-comment-too-long")
        comment = dl.materialize_request(too_long, self.context)["comment"]
        self.assertEqual(501, len(comment))
        accepted = next(
            s for s in self.timeline if s["step_id"] == "publish-atlas-general-v2"
        )
        self.assertTrue(accepted["request"]["acknowledge_no_scenario"])
        self.assertEqual(201, accepted["expected"]["status"])

    def test_stale_draft_ruleset_ready_and_ttl_are_distinct_scenarios(self):
        stale_draft = self.failure("publish-stale-draft")
        stale_ruleset = self.failure("publish-stale-simulation-ruleset")
        stale_ready = self.failure("publish-stale-simulation-ready")
        stale_ttl = self.failure("publish-stale-simulation-ttl")
        self.assertEqual("DRAFT_VERSION_CONFLICT", stale_draft["expected"]["code"])
        for failure in (stale_ruleset, stale_ready, stale_ttl):
            self.assertEqual("STALE_SIMULATION", failure["expected"]["code"])
            self.assertEqual(409, failure["expected"]["status"])
            self.assertFalse(failure["mutates"])
        self.assertEqual(4, len({stale_draft["failure_id"], stale_ruleset["failure_id"],
                                 stale_ready["failure_id"], stale_ttl["failure_id"]}))

    def test_publish_full_ruleset_immutable_version_history_and_batch_binding(self):
        publish = self.context["publishes"]["publish-atlas-general-v2"]
        payload = dl.materialize_publish(publish, self.context)
        self.assertEqual(
            payload["published_version"]["version_id"],
            payload["dictionary"]["active_version_id"],
        )
        self.assertEqual(2, payload["dictionary"]["versions_count"])
        self.assertEqual(2, payload["published_version"]["version_number"])
        self.assertIsNone(payload["published_version"]["restored_from_version_id"])
        # The full active Atlas set, sorted by dictionary_id.
        members = [
            (m["dictionary_id"], m["version_id"]) for m in payload["rule_set"]["members"]
        ]
        self.assertEqual(sorted(members), members)
        self.assertIn(
            ("dictionary-atlas-general", "version-atlas-general-v2"), members
        )
        self.assertIn(
            ("dictionary-atlas-invoices", "version-atlas-invoices-v1"), members
        )

        binding = self.expectations["batch_bindings"][0]
        self.assertFalse(binding["batch_exists"])
        for version_id in binding["version_ids"]:
            self.assertEqual("published", self.context["versions"][version_id]["role"])

        # The later publication of another dictionary leaves v2 and v1 untouched.
        later = self.context["publishes"]["publish-atlas-invoices-v2"]
        later_payload = dl.materialize_publish(later, self.context)
        self.assertNotEqual(
            payload["published_version"], later_payload["published_version"]
        )
        version = dl.materialize_version(
            self.context["versions"]["version-atlas-general-v2"], self.context
        )
        self.assertEqual("version-atlas-general-v2", version["version_id"])
        self.assertIsNone(version["restored_from_version_id"])

    def test_restore_then_publish_records_provenance_and_manual_edit_clears_it(self):
        restore = next(
            s for s in self.timeline if s["step_id"] == "restore-atlas-general-v1"
        )
        restored = dl.materialize_dictionary(
            self.context["states"]["state-atlas-general-restored-v1"], self.context
        )
        self.assertEqual("version-atlas-general-v1", restored["draft"]["based_on_version_id"])
        self.assertEqual(3, restored["draft"]["draft_revision"])
        self.assertEqual("version-atlas-general-v2", restored["active_version_id"])
        self.assertEqual(2, restored["versions_count"])

        publish = self.context["publishes"]["publish-atlas-general-v3"]
        payload = dl.materialize_publish(publish, self.context)
        self.assertEqual(
            "version-atlas-general-v1",
            payload["published_version"]["restored_from_version_id"],
        )
        self.assertEqual(3, payload["published_version"]["version_number"])
        self.assertEqual(3, payload["dictionary"]["versions_count"])

        manual = dl.materialize_dictionary(
            self.context["states"]["state-atlas-general-manual-edit"], self.context
        )
        self.assertIsNone(manual["draft"]["based_on_version_id"])
        self.assertEqual(4, manual["draft"]["draft_revision"])
        self.assertNotIn(
            "version-atlas-general-v3",
            self.context["states"]["state-atlas-general-manual-edit"]["history"],
        )
        self.assertEqual(2, manual["versions_count"])
        self.assertEqual("version-atlas-general-v2", manual["active_version_id"])

    def test_idempotent_replay_returns_same_version_and_altered_body_conflicts(self):
        original = self.context["publishes"]["publish-atlas-general-v2"]
        replay = self.expectations["replays"][0]
        self.assertEqual(original["idempotency_key"], replay["idempotency_key"])
        self.assertEqual(original["actor"], replay["actor"])
        self.assertEqual(original["request"], replay["request"])
        self.assertEqual(replay["before_state"], replay["after_state"])
        self.assertEqual(
            dl.materialize_publish(original, self.context),
            dl.materialize_publish(replay, self.context),
        )
        altered = self.failure("publish-idempotency-altered-body")
        self.assertEqual(
            original["idempotency_key"], altered["idempotency_key"]
        )
        self.assertNotEqual(original["request"], altered["request"])
        self.assertEqual("IDEMPOTENCY_KEY_REUSED", altered["expected"]["code"])
        self.assertEqual(409, altered["expected"]["status"])
        # Idempotency is user-scoped: a different actor with the same UUID is a
        # new operation, not a key conflict; it is rejected as a stale test.
        other = self.failure("publish-other-user-new-operation-stale")
        self.assertEqual(original["idempotency_key"], other["idempotency_key"])
        self.assertEqual(original["request"], other["request"])
        self.assertNotEqual(original["actor"], other["actor"])
        self.assertEqual("STALE_SIMULATION", other["expected"]["code"])
        self.assertNotEqual("IDEMPOTENCY_KEY_REUSED", other["expected"]["code"])

    def test_history_counts_only_the_dictionary_own_published_versions(self):
        page = self.context["version_pages"]["page-atlas-general-versions"]
        payload = dl.materialize_page_versions(page, self.context)
        self.assertEqual(
            [
                "version-atlas-general-v3",
                "version-atlas-general-v2",
                "version-atlas-general-v1",
            ],
            [item["version_id"] for item in payload["items"]],
        )
        scenario_ids = {
            version["version_id"]
            for version in self.context["versions"].values()
            if version["role"] == "scenario"
        }
        self.assertTrue(scenario_ids)
        self.assertEqual(set(), scenario_ids & {item["version_id"] for item in payload["items"]})
        for state in self.context["states"].values():
            self.assertEqual(
                set(), scenario_ids & set(state.get("history", []))
            )
        self.assertEqual(
            3,
            len(
                [
                    version
                    for version in self.context["versions"].values()
                    if version["dictionary_id"] == "dictionary-atlas-general"
                    and version["role"] == "published"
                ]
            ),
        )

    def test_every_rule_and_version_reference_is_fully_defined(self):
        for simulation in self.expectations["simulations"]:
            with self.subTest(simulation=simulation["page_id"]):
                candidate_version = self.context["versions"][
                    simulation["candidate_version_id"]
                ]
                for row in simulation["rows"]:
                    references = list(row.get("matched_rules") or [])
                    if row.get("selected_rule"):
                        references.append(row["selected_rule"])
                    for reference in references:
                        version = self.context["versions"].get(
                            reference["version_id"]
                        )
                        if version is None:
                            # version_id null is the candidate draft.
                            version = candidate_version
                        self.assertEqual(
                            reference["dictionary_id"], version["dictionary_id"]
                        )
                        self.assertIn(
                            reference["rule_id"],
                            [rule["rule_id"] for rule in version["rules"]],
                        )

    def test_every_failure_has_an_exact_request_and_no_mutation(self):
        for failure in self.failures:
            with self.subTest(failure=failure["failure_id"]):
                self.assertIn("request", failure)
                self.assertIn("operation", failure)
                self.assertFalse(failure["mutates"])
                self.assertEqual(failure["before_state"], failure["after_state"])
                self.assertIn("status", failure["expected"])
                self.assertIn("code", failure["expected"])
                self.assertIn("preconditions", failure)
                self.assertTrue(failure["preconditions"])

    def test_audit_expectations_are_future_actions_not_evidence(self):
        known = {
            entry.get("step_id") or entry.get("failure_id") or entry.get("replay_id")
            for key in ("timeline", "failures", "replays")
            for entry in self.expectations[key]
        }
        allowed = set(
            self.context["document"]["components"]["schemas"]["AuditAction"]["enum"]
        )
        expectations = self.expectations["audit_expectations"]
        self.assertTrue(expectations)
        for entry in expectations:
            with self.subTest(scenario=entry["scenario_id"]):
                self.assertIn(entry["scenario_id"], known)
                self.assertFalse(entry["evidence"])
                self.assertTrue(set(entry["actions"]) <= allowed)

    def test_every_required_q_is_covered(self):
        coverage = self.expectations["coverage"]
        for q in dl.KNOWN_Q:
            with self.subTest(q=q):
                self.assertTrue(coverage.get(q), q)


class GeneratedExampleTests(LifecycleMixin, unittest.TestCase):
    def test_generated_examples_match_committed_files(self):
        generated = dl.generated_examples(self.expectations, self.context)
        self.assertEqual(len(dl.EXAMPLE_BINDINGS), len(generated))
        for relative, payload in generated.items():
            with self.subTest(file=relative):
                committed = synthetic.load_json(REPO_ROOT / relative)
                self.assertEqual(committed, payload)

    def test_every_generated_example_is_bound_in_the_manifest(self):
        manifest = self.context["rule_context"]["manifest"]
        bound = {entry["file"]: entry["schema"] for entry in manifest["examples"]}
        for binding in dl.EXAMPLE_BINDINGS:
            self.assertIn(binding["file"], bound)
            self.assertEqual(binding["schema"], bound[binding["file"]])


class NegativeExpectationTests(LifecycleMixin, unittest.TestCase):
    def _errors(self, expectations):
        return dl.expectation_errors(expectations, self.context_for(expectations))

    def test_undefined_rule_reference_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        page = next(
            entry
            for entry in expectations["simulations"]
            if entry["page_id"] == "page-atlas-full-1"
        )
        page["rows"][0]["matched_rules"][0]["rule_id"] = "rule-does-not-exist"
        page["rows"][0]["selected_rule"]["rule_id"] = "rule-does-not-exist"
        errors = self._errors(expectations)
        self.assertTrue(any("undefined rule reference" in m for m in errors), errors)

    def test_simulation_total_not_covering_ready_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        page = next(
            entry
            for entry in expectations["simulations"]
            if entry["page_id"] == "page-atlas-full-1"
        )
        page["total"] = 4
        errors = self._errors(expectations)
        self.assertTrue(any("full READY set" in m for m in errors), errors)

    def test_plan_counts_not_summing_to_total_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        page = next(
            entry
            for entry in expectations["simulations"]
            if entry["page_id"] == "page-atlas-full-1"
        )
        page["counts"]["will_move"] = 1
        errors = self._errors(expectations)
        self.assertTrue(any("PlanCounts do not sum" in m for m in errors), errors)

    def test_missing_empty_ready_warning_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        page = next(
            entry
            for entry in expectations["simulations"]
            if entry["page_id"] == "page-atlas-empty"
        )
        page["warnings"] = []
        errors = self._errors(expectations)
        self.assertTrue(any("EMPTY_READY_SET" in m for m in errors), errors)

    def test_conflict_without_two_matches_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        page = next(
            entry
            for entry in expectations["simulations"]
            if entry["page_id"] == "page-atlas-conflict"
        )
        page["rows"][0]["matched_rules"] = page["rows"][0]["matched_rules"][:1]
        errors = self._errors(expectations)
        self.assertTrue(any("at least two matched rules" in m for m in errors), errors)

    def test_failure_that_mutates_state_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        failure = next(
            f
            for f in expectations["failures"]
            if f["failure_id"] == "save-stale-revision-worker-two"
        )
        failure["mutates"] = True
        errors = self._errors(expectations)
        self.assertTrue(any("mutates=false" in m for m in errors), errors)

    def test_wrong_error_code_for_operation_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        failure = next(
            f
            for f in expectations["failures"]
            if f["failure_id"] == "save-stale-revision-worker-two"
        )
        failure["expected"] = {"status": 409, "code": "STALE_SIMULATION"}
        errors = self._errors(expectations)
        self.assertTrue(any("is not declared by" in m for m in errors), errors)

    def test_publish_history_not_growing_by_one_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        state = next(
            s
            for s in expectations["states"]
            if s["state_id"] == "state-atlas-general-published-v2"
        )
        state["history"] = ["version-atlas-general-v1"]
        errors = self._errors(expectations)
        self.assertTrue(any("history did not grow" in m for m in errors), errors)

    def test_restored_from_foreign_dictionary_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        version = next(
            v
            for v in expectations["versions"]
            if v["version_id"] == "version-atlas-general-v3"
        )
        version["restored_from_version_id"] = "version-nova-general-v1"
        errors = self._errors(expectations)
        self.assertTrue(any("restored_from_version_id" in m for m in errors), errors)

    def test_replay_with_a_different_body_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        expectations["replays"][0]["request"]["comment"] = "Другое тело."
        errors = self._errors(expectations)
        self.assertTrue(any("replay request differs" in m for m in errors), errors)

    def test_scenario_version_in_published_rule_set_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        rule_set = next(
            r
            for r in expectations["rule_sets"]
            if r["rule_set_id"] == "rule-set-atlas-v2"
        )
        rule_set["members"][0]["version_id"] = "version-atlas-general-scenario-conflict-v1"
        errors = self._errors(expectations)
        self.assertTrue(
            any("must reference published versions" in m for m in errors), errors
        )

    def test_missing_coverage_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        expectations["coverage"]["Q-018"] = []
        errors = self._errors(expectations)
        self.assertTrue(any("Q-018" in m for m in errors), errors)

    def test_audit_expectation_claiming_evidence_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        expectations["audit_expectations"][0]["evidence"] = True
        errors = self._errors(expectations)
        self.assertTrue(any("evidence=false" in m for m in errors), errors)

    def test_unknown_audit_action_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        expectations["audit_expectations"][0]["actions"] = ["NOT_AN_ACTION"]
        errors = self._errors(expectations)
        self.assertTrue(any("unknown AuditAction" in m for m in errors), errors)

    def test_publish_comment_mismatch_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        publish = next(
            p
            for p in expectations["publishes"]
            if p["publish_id"] == "publish-atlas-general-v2"
        )
        publish["request"]["comment"] = "Не тот комментарий."
        errors = self._errors(expectations)
        self.assertTrue(any("comment differs" in m for m in errors), errors)

    def test_publish_draft_rules_mismatch_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        publish = next(
            p
            for p in expectations["publishes"]
            if p["publish_id"] == "publish-atlas-general-v2"
        )
        publish["published_version_id"] = "version-atlas-general-v1"
        errors = self._errors(expectations)
        self.assertTrue(any("draft rules differ" in m for m in errors), errors)

    def test_publish_base_ruleset_already_binds_published_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        page = next(
            entry
            for entry in expectations["simulations"]
            if entry["page_id"] == "page-atlas-full-1"
        )
        page["base_rule_set_id"] = "rule-set-atlas-v2"
        errors = self._errors(expectations)
        self.assertTrue(
            any("already binds the published version" in m for m in errors), errors
        )

    def test_simulation_draft_revision_disagrees_with_before_state_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        step = next(
            s
            for s in expectations["timeline"]
            if s["step_id"] == "simulate-atlas-general-v2-full"
        )
        step["expected"]["draft_revision"] = 99
        errors = self._errors(expectations)
        self.assertTrue(
            any("expected draft_revision disagrees" in m for m in errors), errors
        )

    def test_simulation_candidate_version_belongs_to_another_dictionary_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        page = next(
            entry
            for entry in expectations["simulations"]
            if entry["page_id"] == "page-atlas-full-1"
        )
        page["candidate_version_id"] = "version-nova-general-v1"
        errors = self._errors(expectations)
        self.assertTrue(
            any("candidate_version_id belongs to another dictionary" in m for m in errors),
            errors,
        )

    def test_simulation_universe_mismatch_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        step = next(
            s
            for s in expectations["timeline"]
            if s["step_id"] == "simulate-atlas-conflict"
        )
        step["before_state"] = "state-atlas-general-scenario-same-target"
        step["after_state"] = "state-atlas-general-scenario-same-target"
        errors = self._errors(expectations)
        self.assertTrue(
            any("simulation universe disagrees" in m for m in errors), errors
        )

    def test_save_revision_not_incrementing_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        state = next(
            s
            for s in expectations["states"]
            if s["state_id"] == "state-atlas-general-rev2"
        )
        state["draft_revision"] = 1
        errors = self._errors(expectations)
        self.assertTrue(any("increment the draft revision" in m for m in errors), errors)

    def test_restore_based_on_mismatch_is_caught(self):
        expectations = copy.deepcopy(self.expectations)
        state = next(
            s
            for s in expectations["states"]
            if s["state_id"] == "state-atlas-general-restored-v1"
        )
        state["based_on_version_id"] = None
        errors = self._errors(expectations)
        self.assertTrue(
            any("based_on_version_id must equal request.version_id" in m for m in errors),
            errors,
        )

    def test_schema_rejection_classification_is_correct(self):
        expectations = copy.deepcopy(self.expectations)
        failure = next(
            f
            for f in expectations["failures"]
            if f["failure_id"] == "publish-comment-empty"
        )
        failure["schema_rejected"] = False
        errors = dl.request_rejection_errors(
            expectations, self.context, self.registry
        )
        self.assertTrue(any("schema-valid" in m for m in errors), errors)


if __name__ == "__main__":
    unittest.main()
