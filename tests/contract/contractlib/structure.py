"""Structural OpenAPI checks for the WiseWay contract.

The checks assert the accepted public structure: maintained OpenAPI 3.1
validation, reference integrity, operation inventory and path matching,
security/CSRF/idempotency sets, response headers, and HTTP/error-code
relationships.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import expectations as exp
from .loading import RefError, deref, iter_refs, resolve_pointer
from .report import Report

METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "trace")
PATH_VAR_RE = re.compile(r"\{([^}]+)\}")


def operations(document: Dict[str, Any]) -> Iterable[Tuple[str, str, Dict[str, Any], Dict[str, Any]]]:
    """Yield ``(path, method, operation, path_item)`` for every operation."""
    for path, path_item in document.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method in METHODS and isinstance(operation, dict):
                yield path, method, operation, path_item


def resolved_parameters(document, operation, path_item) -> List[Dict[str, Any]]:
    """Merge path-item and operation parameters, resolving ``$ref`` entries."""
    merged: List[Dict[str, Any]] = []
    for source in (path_item.get("parameters", []), operation.get("parameters", [])):
        for param in source or []:
            try:
                merged.append(deref(document, param))
            except RefError:
                merged.append({})
    return merged


def parameter_names(document, operation, path_item, location: Optional[str] = None) -> List[str]:
    names = []
    for param in resolved_parameters(document, operation, path_item):
        if location is not None and param.get("in") != location:
            continue
        name = param.get("name")
        if isinstance(name, str):
            names.append(name)
    return names


def response_for(document, operation, status: str) -> Dict[str, Any]:
    try:
        return deref(document, operation.get("responses", {}).get(status))
    except RefError:
        return {}


def error_codes_from_schema(document, schema: Any) -> set:
    """Collect ``error.code`` enum values declared by a response schema."""
    codes: set = set()
    if not isinstance(schema, dict):
        return codes
    if set(schema.keys()) == {"$ref"}:
        try:
            return error_codes_from_schema(document, resolve_pointer(document, schema["$ref"]))
        except RefError:
            return codes
    for sub in schema.get("allOf", []) or []:
        codes |= error_codes_from_schema(document, sub)
    try:
        codes |= set(schema["properties"]["error"]["properties"]["code"]["enum"])
    except (KeyError, TypeError):
        pass
    return codes


def example_values(document, response: Dict[str, Any]) -> List[Any]:
    content = response.get("content", {})
    media = content.get("application/json", {}) if isinstance(content, dict) else {}
    values: List[Any] = []
    if not isinstance(media, dict):
        return values
    if "example" in media:
        values.append(media["example"])
    for example in (media.get("examples") or {}).values():
        if not isinstance(example, dict):
            continue
        if "$ref" in example:
            try:
                resolved = resolve_pointer(document, example["$ref"])
            except RefError:
                continue
            if isinstance(resolved, dict) and "value" in resolved:
                values.append(resolved["value"])
        elif "value" in example:
            values.append(example["value"])
    return values


def _in_conditional(ptr: str) -> bool:
    return any(token in ("if", "then", "else", "not") for token in ptr.split("/"))


# --------------------------------------------------------------------------- #
# Individual checks
# --------------------------------------------------------------------------- #

def external_refs(document: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Return ``(holder, ref)`` for every non-local ``$ref`` in the document."""
    return [(holder, ref) for holder, ref in iter_refs(document) if not ref.startswith("#")]


def check_maintained_validator(document: Dict[str, Any], report: Report) -> None:
    check = report.check("OAS-BASIC-001", "OpenAPI 3.1.1 accepted by maintained validator")
    # Preflight: never hand attacker-controlled external references to a
    # third-party validator, which could resolve them over the network.
    disallowed = external_refs(document)
    if disallowed:
        check.add(
            f"skipped third-party validation because {len(disallowed)} non-local $ref "
            "must be rejected first",
            disallowed[0][0],
        )
        return
    try:
        from openapi_spec_validator import validate
    except ImportError as exc:  # pragma: no cover - dependency missing
        check.add(f"openapi-spec-validator is not installed: {exc}")
        return
    try:
        validate(document)
    except Exception as exc:  # noqa: BLE001 - report validator message verbatim
        check.add(f"{type(exc).__name__}: {exc}")


