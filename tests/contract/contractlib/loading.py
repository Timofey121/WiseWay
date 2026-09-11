"""Contract loading, JSON-pointer and ``$ref`` helpers.

These helpers are intentionally generic: LT-02.2 semantic checks and WP-03
fixture validation can reuse them to resolve the same canonical schema graph.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterator, List, Sequence, Tuple

import yaml

# Stable logical URI under which the whole OpenAPI document is registered for
# JSON Schema resolution.  Only local fragments (``#/...``) are expected.
CONTRACT_URI = "urn:wiseway:openapi-contract"


class RefError(Exception):
    """Raised when a ``$ref`` cannot be resolved or is not a local fragment."""


def load_contract(path: str | Path) -> Dict[str, Any]:
    """Parse the OpenAPI YAML document into plain Python data."""
    with open(path, "r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    if not isinstance(document, dict):
        raise ValueError(f"Contract at {path!s} did not parse to a mapping")
    return document


def escape_token(token: Any) -> str:
    """Escape a single JSON Pointer reference token (RFC 6901)."""
    return str(token).replace("~", "~0").replace("/", "~1")


def pointer(parts: Sequence[Any]) -> str:
    """Build a local JSON Pointer fragment from path parts."""
    return "#" + "".join("/" + escape_token(part) for part in parts)


def parse_pointer(fragment: str) -> Tuple[Any, ...]:
    """Parse a local JSON Pointer fragment back into unescaped path parts."""
    if fragment in ("", "#"):
        return ()
    if fragment.startswith("#/"):
        fragment = fragment[2:]
    elif fragment.startswith("#"):
        fragment = fragment[1:].lstrip("/")
    return tuple(
        raw.replace("~1", "/").replace("~0", "~") for raw in fragment.split("/")
    )


def iter_refs(node: Any, parts: Tuple[Any, ...] = ()) -> Iterator[Tuple[str, str]]:
    """Yield ``(holder_pointer, ref_string)`` for every ``$ref`` in *node*."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                yield pointer(parts + ("$ref",)), value
            yield from iter_refs(value, parts + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from iter_refs(value, parts + (index,))


def resolve_pointer(document: Any, ref: str) -> Any:
    """Resolve a local JSON Pointer fragment such as ``#/components/schemas/Id``."""
    if not isinstance(ref, str) or not ref.startswith("#"):
        raise RefError(f"External or invalid reference is not allowed: {ref!r}")
    fragment = ref[1:]
    if fragment in ("", "/"):
        return document
    if not fragment.startswith("/"):
        raise RefError(f"Unsupported reference form: {ref!r}")
    current = document
    for raw_token in fragment[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        elif isinstance(current, dict):
            if token not in current:
                raise RefError(f"Reference {ref!r} cannot resolve token {token!r}")
            current = current[token]
        else:
            raise RefError(f"Reference {ref!r} traverses a non-container value")
    return current


def deref(document: Any, node: Any, _seen: frozenset = frozenset()) -> Any:
    """Follow a single ``$ref`` wrapper (recursively, with cycle protection)."""
    if isinstance(node, dict) and set(node.keys()) == {"$ref"}:
        ref = node["$ref"]
        if ref in _seen:
            raise RefError(f"Circular reference detected at {ref!r}")
        return deref(document, resolve_pointer(document, ref), _seen | {ref})
    return node


def build_registry(document: Dict[str, Any]):
    """Register the whole document so JSON Schema ``$ref`` resolves locally."""
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    resource = Resource(contents=document, specification=DRAFT202012)
    return Registry().with_resource(CONTRACT_URI, resource)


def iter_schema_nodes(node: Any, parts: Tuple[Any, ...] = ()) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """Yield every Schema Object reachable from *node* with its pointer.

    The traversal understands the OpenAPI/JSON Schema 2020-12 applicator
    keywords used by the WiseWay contract.
    """
    if not isinstance(node, dict):
        return
    yield pointer(parts), node

    map_children = ("properties", "patternProperties", "$defs", "dependentSchemas")
    single_children = (
        "items",
        "additionalProperties",
        "contains",
        "propertyNames",
        "not",
        "if",
        "then",
        "else",
    )
    list_children = ("allOf", "anyOf", "oneOf", "prefixItems")

    for key in map_children:
        child = node.get(key)
        if isinstance(child, dict):
            for name, value in child.items():
                yield from iter_schema_nodes(value, parts + (key, name))
    for key in list_children:
        child = node.get(key)
        if isinstance(child, list):
            for index, value in enumerate(child):
                yield from iter_schema_nodes(value, parts + (key, index))
    for key in single_children:
        child = node.get(key)
        if isinstance(child, dict):
            yield from iter_schema_nodes(child, parts + (key,))


def all_refs(document: Dict[str, Any]) -> List[Tuple[str, str]]:
    return list(iter_refs(document))
