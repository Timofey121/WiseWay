"""Embedded example enumeration and schema validation.

Every request/response/parameter/header/schema example in the contract is
validated against its canonical schema using JSON Schema 2020-12 semantics
with format checking, so nullable unions, ``oneOf`` and closed objects are
enforced exactly as published.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .loading import (
    RefError,
    escape_token,
    iter_refs,
    iter_schema_nodes,
    parse_pointer,
    pointer,
    resolve_pointer,
)
from .report import Report
from .schemas import validate_value


@dataclass
class ExampleSite:
    """A single embedded example and the schema it must satisfy."""

    kind: str
    pointer: str
    label: str
    schema_pointer: str
    value: Any = None
    ref: Optional[str] = None
    external: bool = False


def _walk_media(document: Any, node: Any, parts: Tuple[Any, ...], out: List[Tuple[str, Dict[str, Any]]]) -> None:
    if isinstance(node, dict):
        content = node.get("content")
        if isinstance(content, dict):
            for media, media_obj in content.items():
                if isinstance(media_obj, dict):
                    out.append((pointer(parts + ("content", media)), media_obj))
        for key, value in node.items():
            _walk_media(document, value, parts + (key,), out)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _walk_media(document, value, parts + (index,), out)


def _walk_parameters(document: Any, node: Any, parts: Tuple[Any, ...], out: List[Tuple[str, Dict[str, Any]]]) -> None:
    if isinstance(node, dict):
        if parts == ("components", "parameters"):
            for name, param in node.items():
                if isinstance(param, dict) and "$ref" not in param:
                    out.append((pointer(parts + (name,)), param))
        params = node.get("parameters")
        if isinstance(params, list):
            for index, param in enumerate(params):
                if isinstance(param, dict) and "$ref" not in param:
                    out.append((pointer(parts + ("parameters", index)), param))
        for key, value in node.items():
            _walk_parameters(document, value, parts + (key,), out)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _walk_parameters(document, value, parts + (index,), out)


def _walk_headers(document: Any, node: Any, parts: Tuple[Any, ...], out: List[Tuple[str, Dict[str, Any]]]) -> None:
    if isinstance(node, dict):
        if parts == ("components", "headers"):
            for name, header in node.items():
                if isinstance(header, dict) and "$ref" not in header:
                    out.append((pointer(parts + (name,)), header))
        headers = node.get("headers")
        if isinstance(headers, dict):
            for name, header in headers.items():
                if isinstance(header, dict) and "$ref" not in header:
                    out.append((pointer(parts + ("headers", name)), header))
        for key, value in node.items():
            if key == "headers":
                continue
            _walk_headers(document, value, parts + (key,), out)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _walk_headers(document, value, parts + (index,), out)


def _schema_roots(document: Dict[str, Any]):
    schemas = document.get("components", {}).get("schemas", {}) or {}
    for name, schema in schemas.items():
        yield pointer(("components", "schemas", name)), schema

    media: List[Tuple[str, Dict[str, Any]]] = []
    _walk_media(document, document, (), media)
    for media_ptr, media_obj in media:
        if isinstance(media_obj.get("schema"), dict):
            yield media_ptr + "/schema", media_obj["schema"]

    params: List[Tuple[str, Dict[str, Any]]] = []
    _walk_parameters(document, document, (), params)
    for param_ptr, param in params:
        if isinstance(param.get("schema"), dict):
            yield param_ptr + "/schema", param["schema"]

    headers: List[Tuple[str, Dict[str, Any]]] = []
    _walk_headers(document, document, (), headers)
    for header_ptr, header in headers:
        if isinstance(header.get("schema"), dict):
            yield header_ptr + "/schema", header["schema"]


def _examples_in(container: Dict[str, Any], container_ptr: str, schema_ptr: str, kind: str, label: str) -> Iterator[ExampleSite]:
    if "example" in container:
        yield ExampleSite(
            kind=kind,
            pointer=container_ptr + "/example",
            label=f"{label} example",
            schema_pointer=schema_ptr,
            value=container["example"],
        )
    examples = container.get("examples")
    if isinstance(examples, dict):
        for name, example in examples.items():
            example_ptr = f"{container_ptr}/examples/{escape_token(name)}"
            if not isinstance(example, dict):
                yield ExampleSite(
                    kind=kind,
                    pointer=example_ptr,
                    label=f"{label} example {name}",
                    schema_pointer=schema_ptr,
                    value=example,
                )
                continue
            if "$ref" in example:
                yield ExampleSite(
                    kind=kind,
                    pointer=example_ptr,
                    label=f"{label} example {name}",
                    schema_pointer=schema_ptr,
                    ref=example["$ref"],
                )
            elif "externalValue" in example:
                yield ExampleSite(
                    kind=kind,
                    pointer=example_ptr,
                    label=f"{label} example {name}",
                    schema_pointer=schema_ptr,
                    external=True,
                )
            elif "value" in example:
                yield ExampleSite(
                    kind=kind,
                    pointer=example_ptr + "/value",
                    label=f"{label} example {name}",
                    schema_pointer=schema_ptr,
                    value=example["value"],
                )


def _schema_level_examples(schema: Dict[str, Any], schema_ptr: str) -> Iterator[ExampleSite]:
    if "example" in schema:
        yield ExampleSite(
            kind="schema",
            pointer=schema_ptr + "/example",
            label="schema example",
            schema_pointer=schema_ptr,
            value=schema["example"],
        )
    examples = schema.get("examples")
    if isinstance(examples, list):
        for index, value in enumerate(examples):
            yield ExampleSite(
                kind="schema",
                pointer=f"{schema_ptr}/examples/{index}",
                label="schema example",
                schema_pointer=schema_ptr,
                value=value,
            )


def iter_example_sites(document: Dict[str, Any]) -> Iterator[ExampleSite]:
    """Yield every embedded example with its canonical schema pointer."""
    seen: set = set()

    media: List[Tuple[str, Dict[str, Any]]] = []
    _walk_media(document, document, (), media)
    for media_ptr, media_obj in media:
        if isinstance(media_obj.get("schema"), dict):
            for site in _examples_in(media_obj, media_ptr, media_ptr + "/schema", "media", media_ptr):
                if site.pointer not in seen:
                    seen.add(site.pointer)
                    yield site

    params: List[Tuple[str, Dict[str, Any]]] = []
    _walk_parameters(document, document, (), params)
    for param_ptr, param in params:
        if isinstance(param.get("schema"), dict):
            for site in _examples_in(param, param_ptr, param_ptr + "/schema", "parameter", param_ptr):
                if site.pointer not in seen:
                    seen.add(site.pointer)
                    yield site

    headers: List[Tuple[str, Dict[str, Any]]] = []
    _walk_headers(document, document, (), headers)
    for header_ptr, header in headers:
        if isinstance(header.get("schema"), dict):
            for site in _examples_in(header, header_ptr, header_ptr + "/schema", "header", header_ptr):
                if site.pointer not in seen:
                    seen.add(site.pointer)
                    yield site

    for root_ptr, root_schema in _schema_roots(document):
        for schema_ptr, schema in iter_schema_nodes(root_schema, parse_pointer(root_ptr)):
            for site in _schema_level_examples(schema, schema_ptr):
                if site.pointer not in seen:
                    seen.add(site.pointer)
                    yield site


def _resolve_example_value(document: Dict[str, Any], site: ExampleSite) -> Tuple[Any, Optional[str]]:
    if site.ref is not None:
        try:
            resolved = resolve_pointer(document, site.ref)
        except RefError as exc:
            return None, str(exc)
        if not isinstance(resolved, dict) or "value" not in resolved:
            return None, f"example reference {site.ref!r} has no value"
        return resolved["value"], None
    return site.value, None


def _external_value_pointers(node: Any, parts: Tuple[Any, ...] = ()) -> Iterator[str]:
    """Yield pointers of every ``externalValue`` keyword in the document."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "externalValue":
                yield pointer(parts + ("externalValue",))
            yield from _external_value_pointers(value, parts + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _external_value_pointers(value, parts + (index,))


def _component_example_status(document: Dict[str, Any]) -> Tuple[set, set]:
    """Return ``(referenced, unreferenced)`` component-example names."""
    component_examples = document.get("components", {}).get("examples", {}) or {}
    names = set(component_examples.keys())
    referenced = set()
    for _holder, ref in iter_refs(document):
        prefix = "#/components/examples/"
        if ref.startswith(prefix):
            referenced.add(ref[len(prefix):])
    return referenced & names, names - referenced


def run_example_checks(document: Dict[str, Any], report: Report, registry) -> None:
    integrity = report.check(
        "OAS-EX-002",
        "Example references resolve, no externalValue, no unreferenced component examples",
    )
    validation = report.check("OAS-EX-001", "Every embedded example validates against its schema")

    # externalValue is never allowed, including on unused component examples.
    for external_ptr in _external_value_pointers(document):
        integrity.add("externalValue is not allowed", external_ptr)

    # Every component example must be reachable from a schema-bound site,
    # otherwise it cannot be schema-validated at all.
    _referenced, unreferenced = _component_example_status(document)
    for name in sorted(unreferenced):
        integrity.add(
            "component example is not referenced by any schema-bound example site "
            "and therefore cannot be validated",
            f"#/components/examples/{name}",
        )

    count = 0
    for site in iter_example_sites(document):
        count += 1
        if site.external:
            integrity.add("externalValue is not allowed", site.pointer)
            continue
        value, error = _resolve_example_value(document, site)
        if error is not None:
            integrity.add(error, site.pointer)
            continue
        try:
            errors = validate_value(registry, site.schema_pointer, value)
        except Exception as exc:  # noqa: BLE001 - surface resolver problems as failures
            validation.add(
                f"cannot validate against {site.schema_pointer}: {type(exc).__name__}: {exc}",
                site.pointer,
            )
            continue
        for message in errors:
            validation.add(f"{message} (schema {site.schema_pointer})", site.pointer)

    report.examples_validated = count
    if count == 0:
        validation.add("no embedded examples were found")

