from __future__ import annotations

import unittest

from wiseway.rules import extension, match_rule, plan_counts, plan_rows


def item(item_id: str, filename: str, *, status: str = "READY") -> dict:
    return {
        "item_id": item_id,
        "item_revision": 1,
        "company_id": "company-atlas",
        "incoming_source_id": "incoming-atlas",
        "source_name": "Atlas incoming",
        "source": {
            "root_id": "incoming-root",
            "relative_path": f"Atlas/{filename}",
            "display_path": f"DEMO:/SandboxRoot/Incoming/Atlas/{filename}",
        },
        "filename": filename,
        "size_bytes": 1,
        "modified_at": "2031-05-10T09:00:00Z",
        "status": status,
        "reason_code": None,
        "selectable": status == "READY",
        "active_attempt_id": None,
    }


def rule(
    rule_id: str,
    *,
    priority: int = 10,
    mask: str = "*",
    target: dict | None = None,
    target_stem: str = "Invoice",
    dictionary_id: str = "dictionary-a",
    version_id: str | None = "version-a",
    match_field: str = "BASENAME",
) -> dict:
    return {
        "rule_id": rule_id,
        "dictionary_id": dictionary_id,
        "version_id": version_id,
        "priority": priority,
        "match_field": match_field,
        "mask": mask,
        "target": target or {"root_id": "archive-root", "relative_directory": "Atlas/Reports"},
        "target_stem": target_stem,
    }


def location(root_id: str, relative_path: str) -> dict:
    return {
        "root_id": root_id,
        "relative_path": relative_path,
        "display_path": f"DEMO:/{root_id}/{relative_path}",
    }


class ExtensionTests(unittest.TestCase):
    def test_uses_only_the_last_nonleading_nontrailing_suffix(self) -> None:
        self.assertEqual(extension("archive.tar.gz"), ".gz")
        self.assertEqual(extension("Report.PDF"), ".PDF")

    def test_hidden_extensionless_and_trailing_dot_names_have_no_suffix(self) -> None:
        self.assertEqual(extension(".env"), "")
        self.assertEqual(extension("README"), "")
        self.assertEqual(extension("name."), "")


class MatchingTests(unittest.TestCase):
    def test_basename_glob_is_whole_string_and_case_insensitive(self) -> None:
        invoice_rule = rule("r1", mask="invoice-??.pdf")

        self.assertTrue(match_rule(invoice_rule, "Atlas/INVOICE-01.PDF"))
        self.assertFalse(match_rule(invoice_rule, "Atlas/old-invoice-01.pdf"))

    def test_matching_uses_casefolding(self) -> None:
        street_rule = rule("r1", mask="straße.pdf")

        self.assertTrue(match_rule(street_rule, "Atlas/STRASSE.PDF"))

    def test_relative_path_normalizes_both_slash_kinds_and_star_crosses_directories(self) -> None:
        path_rule = rule("r1", match_field="RELATIVE_PATH", mask="atlas\\*\\invoice.*")

        self.assertTrue(match_rule(path_rule, "Atlas/Reports/Invoice.PDF"))
        self.assertTrue(match_rule(path_rule, "Atlas\\Reports\\Invoice.PDF"))

    def test_star_matches_every_supported_filename_character(self) -> None:
        any_name = rule("r1", mask="report*.pdf")

        self.assertTrue(match_rule(any_name, "Atlas/report\npart.pdf"))


