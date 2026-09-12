from __future__ import annotations

import unittest

from wiseway.common import ApiError
from wiseway.search import DEMO_SCHEMAS, build_item, facet, search


ROOT = {
    "root_id": "root-demo-1",
    "label": "Demo archive",
    "display_prefix": "DEMO:/SandboxRoot",
    "schema_set_version": "schema-demo-1",
    "index_generation": "generation-1",
    "indexed_at": "2026-01-01T00:00:00Z",
}


def item(item_id: str, path: str) -> dict:
    return build_item(
        ROOT["root_id"],
        ROOT["display_prefix"],
        path,
        size_bytes=0,
        modified_at="2026-01-01T00:00:00Z",
        schema=DEMO_SCHEMAS[ROOT["schema_set_version"]],
        identity=item_id,
    )


def request(query_text: str = "", markers: list[str] | None = None, **extra: object) -> dict:
    value = {
        "request_state_id": "state-1",
        "root_id": ROOT["root_id"],
        "schema_set_version": ROOT["schema_set_version"],
        "selected_marker_ids": markers or [],
        "query_text": query_text,
        "sort": {
            "field": "RELEVANCE" if query_text else "PATH",
            "direction": "DESC" if query_text else "ASC",
        },
        "facet_prefix": "",
    }
    value.update(extra)
    return value


class SearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.atlas_main = item("a-main", "Archive/Atlas/Orion_2031/Reports/Atlas-Main.pdf")
        self.atlas_final = item("a-final", "Archive/Atlas/Orion_2031/Reports/Atlas-Final-Main.pdf")
        self.atlas_maintenance = item("a-maint", "Archive/Atlas/Orion_2031/Reports/Atlas-Maintenance.pdf")
        self.nova = item("nova", "Archive/Nova/Polaris_2030/North/Data/Nova 10.xlsx")

    def test_build_item_parses_markers_extension_and_project_year_tokens(self) -> None:
        value = item("report", "Archive/Atlas/Orion_2031/Reports/Report.v2.PDF")
        self.assertEqual(value["filename"], "Report.v2.PDF")
        self.assertEqual(value["extension"], ".PDF")
        self.assertEqual(
            [marker["raw_value"] for marker in value["markers"]],
            ["Archive", "Atlas", "Orion_2031", "Reports"],
        )
        self.assertEqual(value["structure_status"], "VALID")
        self.assertIsNone(value["structure_issue"])
        self.assertEqual(
            set(value),
            {
                "item_id",
                "location",
                "filename",
                "markers",
                "extension",
                "size_bytes",
                "modified_at",
                "structure_status",
                "structure_issue",
            },
        )

    def test_modified_at_sort_normalizes_fractional_utc_precision_and_keeps_path_ties(self) -> None:
        whole_a = item("whole-a", "Archive/Atlas/Orion_2031/Reports/a.txt")
        whole_b = item("whole-b", "Archive/Atlas/Orion_2031/Reports/b.txt")
        later = item("fraction", "Archive/Atlas/Orion_2031/Reports/c.txt")
        whole_a["modified_at"] = "2026-01-01T00:00:00Z"
        whole_b["modified_at"] = "2026-01-01T00:00:00.000000Z"
        later["modified_at"] = "2026-01-01T00:00:00.001Z"
        rows = [later, whole_b, whole_a]

        ascending = search(ROOT, rows, request("txt", sort={"field": "MODIFIED_AT", "direction": "ASC"}))
        descending = search(ROOT, rows, request("txt", sort={"field": "MODIFIED_AT", "direction": "DESC"}))

        self.assertEqual([row["item_id"] for row in ascending["items"]], ["whole-a", "whole-b", "fraction"])
        self.assertEqual([row["item_id"] for row in descending["items"]], ["fraction", "whole-a", "whole-b"])

    def test_build_item_marks_first_bad_level_and_does_not_guess_children(self) -> None:
        value = item("bad", "Archive/Atlas/UnknownProject/Reports/lost.pdf")
        self.assertEqual(value["structure_status"], "UNRECOGNIZED")
        self.assertEqual([marker["raw_value"] for marker in value["markers"]], ["Archive", "Atlas", None])
        self.assertEqual(value["structure_issue"]["code"], "INVALID_LEVEL_VALUE")

    def test_token_boundaries_include_separators_and_letter_digit_transition(self) -> None:
        values = [item("tokens", "Archive/Atlas/Orion_2031/Reports/Report.v2.pdf")]
        self.assertEqual(search(ROOT, values, request("atlas 203"))["total"], 1)
        self.assertEqual(search(ROOT, values, request("report 2"))["total"], 1)

    def test_case_variants_are_distinct_raw_markers_but_search_casefolds(self) -> None:
        upper = item("upper", "Archive/Atlas/Orion_2031/Reports/upper.pdf")
        lower = item("lower", "Archive/atlas/Orion_2031/Reports/lower.pdf")
        self.assertNotEqual(upper["markers"][1]["marker_id"], lower["markers"][1]["marker_id"])
        self.assertEqual(search(ROOT, [upper, lower], request("atlas"))["total"], 2)

    def test_marker_ids_are_root_scoped_and_foreign_markers_are_rejected(self) -> None:
        foreign_root = {**ROOT, "root_id": "root-demo-2"}
        local = self.atlas_main
        foreign = build_item(
            foreign_root["root_id"],
            foreign_root["display_prefix"],
            "Archive/Atlas/Orion_2031/Reports/foreign.pdf",
            0,
            "2026-01-01T00:00:00Z",
            DEMO_SCHEMAS[foreign_root["schema_set_version"]],
            "foreign",
        )
        self.assertNotEqual(local["markers"][0]["marker_id"], foreign["markers"][0]["marker_id"])
        with self.assertRaises(ApiError) as caught:
            search(ROOT, [local], request("", [foreign["markers"][0]["marker_id"]]))
        self.assertEqual(caught.exception.code, "INVALID_MARKER_SELECTION")

    def test_phrase_requires_adjacent_complete_tokens(self) -> None:
        values = [self.atlas_main, self.atlas_final, self.atlas_maintenance]
        result = search(ROOT, values, request('"atlas main"'))
        self.assertEqual([row["item_id"] for row in result["items"]], ["a-main"])

    def test_root_only_is_idle_but_supplies_first_facet(self) -> None:
        result = search(ROOT, [self.atlas_main, self.nova], request())
        self.assertEqual(result["mode"], "IDLE")
        self.assertIsNone(result["total"])
        self.assertEqual(result["items"], [])
        self.assertEqual(result["next_facet"]["level_id"], "level-section")
        self.assertEqual([x["raw_value"] for x in result["next_facet"]["options"]], ["Archive"])

    def test_marker_chain_is_continuous_and_filters_with_and(self) -> None:
        values = [self.atlas_main, self.nova]
        root_result = search(ROOT, values, request("atlas"))
        archive_marker = root_result["next_facet"]["options"][0]["marker_id"]
        after_archive = search(ROOT, values, request("atlas", [archive_marker]))
        atlas_marker = after_archive["next_facet"]["options"][0]["marker_id"]
        chosen = search(ROOT, values, request("main", [archive_marker, atlas_marker]))
        self.assertEqual([row["item_id"] for row in chosen["items"]], ["a-main"])

    def test_facet_prefix_does_not_change_result_set_or_counts(self) -> None:
        values = [self.atlas_main, self.nova]
        base = search(ROOT, values, request("", facet_prefix=""))
        narrowed = search(ROOT, values, request("", facet_prefix="arc"))
        self.assertEqual(base["mode"], narrowed["mode"])
        self.assertEqual(base["total"], narrowed["total"])
        self.assertEqual(
            base["next_facet"]["options"][0]["count"], narrowed["next_facet"]["options"][0]["count"]
        )

    def test_score_deduplicates_filename_and_company_match(self) -> None:
        matching = item("matching", "Archive/Atlas/Orion_2031/Reports/Atlas.pdf")
        prefix = item("prefix", "Archive/Nova/Orion_2031/Reports/Atlasical.pdf")
        result = search(ROOT, [prefix, matching], request("atlas"))
        self.assertEqual([row["item_id"] for row in result["items"]], ["matching", "prefix"])

    def test_natural_path_breaks_equal_scores(self) -> None:
        ten = item("ten", "Archive/Atlas/Orion_2031/Reports/Report 10.pdf")
        two = item("two", "Archive/Atlas/Orion_2031/Reports/Report 2.pdf")
        result = search(ROOT, [ten, two], request("report"))
        self.assertEqual([row["item_id"] for row in result["items"]], ["two", "ten"])

    def test_unrecognized_marker_is_terminal(self) -> None:
        invalid = item("invalid", "Archive/Atlas/Bad/Reports/file.pdf")
        result = search(
            ROOT,
            [invalid],
            request("", [invalid["markers"][0]["marker_id"], invalid["markers"][1]["marker_id"]]),
        )
        self.assertEqual(result["next_facet"]["options"][0]["kind"], "UNRECOGNIZED")
        marker = result["next_facet"]["options"][0]["marker_id"]
        final = search(
            ROOT,
            [invalid],
            request("", [invalid["markers"][0]["marker_id"], invalid["markers"][1]["marker_id"], marker]),
        )
        self.assertIsNone(final["next_facet"])

    def test_deduped_query_terms_do_not_change_order(self) -> None:
        once = search(ROOT, [self.atlas_main, self.atlas_final], request("atlas"))
        repeated = search(ROOT, [self.atlas_main, self.atlas_final], request("atlas atlas"))
        self.assertEqual([x["item_id"] for x in once["items"]], [x["item_id"] for x in repeated["items"]])

    def test_facet_endpoint_has_separate_response_shape(self) -> None:
        result = facet(
            ROOT,
            [self.atlas_main],
            {
                "request_state_id": "facet-1",
                "root_id": ROOT["root_id"],
                "schema_set_version": ROOT["schema_set_version"],
                "selected_marker_ids": [],
                "query_text": "atlas",
                "facet_prefix": "",
            },
        )
        self.assertEqual(result["request_state_id"], "facet-1")
        self.assertEqual(result["index_generation"], "generation-1")
        self.assertEqual(result["facet"]["level_id"], "level-section")

    def test_relevance_without_tokens_is_rejected(self) -> None:
        with self.assertRaises(ApiError) as caught:
            search(ROOT, [self.atlas_main], request("", sort={"field": "RELEVANCE", "direction": "DESC"}))
        self.assertEqual(caught.exception.code, "INVALID_QUERY")

    def test_quotes_and_whitespace_follow_the_strict_query_grammar(self) -> None:
        result = search(ROOT, [self.atlas_main], request('  "atlas   main"  '))
        self.assertEqual(result["applied_query_text"], '"atlas main"')
        with self.assertRaises(ApiError) as caught:
            search(ROOT, [self.atlas_main], request('"atlas main'))
        self.assertEqual(caught.exception.code, "INVALID_QUERY")

    def test_unsupported_boolean_words_are_plain_search_terms(self) -> None:
        candidate = item("operator", "Archive/Atlas/Orion_2031/Reports/OR-notes.pdf")
        self.assertEqual(search(ROOT, [candidate], request("or"))["total"], 1)

    def test_logical_root_prefix_is_not_a_searchable_path_part(self) -> None:
        self.assertEqual(search(ROOT, [self.atlas_main], request("sandbox"))["total"], 0)


if __name__ == "__main__":
    unittest.main()
