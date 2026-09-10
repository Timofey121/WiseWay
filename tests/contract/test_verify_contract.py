"""Executable tests for the WiseWay contract verifier.

The suite has three layers:

1. the real contract must pass every check (positive evidence);
2. deliberately corrupted contracts must fail the matching check
   (negative regression, including the original B-01 CompanyId defect);
3. individual payloads must be accepted or rejected with correct
   nullable/``oneOf``/closed-object/format/bounds semantics.
"""

from __future__ import annotations

import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from contractlib import (  # noqa: E402
    build_registry,
    iter_example_sites,
    load_contract,
    run_checks,
    validate_value,
)
from contractlib import expectations as exp  # noqa: E402

REPO_ROOT = HERE.parents[1]
CONTRACT = REPO_ROOT / "contracts" / "openapi" / "wiseway-v1.yaml"


class RealContractTests(unittest.TestCase):
    """The accepted contract must be fully valid."""

    @classmethod
    def setUpClass(cls):
        cls.document = load_contract(CONTRACT)
        cls.registry = build_registry(cls.document)
        cls.report = run_checks(cls.document, cls.registry)

    def test_every_check_passes(self):
        self.assertTrue(self.report.ok, self.report.format())

    def test_operation_count_is_33(self):
        self.assertEqual(33, exp.EXPECTED_OPERATION_COUNT)

    def test_a_meaningful_number_of_examples_is_validated(self):
        sites = list(iter_example_sites(self.document))
        self.assertGreaterEqual(len(sites), 100)
        kinds = {site.kind for site in sites}
        self.assertEqual({"media", "parameter", "header", "schema"}, kinds)


