"""Tests for the LT-03.5b canonical audit journal oracle.

The fixture is an *independent* oracle: these tests check that every OAS
``AuditAction`` is represented with its exact category and actor/null scope,
that the dictionary events bind the actual timeline actor/time/IDs/version/
comment/revision, that every described attempt has a start and a terminal or
recovery phase with no duplicate attempt/phase, that the query/actors/updates
expectations are internally consistent and schema-valid, and that the committed
public examples equal the materialized literals.  No test records an audit
event, implements a filter engine or cursor store, or reads a filesystem.
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from contractlib import audit_expectations as ae  # noqa: E402
from contractlib import build_registry, load_contract  # noqa: E402
from contractlib import synthetic  # noqa: E402

REPO_ROOT = HERE.parents[1]
CONTRACT = REPO_ROOT / "contracts" / "openapi" / "wiseway-v1.yaml"

_MISSING = object()


class AuditMixin:
    @classmethod
    def setUpClass(cls):
        cls.registry = build_registry(load_contract(CONTRACT))
        cls.expectations = ae.load_expectations(REPO_ROOT)
        cls.context = ae.build_context(REPO_ROOT, cls.expectations)

    def context_for(self, expectations):
        return ae.build_context(REPO_ROOT, expectations)

    def query(self, query_id):
        return self.context["queries"][query_id]

    def event(self, event_id):
        return self.context["event_by_id"][event_id]["payload"]

    def entry(self, event_id):
        return self.context["event_by_id"][event_id]

    def mutate(self, expectations, operation, path, value=_MISSING):
        mutated = copy.deepcopy(expectations)
        mutation = {"operation": operation, "path": path}
        if value is not _MISSING:
            mutation["value"] = value
        ae._apply_mutation(mutated, mutation)
        return mutated


class OracleStructureTests(AuditMixin, unittest.TestCase):
    def test_expectations_have_no_structural_errors(self):
        self.assertEqual([], ae.expectation_errors(self.expectations, self.context))

    def test_every_payload_materializes_to_a_schema_valid_payload(self):
        self.assertEqual(
            [], ae.payload_errors(self.expectations, self.context, self.registry)
        )

    def test_error_codes_are_declared_by_the_specific_audit_operation(self):
        self.assertEqual(
            [], ae.error_operation_errors(self.expectations, self.context)
        )

    def test_links_are_consistent(self):
        self.assertEqual([], ae.link_errors(self.expectations, self.context))

    def test_coverage_is_complete_and_resolvable(self):
        self.assertEqual([], ae.coverage_errors(self.expectations, self.context))
        for q_id in ae.KNOWN_Q:
            self.assertTrue(self.expectations["coverage"].get(q_id), q_id)

    def test_every_generated_example_matches_the_committed_file(self):
        generated = ae.generated_examples(self.expectations, self.context)
        self.assertTrue(generated)
        for relative, payload in generated.items():
            with self.subTest(example=relative):
                committed = synthetic.load_json(REPO_ROOT / relative)
                self.assertEqual(committed, payload)

    def test_every_generated_example_is_bound_in_the_manifest(self):
        manifest = self.context["manifest"]
        bound = {entry["file"]: entry["schema"] for entry in manifest["examples"]}
        for binding in ae.EXAMPLE_BINDINGS:
            self.assertIn(binding["file"], bound)
            self.assertEqual(binding["schema"], bound[binding["file"]])


class ActionCoverageTests(AuditMixin, unittest.TestCase):
    def test_all_fourteen_actions_are_represented(self):
        present = {entry["payload"]["action"] for entry in self.context["events"]}
        self.assertEqual(set(ae.AUDIT_ACTIONS), present)
        self.assertEqual(14, len(ae.AUDIT_ACTIONS))

    def test_every_business_action_is_business_and_has_an_actor(self):
        for entry in self.context["events"]:
            payload = entry["payload"]
            if payload["action"] not in ae.BUSINESS_ACTIONS:
                continue
            with self.subTest(event=payload["event_id"]):
                self.assertEqual("BUSINESS", payload["category"])
                self.assertIsNotNone(payload["actor"])

    def test_every_system_action_is_system(self):
        for entry in self.context["events"]:
            payload = entry["payload"]
            if payload["action"] not in ae.SYSTEM_ACTIONS:
                continue
            with self.subTest(event=payload["event_id"]):
                self.assertEqual("SYSTEM", payload["category"])

    def test_only_an_uninitiated_login_failed_has_a_null_actor(self):
        null_events = [
            entry["payload"]
            for entry in self.context["events"]
            if entry["payload"]["actor"] is None
        ]
        self.assertTrue(null_events)
        for payload in null_events:
            self.assertEqual("LOGIN_FAILED", payload["action"])
            self.assertEqual("SYSTEM", payload["category"])
            self.assertEqual("FAILED", payload["result"])

    def test_accepted_batch_publish_and_return_never_have_a_null_actor(self):
        for entry in self.context["events"]:
            payload = entry["payload"]
            if payload["action"] in ae.MUTATION_ACTIONS:
                with self.subTest(event=payload["event_id"]):
                    self.assertIsNotNone(payload["actor"])

    def test_all_results_are_used(self):
        results = {entry["payload"]["result"] for entry in self.context["events"]}
        self.assertEqual(set(ae.AUDIT_RESULTS), results)


class ActorTests(AuditMixin, unittest.TestCase):
    def test_blocked_author_stays_in_the_filter_list(self):
        blocked = [entry for entry in self.expectations["actors"] if entry["blocked"]]
        self.assertEqual(1, len(blocked))
        blocked_user = blocked[0]["user_id"]
        listed = [
            item["user_id"]
            for page in self.expectations["actors_pages"]
            for item in ae.materialize_actors_page(page, self.context)["items"]
        ]
        self.assertIn(blocked_user, listed)

    def test_actor_dto_has_no_invented_blocking_field(self):
        page = self.context["actors_pages"]["AUD-ACTORS-ALL"]
        payload = ae.materialize_actors_page(page, self.context)
        for item in payload["items"]:
            self.assertEqual(
                {"user_id", "login", "display_name", "role"}, set(item.keys())
            )

    def test_blocked_event_uses_the_historical_display_snapshot(self):
        spec = next(
            entry for entry in self.expectations["actors"] if entry["blocked"]
        )
        event = self.event("AUD-DICT-BLOCKED-SAVE")
        self.assertEqual(spec["display_name_at_event"], event["actor"]["display_name"])
        self.assertNotEqual(spec["display_name"], event["actor"]["display_name"])
        page = ae.materialize_actors_page(
            self.context["actors_pages"]["AUD-ACTORS-ALL"], self.context
        )
        current = next(
            item for item in page["items"] if item["user_id"] == spec["user_id"]
        )
        self.assertEqual(spec["display_name"], current["display_name"])

    def test_empty_prefix_page_is_empty(self):
        page = self.context["actors_pages"]["AUD-ACTORS-EMPTY"]
        payload = ae.materialize_actors_page(page, self.context)
        self.assertEqual([], payload["items"])
        self.assertIsNone(payload["next_cursor"])

    def test_actor_pages_are_internally_consistent(self):
        self.assertEqual([], ae.actors_errors(self.expectations, self.context))


class DictionaryBindingTests(AuditMixin, unittest.TestCase):
    def test_dictionary_events_bind_the_actual_timeline(self):
        self.assertEqual(
            [], ae._dictionary_binding_errors(self.expectations, self.context)
        )
        dictionary = self.context["dictionary"]
        simulations = {}
        for simulation in dictionary["simulations"].values():
            simulations.setdefault(simulation["simulation_id"], simulation)
        for descriptor in self.expectations["dictionary_events"]:
            step = next(
                item
                for item in dictionary["expectations"]["timeline"]
                if item["step_id"] == descriptor["timeline_step"]
            )
            with self.subTest(event=descriptor["event_id"]):
                # The time is derived from the linked lifecycle, never a literal.
                self.assertNotIn("occurred_at", descriptor)
                if descriptor["action"] == "DICTIONARY_SIMULATED":
                    source = simulations[step["expected"]["simulation_id"]]["created_at"]
                elif descriptor["action"] == "DICTIONARY_PUBLISHED":
                    state = dictionary["states"][step["after_state"]]
                    version = dictionary["versions"][
                        step["expected"]["active_version_id"]
                    ]
                    self.assertEqual(state["updated_at"], version["published_at"])
                    source = version["published_at"]
                else:
                    source = dictionary["states"][step["after_state"]]["updated_at"]
                event = ae.materialize_dictionary_event(descriptor, self.context)
                self.assertEqual(source, event["occurred_at"])

    def test_publish_event_binds_version_rule_set_and_comment(self):
        event = self.event("AUD-DICT-PUBLISH-ATLAS-GENERAL-V2")
        self.assertEqual("version-atlas-general-v2", event["version_id"])
        self.assertEqual("rule-set-atlas-v2", event["rule_set_id"])
        self.assertEqual("Публикация проверенного черновика Atlas.", event["comment"])
        self.assertEqual("company-demo-atlas", event["company_id"])
        self.assertEqual("dictionary-atlas-general", event["dictionary_id"])

    def test_restore_event_binds_the_restored_version(self):
        event = self.event("AUD-DICT-RESTORE-ATLAS-GENERAL-V1")
        self.assertEqual("version-atlas-general-v1", event["version_id"])

    def test_read_timeline_steps_create_no_business_event(self):
        read_steps = {
            step["step_id"]
            for step in self.context["dictionary"]["expectations"]["timeline"]
            if step.get("mutates") is False
            and step.get("operation") != "createDictionarySimulation"
        }
        bound_steps = {
            descriptor["timeline_step"]
            for descriptor in self.expectations["dictionary_events"]
        }
        self.assertFalse(read_steps & bound_steps)

    def test_every_dictionary_event_revision_matches_the_timeline(self):
        for descriptor in self.expectations["dictionary_events"]:
            step = next(
                item
                for item in self.context["dictionary"]["expectations"]["timeline"]
                if item["step_id"] == descriptor["timeline_step"]
            )
            with self.subTest(event=descriptor["event_id"]):
                self.assertEqual(
                    step["expected"]["draft_revision"], descriptor["draft_revision"]
                )


class AttemptTests(AuditMixin, unittest.TestCase):
    def test_no_duplicate_attempt_phase(self):
        self.assertEqual([], ae._phase_errors(self.expectations, self.context))

    def test_every_attempt_has_a_start_and_a_terminal_or_recovery(self):
        self.assertEqual(
            [], ae._attempt_completeness_errors(self.expectations, self.context)
        )

    def test_batch_acceptance_is_exactly_once_per_batch(self):
        for batch_id in self.expectations["batch_universes"]:
            accepts = [
                entry
                for entry in self.context["events"]
                if entry["payload"]["action"] == "BATCH_ACCEPTED"
                and entry["payload"]["batch_id"] == batch_id
            ]
            with self.subTest(batch=batch_id):
                self.assertEqual(1, len(accepts))

    def test_attempt_events_use_the_batch_request_envelope(self):
        for entry in self.context["events"]:
            payload = entry["payload"]
            if payload["action"] not in ("FILE_ATTEMPT_STARTED", "FILE_ATTEMPT_FINISHED"):
                continue
            batch_id = payload["batch_id"]
            if batch_id in self.expectations["batch_request_ids"]:
                with self.subTest(event=payload["event_id"]):
                    self.assertEqual(
                        self.expectations["batch_request_ids"][batch_id],
                        payload["request_id"],
                    )

    def test_recovery_event_links_the_registered_operation(self):
        event = self.event("audit-attempt-batch-atlas-technical-batch-tech-recovery-unknown-recovery")
        self.assertEqual("RECOVERY_REQUIRED", event["action"])
        self.assertEqual(
            "recovery-batch-atlas-technical-batch-tech-recovery-unknown",
            event["operation_id"],
        )
        self.assertEqual(event["attempt_id"], event["source_attempt_id"])

    def test_pending_attempt_has_no_events(self):
        states = ae._attempt_state_map(self.context)
        pending = [attempt for attempt, state in states.items() if state == "PENDING"]
        self.assertTrue(pending)
        for attempt in pending:
            events = [
                entry
                for entry in self.context["events"]
                if entry["attempt_id"] == attempt
            ]
            self.assertEqual([], events)

    def test_processing_attempt_is_observed_after_its_start_only(self):
        states = ae._attempt_state_map(self.context)
        processing = [
            attempt for attempt, state in states.items() if state == "PROCESSING"
        ]
        self.assertTrue(processing)
        for attempt in processing:
            phases = {
                entry["phase"]
                for entry in self.context["events"]
                if entry["attempt_id"] == attempt
            }
            self.assertEqual({"ATTEMPT_START"}, phases)


class UniverseTests(AuditMixin, unittest.TestCase):
    def test_isolated_universes_are_declared_and_separate(self):
        self.assertEqual([], ae._universe_errors(self.expectations, self.context))
        kinds = {
            entry["universe_id"]: entry["kind"]
            for entry in self.expectations["universes"]
        }
        self.assertEqual("primary", kinds["primary"])
        self.assertTrue(all(
            kind == "isolated"
            for universe_id, kind in kinds.items()
            if universe_id != "primary"
        ))

    def test_primary_query_never_returns_an_isolated_event(self):
        expected = set(self.query("AUD-Q-PRIMARY-PAGE1")["expected"]["event_ids"])
        isolated = {
            entry["payload"]["event_id"]
            for entry in self.context["events"]
            if entry["universe"] != "primary"
        }
        self.assertFalse(expected & isolated)

    def test_isolated_queries_are_scoped_to_their_universe(self):
        for query_id in ("AUD-Q-ISOLATED-OVERLAP", "AUD-Q-ISOLATED-RETRY", "AUD-Q-ISOLATED-BATCH"):
            query = self.query(query_id)
            for event_id in query["expected"]["event_ids"]:
                with self.subTest(query=query_id, event=event_id):
                    self.assertEqual(
                        query["universe"], self.entry(event_id)["universe"]
                    )


class QueryTests(AuditMixin, unittest.TestCase):
    def test_query_literals_match_the_computed_pages(self):
        self.assertEqual([], ae.query_errors(self.expectations, self.context))

    def test_day_interval_is_the_moscow_day_in_utc(self):
        self.assertEqual("Europe/Moscow", self.expectations["timezone"]["id"])
        self.assertEqual("+03:00", self.expectations["timezone"]["utc_offset"])
        day_from = self.expectations["timezone"]["from_utc"]
        day_to = self.expectations["timezone"]["to_utc"]
        for query in self.expectations["queries"]:
            request = query["request"]
            with self.subTest(query=query["query_id"]):
                self.assertLess(request["from"], request["to"])
                if query["query_id"] == "AUD-Q-EMPTY-WINDOW":
                    self.assertGreaterEqual(request["from"], day_from)
                    self.assertLessEqual(request["to"], day_to)
                else:
                    self.assertEqual(day_from, request["from"])
                    self.assertEqual(day_to, request["to"])

    def test_expected_pages_are_unique_and_ordered(self):
        for query in self.expectations["queries"]:
            ids = query["expected"]["event_ids"]
            with self.subTest(query=query["query_id"]):
                self.assertEqual(len(ids), len(set(ids)))
                keys = [
                    (self.event(event_id)["occurred_at"], event_id) for event_id in ids
                ]
                self.assertEqual(keys, sorted(keys, reverse=True))

    def test_pages_never_exceed_one_hundred(self):
        for query in self.expectations["queries"]:
            with self.subTest(query=query["query_id"]):
                self.assertLessEqual(query["request"]["limit"], 100)
                self.assertLessEqual(len(query["expected"]["event_ids"]), 100)

    def test_cursor_page_is_pinned_to_the_frozen_upper_bound(self):
        page2 = self.query("AUD-Q-PRIMARY-PAGE2")
        self.assertIsNotNone(page2["frozen_newest_event_id"])
        for new_event in page2["new_events"]:
            self.assertNotIn(new_event, page2["expected"]["event_ids"])
        self.assertEqual(
            self.query("AUD-Q-PRIMARY-PAGE1")["expected"]["newest_event_id"],
            page2["expected"]["newest_event_id"],
        )

    def test_company_filter_returns_only_that_company(self):
        query = self.query("AUD-Q-COMPANY-NOVA")
        for event_id in query["expected"]["event_ids"]:
            self.assertEqual("company-demo-nova", self.event(event_id)["company_id"])

    def test_action_filter_returns_only_that_action(self):
        query = self.query("AUD-Q-ACTION-BATCH-ACCEPTED")
        self.assertEqual(4, len(query["expected"]["event_ids"]))
        for event_id in query["expected"]["event_ids"]:
            self.assertEqual("BATCH_ACCEPTED", self.event(event_id)["action"])

    def test_result_filter_returns_only_that_result(self):
        query = self.query("AUD-Q-RESULT-ISSUE")
        for event_id in query["expected"]["event_ids"]:
            self.assertEqual("ISSUE", self.event(event_id)["result"])

    def test_author_filter_uses_the_actor_user_id(self):
        query = self.query("AUD-Q-ACTOR-WORKER1")
        for event_id in query["expected"]["event_ids"]:
            self.assertEqual("user-demo-worker-1", self.event(event_id)["actor"]["user_id"])

    def test_text_filter_matches_the_logical_display_path(self):
        query = self.query("AUD-Q-TEXT-QUARANTINE")
        self.assertTrue(query["expected"]["event_ids"])
        for event_id in query["expected"]["event_ids"]:
            event = self.event(event_id)
            haystack = " ".join(
                location[field]
                for side in ("source", "target")
                if event.get(side)
                for location in [event[side]]
                for field in ("relative_path", "display_path")
            ).casefold()
            self.assertIn(query["request"]["query_text"].casefold(), haystack)

    def test_same_filter_replay_returns_the_same_page(self):
        first = self.query("AUD-Q-COMPANY-NOVA")
        replay = self.query("AUD-Q-REPLAY-COMPANY-NOVA")
        self.assertEqual(first["request"], replay["request"])
        self.assertEqual(first["expected"], replay["expected"])

    def test_empty_window_has_null_newest_and_no_cursor(self):
        query = self.query("AUD-Q-EMPTY-WINDOW")
        self.assertEqual([], query["expected"]["event_ids"])
        self.assertIsNone(query["expected"]["newest_event_id"])
        self.assertIsNone(query["expected"]["next_cursor"])

    def test_worker_only_sees_the_shared_business_journal(self):
        query = self.query("AUD-Q-ROLE-WORKER")
        self.assertEqual("WORKER", query["viewer_role"])
        self.assertTrue(query["expected"]["event_ids"])
        for event_id in query["expected"]["event_ids"]:
            self.assertEqual("BUSINESS", self.event(event_id)["category"])

    def test_admin_also_sees_the_system_journal(self):
        query = self.query("AUD-Q-ROLE-ADMIN")
        self.assertEqual("ADMIN", query["viewer_role"])
        categories = {
            self.event(event_id)["category"]
            for event_id in query["expected"]["event_ids"]
        }
        self.assertTrue(categories)
        # The full matching set (not only the page) contains both categories.
        result = ae.compute_query(self.expectations, self.context, query)
        self.assertEqual(["BUSINESS", "SYSTEM"], result["all_categories"])


class UpdatesTests(AuditMixin, unittest.TestCase):
    def test_updates_scenarios_are_consistent(self):
        self.assertEqual([], ae.updates_errors(self.expectations, self.context))

    def test_after_known_event_reports_new_events(self):
        scenario = self.context["updates"]["AUD-UPDATES-AFTER-KNOWN"]
        self.assertTrue(ae.materialize_updates(scenario, self.context)["has_new_events"])

    def test_after_newest_event_reports_no_new_events(self):
        scenario = self.context["updates"]["AUD-UPDATES-AFTER-NEWEST"]
        self.assertFalse(ae.materialize_updates(scenario, self.context)["has_new_events"])

    def test_absent_after_event_id_is_an_absent_lower_bound(self):
        scenario = self.context["updates"]["AUD-UPDATES-NO-AFTER"]
        self.assertIsNone(scenario["after_event_id"])
        self.assertTrue(ae.materialize_updates(scenario, self.context)["has_new_events"])

    def test_empty_initial_journal_reports_no_new_events(self):
        scenario = self.context["updates"]["AUD-UPDATES-NO-AFTER-EMPTY"]
        self.assertTrue(scenario["empty_journal"])
        self.assertFalse(ae.materialize_updates(scenario, self.context)["has_new_events"])

    def test_update_button_finite_steps_are_consistent(self):
        self.assertEqual([], ae.update_button_errors(self.expectations, self.context))
        button = self.expectations["update_button"]
        initial = ae.compute_query(
            self.expectations, self.context, self.context["queries"][button["query_id"]]
        )
        fresh = ae.compute_query(
            self.expectations,
            self.context,
            self.context["queries"][button["fresh_query_id"]],
        )
        self.assertEqual(button["initial_newest_event_id"], initial["newest_event_id"])
        self.assertEqual(button["new_event_id"], fresh["newest_event_id"])
        self.assertIn(button["new_event_id"], fresh["event_ids"])


class ReadOnlyTests(AuditMixin, unittest.TestCase):
    def test_read_only_scenarios_are_declared(self):
        self.assertEqual([], ae.no_business_errors(self.expectations, self.context))

    def test_search_navigation_and_copy_create_no_business_event(self):
        operations = {
            scenario["operation"] for scenario in self.expectations["no_business_scenarios"]
        }
        self.assertEqual(
            {"searchFiles", "getSearchFacet", "listRoots", "copyDisplayPath"}, operations
        )
        actions = {entry["payload"]["action"] for entry in self.context["events"]}
        for action in actions:
            self.assertIn(action, ae.AUDIT_ACTIONS)


class HeaderTests(AuditMixin, unittest.TestCase):
    def test_safe_headers_are_no_store_and_request_id_bound(self):
        self.assertEqual([], ae.headers_errors(self.expectations, self.context))
        headers = self.expectations["safe_headers"]
        self.assertEqual("no-store", headers["cache_control"])
        self.assertRegex(headers["request_id"], ae.ID_RE)

    def test_error_request_id_matches_the_header(self):
        error = self.context["errors"]["error-audit-validation"]
        self.assertEqual(
            self.expectations["safe_headers"]["request_id"], error["request_id"]
        )


class DescriptorTests(AuditMixin, unittest.TestCase):
    def test_every_lt034b_descriptor_has_a_canonical_representative(self):
        self.assertEqual([], ae._descriptor_errors(self.expectations, self.context))

    def test_viewer_swap_keeps_the_accepted_actor(self):
        self.assertEqual([], ae._viewer_swap_errors(self.expectations, self.context))
        swap = self.expectations["viewer_swap"]
        event = self.event(f"audit-{swap['batch_id']}-accepted")
        expected = self.context["actor_by_alias"][swap["accepted_actor"]]
        self.assertEqual(expected["user_id"], event["actor"]["user_id"])


class NegativeExpectationTests(AuditMixin, unittest.TestCase):
    def _errors(self, expectations):
        return ae.expectation_errors(expectations, self.context_for(expectations))

    def test_declared_mutations_are_rejected(self):
        self.assertEqual(
            [], ae.mutation_errors(self.expectations, self.context, self.registry)
        )

    def test_business_null_actor_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["explicit_events", 7, "actor"], None
        )
        self.assertTrue(self._errors(mutated))

    def test_system_action_as_business_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["explicit_events", 0, "category"], "BUSINESS"
        )
        self.assertTrue(self._errors(mutated))

    def test_actorless_logout_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["explicit_events", 5, "actor"], None
        )
        self.assertTrue(self._errors(mutated))

    def test_duplicate_attempt_phase_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["isolated_events", 1, "phase"], "ATTEMPT_START"
        )
        self.assertTrue(
            any("duplicate attempt/phase" in message for message in self._errors(mutated))
        )

    def test_unknown_query_event_id_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["queries", 0, "expected", "event_ids", 0],
            "audit-does-not-exist",
        )
        errors = ae.query_errors(mutated, self.context_for(mutated))
        self.assertTrue(errors)

    def test_cursor_drift_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["queries", 2, "expected", "next_cursor"],
            "cursor-wrong",
        )
        self.assertTrue(ae.query_errors(mutated, self.context_for(mutated)))

    def test_frozen_bound_drift_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["queries", 2, "frozen_newest_event_id"],
            None,
        )
        self.assertTrue(ae.query_errors(mutated, self.context_for(mutated)))

    def test_dropped_blocked_actor_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["actors_pages", 0, "expected_user_ids"],
            ["user-demo-worker-1", "user-demo-worker-2", "user-demo-admin-1"],
        )
        self.assertTrue(ae.actors_errors(mutated, self.context_for(mutated)))

    def test_updates_drift_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["updates_scenarios", 0, "expected", "has_new_events"],
            False,
        )
        self.assertTrue(ae.updates_errors(mutated, self.context_for(mutated)))

    def test_read_only_size_change_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["no_business_scenarios", 0, "after_event_count"],
            999,
        )
        self.assertTrue(ae.no_business_errors(mutated, self.context_for(mutated)))

    def test_cache_control_drift_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["safe_headers", "cache_control"], "public"
        )
        self.assertTrue(ae.headers_errors(mutated, self.context_for(mutated)))

    def test_link_drift_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["links", 0, "target", "path"], ["item", "item_id"]
        )
        self.assertTrue(ae.link_errors(mutated, self.context_for(mutated)))

    def test_descriptor_without_canonical_event_is_caught(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["isolated_events", 0, "action"],
            "FILE_ATTEMPT_FINISHED",
        )
        self.assertTrue(
            ae._descriptor_errors(mutated, self.context_for(mutated))
        )

    def test_dictionary_revision_drift_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["dictionary_events", 0, "draft_revision"], 99
        )
        self.assertTrue(
            ae._dictionary_binding_errors(mutated, self.context_for(mutated))
        )

    def test_dictionary_comment_drift_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["dictionary_events", 5, "comment"], "wrong"
        )
        self.assertTrue(
            ae._dictionary_binding_errors(mutated, self.context_for(mutated))
        )

    def test_coverage_gap_is_caught(self):
        mutated = self.mutate(self.expectations, "set", ["coverage", "Q-041"], [])
        self.assertTrue(ae.coverage_errors(mutated, self.context_for(mutated)))

    def test_invalid_instant_is_caught_by_the_payload_validator(self):
        mutated = self.mutate(
            self.expectations,
            "set",
            ["explicit_events", 0, "occurred_at"],
            "not-an-instant",
        )
        errors = ae.payload_errors(mutated, self.context_for(mutated), self.registry)
        self.assertTrue(errors)

    def test_undeclared_error_code_is_caught(self):
        mutated = self.mutate(
            self.expectations, "set", ["errors", 0, "code"], "STALE_PREVIEW"
        )
        self.assertTrue(
            ae.error_operation_errors(mutated, self.context_for(mutated))
        )

    def test_worker_system_event_is_caught(self):
        role_query = next(
            index
            for index, query in enumerate(self.expectations["queries"])
            if query["query_id"] == "AUD-Q-ROLE-WORKER"
        )
        mutated = self.mutate(
            self.expectations,
            "set",
            ["queries", role_query, "expected", "event_ids", 0],
            "AUD-LOGIN-SUCCESS-WORKER1",
        )
        self.assertTrue(ae.query_errors(mutated, self.context_for(mutated)))


if __name__ == "__main__":
    unittest.main()