def check_document_basics(document: Dict[str, Any], report: Report) -> None:
    check = report.check("OAS-BASIC-002", "Document metadata, server prefix and global security")
    if document.get("openapi") != "3.1.1":
        check.add(f"openapi must be 3.1.1, found {document.get('openapi')!r}")
    info = document.get("info") or {}
    if not info.get("version"):
        check.add("info.version is missing")
    if not info.get("title"):
        check.add("info.title is missing")
    servers = document.get("servers") or []
    if not any(isinstance(s, dict) and s.get("url") == "/api/v1" for s in servers):
        check.add("servers must declare the /api/v1 prefix")
    if document.get("security") != [{"cookieAuth": []}]:
        check.add(f"global security must be [{{cookieAuth: []}}], found {document.get('security')!r}")
    scheme = (document.get("components", {}).get("securitySchemes", {}) or {}).get("cookieAuth")
    if not isinstance(scheme, dict):
        check.add("components.securitySchemes.cookieAuth is missing")
    else:
        if scheme.get("type") != "apiKey" or scheme.get("in") != "cookie":
            check.add("cookieAuth must be an apiKey cookie security scheme")
        if scheme.get("name") != "wiseway_session":
            check.add(f"cookieAuth cookie must be wiseway_session, found {scheme.get('name')!r}")


def check_refs(document: Dict[str, Any], report: Report) -> None:
    external = report.check("OAS-REF-001", "No external $ref values")
    unresolved = report.check("OAS-REF-002", "Every local $ref resolves")
    for holder, ref in iter_refs(document):
        if not ref.startswith("#"):
            external.add(f"non-local reference {ref!r}", holder)
            continue
        try:
            resolve_pointer(document, ref)
        except RefError as exc:
            unresolved.add(str(exc), holder)


def check_operations(document: Dict[str, Any], report: Report) -> None:
    inventory = report.check(
        "OAS-OPS-001", f"Exactly {exp.EXPECTED_OPERATION_COUNT} unique operationIds"
    )
    found: Dict[Tuple[str, str], str] = {}
    seen_ids: Dict[str, str] = {}
    for path, method, operation, _ in operations(document):
        operation_id = operation.get("operationId")
        if not operation_id:
            inventory.add("operation is missing operationId", f"{method.upper()} {path}")
            continue
        if operation_id in seen_ids:
            inventory.add(
                f"duplicate operationId {operation_id!r} (also at {seen_ids[operation_id]})",
                f"{method.upper()} {path}",
            )
        seen_ids[operation_id] = f"{method.upper()} {path}"
        found[(method, path)] = operation_id

    if len(found) != exp.EXPECTED_OPERATION_COUNT:
        inventory.add(
            f"expected {exp.EXPECTED_OPERATION_COUNT} operations, found {len(found)}"
        )
    for key, expected_id in exp.EXPECTED_OPERATIONS.items():
        actual = found.get(key)
        if actual is None:
            inventory.add(f"missing expected operation {expected_id!r}", f"{key[0].upper()} {key[1]}")
        elif actual != expected_id:
            inventory.add(f"expected operationId {expected_id!r}, found {actual!r}", f"{key[0].upper()} {key[1]}")
    for key, actual in found.items():
        if key not in exp.EXPECTED_OPERATIONS:
            inventory.add(f"unexpected operation {actual!r}", f"{key[0].upper()} {key[1]}")


def check_path_matching(document: Dict[str, Any], report: Report) -> None:
    check = report.check("OAS-PATH-001", "Path template variables match path parameters")
    for path, method, operation, path_item in operations(document):
        variables = set(PATH_VAR_RE.findall(path))
        path_params = {}
        for param in resolved_parameters(document, operation, path_item):
            if param.get("in") != "path":
                continue
            name = param.get("name")
            if not isinstance(name, str):
                check.add("path parameter without a name", f"{method.upper()} {path}")
                continue
            path_params[name] = param
        for variable in variables:
            if variable not in path_params:
                check.add(
                    f"path variable {{{variable}}} has no matching path parameter",
                    f"{method.upper()} {path}",
                )
            elif path_params[variable].get("required") is not True:
                check.add(
                    f"path parameter {variable!r} must be required",
                    f"{method.upper()} {path}",
                )
        for name, param in path_params.items():
            if name not in variables:
                check.add(
                    f"path parameter {name!r} is not present in the path template",
                    f"{method.upper()} {path}",
                )
            if param.get("required") is not True:
                check.add(
                    f"path parameter {name!r} must be required",
                    f"{method.upper()} {path}",
                )


def _effective_security(document, operation):
    if "security" in operation:
        return operation.get("security")
    return document.get("security")


