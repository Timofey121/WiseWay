"""Persistent, generation-scoped SQLite FTS5 search index.

The public search contract deliberately remains in :mod:`wiseway.search`.
This module stores its exact token stream in FTS5-safe ASCII words, so SQLite's
own Unicode tokenizer cannot change casefolding or punctuation semantics.
"""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
import sqlite3
from time import monotonic
from typing import Any, Iterable

from .common import ApiError, instant_sort_key, utc
from .search import (
    RANKING_PROFILE_VERSION,
    _NATURAL_CHUNKS,
    _error,
    _parse_query,
    _tokens,
    _validate_context,
)


_SENTINEL = "s"
_COLUMNS = (("filename", 5), ("project", 4), ("company", 3), ("markers", 1), ("path", 1))
_JOINED_CLAUSE_LIMIT = 16
_SEARCH_DEADLINE_SECONDS = 30.0
_PROGRESS_HANDLER_STEPS = 1000


def _encoded_token(token: str) -> str:
    # x makes a token that starts with a letter; hex makes all following input
    # ASCII.  This prevents unicode61 from applying any second tokenization.
    return "x" + token.encode("utf-8").hex()


def _encoded_stream(tokens: Iterable[str]) -> str:
    return " ".join(_encoded_token(token) for token in tokens)


def _generation_token(generation_id: str) -> str:
    return "g" + sha256(generation_id.encode("utf-8")).hexdigest()


def _bytes_successor(prefix: bytes) -> bytes:
    """Exclusive upper bound for a non-empty BLOB prefix range."""
    for offset in range(len(prefix) - 1, -1, -1):
        if prefix[offset] != 0xFF:
            return prefix[:offset] + bytes((prefix[offset] + 1,))
    return prefix + b"\x00"


def _natural_blob(value: str) -> bytes:
    """Binary order equivalent to search._natural_key for valid text values."""
    result = bytearray()

    def escaped(value: str) -> bytes:
        # Preserve ordinary UTF-8 lexicographic ordering while making a NUL
        # unambiguous: 00 00 terminates a chunk; 00 ff encodes U+0000.
        return value.encode("utf-8").replace(b"\x00", b"\x00\xff")

    for chunk in _NATURAL_CHUNKS.split(value):
        if not chunk:
            continue
        if chunk.isdecimal():
            # int() is the same normalisation used by _natural_key and accepts
            # every Unicode decimal digit, while str() gives sortable ASCII.
            magnitude = str(int(chunk))
            result.extend(b"\x01")
            result.extend(len(magnitude).to_bytes(4, "big"))
            result.extend(magnitude.encode("ascii"))
        else:
            result.extend(b"\x02")
            result.extend(escaped(chunk.casefold()))
        result.extend(b"\x00\x00")
    return bytes(result)


def _columns(item: dict[str, Any]) -> tuple[str, str, str, str, str]:
    buckets: dict[str, list[str]] = {"project": [], "company": [], "markers": []}
    for marker in item["markers"]:
        if marker["kind"] != "VALUE":
            continue
        target = (
            "project"
            if marker["level_id"] == "level-project"
            else "company"
            if marker["level_id"] == "level-company"
            else "markers"
        )
        stream = _encoded_stream(_tokens(marker["raw_value"]))
        if stream:
            buckets[target].append(stream)

    # Every marker is a distinct logical field.  A sentinel blocks FTS phrase
    # matches across their boundary; it is unreachable from encoded user text.
    def joined(name: str) -> str:
        return f" {_SENTINEL} ".join(buckets[name])

    return (
        _encoded_stream(_tokens(item["filename"])),
        joined("project"),
        joined("company"),
        joined("markers"),
        _encoded_stream(_tokens(item["location"]["relative_path"])),
    )


def create_generation(tx, root: dict[str, Any], generation_id: str) -> None:
    """Create an invisible BUILDING generation in the caller's short write unit."""
    tx.connection.execute(
        "INSERT INTO search_generations(generation_id,root_id,state,created_at) VALUES(?,?,?,?)",
        (generation_id, root["root_id"], "BUILDING", utc()),
    )


