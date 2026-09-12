"""Canonical expectations derived from the WiseWay specifications.

These constants encode the accepted public contract (``contracts/openapi/wiseway-v1.yaml``)
so that the executable verifier can detect structural drift.  They describe
*what the contract must look like*, not new business behaviour.
"""

from __future__ import annotations

from typing import Dict, Set, Tuple

# (method, path) -> operationId. Exactly 33 operations.
EXPECTED_OPERATIONS: Dict[Tuple[str, str], str] = {
    ("get", "/health"): "getHealth",
    ("post", "/auth/login"): "login",
    ("get", "/session"): "getSession",
    ("post", "/auth/logout"): "logout",
    ("get", "/app-config"): "getAppConfig",
    ("get", "/roots"): "listRoots",
    ("get", "/companies"): "listCompanies",
    ("post", "/search"): "searchFiles",
    ("post", "/search/facet"): "getSearchFacet",
    ("get", "/companies/{company_id}/target-directories"): "listTargetDirectories",
    ("post", "/companies/{company_id}/target-directories/resolve"): "resolveTargetDirectory",
    ("get", "/companies/{company_id}/dictionaries"): "listDictionaries",
    ("post", "/companies/{company_id}/dictionaries"): "createDictionary",
    ("get", "/dictionaries/{dictionary_id}"): "getDictionary",
    ("put", "/dictionaries/{dictionary_id}/draft"): "replaceDictionaryDraft",
    ("get", "/dictionaries/{dictionary_id}/versions"): "listDictionaryVersions",
    ("get", "/dictionaries/{dictionary_id}/versions/{version_id}"): "getDictionaryVersion",
    ("post", "/dictionaries/{dictionary_id}/restore-draft"): "restoreDictionaryDraft",
    ("post", "/dictionaries/{dictionary_id}/simulate"): "createDictionarySimulation",
    ("get", "/simulations/{simulation_id}"): "getSimulation",
    ("post", "/dictionaries/{dictionary_id}/publish"): "publishDictionary",
    ("post", "/sorting/queue/query"): "querySortingQueue",
    ("post", "/sorting/selections"): "createSortingSelection",
    ("post", "/sorting/previews"): "createSortingPreview",
    ("get", "/sorting/previews/{preview_id}"): "getSortingPreview",
    ("post", "/sorting/batches"): "createSortingBatch",
    ("get", "/sorting/batches"): "listSortingBatches",
    ("get", "/sorting/batches/{batch_id}"): "getSortingBatch",
    ("get", "/quarantine"): "listQuarantineItems",
    ("post", "/quarantine/{quarantine_id}/return"): "returnQuarantineItem",
    ("post", "/audit/query"): "queryAuditEvents",
    ("get", "/audit/updates"): "getAuditUpdates",
    ("get", "/audit/actors"): "listAuditActors",
}

EXPECTED_OPERATION_COUNT = len(EXPECTED_OPERATIONS)

# API section 2: only /health and /auth/login are anonymous.
EXPECTED_ANONYMOUS: Set[str] = {"getHealth", "login"}

# The accepted security requirement for every protected operation.  An empty
# alternative ({}) would silently make the operation anonymous and is rejected.
EXPECTED_SECURITY_REQUIREMENT = [{"cookieAuth": []}]

# Operations whose effective company_id parameter is a required query parameter
# (B-01 normalized placement) and whose effective company_id is a path
# parameter (paths that actually contain {company_id}).
EXPECTED_COMPANY_QUERY_OPS: Set[str] = {"listSortingBatches", "listQuarantineItems"}
EXPECTED_COMPANY_PATH_OPS: Set[str] = {
    "listTargetDirectories",
    "resolveTargetDirectory",
    "listDictionaries",
    "createDictionary",
}
COMPANY_ID_SCHEMA = {"$ref": "#/components/schemas/Id"}