def _is_exact_cookie_auth(entries) -> bool:
    return (
        isinstance(entries, list)
        and len(entries) == 1
        and isinstance(entries[0], dict)
        and set(entries[0].keys()) == {"cookieAuth"}
        and entries[0].get("cookieAuth") == []
    )


def check_security(document: Dict[str, Any], report: Report) -> None:
    check = report.check(
        "OAS-SEC-001",
        "Only health and login are anonymous; protected operations are exactly cookieAuth",
    )
    anonymous: set = set()
    for path, method, operation, _ in operations(document):
        operation_id = operation.get("operationId", f"{method.upper()} {path}")
        explicit = operation.get("security")
        if explicit == []:
            anonymous.add(operation_id)
            continue
        effective = _effective_security(document, operation)
        # An empty alternative ({}) anywhere would make the operation anonymous.
        if not _is_exact_cookie_auth(effective):
            check.add(
                f"protected security must be exactly {exp.EXPECTED_SECURITY_REQUIREMENT!r} "
                f"(no empty alternative), found {effective!r}",
                operation_id,
            )
    if anonymous != exp.EXPECTED_ANONYMOUS:
        check.add(
            f"anonymous operations must be {sorted(exp.EXPECTED_ANONYMOUS)}, found {sorted(anonymous)}"
        )


def check_company_parameters(document: Dict[str, Any], report: Report) -> None:
    check = report.check(
        "OAS-PARAM-001",
        "Effective required company_id query/path parameters with Id schema",
    )
    for path, method, operation, path_item in operations(document):
        operation_id = operation.get("operationId", f"{method.upper()} {path}")
        company_params = [
            param
            for param in resolved_parameters(document, operation, path_item)
            if param.get("name") == "company_id"
        ]
        if operation_id in exp.EXPECTED_COMPANY_QUERY_OPS:
            expected_location = "query"
        elif operation_id in exp.EXPECTED_COMPANY_PATH_OPS:
            expected_location = "path"
        else:
            if company_params:
                check.add("unexpected company_id parameter", operation_id)
            continue
        if len(company_params) != 1:
            check.add(
                f"expected exactly one company_id parameter, found {len(company_params)}",
                operation_id,
            )
            continue
        param = company_params[0]
        if param.get("in") != expected_location:
            check.add(
                f"company_id must be in {expected_location!r}, found {param.get('in')!r}",
                operation_id,
            )
        if param.get("required") is not True:
            check.add("company_id must be required", operation_id)
        if param.get("schema") != exp.COMPANY_ID_SCHEMA:
            check.add(
                f"company_id schema must be {exp.COMPANY_ID_SCHEMA!r}, found {param.get('schema')!r}",
                operation_id,
            )



def check_csrf_and_idempotency(document: Dict[str, Any], report: Report) -> None:
    csrf = report.check("OAS-SEC-002", "Exact X-CSRF-Token operation set")
    idem = report.check("OAS-IDEM-001", "Exact Idempotency-Key operation set")

    csrf_ops: set = set()
    idem_ops: set = set()
    for path, method, operation, path_item in operations(document):
        operation_id = operation.get("operationId", f"{method.upper()} {path}")
        for param in resolved_parameters(document, operation, path_item):
            if param.get("name") == "X-CSRF-Token":
                csrf_ops.add(operation_id)
                if param.get("in") != "header" or param.get("required") is not True:
                    csrf.add("X-CSRF-Token must be a required header parameter", operation_id)
            if param.get("name") == "Idempotency-Key":
                idem_ops.add(operation_id)
                if param.get("in") != "header" or param.get("required") is not True:
                    idem.add("Idempotency-Key must be a required header parameter", operation_id)

    if csrf_ops != exp.EXPECTED_CSRF:
        csrf.add(
            f"CSRF operations must be {sorted(exp.EXPECTED_CSRF)}, found {sorted(csrf_ops)}"
        )
    for path, method, operation, _ in operations(document):
        operation_id = operation.get("operationId")
        if operation_id in csrf_ops and method not in ("post", "put", "patch", "delete"):
            csrf.add("CSRF token declared on a non-mutating method", operation_id)

    if idem_ops != exp.EXPECTED_IDEMPOTENCY:
        idem.add(
            f"idempotency operations must be {sorted(exp.EXPECTED_IDEMPOTENCY)}, "
            f"found {sorted(idem_ops)}"
        )