def add_items(tx, generation_id: str, rows: Iterable[dict[str, Any]]) -> int:
    """Append one bounded caller batch.  ``rows`` may be a generator."""
    state = tx.connection.execute(
        "SELECT state FROM search_generations WHERE generation_id=?", (generation_id,)
    ).fetchone()
    if state is None or state[0] != "BUILDING":
        raise ValueError("search generation is not BUILDING")
    next_no = tx.connection.execute(
        "SELECT COALESCE(MAX(item_no) + 1, 0) FROM search_items WHERE generation_id=?", (generation_id,)
    ).fetchone()[0]
    count = 0
    for item in rows:
        body = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        cursor = tx.connection.execute(
            "INSERT INTO search_items(generation_id,item_no,item_id,body,filename_key,path_key,relative_path,modified_at,modified_key,size_bytes) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                generation_id,
                next_no,
                item["item_id"],
                body,
                _natural_blob(item["filename"]),
                _natural_blob(item["location"]["relative_path"]),
                item["location"]["relative_path"],
                item["modified_at"],
                instant_sort_key(item["modified_at"]),
                item["size_bytes"],
            ),
        )
        row_id = cursor.lastrowid
        parent = None
        for depth, marker in enumerate(item["markers"]):
            marker_id = marker["marker_id"]
            tx.connection.execute(
                "INSERT INTO search_item_markers(generation_id,row_id,depth,marker_id) VALUES(?,?,?,?)",
                (generation_id, row_id, depth, marker_id),
            )
            tx.connection.execute(
                "INSERT OR IGNORE INTO search_markers("
                "generation_id,marker_id,parent_marker_id,depth,marker_json,unrecognized,display_folded,display_key,raw_value"
                ") VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    generation_id,
                    marker_id,
                    parent,
                    depth,
                    json.dumps(marker, ensure_ascii=False, separators=(",", ":")),
                    int(marker["kind"] == "UNRECOGNIZED"),
                    marker["display_value"].casefold().encode("utf-8"),
                    _natural_blob(marker["display_value"]),
                    marker["raw_value"] or "",
                ),
            )
            parent = marker_id
        tx.connection.execute(
            "INSERT INTO search_fts(rowid,generation,filename,project,company,markers,path) VALUES(?,?,?,?,?,?,?)",
            (row_id, _generation_token(generation_id), *_columns(item)),
        )
        next_no += 1
        count += 1
    return count


def finish(tx, generation_id: str) -> None:
    changed = tx.connection.execute(
        "UPDATE search_generations SET state='READY' WHERE generation_id=? AND state='BUILDING'",
        (generation_id,),
    ).rowcount
    if changed != 1:
        raise ValueError("search generation cannot be finished")


def activate_generation(tx, generation_id: str) -> None:
    """Atomically make a READY generation the one visible for its root."""
    row = tx.connection.execute(
        "SELECT root_id,state FROM search_generations WHERE generation_id=?", (generation_id,)
    ).fetchone()
    if row is None or row[1] != "READY":
        raise ValueError("search generation cannot be activated")
    tx.connection.execute(
        "UPDATE search_generations SET state='READY' WHERE root_id=? AND state='ACTIVE'", (row[0],)
    )
    tx.connection.execute(
        "UPDATE search_generations SET state='ACTIVE' WHERE generation_id=?", (generation_id,)
    )


