"""Schema validation helpers with correct OpenAPI 3.1 / JSON Schema 2020-12
semantics (nullable unions, ``oneOf``, closed objects, formats).

Reusable by LT-02.2 semantic checks and WP-03 fixture validation: pass a
schema pointer (for example ``#/components/schemas/SelectionRequest``) and an
instance, and receive formatted errors.
"""

from __future__ import annotations

from typing import Any, Dict, List

from jsonschema import Draft202012Validator, FormatChecker

from .loading import CONTRACT_URI, build_registry

# ``date-time``, ``uuid`` and friends are only enforced when a format checker
# is supplied.  This is what makes the contract's ``format`` declarations real.
FORMAT_CHECKER = FormatChecker()


def make_validator(registry, schema_pointer: str) -> Draft202012Validator:
    """Return a validator for the schema located at *schema_pointer*."""
    schema = {"$ref": f"{CONTRACT_URI}{schema_pointer}"}
    return Draft202012Validator(
        schema,
        registry=registry,
        format_checker=FORMAT_CHECKER,
    )


def schema_validator(document: Dict[str, Any], schema_pointer: str) -> Draft202012Validator:
    """Convenience wrapper that builds a registry from *document*."""
    return make_validator(build_registry(document), schema_pointer)


def iter_errors(registry, schema_pointer: str, instance: Any) -> List[Any]:
    """Return validation errors sorted by instance path."""
    validator = make_validator(registry, schema_pointer)
    return sorted(
        validator.iter_errors(instance),
        key=lambda error: (list(error.absolute_path), error.message),
    )


def validate_value(registry, schema_pointer: str, instance: Any) -> List[str]:
    """Validate *instance* and return human-readable error strings."""
    return [format_error(error) for error in iter_errors(registry, schema_pointer, instance)]


def format_error(error: Any) -> str:
    path = "/".join(str(part) for part in error.absolute_path)
    return f"{path or '<root>'}: {error.message}"
