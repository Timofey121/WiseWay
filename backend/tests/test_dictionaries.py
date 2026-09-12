from __future__ import annotations

import copy
import unittest
from types import SimpleNamespace

from wiseway.common import ApiError
from wiseway.dictionaries import DictionaryService, flattened_rules, rule_set
from wiseway.rules import plan_rows


ACTOR = {"user_id": "user-admin", "login": "admin", "display_name": "Admin", "role": "ADMIN"}
TARGET = {
    "root_id": "archive-root",
    "relative_directory": "Atlas/Reports",
    "display_path": "DEMO:/SandboxRoot/Archive/Atlas/Reports",
}
MANUAL = {
    "root_id": "manual-root",
    "relative_directory": "Atlas",
    "display_path": "DEMO:/SandboxRoot/ManualReview/Atlas",
}


class MemoryTx:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict] = {}
        self.events: list[dict] = []

    def get(self, kind, key, default=None):
        value = self.objects.get((kind, key))
        return copy.deepcopy(value) if value is not None else default

    def require(self, kind, key):
        value = self.get(kind, key)
        if value is None:
            raise ApiError("NOT_FOUND", status=404)
        return value

    def put(self, kind, key, value):
        self.objects[(kind, key)] = copy.deepcopy(value)

    def insert(self, kind, key, value):
        if (kind, key) in self.objects:
            raise RuntimeError("duplicate")
        self.put(kind, key, value)

    def list(self, kind):
        return [
            copy.deepcopy(value)
            for (stored_kind, _), value in sorted(self.objects.items())
            if stored_kind == kind
        ]

    def delete(self, kind, key):
        self.objects.pop((kind, key), None)

    def append_event(self, event):
        self.events.append(event)


class Context:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(clock=lambda: 1_000.0, ttl=300)
        self.target_directories = [TARGET, MANUAL]
        self.ready = [queue_item("ready-1", "invoice.pdf")]

    def location(self, tx, root_id, relative_path):
        return {
            "root_id": root_id,
            "relative_path": relative_path,
            "display_path": f"DEMO:/{root_id}/{relative_path}",
        }

    def targets(self, tx, company_id):
        return copy.deepcopy(self.target_directories)

    def exists(self, tx, target):
        return False

    def page(self, tx, scope, actor, query, payload, field="items", cursor=None, limit=100):
        values = payload[field]
        return {**payload, field: values[:limit], "next_cursor": None}

    def ready_items(self, tx, company_id):
        return [
            copy.deepcopy(item)
            for item in self.ready
            if item["company_id"] == company_id and item["status"] == "READY"
        ]

    def plan(self, tx, items, rules, company_id):
        return plan_rows(
            items,
            rules,
            {"root_id": MANUAL["root_id"], "relative_directory": MANUAL["relative_directory"]},
            lambda target: self.exists(tx, target),
            location=lambda root_id, relative: self.location(tx, root_id, relative),
        )


def queue_item(item_id, filename):
    return {
        "item_id": item_id,
        "item_revision": 1,
        "company_id": "company-atlas",
        "incoming_source_id": "incoming-atlas",
        "source_name": "Atlas",
        "source": {
            "root_id": "incoming-root",
            "relative_path": f"Atlas/{filename}",
            "display_path": f"DEMO:/SandboxRoot/Incoming/Atlas/{filename}",
        },
        "filename": filename,
        "size_bytes": 10,
        "modified_at": "2031-01-01T00:00:00Z",
        "status": "READY",
        "reason_code": None,
        "selectable": True,
        "active_attempt_id": None,
    }


def sorting_rule(rule_id="rule-1", *, stem="Invoice", target=TARGET):
    return {
        "rule_id": rule_id,
        "priority": 10,
        "match_field": "BASENAME",
        "mask": "*.pdf",
        "target": {"root_id": target["root_id"], "relative_directory": target["relative_directory"]},
        "target_stem": stem,
    }


class DictionaryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tx = MemoryTx()
        self.tx.insert("company", "company-atlas", {"company_id": "company-atlas", "name": "Atlas"})
        self.tx.insert("company", "company-nova", {"company_id": "company-nova", "name": "Nova"})
        self.ctx = Context()
        self.service = DictionaryService(self.ctx)

    def call(self, operation, *, params=None, body=None):
        return self.service.handle(operation, self.tx, ACTOR, params or {}, body or {}, "request-1")

    def create(self, name="Invoices"):
        status, dictionary = self.call(
            "createDictionary",
            params={"company_id": "company-atlas"},
            body={"name": name, "description": "Sort invoices"},
        )
        self.assertEqual(status, 201)
        return dictionary

    def test_targets_are_paginated_and_resolve_only_configured_company_directory(self) -> None:
        status, page = self.call(
            "listTargetDirectories", params={"company_id": "company-atlas", "cursor": None, "limit": 100}
        )
        self.assertEqual(status, 200)
        self.assertEqual(page["items"], [TARGET, MANUAL])

        status, target = self.call(
            "resolveTargetDirectory",
            params={"company_id": "company-atlas"},
            body={"display_path": TARGET["display_path"]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(target, TARGET)
        with self.assertRaisesRegex(ApiError, "") as rejected:
            self.call(
                "resolveTargetDirectory",
                params={"company_id": "company-atlas"},
                body={"display_path": "DEMO:/Outside"},
            )
        self.assertEqual(rejected.exception.code, "INVALID_TARGET")

    def test_name_is_trimmed_and_unique_by_casefold_within_company(self) -> None:
        dictionary = self.create("  Invoices  ")
        self.assertEqual(dictionary["name"], "Invoices")
        with self.assertRaises(ApiError) as rejected:
            self.create("invoices")
        self.assertEqual(rejected.exception.code, "DICTIONARY_NAME_CONFLICT")

    def test_draft_replacement_requires_current_revision_and_valid_existing_targets(self) -> None:
        dictionary = self.create()
        body = {
            "expected_draft_revision": 1,
            "name": "Invoices",
            "description": "Updated",
            "rules": [sorting_rule()],
        }
        status, updated = self.call(
            "replaceDictionaryDraft", params={"dictionary_id": dictionary["dictionary_id"]}, body=body
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["draft"]["draft_revision"], 2)

        with self.assertRaises(ApiError) as stale:
            self.call(
                "replaceDictionaryDraft", params={"dictionary_id": dictionary["dictionary_id"]}, body=body
            )
        self.assertEqual(stale.exception.code, "DRAFT_VERSION_CONFLICT")

        bad_target = {
            **body,
            "expected_draft_revision": 2,
            "rules": [sorting_rule(target={**TARGET, "relative_directory": "Not/Configured"})],
        }
        with self.assertRaises(ApiError) as invalid:
            self.call(
                "replaceDictionaryDraft",
                params={"dictionary_id": dictionary["dictionary_id"]},
                body=bad_target,
            )
        self.assertEqual(invalid.exception.code, "INVALID_TARGET")

    def test_simulation_uses_candidate_draft_and_detects_stale_ready_snapshot(self) -> None:
        dictionary = self.create()
        self.call(
            "replaceDictionaryDraft",
            params={"dictionary_id": dictionary["dictionary_id"]},
            body={
                "expected_draft_revision": 1,
                "name": "Invoices",
                "description": "Sort",
                "rules": [sorting_rule()],
            },
        )
        status, simulation = self.call(
            "createDictionarySimulation",
            params={"dictionary_id": dictionary["dictionary_id"]},
            body={"expected_draft_revision": 2},
        )
        self.assertEqual(status, 201)
        self.assertEqual(simulation["counts"]["will_move"], 1)
        self.assertEqual(simulation["rows"][0]["selected_rule"]["version_id"], None)

        status, current = self.call(
            "getSimulation",
            params={"simulation_id": simulation["simulation_id"], "cursor": None, "limit": 100},
        )
        self.assertEqual(status, 200)
        self.assertEqual(current["simulation_id"], simulation["simulation_id"])

        self.ctx.ready.append(queue_item("ready-2", "another.pdf"))
        status, historical = self.call(
            "getSimulation",
            params={"simulation_id": simulation["simulation_id"], "cursor": None, "limit": 100},
        )
        self.assertEqual(status, 200)
        self.assertEqual(historical["simulation_id"], simulation["simulation_id"])
        with self.assertRaises(ApiError) as stale:
            self.call(
                "publishDictionary",
                params={"dictionary_id": dictionary["dictionary_id"]},
                body={
                    "expected_draft_revision": 2,
                    "simulation_id": simulation["simulation_id"],
                    "acknowledge_no_scenario": False,
                    "comment": "Outdated test",
                },
            )
        self.assertEqual(stale.exception.code, "STALE_SIMULATION")

    def test_publish_requires_fresh_simulation_and_creates_immutable_version(self) -> None:
        dictionary = self.create()
        self.call(
            "replaceDictionaryDraft",
            params={"dictionary_id": dictionary["dictionary_id"]},
            body={
                "expected_draft_revision": 1,
                "name": "Invoices",
                "description": "Sort",
                "rules": [sorting_rule()],
            },
        )
        _, simulation = self.call(
            "createDictionarySimulation",
            params={"dictionary_id": dictionary["dictionary_id"]},
            body={"expected_draft_revision": 2},
        )
        status, result = self.call(
            "publishDictionary",
            params={"dictionary_id": dictionary["dictionary_id"]},
            body={
                "expected_draft_revision": 2,
                "simulation_id": simulation["simulation_id"],
                "acknowledge_no_scenario": False,
                "comment": "Initial publication",
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(result["published_version"]["version_number"], 1)
        self.assertEqual(result["dictionary"]["active_version_id"], result["published_version"]["version_id"])
        self.assertEqual(
            rule_set(self.tx, "company-atlas")["members"],
            [
                {
                    "dictionary_id": dictionary["dictionary_id"],
                    "version_id": result["published_version"]["version_id"],
                }
            ],
        )

        version = self.call(
            "getDictionaryVersion",
            params={
                "dictionary_id": dictionary["dictionary_id"],
                "version_id": result["published_version"]["version_id"],
            },
        )[1]
        self.assertEqual(version["rules"], [sorting_rule()])

    def test_no_scenario_needs_explicit_acknowledgement_and_restore_sets_provenance(self) -> None:
        dictionary = self.create()
        _, empty_simulation = self.call(
            "createDictionarySimulation",
            params={"dictionary_id": dictionary["dictionary_id"]},
            body={"expected_draft_revision": 1},
        )
        publish = {
            "expected_draft_revision": 1,
            "simulation_id": empty_simulation["simulation_id"],
            "acknowledge_no_scenario": False,
            "comment": "Empty rules",
        }
        with self.assertRaises(ApiError) as rejected:
            self.call(
                "publishDictionary", params={"dictionary_id": dictionary["dictionary_id"]}, body=publish
            )
        self.assertEqual(rejected.exception.code, "NO_SCENARIO_ACK_REQUIRED")
        _, published = self.call(
            "publishDictionary",
            params={"dictionary_id": dictionary["dictionary_id"]},
            body={**publish, "acknowledge_no_scenario": True},
        )

        status, restored = self.call(
            "restoreDictionaryDraft",
            params={"dictionary_id": dictionary["dictionary_id"]},
            body={"version_id": published["published_version"]["version_id"], "expected_draft_revision": 1},
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            restored["draft"]["based_on_version_id"], published["published_version"]["version_id"]
        )

    def test_flattened_rules_replace_only_candidate_dictionary_active_version(self) -> None:
        dictionary = self.create()
        self.call(
            "replaceDictionaryDraft",
            params={"dictionary_id": dictionary["dictionary_id"]},
            body={
                "expected_draft_revision": 1,
                "name": "Invoices",
                "description": "Sort",
                "rules": [sorting_rule()],
            },
        )
        _, simulation = self.call(
            "createDictionarySimulation",
            params={"dictionary_id": dictionary["dictionary_id"]},
            body={"expected_draft_revision": 2},
        )
        self.call(
            "publishDictionary",
            params={"dictionary_id": dictionary["dictionary_id"]},
            body={
                "expected_draft_revision": 2,
                "simulation_id": simulation["simulation_id"],
                "acknowledge_no_scenario": False,
                "comment": "Initial",
            },
        )
        candidate = self.tx.require("dictionary", dictionary["dictionary_id"])
        candidate["draft"]["rules"] = [sorting_rule("candidate-rule", stem="Candidate")]
        rules = flattened_rules(self.tx, "company-atlas", candidate)
        self.assertEqual(rules[0]["rule_id"], "candidate-rule")
        self.assertIsNone(rules[0]["version_id"])