def delete_generation(tx, generation_id: str, batch_size: int = 1_000) -> bool:
    """Delete at most one bounded chunk; return true only when fully removed."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    row = tx.connection.execute(
        "SELECT state FROM search_generations WHERE generation_id=?", (generation_id,)
    ).fetchone()
    if row is None:
        return True
    if row[0] == "ACTIVE":
        raise ValueError("active generation cannot be deleted")
    pointed_to = tx.connection.execute(
        "SELECT 1 FROM objects WHERE kind='index' AND json_extract(body, '$._generation')=? LIMIT 1",
        (generation_id,),
    ).fetchone()
    if pointed_to is not None:
        raise ValueError("published generation cannot be deleted")
    rows = tx.connection.execute(
        "SELECT row_id,body FROM search_items WHERE generation_id=? ORDER BY row_id LIMIT ?",
        (generation_id, batch_size),
    ).fetchall()
    token = _generation_token(generation_id)
    for row_id, body in rows:
        tx.connection.execute(
            "INSERT INTO search_fts(search_fts,rowid,generation,filename,project,company,markers,path) VALUES('delete',?,?,?,?,?,?,?)",
            (row_id, token, *_columns(json.loads(body))),
        )
    if rows:
        tx.connection.executemany(
            "DELETE FROM search_items WHERE row_id=?", ((row_id,) for row_id, _ in rows)
        )
        return False
    tx.connection.execute("DELETE FROM search_generations WHERE generation_id=?", (generation_id,))
    return True


def garbage_collect(tx, root_id: str, keep_generation_id: str) -> int:
    stale = tx.connection.execute(
        "SELECT generation_id FROM search_generations WHERE root_id=? AND generation_id!=? AND state!='ACTIVE'",
        (root_id, keep_generation_id),
    ).fetchall()
    completed = 0
    for (generation_id,) in stale:
        completed += int(delete_generation(tx, generation_id))
    return completed


class SqlSearchIndex:
    """Read a READY or ACTIVE immutable generation without decoding all rows."""

    def __init__(self, tx, generation_id: str, *, clock=monotonic):
        self.connection = tx.connection
        self.generation_id = generation_id
        self.generation_token = _generation_token(generation_id)
        self._clock = clock
        row = self.connection.execute(
            "SELECT root_id,state FROM search_generations WHERE generation_id=?", (generation_id,)
        ).fetchone()
        if row is None or row[1] not in {"READY", "ACTIVE"}:
            raise ValueError("search generation is not readable")
        self.root_id = row[0]

    @contextmanager
    def _deadline(self):
        """Interrupt one public read rather than occupying a request worker forever."""
        expires_at = self._clock() + _SEARCH_DEADLINE_SECONDS

        def interrupted() -> int:
            return int(self._clock() >= expires_at)

        self.connection.set_progress_handler(interrupted, _PROGRESS_HANDLER_STEPS)
        try:
            yield
        except sqlite3.OperationalError as error:
            if getattr(error, "sqlite_errorcode", None) == sqlite3.SQLITE_INTERRUPT:
                raise ApiError(
                    "SEARCH_UNAVAILABLE", "Поиск временно недоступен.", 503, retryable=True
                ) from error
            raise
        finally:
            self.connection.set_progress_handler(None, 0)

    def _root(self, root: dict[str, Any]) -> None:
        if root.get("root_id") != self.root_id:
            raise ValueError("search generation belongs to another root")

    def _selected(self, selected: list[str]) -> list[dict[str, Any]]:
        if len(selected) != len(set(selected)):
            raise ApiError("INVALID_MARKER_SELECTION", "Цепочка содержит повторный маркер", 422)
        result = []
        parent = None
        for depth, marker_id in enumerate(selected):
            row = self.connection.execute(
                "SELECT parent_marker_id,marker_json FROM search_markers "
                "WHERE generation_id=? AND marker_id=? AND depth=?",
                (self.generation_id, marker_id, depth),
            ).fetchone()
            if row is None or row[0] != parent:
                raise ApiError("INVALID_MARKER_SELECTION", "Недопустимая цепочка маркеров", 422)
            result.append(json.loads(row[1]))
            parent = marker_id
        return result

    def _filter_sql(self, selected: list[str]) -> tuple[str, list[Any]]:
        parts, params = [], []
        for depth, marker_id in enumerate(selected):
            parts.append(
                "i.row_id IN (SELECT row_id FROM search_item_markers "
                "WHERE generation_id=? AND depth=? AND marker_id=?)"
            )
            params.extend((self.generation_id, depth, marker_id))
        return (" AND " + " AND ".join(parts)) if parts else "", params

    def _match(self, column: str, encoded: str, *, prefix: bool) -> str:
        suffix = "*" if prefix else ""
        return f"generation : {self.generation_token} AND {column} : {encoded}{suffix}"

    def _prefix_without_exact(self, column: str, encoded: str) -> str:
        """Prefix postings that cannot be dominated by an exact same-column hit."""
        return f"generation : {self.generation_token} AND {column} : ({encoded}* NOT {encoded})"

    def _term_cte(self, name: str, term: str) -> tuple[str, list[str]]:
        encoded = _encoded_token(term)
        statements, params = [], []
        for column, weight in _COLUMNS:
            statements.append("SELECT rowid, ? AS score FROM search_fts WHERE search_fts MATCH ?")
            params.extend((weight * 2, self._match(column, encoded, prefix=False)))
            statements.append("SELECT rowid, ? AS score FROM search_fts WHERE search_fts MATCH ?")
            params.extend((weight, self._prefix_without_exact(column, encoded)))
        return (
            f"{name} AS (SELECT rowid,MAX(score) score FROM ({' UNION ALL '.join(statements)}) GROUP BY rowid)",
            params,
        )

    def _phrase_cte(self, name: str, phrase: tuple[str, ...]) -> tuple[str, list[str]]:
        encoded = '"' + " ".join(_encoded_token(token) for token in phrase) + '"'
        statements, params = [], []
        for column, weight in _COLUMNS:
            statements.append("SELECT rowid, ? AS score FROM search_fts WHERE search_fts MATCH ?")
            params.extend((2 * len(phrase) * weight, self._match(column, encoded, prefix=False)))
        return (
            f"{name} AS (SELECT rowid,MAX(score) score FROM ({' UNION ALL '.join(statements)}) GROUP BY rowid)",
            params,
        )

    def _candidates(self, query, selected: list[str]) -> tuple[str, list[Any]]:
        ctes, params, names = [], [], []
        for number, (term,) in enumerate(query.terms):
            name = f"term_{number}"
            cte, values = self._term_cte(name, term)
            ctes.append(cte)
            params.extend(values)
            names.append(name)
        for number, phrase in enumerate(query.phrases):
            name = f"phrase_{number}"
            cte, values = self._phrase_cte(name, phrase)
            ctes.append(cte)
            params.extend(values)
            names.append(name)
        selected_sql, selected_params = self._filter_sql(selected)
        params.append(self.generation_id)
        params.extend(selected_params)
        if names:
            if len(names) <= _JOINED_CLAUSE_LIMIT:
                joins = " ".join(f"JOIN {name} USING(rowid)" for name in names[1:])
                score = " + ".join(f"{name}.score" for name in names)
                source = f"{names[0]} {joins}"
                item_join = f" JOIN search_items i ON i.row_id={names[0]}.rowid"
            else:
                # The public 512-character limit permits more than SQLite's
                # 64-table JOIN limit. Each CTE already has one score per row;
                # unioning them and requiring every clause is equivalent to
                # the AND join, without an undocumented query-size limit.
                combined = "candidate_scores"
                ctes.append(
                    f"{combined} AS (SELECT rowid,SUM(score) score FROM ("
                    + " UNION ALL ".join(f"SELECT rowid,score FROM {name}" for name in names)
                    + ") GROUP BY rowid HAVING COUNT(*)="
                    + str(len(names))
                    + ")"
                )
                score = f"{combined}.score"
                source = combined
                item_join = f" JOIN search_items i ON i.row_id={combined}.rowid"
        else:
            score = "0"
            source = "search_items i"
            item_join = ""
        # This intentionally returns only the durable row id and score.  The
        # request materializes it once in the connection-local TEMP database;
        # sort metadata and body JSON stay in search_items until needed.
        prefix = "WITH " + ",".join(ctes) if ctes else ""
        select = (
            f"{prefix} SELECT i.row_id,{score} score "
            f"FROM {source}{item_join} "
            f"WHERE i.generation_id=?{selected_sql}"
        )
        return select, params

    @contextmanager
    def _materialized_candidates(self, query, selected: list[str]):
        """Build one disk-backed, connection-private candidate snapshot.

        TEMP writes do not acquire the main SQLite writer lock.  The table is
        bounded by the result set on disk, never by a Python list, and is
        dropped on every normal or exceptional request exit.
        """
        table = "temp.wiseway_search_candidates"
        self.connection.execute(f"DROP TABLE IF EXISTS {table}")
        self.connection.execute(
            f"CREATE TEMP TABLE {table}(row_id INTEGER PRIMARY KEY,score INTEGER NOT NULL) WITHOUT ROWID"
        )
        try:
            candidates_sql, params = self._candidates(query, selected)
            self.connection.execute(
                f"INSERT INTO {table}(row_id,score) SELECT c.row_id,c.score FROM (" + candidates_sql + ") c",
                params,
            )
            yield table
        finally:
            # A deadline may have interrupted the statement inside this
            # context.  Clearing the hook first makes cleanup reliable, then
            # the outer deadline context maps that interruption to an API error.
            self.connection.set_progress_handler(None, 0)
            self.connection.execute(f"DROP TABLE IF EXISTS {table}")

    @staticmethod
    def _order(sort: dict[str, Any]) -> str:
        field, direction = sort.get("field"), sort.get("direction")
        if direction not in {"ASC", "DESC"}:
            raise _error("INVALID_QUERY", "Неизвестное направление сортировки", 400)
        if field == "RELEVANCE":
            if direction != "DESC":
                raise _error("INVALID_QUERY", "RELEVANCE требует DESC", 400)
            return "score DESC,path_key ASC,relative_path COLLATE BINARY ASC,item_id COLLATE BINARY ASC"
        if field == "PATH":
            return f"path_key {direction},relative_path COLLATE BINARY {direction},item_id COLLATE BINARY {direction}"
        if field == "NAME":
            return f"filename_key {direction},path_key ASC,relative_path COLLATE BINARY ASC,item_id COLLATE BINARY ASC"
        if field == "MODIFIED_AT":
            return f"modified_key {direction},path_key ASC,relative_path COLLATE BINARY ASC,item_id COLLATE BINARY ASC"
        if field == "SIZE":
            return f"size_bytes {direction},path_key ASC,relative_path COLLATE BINARY ASC,item_id COLLATE BINARY ASC"
        raise _error("INVALID_QUERY", "Неизвестная сортировка", 400)

    def _top_ids(self, table: str, sort: dict[str, Any], limit: int) -> list[int]:
        return [
            row[0]
            for row in self.connection.execute(
                "SELECT c.row_id FROM "
                + table
                + " c JOIN search_items i ON i.row_id=c.row_id ORDER BY "
                + self._order(sort)
                + " LIMIT ?",
                (limit,),
            )
        ]

    def _read_bodies(self, row_ids: list[int]) -> list[dict[str, Any]]:
        if not row_ids:
            return []
        placeholders = ",".join("?" for _ in row_ids)
        rows = self.connection.execute(
            "SELECT row_id,body FROM search_items WHERE row_id IN (" + placeholders + ")", row_ids
        ).fetchall()
        values = {row_id: json.loads(body) for row_id, body in rows}
        return [values[row_id] for row_id in row_ids]

    def _facet(self, candidates_sql: str, params: list[Any], selected: list[str], prefix: str):
        depth = len(selected)
        folded = prefix.casefold().encode("utf-8")
        prefix_sql, prefix_params = (
            ("", [])
            if not folded
            else (" AND m.display_folded>=? AND m.display_folded<?", [folded, _bytes_successor(folded)])
        )
        first = self.connection.execute(
            "WITH candidates AS (" + candidates_sql + ") "
            "SELECT m.marker_json FROM candidates c "
            "JOIN search_item_markers im ON im.generation_id=? AND im.row_id=c.row_id AND im.depth=? "
            "CROSS JOIN search_markers m ON m.generation_id=im.generation_id AND m.marker_id=im.marker_id "
            "GROUP BY m.marker_id ORDER BY MIN(c.row_id) LIMIT 1",
            [*params, self.generation_id, depth],
        ).fetchone()
        if first is None:
            return None
        rows = self.connection.execute(
            "WITH candidates AS (" + candidates_sql + ") "
            "SELECT m.marker_json,COUNT(*) FROM candidates c "
            "JOIN search_item_markers im ON im.generation_id=? AND im.row_id=c.row_id AND im.depth=? "
            "CROSS JOIN search_markers m ON m.generation_id=im.generation_id AND m.marker_id=im.marker_id "
            + prefix_sql
            + " GROUP BY m.marker_id ORDER BY m.unrecognized,m.display_key,m.raw_value COLLATE BINARY,m.marker_id COLLATE BINARY",
            [*params, self.generation_id, depth, *prefix_params],
        ).fetchall()
        marker = json.loads(first[0])
        options = [{**json.loads(marker_json), "count": count} for marker_json, count in rows]
        return {"level_id": marker["level_id"], "level_name": marker["level_name"], "options": options}

    def _facet_table(self, table: str, selected: list[str], prefix: str):
        """Facet one already materialized candidate set without re-running FTS."""
        depth = len(selected)
        folded = prefix.casefold().encode("utf-8")
        prefix_sql, prefix_params = (
            ("", [])
            if not folded
            else (" AND m.display_folded>=? AND m.display_folded<?", [folded, _bytes_successor(folded)])
        )
        first = self.connection.execute(
            "SELECT m.marker_json FROM " + table + " c CROSS JOIN search_item_markers im "
            "ON im.generation_id=? AND im.row_id=c.row_id AND im.depth=? "
            "CROSS JOIN search_markers m ON m.generation_id=im.generation_id AND m.marker_id=im.marker_id "
            "ORDER BY c.row_id LIMIT 1",
            (self.generation_id, depth),
        ).fetchone()
        if first is None:
            return None
        rows = self.connection.execute(
            "SELECT m.marker_json,COUNT(*) FROM " + table + " c CROSS JOIN search_item_markers im "
            "ON im.generation_id=? AND im.row_id=c.row_id AND im.depth=? "
            "CROSS JOIN search_markers m ON m.generation_id=im.generation_id AND m.marker_id=im.marker_id "
            + prefix_sql
            + " GROUP BY m.marker_id ORDER BY m.unrecognized,m.display_key,m.raw_value COLLATE BINARY,m.marker_id COLLATE BINARY",
            (self.generation_id, depth, *prefix_params),
        ).fetchall()
        marker = json.loads(first[0])
        options = [{**json.loads(marker_json), "count": count} for marker_json, count in rows]
        return {"level_id": marker["level_id"], "level_name": marker["level_name"], "options": options}

    def _root_facet(self, prefix: str):
        """Return the IDLE root facet from the marker covering index alone."""
        folded = prefix.casefold().encode("utf-8")
        prefix_sql, prefix_params = (
            ("", [])
            if not folded
            else (" AND m.display_folded>=? AND m.display_folded<?", [folded, _bytes_successor(folded)])
        )
        first = self.connection.execute(
            "SELECT marker_json FROM search_markers "
            "WHERE generation_id=? AND depth=0 AND parent_marker_id IS NULL ORDER BY marker_id LIMIT 1",
            (self.generation_id,),
        ).fetchone()
        if first is None:
            return None
        rows = self.connection.execute(
            "SELECT m.marker_json,COUNT(*) FROM search_item_markers im "
            "JOIN search_markers m ON m.generation_id=im.generation_id AND m.marker_id=im.marker_id "
            "WHERE im.generation_id=? AND im.depth=0"
            + prefix_sql
            + " GROUP BY m.marker_id ORDER BY m.unrecognized,m.display_key,m.raw_value COLLATE BINARY,m.marker_id COLLATE BINARY",
            (self.generation_id, *prefix_params),
        ).fetchall()
        marker = json.loads(first[0])
        options = [{**json.loads(marker_json), "count": count} for marker_json, count in rows]
        return {"level_id": marker["level_id"], "level_name": marker["level_name"], "options": options}

    def _selected_idle_facet(self, selected: list[str], prefix: str):
        """Facet the children of a validated chain without scanning items."""
        parent, depth = selected[-1], len(selected)
        folded = prefix.casefold().encode("utf-8")
        prefix_sql, prefix_params = (
            ("", [])
            if not folded
            else (" AND m.display_folded>=? AND m.display_folded<?", [folded, _bytes_successor(folded)])
        )
        first = self.connection.execute(
            "SELECT marker_json FROM search_markers "
            "WHERE generation_id=? AND parent_marker_id=? AND depth=? ORDER BY marker_id LIMIT 1",
            (self.generation_id, parent, depth),
        ).fetchone()
        if first is None:
            return None
        rows = self.connection.execute(
            "SELECT m.marker_json,COUNT(*) FROM search_item_markers im "
            "JOIN search_markers m ON m.generation_id=im.generation_id AND m.marker_id=im.marker_id "
            "WHERE im.generation_id=? AND im.depth=? AND m.parent_marker_id=?"
            + prefix_sql
            + " GROUP BY m.marker_id ORDER BY m.unrecognized,m.display_key,m.raw_value COLLATE BINARY,m.marker_id COLLATE BINARY",
            (self.generation_id, depth, parent, *prefix_params),
        ).fetchall()
        marker = json.loads(first[0])
        options = [{**json.loads(marker_json), "count": count} for marker_json, count in rows]
        return {"level_id": marker["level_id"], "level_name": marker["level_name"], "options": options}

    def _search(self, root: dict[str, Any], request: dict[str, Any], limit: int = 100) -> dict[str, Any]:
        self._root(root)
        _validate_context(root, request)
        if limit < 1:
            raise ValueError("limit must be positive")
        query = _parse_query(str(request.get("query_text", "")))
        selected = list(request.get("selected_marker_ids", []))
        selected_markers = self._selected(selected)
        is_idle = not selected and not query.terms and not query.phrases
        if request.get("sort", {}).get("field") == "RELEVANCE" and not (query.terms or query.phrases):
            raise _error("INVALID_QUERY", "RELEVANCE требует непустой текст", 400)
        freshness = {
            "indexed_at": root["indexed_at"],
            "last_successful_sync_at": root["indexed_at"],
            "status": "CURRENT",
        }
        if is_idle:
            next_facet = self._root_facet(str(request.get("facet_prefix", "")))
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
                "freshness": freshness,
            }
        with self._materialized_candidates(query, selected) as candidates:
            next_facet = (
                self._selected_idle_facet(selected, str(request.get("facet_prefix", "")))
                if not query.terms and not query.phrases
                else self._facet_table(candidates, selected, str(request.get("facet_prefix", "")))
            )
            total = self.connection.execute(f"SELECT COUNT(*) FROM {candidates}").fetchone()[0]
            top_ids = self._top_ids(candidates, request.get("sort", {}), limit)
            items = self._read_bodies(top_ids)
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
            "returned_count": len(items),
            "result_limit": limit,
            "limited": total > limit,
            "items": items,
            "next_facet": next_facet,
            "freshness": freshness,
        }

    def _public_facet(self, root: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        self._root(root)
        _validate_context(root, request)
        query = _parse_query(str(request.get("query_text", "")))
        selected = list(request.get("selected_marker_ids", []))
        self._selected(selected)
        if not query.terms and not query.phrases:
            result = (
                self._selected_idle_facet(selected, str(request.get("facet_prefix", "")))
                if selected
                else self._root_facet(str(request.get("facet_prefix", "")))
            )
        else:
            with self._materialized_candidates(query, selected) as candidates:
                result = self._facet_table(candidates, selected, str(request.get("facet_prefix", "")))
        return {
            "request_state_id": request["request_state_id"],
            "root_id": root["root_id"],
            "schema_set_version": root["schema_set_version"],
            "index_generation": root["index_generation"],
            "facet": result,
        }

    def search(self, root: dict[str, Any], request: dict[str, Any], limit: int = 100) -> dict[str, Any]:
        with self._deadline():
            return self._search(root, request, limit)

    def facet(self, root: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        with self._deadline():
            return self._public_facet(root, request)