def check_response_headers(document: Dict[str, Any], report: Report) -> None:
    check = report.check("OAS-HDR-001", "Responses declare X-Request-ID and no-store Cache-Control")
    for path, method, operation, _ in operations(document):
        operation_id = operation.get("operationId", f"{method.upper()} {path}")
        for status, _raw in operation.get("responses", {}).items():
            response = response_for(document, operation, status)
            headers = response.get("headers", {}) if isinstance(response, dict) else {}
            if "X-Request-ID" not in headers:
                check.add(f"response {status} is missing X-Request-ID", operation_id)
            if "Cache-Control" not in headers:
                check.add(f"response {status} is missing Cache-Control", operation_id)
            else:
                try:
                    cache_header = deref(document, headers["Cache-Control"])
                except RefError:
                    cache_header = {}
                schema = cache_header.get("schema", {}) if isinstance(cache_header, dict) else {}
                if schema.get("const") != "no-store":
                    check.add(
                        f"response {status} Cache-Control must be no-store",
                        operation_id,
                    )
            if status == "429" and "Retry-After" not in headers:
                check.add(f"response 429 is missing Retry-After", operation_id)


def check_http_error_relationships(document: Dict[str, Any], report: Report) -> None:
    check = report.check("OAS-ERR-001", "Declared error codes match their HTTP status")
    for path, method, operation, _ in operations(document):
        operation_id = operation.get("operationId", f"{method.upper()} {path}")
        for status in operation.get("responses", {}):
            if status.startswith("2"):
                continue
            allowed = exp.HTTP_ERROR_CODES.get(status)
            if allowed is None:
                check.add(f"unexpected error status {status}", operation_id)
                continue
            response = response_for(document, operation, status)
            schema = (
                response.get("content", {}).get("application/json", {}).get("schema")
                if isinstance(response, dict)
                else None
            )
            codes = error_codes_from_schema(document, schema)
            if not codes:
                check.add(f"response {status} declares no error.code enum", operation_id)
            for code in sorted(codes - allowed):
                check.add(f"error.code {code} is not allowed for HTTP {status}", operation_id)
            for value in example_values(document, response):
                code = None
                if isinstance(value, dict) and isinstance(value.get("error"), dict):
                    code = value["error"].get("code")
                if code is not None and code not in codes:
                    check.add(
                        f"example error.code {code!r} is outside the response enum for {status}",
                        operation_id,
                    )


def check_success_statuses(document: Dict[str, Any], report: Report) -> None:
    check = report.check("OAS-SUCC-001", "Expected success status per operation")
    for path, method, operation, _ in operations(document):
        operation_id = operation.get("operationId")
        expected = exp.EXPECTED_SUCCESS_STATUS.get(operation_id)
        actual = [s for s in operation.get("responses", {}) if s.startswith("2")]
        if expected is None:
            continue
        if actual != [expected]:
            check.add(f"expected success status {expected}, found {actual}", operation_id)


def check_request_bodies(document: Dict[str, Any], report: Report) -> None:
    check = report.check("OAS-BODY-001", "Request bodies present and required where declared")
    for path, method, operation, _ in operations(document):
        operation_id = operation.get("operationId")
        request_body = operation.get("requestBody")
        expects_body = operation_id in exp.EXPECTED_REQUEST_BODY
        if not expects_body:
            if request_body is not None:
                check.add("unexpected request body", operation_id)
            continue
        if not isinstance(request_body, dict):
            check.add("expected a request body", operation_id)
            continue
        if request_body.get("required") is not True:
            check.add("request body must be required", operation_id)
        content = request_body.get("content", {})
        if "application/json" not in content:
            check.add("request body must use application/json", operation_id)


def check_closed_objects(document: Dict[str, Any], report: Report) -> None:
    check = report.check("OAS-SCHEMA-001", "Data object schemas are closed (additionalProperties: false)")
    schemas = document.get("components", {}).get("schemas", {}) or {}
    for name, schema in schemas.items():
        for ptr, node in _walk_schemas(schema, f"#/components/schemas/{name}"):
            if node.get("type") == "object" and not _in_conditional(ptr):
                if node.get("additionalProperties") is not False:
                    check.add(
                        "object schema must set additionalProperties: false",
                        ptr,
                    )


def _walk_schemas(node: Any, ptr: str):
    if not isinstance(node, dict):
        return
    yield ptr, node
    for key in ("properties", "patternProperties", "$defs"):
        child = node.get(key)
        if isinstance(child, dict):
            for name, value in child.items():
                yield from _walk_schemas(value, f"{ptr}/{key}/{name}")
    for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        child = node.get(key)
        if isinstance(child, list):
            for index, value in enumerate(child):
                yield from _walk_schemas(value, f"{ptr}/{key}/{index}")
    for key in ("items", "additionalProperties", "not", "if", "then", "else", "contains"):
        child = node.get(key)
        if isinstance(child, dict):
            yield from _walk_schemas(child, f"{ptr}/{key}")


