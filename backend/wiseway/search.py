"""Pure, generation-scoped search primitives for Wise Way.

The HTTP layer supplies a published root and items from one index generation.  This
module deliberately has no persistence or filesystem dependency so its semantics
can be tested independently of an index implementation.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
from functools import lru_cache
import re
from types import MappingProxyType
from typing import Any

from .common import ApiError, instant_sort_key


RANKING_PROFILE_VERSION = "ranking-demo-1"

# The demo schema is configuration, rather than assumptions in an HTTP handler.
# A production installation can replace this mapping with its own published schema.
DEMO_SCHEMAS: dict[str, dict[str, Any]] = {
    "schema-demo-1": {
        "schema_set_version": "schema-demo-1",
        "root_levels": (
            ("level-section", "Раздел", frozenset({"Archive"}), False),
            ("level-company", "Компания", frozenset({"Atlas", "Nova"}), False),
            ("level-project", "Проект", frozenset({"Orion_2031", "Polaris_2030"}), False),
        ),
        "tail_by_company": {
            "Atlas": (
                ("level-category", "Категория", frozenset({"Reports", "Data"}), False),
                ("level-subcategory", "Подкатегория", frozenset({"Text", "Maps"}), True),
            ),
            "Nova": (
                ("level-area", "Район", frozenset({"North", "South"}), False),
                ("level-category", "Категория", frozenset({"Reports", "Data"}), False),
                ("level-subcategory", "Подкатегория", frozenset({"Text", "Maps"}), True),
            ),
        },
    }
}

_TOKEN_SEPARATOR = re.compile(r"[\s\-_.\\/]+", re.UNICODE)
_LETTER_DIGIT_BOUNDARY = re.compile(r"(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])", re.UNICODE)
_NATURAL_CHUNKS = re.compile(r"(\d+)")


@dataclass(frozen=True)
class _Level:
    level_id: str
    level_name: str
    values: frozenset[str]
    optional: bool = False


@dataclass(frozen=True)
class _CompiledLevel:
    """A schema level reduced to immutable lookup data for an import run."""

    level_id: str
    level_name: str
    folded_values: frozenset[str]
    optional: bool = False


@dataclass(frozen=True)
class CompiledSchema:
    """Private snapshot of a schema; callers own its lifetime and invalidation."""

    schema_set_version: str
    root_levels: tuple[_CompiledLevel, ...]
    tail_by_company: MappingProxyType

    def levels(self, parsed_values: list[str]) -> tuple[_CompiledLevel, ...]:
        company = parsed_values[1] if len(parsed_values) > 1 else None
        return self.root_levels + self.tail_by_company.get(str(company).casefold(), ())


@dataclass(frozen=True)
class _Query:
    terms: tuple[tuple[str, ...], ...]
    phrases: tuple[tuple[str, ...], ...]
    applied_text: str


def _error(code: str, message: str, status: int) -> ApiError:
    return ApiError(code=code, message=message, status=status)


def _stable_id(*parts: str) -> str:
    digest = sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"marker-{digest}"


@lru_cache(maxsize=8192)
def _tokens(text: str) -> tuple[str, ...]:
    """Return case-folded tokens without Unicode normalisation.

    ``isalpha``/``isdigit`` behavior is intentional: the contract asks for the
    letter-to-digit boundary, not an ASCII-only approximation.
    """
    separated = _LETTER_DIGIT_BOUNDARY.sub(" ", text)
    return tuple(part.casefold() for part in _TOKEN_SEPARATOR.split(separated) if part)


def _extension(filename: str) -> str:
    # The final suffix is kept exactly, including original case. Dotfiles and a
    # trailing dot have no extension under the product rule.
    if filename.startswith(".") and filename.count(".") == 1:
        return ""
    stem, dot, suffix = filename.rpartition(".")
    return f".{suffix}" if dot and stem and suffix else ""


def _levels(schema: dict[str, Any], parsed_values: list[str]) -> tuple[_Level, ...]:
    try:
        base = tuple(_Level(*entry) for entry in schema["root_levels"])
        company = parsed_values[1] if len(parsed_values) > 1 else None
        tail_map = {str(key).casefold(): value for key, value in schema["tail_by_company"].items()}
        tail = tuple(_Level(*entry) for entry in tail_map.get(str(company).casefold(), ()))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid private search schema") from exc
    return base + tail


def compile_schema(schema: dict[str, Any]) -> CompiledSchema:
    """Snapshot private schema lookups once for a bounded indexing operation.

    The object deliberately has no process-wide cache: a caller that mutates a
    loaded schema must explicitly create a new snapshot.  This prevents stale
    permissions/shape validation while avoiding an unbounded cache of schemas.
    """

    try:

        def compile_level(entry: Any) -> _CompiledLevel:
            level = _Level(*entry)
            return _CompiledLevel(
                level.level_id,
                level.level_name,
                frozenset(value.casefold() for value in level.values),
                level.optional,
            )

        root_levels = tuple(compile_level(entry) for entry in schema["root_levels"])
        tail_by_company = MappingProxyType(
            {
                str(company).casefold(): tuple(compile_level(entry) for entry in entries)
                for company, entries in schema["tail_by_company"].items()
            }
        )
        return CompiledSchema(str(schema["schema_set_version"]), root_levels, tail_by_company)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid private search schema") from exc


def _marker(
    root_id: str,
    schema_version: str,
    level: _Level,
    raw_value: str | None,
    parents: Iterable[str],
    kind: str = "VALUE",
) -> dict[str, Any]:
    parent_key = "\x1e".join(parents)
    if kind == "UNRECOGNIZED":
        return {
            "marker_id": _stable_id(root_id, schema_version, level.level_id, parent_key, "unrecognized"),
            "level_id": level.level_id,
            "level_name": level.level_name,
            "raw_value": None,
            "display_value": "Не распознано",
            "kind": "UNRECOGNIZED",
        }
    assert raw_value is not None
    return {
        "marker_id": _stable_id(root_id, schema_version, level.level_id, parent_key, raw_value, "value"),
        "level_id": level.level_id,
        "level_name": level.level_name,
        "raw_value": raw_value,
        "display_value": raw_value,
        "kind": "VALUE",
    }


def _issue(level: _Level | None, code: str, message: str) -> dict[str, Any]:
    return {
        "level_id": None if level is None else level.level_id,
        "level_name": "Дополнительный уровень" if level is None else level.level_name,
        "code": code,
        "message": message,
    }


def build_item(
    root_id: str,
    display_prefix: str,
    relative_path: str,
    size_bytes: int,
    modified_at: str,
    schema: dict[str, Any],
    identity: str,
    *,
    compiled_schema: CompiledSchema | None = None,
) -> dict[str, Any]:
    """Build the public ``SearchItem`` from one index record's logical path.

    The path is relative to a configured root and must include a filename.  No
    hidden fields are attached: callers may persist their own index metadata.
    """
    clean = relative_path.replace("\\", "/").strip("/")
    parts = tuple(part for part in clean.split("/") if part)
    if not parts:
        raise ValueError("relative_path must contain a filename")
    filename = parts[-1]
    directories = parts[:-1]
    schema_version = (
        compiled_schema.schema_set_version
        if compiled_schema is not None
        else str(schema["schema_set_version"])
    )
    markers: list[dict[str, Any]] = []
    parsed_values: list[str] = []
    issue: dict[str, Any] | None = None
    position = 0

    while issue is None:
        expected = (
            compiled_schema.levels(parsed_values)
            if compiled_schema is not None
            else _levels(schema, parsed_values)
        )
        if position == len(expected):
            if position < len(directories):
                extra = _Level("level-extra-depth", "Дополнительный уровень", frozenset())
                markers.append(_marker(root_id, schema_version, extra, None, parsed_values, "UNRECOGNIZED"))
                issue = _issue(None, "UNEXPECTED_DEPTH", "В пути есть дополнительный уровень")
            break
        level = expected[position]
        if position == len(directories):
            if level.optional:
                break
            markers.append(_marker(root_id, schema_version, level, None, parsed_values, "UNRECOGNIZED"))
            issue = _issue(level, "MISSING_REQUIRED_LEVEL", "Отсутствует обязательный уровень")
            break
        value = directories[position]
        # Schema values establish the accepted shape.  Their raw casing is never
        # rewritten: ``Atlas`` and ``atlas`` therefore become distinct markers.
        allowed = (
            level.folded_values
            if compiled_schema is not None
            else {allowed.casefold() for allowed in level.values}
        )
        if value.casefold() not in allowed:
            markers.append(_marker(root_id, schema_version, level, None, parsed_values, "UNRECOGNIZED"))
            issue = _issue(level, "INVALID_LEVEL_VALUE", "Недопустимое значение уровня")
            break
        markers.append(_marker(root_id, schema_version, level, value, parsed_values))
        parsed_values.append(value)
        position += 1

    display_path = f"{display_prefix.rstrip('/')}/{clean}" if display_prefix else clean
    return {
        "item_id": identity,
        "location": {"root_id": root_id, "relative_path": clean, "display_path": display_path},
        "filename": filename,
        "markers": markers,
        "extension": _extension(filename),
        "size_bytes": size_bytes,
        "modified_at": modified_at,
        "structure_status": "UNRECOGNIZED" if issue else "VALID",
        "structure_issue": issue,
    }


def _parse_query(value: str) -> _Query:
    chunks: list[tuple[bool, str]] = []
    index = 0
    while index < len(value):
        if value[index].isspace():
            index += 1
            continue
        quoted = value[index] == '"'
        if quoted:
            closing = value.find('"', index + 1)
            if closing < 0:
                raise _error("INVALID_QUERY", "Закройте кавычку", 400)
            content = value[index + 1 : closing]
            index = closing + 1
            if index < len(value) and not value[index].isspace():
                raise _error("INVALID_QUERY", "Кавычки должны отделять фразу", 400)
        else:
            closing = index
            while closing < len(value) and not value[closing].isspace():
                if value[closing] == '"':
                    raise _error("INVALID_QUERY", "Кавычки должны отделять фразу", 400)
                closing += 1
            content = value[index:closing]
            index = closing
        token_group = _tokens(content)
        if not token_group:
            raise _error("INVALID_QUERY", "Пустая часть запроса", 400)
        chunks.append((quoted, token_group))

    terms: list[tuple[str, ...]] = []
    phrases: list[tuple[str, ...]] = []
    for quoted, group in chunks:
        target = phrases if quoted else terms
        if quoted:
            if group not in target:
                target.append(group)
        else:
            for token in group:
                singleton = (token,)
                if singleton not in target:
                    target.append(singleton)
    applied = " ".join((f'"{" ".join(group)}"' if quoted else " ".join(group)) for quoted, group in chunks)
    return _Query(tuple(terms), tuple(phrases), applied)


def _field_streams(item: dict[str, Any]) -> tuple[tuple[int, tuple[str, ...]], ...]:
    streams: list[tuple[int, tuple[str, ...]]] = [(5, _tokens(item["filename"]))]
    for marker in item["markers"]:
        if marker["kind"] != "VALUE":
            continue
        level = marker["level_id"]
        weight = 4 if level == "level-project" else 3 if level == "level-company" else 1
        streams.append((weight, _tokens(marker["raw_value"])))
    streams.append((1, _path_stream(item)))
    return tuple(stream for stream in streams if stream[1])


def _path_stream(item: dict[str, Any]) -> tuple[str, ...]:
    # Logical root prefix is deliberately excluded from matching/scoring.
    return _tokens(item["location"]["relative_path"])


def _contains_phrase(stream: tuple[str, ...], phrase: tuple[str, ...]) -> bool:
    size = len(phrase)
    return any(stream[offset : offset + size] == phrase for offset in range(len(stream) - size + 1))


def _matches_and_score(item: dict[str, Any], query: _Query) -> int | None:
    streams = _field_streams(item)
    score = 0
    for (term,) in query.terms:
        matching = [
            weight * (2 if token == term else 1)
            for weight, tokens in streams
            for token in tokens
            if token.startswith(term)
        ]
        if not matching:
            return None
        score += max(matching)
    path = _path_stream(item)
    for phrase in query.phrases:
        same_field = [weight for weight, tokens in streams if _contains_phrase(tokens, phrase)]
        crosses_path = _contains_phrase(path, phrase)
        if not same_field and not crosses_path:
            return None
        score += 2 * len(phrase) * (max(same_field) if same_field else 1)
    return score


@lru_cache(maxsize=8192)
def _natural_key(value: str) -> tuple[tuple[int, int | str], ...]:
    result: list[tuple[int, int | str]] = []
    for chunk in _NATURAL_CHUNKS.split(value):
        if not chunk:
            continue
        result.append((0, int(chunk)) if chunk.isdecimal() else (1, chunk.casefold()))
    return tuple(result)


def _path_tie(item: dict[str, Any]) -> tuple[Any, ...]:
    path = item["location"]["relative_path"]
    return (_natural_key(path), path, item["item_id"])


def _validate_context(root: dict[str, Any], request: dict[str, Any]) -> None:
    if request.get("root_id") != root.get("root_id"):
        raise _error("INVALID_MARKER_SELECTION", "Маркер относится к другому корню", 422)
    if request.get("schema_set_version") != root.get("schema_set_version"):
        raise _error("SCHEMA_VERSION_CHANGED", "Версия схемы изменилась", 409)


def _selected_chain(items: list[dict[str, Any]], selected: list[str]) -> list[dict[str, Any]]:
    if not selected:
        return items
    if len(selected) != len(set(selected)):
        raise _error("INVALID_MARKER_SELECTION", "Цепочка содержит повторный маркер", 422)
    possible = [
        item
        for item in items
        if len(item["markers"]) >= len(selected)
        and [marker["marker_id"] for marker in item["markers"][: len(selected)]] == selected
    ]
    if selected and not possible:
        raise _error("INVALID_MARKER_SELECTION", "Недопустимая цепочка маркеров", 422)
    if selected:
        all_marker_ids = {marker["marker_id"] for item in items for marker in item["markers"]}
        if selected[-1] not in all_marker_ids:
            raise _error("INVALID_MARKER_SELECTION", "Неизвестный маркер", 422)
    return possible if selected else items


def _option(marker: dict[str, Any], count: int) -> dict[str, Any]:
    return {**marker, "count": count}


def _facet(candidates: list[dict[str, Any]], selected_length: int, prefix: str) -> dict[str, Any] | None:
    grouped: dict[str, tuple[dict[str, Any], int]] = {}
    for item in candidates:
        if len(item["markers"]) <= selected_length:
            continue
        marker = item["markers"][selected_length]
        marker_id = marker["marker_id"]
        known, count = grouped.get(marker_id, (marker, 0))
        grouped[marker_id] = (known, count + 1)
    return _facet_from_groups(grouped, prefix)


def _facet_from_groups(grouped, prefix):
    if not grouped:
        return None
    choices = [
        _option(marker, count)
        for marker, count in grouped.values()
        if marker["display_value"].casefold().startswith(prefix.casefold())
    ]
    choices.sort(
        key=lambda value: (
            value["kind"] == "UNRECOGNIZED",
            _natural_key(value["display_value"]),
            value["raw_value"] or "",
            value["marker_id"],
        )
    )
    first = next(iter(grouped.values()))[0]
    return {"level_id": first["level_id"], "level_name": first["level_name"], "options": choices}


def _sort_rows(rows: list[tuple[dict[str, Any], int]], sort: dict[str, Any]) -> list[dict[str, Any]]:
    field = sort.get("field")
    direction = sort.get("direction")
    if direction not in {"ASC", "DESC"}:
        raise _error("INVALID_QUERY", "Неизвестное направление сортировки", 400)
    if field == "RELEVANCE":
        if direction != "DESC":
            raise _error("INVALID_QUERY", "RELEVANCE требует DESC", 400)
        rows.sort(key=lambda pair: (-pair[1], *_path_tie(pair[0])))
    elif field == "PATH":
        rows.sort(key=lambda pair: _path_tie(pair[0]), reverse=direction == "DESC")
    elif field == "NAME":
        rows.sort(key=lambda pair: _path_tie(pair[0]))
        rows.sort(key=lambda pair: _natural_key(pair[0]["filename"]), reverse=direction == "DESC")
    elif field == "MODIFIED_AT":
        rows.sort(key=lambda pair: _path_tie(pair[0]))
        rows.sort(key=lambda pair: instant_sort_key(pair[0]["modified_at"]), reverse=direction == "DESC")
    elif field == "SIZE":
        rows.sort(key=lambda pair: _path_tie(pair[0]))
        rows.sort(key=lambda pair: pair[0]["size_bytes"], reverse=direction == "DESC")
    else:
        raise _error("INVALID_QUERY", "Неизвестная сортировка", 400)
    return [row for row, _ in rows]


def _freshness(root: dict[str, Any]) -> dict[str, str]:
    indexed_at = root["indexed_at"]
    return {"indexed_at": indexed_at, "last_successful_sync_at": indexed_at, "status": "CURRENT"}


def search(
    root: dict[str, Any],
    items: list[dict[str, Any]],
    request: dict[str, Any],
    limit: int = 100,
    *,
    prepared=None,
) -> dict[str, Any]:
    """Return a contract-shaped search response for one published generation."""
    _validate_context(root, request)
    if prepared is not None and prepared.items is not items:
        raise ValueError("Prepared search index belongs to another snapshot")
    if limit < 1:
        raise ValueError("limit must be positive")
    query = _parse_query(str(request.get("query_text", "")))
    selected = list(request.get("selected_marker_ids", []))
    if prepared is not None:
        selected_markers = prepared.selected_markers(selected)
    else:
        candidates = _selected_chain(items, selected)
        selected_markers = candidates[0]["markers"][: len(selected)] if selected and candidates else []
    is_idle = not selected and not query.terms and not query.phrases
    if request.get("sort", {}).get("field") == "RELEVANCE" and not (query.terms or query.phrases):
        raise _error("INVALID_QUERY", "RELEVANCE требует непустой текст", 400)
    matching: list[tuple[dict[str, Any], int]] = []
    if not is_idle:
        if prepared is not None:
            matching = prepared.match(query, selected)
        else:
            for item in candidates:
                score = _matches_and_score(item, query)
                if score is not None:
                    matching.append((item, score))
    prefix = str(request.get("facet_prefix", ""))
    if is_idle and prepared is not None:
        next_facet = prepared.next_facet(selected, prefix)
    else:
        facet_candidates = candidates if is_idle else [item for item, _ in matching]
        next_facet = _facet(facet_candidates, len(selected), prefix)
    if is_idle:
        return {
            "request_state_id": request["request_state_id"],
            "mode": "IDLE",
            "root_id": root["root_id"],
            "schema_set_version": root["schema_set_version"],
            "index_generation": root["index_generation"],
            "ranking_profile_version": RANKING_PROFILE_VERSION,
            "applied_query_text": "",
            "selected_markers": [],
            "total": None,
            "returned_count": 0,
            "result_limit": limit,
            "limited": False,
            "items": [],
            "next_facet": next_facet,
            "freshness": _freshness(root),
        }
    total = len(matching)
    returned = (
        prepared.sort_rows(matching, request.get("sort", {}), limit)
        if prepared is not None
        else _sort_rows(matching, request.get("sort", {}))[:limit]
    )
    return {
        "request_state_id": request["request_state_id"],
        "mode": "RESULTS",
        "root_id": root["root_id"],
        "schema_set_version": root["schema_set_version"],
        "index_generation": root["index_generation"],
        "ranking_profile_version": RANKING_PROFILE_VERSION,
        "applied_query_text": query.applied_text,
        "selected_markers": selected_markers,
        "total": total,
        "returned_count": len(returned),
        "result_limit": limit,
        "limited": total > limit,
        "items": returned,
        "next_facet": next_facet,
        "freshness": _freshness(root),
    }


def facet(
    root: dict[str, Any], items: list[dict[str, Any]], request: dict[str, Any], *, prepared=None
) -> dict[str, Any]:
    """Return the independent facet response; it never changes table state."""
    _validate_context(root, request)
    if prepared is not None and prepared.items is not items:
        raise ValueError("Prepared search index belongs to another snapshot")
    query = _parse_query(str(request.get("query_text", "")))
    selected = list(request.get("selected_marker_ids", []))
    prefix = str(request.get("facet_prefix", ""))
    if prepared is not None and not query.terms and not query.phrases:
        result = prepared.next_facet(selected, prefix)
    elif prepared is not None:
        matching = [item for item, _ in prepared.match(query, selected)]
        result = _facet(matching, len(selected), prefix)
    else:
        candidates = _selected_chain(items, selected)
        matching = [item for item in candidates if _matches_and_score(item, query) is not None]
        result = _facet(matching, len(selected), prefix)
    return {
        "request_state_id": request["request_state_id"],
        "root_id": root["root_id"],
        "schema_set_version": root["schema_set_version"],
        "index_generation": root["index_generation"],
        "facet": result,
    }