class CorruptContractTests(unittest.TestCase):
    """The verifier must detect structural corruption, not only happy paths."""

    @classmethod
    def setUpClass(cls):
        cls.document = load_contract(CONTRACT)

    def _run(self, mutate):
        document = copy.deepcopy(self.document)
        mutate(document)
        return run_checks(document)

    def _assert_fails(self, report, check_id):
        self.assertFalse(report.ok, "corrupted contract was not detected")
        self.assertIn(check_id, report.failed_check_ids, report.format())

    def test_original_invalid_company_id_path_placement(self):
        # B-01 regression: CompanyId (in: path) used on /sorting/batches,
        # which has no {company_id} variable.
        def mutate(document):
            document["paths"]["/sorting/batches"]["get"]["parameters"][0] = {
                "$ref": "#/components/parameters/CompanyId"
            }

        self._assert_fails(self._run(mutate), "OAS-PATH-001")

    def test_company_query_used_on_path_with_variable(self):
        def mutate(document):
            document["paths"]["/companies/{company_id}/dictionaries"]["parameters"] = [
                {"$ref": "#/components/parameters/CompanyIdQuery"}
            ]

        self._assert_fails(self._run(mutate), "OAS-PATH-001")

    def test_duplicate_operation_id(self):
        def mutate(document):
            document["paths"]["/roots"]["get"]["operationId"] = "getHealth"

        self._assert_fails(self._run(mutate), "OAS-OPS-001")

    def test_missing_operation_id(self):
        def mutate(document):
            del document["paths"]["/roots"]["get"]["operationId"]

        self._assert_fails(self._run(mutate), "OAS-OPS-001")

    def test_external_ref(self):
        def mutate(document):
            document["paths"]["/roots"]["get"]["responses"]["200"]["content"]["application/json"][
                "schema"
            ] = {"$ref": "other.yaml#/RootsResponse"}

        self._assert_fails(self._run(mutate), "OAS-REF-001")

    def test_unresolved_local_ref(self):
        def mutate(document):
            document["paths"]["/roots"]["get"]["responses"]["200"]["content"]["application/json"][
                "schema"
            ] = {"$ref": "#/components/schemas/DoesNotExist"}

        self._assert_fails(self._run(mutate), "OAS-REF-002")

    def test_extra_anonymous_operation(self):
        def mutate(document):
            document["paths"]["/roots"]["get"]["security"] = []

        self._assert_fails(self._run(mutate), "OAS-SEC-001")

    def test_missing_csrf_on_mutation(self):
        def mutate(document):
            document["paths"]["/dictionaries/{dictionary_id}/publish"]["post"]["parameters"] = [
                param
                for param in document["paths"]["/dictionaries/{dictionary_id}/publish"]["post"]["parameters"]
                if param.get("$ref") != "#/components/parameters/XCSRFToken"
            ]

        self._assert_fails(self._run(mutate), "OAS-SEC-002")

    def test_missing_idempotency_key(self):
        def mutate(document):
            document["paths"]["/sorting/batches"]["post"]["parameters"] = [
                param
                for param in document["paths"]["/sorting/batches"]["post"]["parameters"]
                if param.get("$ref") != "#/components/parameters/IdempotencyKey"
            ]

        self._assert_fails(self._run(mutate), "OAS-IDEM-001")

    def test_missing_request_id_header(self):
        def mutate(document):
            del document["paths"]["/health"]["get"]["responses"]["200"]["headers"]["X-Request-ID"]

        self._assert_fails(self._run(mutate), "OAS-HDR-001")

    def test_error_code_not_allowed_for_status(self):
        def mutate(document):
            document["paths"]["/health"]["get"]["responses"]["503"] = {
                "$ref": "#/components/responses/InternalError"
            }

        self._assert_fails(self._run(mutate), "OAS-ERR-001")

    def test_wrong_success_status(self):
        def mutate(document):
            responses = document["paths"]["/sorting/batches"]["post"]["responses"]
            responses["200"] = responses.pop("202")

        self._assert_fails(self._run(mutate), "OAS-SUCC-001")

    def test_open_object_schema(self):
        def mutate(document):
            del document["components"]["schemas"]["LoginRequest"]["additionalProperties"]

        self._assert_fails(self._run(mutate), "OAS-SCHEMA-001")

    def test_corrupt_embedded_example(self):
        def mutate(document):
            examples = document["paths"]["/health"]["get"]["responses"]["200"]["content"][
                "application/json"
            ]["examples"]
            examples["available"]["value"]["status"] = "down"

        self._assert_fails(self._run(mutate), "OAS-EX-001")

    def test_external_value_example(self):
        def mutate(document):
            document["components"]["examples"]["SharedAuthenticated"] = {
                "externalValue": "https://example.invalid/session.json"
            }

        self._assert_fails(self._run(mutate), "OAS-EX-002")

    # --- effective company_id enforcement (B-01 regression) --------------- #

    def test_company_query_removed_from_sorting_batches(self):
        def mutate(document):
            operation = document["paths"]["/sorting/batches"]["get"]
            operation["parameters"] = [
                param
                for param in operation["parameters"]
                if param.get("$ref") != "#/components/parameters/CompanyIdQuery"
            ]

        self._assert_fails(self._run(mutate), "OAS-PARAM-001")

    def test_company_query_removed_from_quarantine(self):
        def mutate(document):
            operation = document["paths"]["/quarantine"]["get"]
            operation["parameters"] = [
                param
                for param in operation["parameters"]
                if param.get("$ref") != "#/components/parameters/CompanyIdQuery"
            ]

        self._assert_fails(self._run(mutate), "OAS-PARAM-001")

    def test_company_query_removed_from_both(self):
        def mutate(document):
            for path in ("/sorting/batches", "/quarantine"):
                operation = document["paths"][path]["get"]
                operation["parameters"] = [
                    param
                    for param in operation["parameters"]
                    if param.get("$ref") != "#/components/parameters/CompanyIdQuery"
                ]

        self._assert_fails(self._run(mutate), "OAS-PARAM-001")

    def test_company_query_schema_unconstrained(self):
        def mutate(document):
            document["components"]["parameters"]["CompanyIdQuery"]["schema"] = {"type": "string"}

        self._assert_fails(self._run(mutate), "OAS-PARAM-001")

    def test_company_query_wrong_location(self):
        def mutate(document):
            document["components"]["parameters"]["CompanyIdQuery"]["in"] = "header"

        self._assert_fails(self._run(mutate), "OAS-PARAM-001")

    def test_company_query_not_required(self):
        def mutate(document):
            document["components"]["parameters"]["CompanyIdQuery"]["required"] = False

        self._assert_fails(self._run(mutate), "OAS-PARAM-001")

    def test_company_path_consumer_broken(self):
        def mutate(document):
            document["paths"]["/companies/{company_id}/dictionaries"]["parameters"] = []

        self._assert_fails(self._run(mutate), "OAS-PARAM-001")

    # --- security empty alternative --------------------------------------- #

    def test_security_empty_alternative_first(self):
        def mutate(document):
            document["paths"]["/roots"]["get"]["security"] = [{}, {"cookieAuth": []}]

        self._assert_fails(self._run(mutate), "OAS-SEC-001")

    def test_security_empty_alternative_last(self):
        def mutate(document):
            document["paths"]["/roots"]["get"]["security"] = [{"cookieAuth": []}, {}]

        self._assert_fails(self._run(mutate), "OAS-SEC-001")

    # --- external ref preflight must not call the third-party validator ---- #

    def test_external_ref_skips_third_party_validator(self):
        document = copy.deepcopy(self.document)
        document["paths"]["/roots"]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ] = {"$ref": "https://attacker.invalid/schema.json"}

        with mock.patch("openapi_spec_validator.validate") as spy:
            report = run_checks(document)

        self.assertFalse(
            spy.called,
            "third-party validator was invoked on a document containing non-local refs",
        )
        self.assertIn("OAS-REF-001", report.failed_check_ids, report.format())
        self.assertIn("OAS-BASIC-001", report.failed_check_ids, report.format())

    # --- exact response-status set / unreferenced component examples ------ #

    def test_missing_declared_error_status(self):
        def mutate(document):
            del document["paths"]["/roots"]["get"]["responses"]["429"]

        self._assert_fails(self._run(mutate), "OAS-RESP-001")

    def test_unused_component_example_external_value(self):
        def mutate(document):
            document["components"]["examples"]["UnusedExternal"] = {
                "externalValue": "https://example.invalid/unused.json"
            }

        self._assert_fails(self._run(mutate), "OAS-EX-002")

    def test_unreferenced_component_example(self):
        def mutate(document):
            document["components"]["examples"]["UnusedValue"] = {"value": {"anything": True}}

        self._assert_fails(self._run(mutate), "OAS-EX-002")