# Reviewed authoritative declared HTTP response-status set per operation
# (includes success and every declared error).  This is a regression baseline
# taken from the accepted contract, not read back from the runtime document.
EXPECTED_RESPONSE_STATUSES: Dict[str, frozenset] = {
    "getHealth": frozenset({"200", "403", "422", "500", "503"}),
    "login": frozenset({"200", "401", "403", "422", "429", "500", "503"}),
    "getSession": frozenset({"200", "401", "403", "422", "429", "500", "503"}),
    "logout": frozenset({"204", "401", "403", "422", "429", "500", "503"}),
    "getAppConfig": frozenset({"200", "401", "403", "422", "429", "500", "503"}),
    "listRoots": frozenset({"200", "401", "403", "422", "429", "500", "503"}),
    "listCompanies": frozenset({"200", "401", "403", "422", "429", "500", "503"}),
    "searchFiles": frozenset({"200", "400", "401", "403", "409", "422", "429", "500", "503"}),
    "getSearchFacet": frozenset({"200", "400", "401", "403", "409", "422", "429", "500", "503"}),
    "listTargetDirectories": frozenset({"200", "401", "403", "404", "422", "429", "500", "503"}),
    "resolveTargetDirectory": frozenset({"200", "401", "403", "404", "422", "429", "500", "503"}),
    "listDictionaries": frozenset({"200", "401", "403", "404", "422", "429", "500", "503"}),
    "createDictionary": frozenset({"201", "401", "403", "404", "409", "422", "429", "500", "503"}),
    "getDictionary": frozenset({"200", "401", "403", "404", "422", "429", "500", "503"}),
    "replaceDictionaryDraft": frozenset({"200", "401", "403", "404", "409", "422", "429", "500", "503"}),
    "listDictionaryVersions": frozenset({"200", "401", "403", "404", "422", "429", "500", "503"}),
    "getDictionaryVersion": frozenset({"200", "401", "403", "404", "422", "429", "500", "503"}),
    "restoreDictionaryDraft": frozenset({"200", "401", "403", "404", "409", "422", "429", "500", "503"}),
    "createDictionarySimulation": frozenset({"201", "401", "403", "404", "409", "422", "429", "500", "503"}),
    "getSimulation": frozenset({"200", "401", "403", "404", "422", "429", "500", "503"}),
    "publishDictionary": frozenset({"201", "401", "403", "404", "409", "422", "429", "500", "503"}),
    "querySortingQueue": frozenset({"200", "401", "403", "422", "429", "500", "503"}),
    "createSortingSelection": frozenset({"201", "401", "403", "409", "422", "429", "500", "503"}),
    "createSortingPreview": frozenset({"201", "401", "403", "404", "409", "422", "429", "500", "503"}),
    "getSortingPreview": frozenset({"200", "401", "403", "404", "422", "429", "500", "503"}),
    "createSortingBatch": frozenset({"202", "401", "403", "404", "409", "422", "429", "500", "503"}),
    "listSortingBatches": frozenset({"200", "401", "403", "422", "429", "500", "503"}),
    "getSortingBatch": frozenset({"200", "401", "403", "404", "422", "429", "500", "503"}),
    "listQuarantineItems": frozenset({"200", "401", "403", "422", "429", "500", "503"}),
    "returnQuarantineItem": frozenset({"200", "401", "403", "404", "409", "422", "429", "500", "503"}),
    "queryAuditEvents": frozenset({"200", "401", "403", "422", "429", "500", "503"}),
    "getAuditUpdates": frozenset({"200", "401", "403", "422", "429", "500", "503"}),
    "listAuditActors": frozenset({"200", "401", "403", "422", "429", "500", "503"}),
}


# API section 2: every state-changing request after login carries X-CSRF-Token.
# Search and audit/query are reads and must not require it.
EXPECTED_CSRF: Set[str] = {
    "logout",
    "createDictionary",
    "replaceDictionaryDraft",
    "restoreDictionaryDraft",
    "createDictionarySimulation",
    "publishDictionary",
    "createSortingSelection",
    "createSortingPreview",
    "createSortingBatch",
    "returnQuarantineItem",
}

# API section 2: exactly publish/batch/return require Idempotency-Key.
EXPECTED_IDEMPOTENCY: Set[str] = {
    "publishDictionary",
    "createSortingBatch",
    "returnQuarantineItem",
}