class PlanningTests(unittest.TestCase):
    def test_winner_preserves_suffix_and_uses_stable_attribution_for_same_target(self) -> None:
        rules = [
            rule("rule-z", dictionary_id="dictionary-z", target_stem="Invoice.v2"),
            rule("rule-a", dictionary_id="dictionary-a", target_stem="Invoice.v2"),
        ]

        row = plan_rows(
            [item("one", "source.PDF")],
            rules,
            {"root_id": "manual-root", "relative_directory": "Atlas"},
            lambda _: False,
            location=location,
        )[0]

        self.assertEqual(row["predicted_state"], "WILL_MOVE")
        self.assertEqual(row["target"]["relative_path"], "Atlas/Reports/Invoice.v2.PDF")
        self.assertEqual(
            row["selected_rule"],
            {"dictionary_id": "dictionary-a", "version_id": "version-a", "rule_id": "rule-a"},
        )
        self.assertEqual(len(row["matched_rules"]), 2)

    def test_different_targets_at_the_best_priority_go_to_manual_review(self) -> None:
        rules = [
            rule("rule-a", target={"root_id": "archive-root", "relative_directory": "Atlas/A"}),
            rule("rule-b", target={"root_id": "archive-root", "relative_directory": "Atlas/B"}),
        ]

        row = plan_rows(
            [item("one", "source.pdf")],
            rules,
            {"root_id": "manual-root", "relative_directory": "Atlas"},
            lambda _: False,
            location=location,
        )[0]

        self.assertEqual(row["predicted_state"], "WILL_MANUAL_REVIEW")
        self.assertEqual(row["reason_code"], "RULE_CONFLICT")
        self.assertIsNone(row["target"])
        self.assertIsNone(row["selected_rule"])

    def test_unmatched_file_goes_to_manual_review(self) -> None:
        row = plan_rows(
            [item("one", "source.pdf")],
            [],
            {"root_id": "manual-root", "relative_directory": "Atlas"},
            lambda _: False,
            location=location,
        )[0]

        self.assertEqual(row["predicted_state"], "WILL_MANUAL_REVIEW")
        self.assertEqual(row["reason_code"], "NO_SCENARIO")

    def test_existing_target_blocks_move_with_collision_details(self) -> None:
        source_item = item("one", "source.pdf")
        source_item["size_bytes"] = 42
        source_item["modified_at"] = "2031-05-11T10:00:00Z"
        row = plan_rows(
            [source_item],
            [rule("rule-a")],
            {"root_id": "manual-root", "relative_directory": "Atlas"},
            lambda _: True,
            location=location,
        )[0]

        self.assertEqual(row["predicted_state"], "REQUIRES_DECISION")
        self.assertEqual(row["reason_code"], "TARGET_OCCUPIED")
        self.assertEqual(row["collision"]["kind"], "EXISTING_TARGET")
        self.assertEqual(row["collision"]["source_metadata"]["size_bytes"], 42)
        self.assertEqual(row["collision"]["source_metadata"]["modified_at"], "2031-05-11T10:00:00Z")

    def test_all_members_of_a_duplicate_planned_target_are_blocked(self) -> None:
        rows = plan_rows(
            [item("one", "source.pdf"), item("two", "other.pdf")],
            [rule("rule-a")],
            {"root_id": "manual-root", "relative_directory": "Atlas"},
            lambda _: False,
            location=location,
        )

        self.assertEqual([row["reason_code"] for row in rows], ["TARGET_OCCUPIED", "TARGET_OCCUPIED"])
        self.assertEqual(rows[0]["collision"]["conflicting_item_ids"], ["two"])
        self.assertEqual(rows[1]["collision"]["conflicting_item_ids"], ["one"])

    def test_occupied_manual_review_name_requires_decision(self) -> None:
        row = plan_rows(
            [item("one", "source.pdf")],
            [],
            {"root_id": "manual-root", "relative_directory": "Atlas"},
            lambda _: True,
            location=location,
        )[0]

        self.assertEqual(row["predicted_state"], "REQUIRES_DECISION")
        self.assertEqual(row["reason_code"], "MANUAL_REVIEW_NAME_OCCUPIED")
        self.assertEqual(row["collision"]["kind"], "MANUAL_REVIEW_NAME")

    def test_non_ready_item_is_not_planned(self) -> None:
        row = plan_rows(
            [item("one", "source.pdf", status="WAITING_READY")],
            [rule("rule-a")],
            {"root_id": "manual-root", "relative_directory": "Atlas"},
            lambda _: False,
            location=location,
        )[0]

        self.assertEqual(row["predicted_state"], "NOT_READY")
        self.assertEqual(row["reason_code"], "NOT_READY")

    def test_selectable_requires_decision_item_can_be_replanned(self) -> None:
        retryable = item("one", "source.pdf", status="REQUIRES_DECISION")
        retryable["selectable"] = True
        row = plan_rows(
            [retryable],
            [rule("rule-a")],
            {"root_id": "manual-root", "relative_directory": "Atlas"},
            lambda _: False,
            location=location,
        )[0]

        self.assertEqual(row["predicted_state"], "WILL_MOVE")

    def test_counts_cover_primary_states_and_keep_reasons_separate(self) -> None:
        rows = [
            {
                "predicted_state": "WILL_MOVE",
                "reason_code": None,
                "selected_rule": {"rule_id": "one"},
                "matched_rules": [{"rule_id": "one"}],
            },
            {
                "predicted_state": "WILL_MANUAL_REVIEW",
                "reason_code": "RULE_CONFLICT",
                "selected_rule": None,
                "matched_rules": [{"rule_id": "one"}, {"rule_id": "two"}],
            },
            {
                "predicted_state": "WILL_MANUAL_REVIEW",
                "reason_code": "NO_SCENARIO",
                "selected_rule": None,
                "matched_rules": [],
            },
            {
                "predicted_state": "REQUIRES_DECISION",
                "reason_code": "TARGET_OCCUPIED",
                "selected_rule": {"rule_id": "one"},
                "matched_rules": [{"rule_id": "one"}],
            },
            {
                "predicted_state": "NOT_READY",
                "reason_code": "NOT_READY",
                "selected_rule": None,
                "matched_rules": [],
            },
        ]

        self.assertEqual(
            plan_counts(rows),
            {
                "will_move": 1,
                "will_manual_review": 2,
                "requires_decision": 1,
                "not_ready": 1,
                "rule_conflicts": 1,
                "no_scenario": 1,
            },
        )

    def test_counts_keep_no_scenario_when_manual_destination_is_occupied(self) -> None:
        rows = plan_rows(
            [item("one", "unmatched.pdf")],
            [],
            {"root_id": "manual-root", "relative_directory": "Atlas"},
            lambda _: True,
            location=location,
        )

        self.assertEqual(rows[0]["reason_code"], "MANUAL_REVIEW_NAME_OCCUPIED")
        self.assertEqual(plan_counts(rows)["no_scenario"], 1)

    def test_counts_keep_rule_conflict_when_manual_destination_is_occupied(self) -> None:
        rows = plan_rows(
            [item("one", "ambiguous.pdf")],
            [
                rule("rule-a", target={"root_id": "archive-root", "relative_directory": "Atlas/A"}),
                rule("rule-b", target={"root_id": "archive-root", "relative_directory": "Atlas/B"}),
            ],
            {"root_id": "manual-root", "relative_directory": "Atlas"},
            lambda _: True,
            location=location,
        )

        self.assertEqual(rows[0]["reason_code"], "MANUAL_REVIEW_NAME_OCCUPIED")
        self.assertEqual(plan_counts(rows)["rule_conflicts"], 1)