class PayloadSemanticsTests(unittest.TestCase):
    """Canonical schema semantics for representative payloads."""

    @classmethod
    def setUpClass(cls):
        cls.registry = build_registry(load_contract(CONTRACT))

    def errors(self, pointer, value):
        return validate_value(self.registry, pointer, value)

    # --- closed objects / required / nullable ----------------------------- #

    def test_unknown_request_field_is_rejected(self):
        errors = self.errors(
            "#/components/schemas/LoginRequest",
            {"login": "worker-atlas", "password": "synthetic-password-example", "extra": True},
        )
        self.assertTrue(any("Additional properties" in error for error in errors), errors)

    def test_missing_required_field_is_rejected(self):
        errors = self.errors("#/components/schemas/LoginRequest", {"login": "worker-atlas"})
        self.assertTrue(any("required" in error for error in errors), errors)

    def test_allowed_null_is_accepted_but_omission_and_wrong_type_are_not(self):
        pointer = "#/components/schemas/ErrorDetails"
        valid = {
            "code": "NOT_FOUND",
            "message": "Объект не найден.",
            "request_id": "request-demo-1",
            "operation_id": None,
            "retryable": False,
            "field_errors": [],
        }
        self.assertEqual([], self.errors(pointer, valid))
        without_operation_id = dict(valid)
        del without_operation_id["operation_id"]
        self.assertTrue(self.errors(pointer, without_operation_id))
        wrong_type = dict(valid)
        wrong_type["operation_id"] = 5
        self.assertTrue(self.errors(pointer, wrong_type))

    def test_invalid_enum_value_is_rejected(self):
        errors = self.errors("#/components/schemas/BatchState", "BROKEN")
        self.assertTrue(any("BROKEN" in error for error in errors), errors)
        self.assertEqual([], self.errors("#/components/schemas/BatchState", "RUNNING"))

    # --- oneOf variants --------------------------------------------------- #

    def test_selection_request_oneof_variants(self):
        pointer = "#/components/schemas/SelectionRequest"
        explicit = {
            "company_id": "company-demo-1",
            "mode": "EXPLICIT",
            "items": [{"item_id": "file-demo-1", "item_revision": 3}],
        }
        all_matching = {
            "company_id": "company-demo-1",
            "mode": "ALL_MATCHING",
            "filters": {"statuses": ["READY"], "query_text": ""},
            "expected_eligible_count": 120,
        }
        self.assertEqual([], self.errors(pointer, explicit))
        self.assertEqual([], self.errors(pointer, all_matching))
        # No variant matches.
        self.assertTrue(self.errors(pointer, {"company_id": "c", "mode": "EXPLICIT", "items": []}))
        # Contaminated payload matches neither variant.
        contaminated = dict(explicit, filters={"statuses": [], "query_text": ""})
        self.assertTrue(self.errors(pointer, contaminated))

    def test_batch_create_request_oneof_variants(self):
        pointer = "#/components/schemas/BatchCreateRequest"
        direct = {"selection_id": "selection-demo-1", "execution_mode": "DIRECT"}
        previewed = {
            "selection_id": "selection-demo-1",
            "execution_mode": "PREVIEWED",
            "preview_id": "preview-demo-1",
        }
        self.assertEqual([], self.errors(pointer, direct))
        self.assertEqual([], self.errors(pointer, previewed))
        # PREVIEWED without preview_id.
        self.assertTrue(
            self.errors(pointer, {"selection_id": "s", "execution_mode": "PREVIEWED"})
        )
        # DIRECT must not carry preview_id (closed object).
        self.assertTrue(
            self.errors(
                pointer,
                {"selection_id": "s", "execution_mode": "DIRECT", "preview_id": "preview-demo-1"},
            )
        )
        self.assertTrue(self.errors(pointer, {"selection_id": "s", "execution_mode": "RUNNING"}))

    # --- bounds and formats ----------------------------------------------- #

    def test_id_bounds(self):
        pointer = "#/components/schemas/Id"
        self.assertEqual([], self.errors(pointer, "company-demo-1"))
        self.assertTrue(self.errors(pointer, ""))
        self.assertTrue(self.errors(pointer, "a" * 97))
        self.assertTrue(self.errors(pointer, "bad/id"))
        self.assertTrue(self.errors(pointer, "with space"))

    def test_count_bounds(self):
        pointer = "#/components/schemas/Count"
        self.assertEqual([], self.errors(pointer, 0))
        self.assertEqual([], self.errors(pointer, 9007199254740991))
        self.assertTrue(self.errors(pointer, -1))
        self.assertTrue(self.errors(pointer, 9007199254740992))
        self.assertTrue(self.errors(pointer, "5"))

    def test_instant_format_and_trailing_z(self):
        pointer = "#/components/schemas/Instant"
        self.assertEqual([], self.errors(pointer, "2031-05-10T09:30:00Z"))
        self.assertTrue(self.errors(pointer, "2031-05-10T09:30:00+00:00"))
        self.assertTrue(self.errors(pointer, "2031-05-10 09:30:00Z"))
        self.assertTrue(self.errors(pointer, "2031-13-40T99:99:99Z"))

    def test_limit_bounds(self):
        pointer = "#/components/parameters/Limit/schema"
        self.assertEqual([], self.errors(pointer, 1))
        self.assertEqual([], self.errors(pointer, 100))
        self.assertTrue(self.errors(pointer, 0))
        self.assertTrue(self.errors(pointer, 101))

    def test_relative_path_bounds(self):
        pointer = "#/components/schemas/RelativeFilePath"
        self.assertEqual([], self.errors(pointer, "Incoming/atlas/invoice-2031.TXT"))
        for invalid in ("", "/abs/path", "a//b", "a\\b", "../escape", "a:b", "a/./b"):
            self.assertTrue(self.errors(pointer, invalid), f"{invalid!r} should be rejected")


class CliTests(unittest.TestCase):
    """The README entry point must run and report exit codes correctly."""

    def test_cli_passes_on_real_contract(self):
        process = subprocess.run(
            [sys.executable, str(HERE / "verify_contract.py")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, process.returncode, process.stdout + process.stderr)
        self.assertIn("RESULT: PASS", process.stdout)

    def test_cli_fails_on_corrupt_contract(self):
        document = load_contract(CONTRACT)
        document["paths"]["/health"]["get"]["operationId"] = "brokenHealth"
        with tempfile.TemporaryDirectory() as tmp:
            corrupted = Path(tmp) / "corrupt.yaml"
            corrupted.write_text(
                yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            process = subprocess.run(
                [sys.executable, str(HERE / "verify_contract.py"), str(corrupted)],
                capture_output=True,
                text=True,
            )
        self.assertEqual(1, process.returncode, process.stdout + process.stderr)
        self.assertIn("RESULT: FAIL", process.stdout)

    def test_cli_reports_missing_file(self):
        process = subprocess.run(
            [sys.executable, str(HERE / "verify_contract.py"), "does-not-exist.yaml"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(2, process.returncode)


if __name__ == "__main__":
    unittest.main()