# Expected single 2xx success status per operation.
EXPECTED_SUCCESS_STATUS: Dict[str, str] = {
    "getHealth": "200",
    "login": "200",
    "getSession": "200",
    "logout": "204",
    "getAppConfig": "200",
    "listRoots": "200",
    "listCompanies": "200",
    "searchFiles": "200",
    "getSearchFacet": "200",
    "listTargetDirectories": "200",
    "resolveTargetDirectory": "200",
    "listDictionaries": "200",
    "createDictionary": "201",
    "getDictionary": "200",
    "replaceDictionaryDraft": "200",
    "listDictionaryVersions": "200",
    "getDictionaryVersion": "200",
    "restoreDictionaryDraft": "200",
    "createDictionarySimulation": "201",
    "getSimulation": "200",
    "publishDictionary": "201",
    "querySortingQueue": "200",
    "createSortingSelection": "201",
    "createSortingPreview": "201",
    "getSortingPreview": "200",
    "createSortingBatch": "202",
    "listSortingBatches": "200",
    "getSortingBatch": "200",
    "listQuarantineItems": "200",
    "returnQuarantineItem": "200",
    "queryAuditEvents": "200",
    "getAuditUpdates": "200",
    "listAuditActors": "200",
}

# Operations that must declare an application/json request body.
EXPECTED_REQUEST_BODY: Set[str] = {
    "login",
    "searchFiles",
    "getSearchFacet",
    "resolveTargetDirectory",
    "createDictionary",
    "replaceDictionaryDraft",
    "restoreDictionaryDraft",
    "createDictionarySimulation",
    "publishDictionary",
    "querySortingQueue",
    "createSortingSelection",
    "createSortingPreview",
    "createSortingBatch",
    "returnQuarantineItem",
    "queryAuditEvents",
}

# API section 11: allowed error.code values per HTTP status.
HTTP_ERROR_CODES: Dict[str, Set[str]] = {
    "400": {"INVALID_QUERY"},
    "401": {"LOGIN_FAILED", "UNAUTHENTICATED"},
    "403": {"FORBIDDEN", "CSRF_FAILED"},
    "404": {"NOT_FOUND"},
    "409": {
        "DRAFT_VERSION_CONFLICT",
        "DICTIONARY_NAME_CONFLICT",
        "QUARANTINE_VERSION_CONFLICT",
        "STALE_SIMULATION",
        "STALE_PREVIEW",
        "SELECTION_EXPIRED",
        "SELECTION_CHANGED",
        "SCHEMA_VERSION_CHANGED",
        "ROOT_NOT_READY",
        "RULE_CONFLICT",
        "NO_SCENARIO_ACK_REQUIRED",
        "ORIGINAL_PATH_OCCUPIED",
        "RECOVERY_REQUIRED",
        "IDEMPOTENCY_KEY_REUSED",
        "INVALID_STATE",
    },
    "422": {
        "VALIDATION_ERROR",
        "INVALID_MARKER_SELECTION",
        "INVALID_TARGET",
        "PATH_OUTSIDE_ROOT",
        "EMPTY_SELECTION",
        "BATCH_LIMIT_EXCEEDED",
    },
    "429": {"RATE_LIMITED"},
    "500": {"INTERNAL_ERROR"},
    "503": {"SEARCH_UNAVAILABLE", "SERVICE_UNAVAILABLE"},
}

# Canonical primitive constraints (API section 2).
CANONICAL_PRIMITIVES: Dict[str, Dict[str, object]] = {
    "Id": {"type": "string", "minLength": 1, "maxLength": 96},
    "Revision": {"type": "integer", "minimum": 0},
    "Count": {"type": "integer", "minimum": 0, "maximum": 9007199254740991},
    "Instant": {"type": "string", "format": "date-time"},
    "RelativeDirectory": {"type": "string", "minLength": 1, "maxLength": 4096},
    "RelativeFilePath": {"type": "string", "minLength": 1, "maxLength": 4096},
}