def check_canonical_primitives(document: Dict[str, Any], report: Report) -> None:
    check = report.check("OAS-SCHEMA-002", "Canonical primitive constraints (Id/Revision/Count/Instant/paths)")
    schemas = document.get("components", {}).get("schemas", {}) or {}
    for name, expected in exp.CANONICAL_PRIMITIVES.items():
        schema = schemas.get(name)
        if not isinstance(schema, dict):
            check.add(f"schema {name} is missing")
            continue
        for key, value in expected.items():
            if schema.get(key) != value:
                check.add(f"{name}.{key} must be {value!r}, found {schema.get(key)!r}")
    for name in ("Id",):
        pattern = schemas.get(name, {}).get("pattern", "")
        if not re.search(r"A-Za-z0-9", pattern):
            check.add(f"{name}.pattern must restrict to ASCII [A-Za-z0-9-]")
    for name in ("RelativeDirectory", "RelativeFilePath"):
        pattern = schemas.get(name, {}).get("pattern", "")
        if not pattern:
            check.add(f"{name}.pattern is missing")
    instant_pattern = schemas.get("Instant", {}).get("pattern", "")
    if not instant_pattern.endswith("Z$"):
        check.add("Instant.pattern must require a trailing Z")

    parameters = document.get("components", {}).get("parameters", {}) or {}
    expectations = {
        "CompanyId": {"in": "path", "name": "company_id", "required": True},
        "CompanyIdQuery": {"in": "query", "name": "company_id", "required": True},
        "XCSRFToken": {"in": "header", "name": "X-CSRF-Token", "required": True},
        "IdempotencyKey": {"in": "header", "name": "Idempotency-Key", "required": True},
    }
    for name, expected in expectations.items():
        param = parameters.get(name)
        if not isinstance(param, dict):
            check.add(f"parameter {name} is missing")
            continue
        for key, value in expected.items():
            if param.get(key) != value:
                check.add(f"parameter {name}.{key} must be {value!r}, found {param.get(key)!r}")
    for name in ("CompanyId", "CompanyIdQuery"):
        schema = parameters.get(name, {}).get("schema") if isinstance(parameters.get(name), dict) else None
        if schema != exp.COMPANY_ID_SCHEMA:
            check.add(
                f"parameter {name}.schema must be {exp.COMPANY_ID_SCHEMA!r}, found {schema!r}"
            )
    limit = parameters.get("Limit", {}).get("schema", {}) if isinstance(parameters.get("Limit"), dict) else {}
    if limit.get("minimum") != 1 or limit.get("maximum") != 100:
        check.add("Limit must be integer 1..100")
    idem_schema = parameters.get("IdempotencyKey", {}).get("schema", {})
    if idem_schema.get("format") != "uuid":
        check.add("Idempotency-Key schema must declare format: uuid")


def check_response_statuses(document: Dict[str, Any], report: Report) -> None:
    check = report.check(
        "OAS-RESP-001", "Exact declared HTTP response-status set per operation"
    )
    for path, method, operation, _ in operations(document):
        operation_id = operation.get("operationId", f"{method.upper()} {path}")
        expected = exp.EXPECTED_RESPONSE_STATUSES.get(operation_id)
        if expected is None:
            check.add("operation has no reviewed response-status baseline", operation_id)
            continue
        actual = set(operation.get("responses", {}).keys())
        missing = set(expected) - actual
        extra = actual - set(expected)
        if missing:
            check.add(f"missing declared response statuses {sorted(missing)}", operation_id)
        if extra:
            check.add(f"unexpected declared response statuses {sorted(extra)}", operation_id)


def run_structure_checks(document: Dict[str, Any], report: Report) -> None:
    # Reference preflight first: never let a third-party validator fetch a
    # non-local reference.
    check_refs(document, report)
    check_maintained_validator(document, report)
    check_document_basics(document, report)
    check_operations(document, report)
    check_path_matching(document, report)
    check_company_parameters(document, report)
    check_security(document, report)
    check_csrf_and_idempotency(document, report)
    check_response_headers(document, report)
    check_http_error_relationships(document, report)
    check_success_statuses(document, report)
    check_response_statuses(document, report)
    check_request_bodies(document, report)
    check_closed_objects(document, report)
    check_canonical_primitives(document, report)
