"""Exact contract search over compact, externally versioned OpenSearch documents."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import http.client
import json
import queue
import re
import ssl
from time import monotonic
from urllib.parse import urlsplit

from .common import ApiError, instant_sort_key
from .search import (
    RANKING_PROFILE_VERSION,
    _facet_from_groups,
    _freshness,
    _parse_query,
    _validate_context,
    build_item,
    compile_schema,
)
from .sqlite_search import _columns, _encoded_stream, _encoded_token, _natural_blob

FIELDS = (("t_name", 5), ("t_project", 4), ("t_company", 3), ("t_markers", 1), ("t_path", 1))
MAX_FACETS = 10_000
MAX_RESPONSE = 16 * 1024 * 1024
DEFAULT_BULK_TARGET = 12 * 1024 * 1024
MAX_DEPTH = 64
_MAX_SCORE_PROBE_THRESHOLD = 10_000
SEARCH_FORMAT = "wiseway-search-3"
LEGACY_SEARCH_FORMAT = "wiseway-search-2"


def unavailable():
    return ApiError("SEARCH_UNAVAILABLE", "Поиск временно недоступен.", 503, retryable=True)


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class BulkBatch:
    """One already encoded bounded bulk request, retaining replay records."""

    records: tuple[tuple[dict, int], ...]
    payload: bytes

    def __iter__(self):
        return iter(self.records)

    def __len__(self):
        return len(self.records)


class BulkBatchBuilder:
    """Encode each action/document once while enforcing byte limits."""

    def __init__(self, *, target_bytes=DEFAULT_BULK_TARGET, hard_limit_bytes=MAX_RESPONSE):
        if not 1 <= target_bytes <= hard_limit_bytes <= MAX_RESPONSE:
            raise ValueError("Invalid bulk byte limits")
        self.target_bytes, self.hard_limit_bytes = target_bytes, hard_limit_bytes
        self._records, self._parts, self._size = [], [], 0

    def add(self, doc, version):
        if len(self._records) >= 5000 or type(version) is not int or not 0 < version < 2**63:
            raise ValueError("Invalid bulk size or external version")
        encoded = (
            _json({"index": {"_id": doc["id"], "version": version, "version_type": "external_gte"}}).encode()
            + b"\n"
            + _json(doc).encode()
            + b"\n"
        )
        if len(encoded) > self.hard_limit_bytes:
            raise ValueError("Bulk record exceeds hard limit")
        if self._records and self._size + len(encoded) > self.target_bytes:
            return False
        self._records.append((doc, version))
        self._parts.append(encoded)
        self._size += len(encoded)
        return True

    def finish(self):
        if not self._records:
            raise ValueError("Cannot finish an empty bulk batch")
        batch = BulkBatch(tuple(self._records), b"".join(self._parts))
        self._records, self._parts, self._size = [], [], 0
        return batch

    def __bool__(self):
        return bool(self._records)


def index_name(name):
    if not isinstance(name, str) or not re.fullmatch(r"wiseway-[a-z0-9][a-z0-9-]{0,180}", name):
        raise ValueError("Invalid Wise Way search index name")
    return name


class OpenSearch:
    """Bounded reusable HTTP connections. TLS verifies host and CA by default.

    No redirects, proxy environment, automatic mutation retries or error bodies in
    public exceptions. A failed bulk is replayed from the import checkpoint.
    """

    def __init__(
        self, url, *, ca_file=None, credentials_file=None, allow_http=False, timeout=30, pool_size=4
    ):
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or any(c.isspace() for c in url)
            or "\\" in url
        ):
            raise ValueError("Search URL must be an HTTP(S) origin without credentials")
        if parsed.scheme == "http" and (
            not allow_http or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        ):
            raise ValueError("Plain HTTP search is restricted to explicit loopback tests")
        if not 1 <= pool_size <= 64 or not 0 < timeout <= 120:
            raise ValueError("Invalid search connection limits")
        self.timeout = timeout
        self.headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if credentials_file:
            from pathlib import Path

            credentials = json.loads(Path(credentials_file).read_text())
            user, password = credentials["username"], credentials["password"]
            if (
                not isinstance(user, str)
                or not isinstance(password, str)
                or not user
                or not password
                or ":" in user
            ):
                raise ValueError("Invalid search credentials")
            self.headers["Authorization"] = (
                "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
            )
        context = ssl.create_default_context(cafile=ca_file) if parsed.scheme == "https" else None
        self.pool = queue.LifoQueue(pool_size)
        self.connections = []
        for _ in range(pool_size):
            connection = (
                http.client.HTTPSConnection(parsed.hostname, parsed.port, timeout=timeout, context=context)
                if context
                else http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=timeout)
            )
            self.connections.append(connection)
            self.pool.put(connection)

    def close(self):
        for connection in self.connections:
            connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def request(self, method, path, body=None, *, ndjson=False):
        payload = body if isinstance(body, bytes) else None if body is None else _json(body).encode()
        if payload is not None and len(payload) > MAX_RESPONSE:
            raise ValueError("Search request exceeds bounded batch size")
        try:
            connection = self.pool.get(timeout=self.timeout)
        except queue.Empty:
            raise unavailable() from None
        try:
            headers = {
                **self.headers,
                "Content-Type": "application/x-ndjson" if ndjson else "application/json",
            }
            connection.request(method, path, payload, headers)
            response = connection.getresponse()
            raw = response.read(MAX_RESPONSE + 1)
            if not 200 <= response.status < 300 or len(raw) > MAX_RESPONSE:
                connection.close()
                raise unavailable()
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("Invalid engine response")
            return value
        except (OSError, http.client.HTTPException, ValueError):
            connection.close()
            raise unavailable() from None
        finally:
            self.pool.put(connection)

    def create(self, name, *, shards=8, config_hash="contract-v1"):
        body = mapping(shards)
        body["mappings"]["_meta"] = {"config_hash": config_hash, "format": SEARCH_FORMAT}
        response = self.request("PUT", "/" + index_name(name), body)
        if response.get("acknowledged") is not True or response.get("shards_acknowledged") is not True:
            raise unavailable()

    def ensure(self, name, *, shards=8, config_hash):
        name = index_name(name)
        try:
            value = self.request("GET", f"/{name}/_mapping")
        except ApiError:
            self.create(name, shards=shards, config_hash=config_hash)
            value = self.request("GET", f"/{name}/_mapping")
        if value.get(name, {}).get("mappings", {}).get("_meta") != {
            "config_hash": config_hash,
            "format": SEARCH_FORMAT,
        }:
            raise ValueError("Search index configuration mismatch")

    def bulk(self, name, records):
        index_name(name)
        if isinstance(records, BulkBatch):
            count, payload = len(records), records.payload
            if (
                not 1 <= count <= 5000
                or not isinstance(payload, bytes)
                or not 0 < len(payload) <= MAX_RESPONSE
            ):
                raise ValueError("Invalid preencoded bulk batch")
        else:
            lines = []
            count = 0
            for doc, version in records:
                if count >= 5000 or type(version) is not int or not 0 < version < 2**63:
                    raise ValueError("Invalid bulk size or external version")
                lines.append(
                    _json({"index": {"_id": doc["id"], "version": version, "version_type": "external_gte"}})
                )
                lines.append(_json(doc))
                count += 1
            payload = ("\n".join(lines) + "\n").encode() if count else b""
        if not count:
            return
        value = self.request("POST", f"/{name}/_bulk?refresh=false", payload, ndjson=True)
        items = value.get("items", [])
        if len(items) != count:
            raise unavailable()
        for item in items:
            result = item.get("index", {})
            status = result.get("status")
            if status in {200, 201}:
                continue
            # A strictly older external revision has already been superseded.
            if status == 409 and result.get("error", {}).get("type") == "version_conflict_engine_exception":
                continue
            raise unavailable()

    def publish(self, name):
        name = index_name(name)
        _complete(self.request("POST", f"/{name}/_refresh"))
        value = self.request(
            "POST", f"/{name}/_search/point_in_time?keep_alive=24h&allow_partial_pit_creation=false"
        )
        _complete(value)
        if not isinstance(value.get("pit_id"), str) or not value["pit_id"]:
            raise unavailable()
        return value["pit_id"]

    def close_pit(self, pit):
        self.request("DELETE", "/_search/point_in_time", {"pit_id": [pit]})


def _complete(value):
    # Composite aggregation may report terminated_early as an optimization.
    # We never send terminate_after; timeouts, shard failures and inexact totals
    # are checked separately.
    shards = value.get("_shards", {})
    if (
        value.get("timed_out", False)
        or shards.get("failed", 1) != 0
        or shards.get("successful", -1) != shards.get("total", -2)
    ):
        raise unavailable()


def mapping(shards=8):
    if type(shards) is not int or not 1 <= shards <= 128:
        raise ValueError("Search shards must be between 1 and 128")
    props = {name: {"type": "text", "analyzer": "encoded", "norms": False} for name, _ in FIELDS}
    props.update(
        {
            name: {"type": "keyword"}
            for name in ("id", "path", "name_key", "path_key", "modified", "marker_ids")
        }
    )
    for name in ("id", "path", "name_key", "path_key", "modified"):
        props[name].update(index=False, doc_values=True)
    props["modified_key"] = {"type": "keyword", "index": False, "doc_values": True}
    props["marker_ids"]["doc_values"] = False
    props.update({f"f{n}": {"type": "keyword", "index": False, "doc_values": True} for n in range(MAX_DEPTH)})
    props.update(size={"type": "long"}, deleted={"type": "boolean", "doc_values": False})
    return {
        "settings": {
            "number_of_shards": shards,
            "number_of_replicas": 0,
            "refresh_interval": "-1",
            "index.sort.field": ["path_key", "path", "id"],
            "index.sort.order": ["asc", "asc", "asc"],
            "analysis": {
                "tokenizer": {"encoded_words": {"type": "whitespace", "max_token_length": 32766}},
                "analyzer": {"encoded": {"type": "custom", "tokenizer": "encoded_words", "filter": []}},
            },
        },
        "mappings": {
            "dynamic": "strict",
            "_source": {"includes": ["id", "path", "size", "modified", "deleted"]},
            "properties": props,
        },
    }


def document(item):
    path = item["location"]["relative_path"]
    markers = item["markers"]
    result = {
        "id": item["item_id"],
        "path": path,
        "size": item["size_bytes"],
        "modified": item["modified_at"],
        "modified_key": instant_sort_key(item["modified_at"]),
        "deleted": False,
        "name_key": _natural_blob(item["filename"]).hex(),
        "path_key": _natural_blob(path).hex(),
        "marker_ids": [m["marker_id"] for m in markers],
    }
    result.update({name: value for (name, _), value in zip(FIELDS, _columns(item))})
    result.update({f"f{n}": _json(marker) for n, marker in enumerate(markers)})
    if len(markers) > MAX_DEPTH or len(str(result["id"]).encode()) > 512:
        raise ValueError("Search document exceeds identity/depth limits")
    for name, value in result.items():
        if isinstance(value, str) and not name.startswith("t_") and len(value.encode()) > 32760:
            raise ValueError("Search document exceeds keyword limit")
    if any(len(token.encode()) > 32760 for name, _ in FIELDS for token in result[name].split()):
        raise ValueError("Search document exceeds token limit")
    return result


def query_dsl(text, selected):
    parsed = _parse_query(text)
    clauses = []
    for (term,) in parsed.terms:
        queries = []
        token = _encoded_token(term)
        for field, weight in FIELDS:
            queries.extend(
                [
                    {"constant_score": {"filter": {"term": {field: token}}, "boost": 2 * weight}},
                    {"constant_score": {"filter": {"prefix": {field: token}}, "boost": weight}},
                ]
            )
        clauses.append({"dis_max": {"queries": queries, "tie_breaker": 0}})
    for phrase in parsed.phrases:
        clauses.append(
            {
                "dis_max": {
                    "tie_breaker": 0,
                    "queries": [
                        {
                            "constant_score": {
                                "filter": {"match_phrase": {field: _encoded_stream(phrase)}},
                                "boost": 2 * len(phrase) * weight,
                            }
                        }
                        for field, weight in FIELDS
                    ],
                }
            }
        )
    return {
        "bool": {
            "filter": [
                {"term": {"deleted": False}},
                *[{"term": {"marker_ids": marker}} for marker in selected],
            ],
            "must": clauses,
        }
    }


def candidate_dsl(text, selected, *, exact_name=False):
    """Every searchable filename/marker token is also in the logical path.

    The path therefore determines membership without computing field weights.
    Exact filename matches simultaneously attain the maximum possible score
    for every term/phrase and can be ordered by the path tie-break directly.
    """
    parsed = _parse_query(text)
    field = "t_name" if exact_name else "t_path"
    filters = [{"term": {"deleted": False}}, *[{"term": {"marker_ids": marker}} for marker in selected]]
    filters.extend(
        {"term" if exact_name else "prefix": {field: _encoded_token(term)}} for (term,) in parsed.terms
    )
    filters.extend({"match_phrase": {field: _encoded_stream(phrase)}} for phrase in parsed.phrases)
    return {"bool": {"filter": filters}}


def _sort(order, *, modified_field="modified"):
    field, direction = order.get("field"), order.get("direction")
    if (
        direction not in {"ASC", "DESC"}
        or field not in {"RELEVANCE", "NAME", "PATH", "MODIFIED_AT", "SIZE"}
        or field == "RELEVANCE"
        and direction != "DESC"
    ):
        raise ApiError("INVALID_QUERY", "Неизвестная сортировка", 400)
    tail = [{name: direction.lower() if field == "PATH" else "asc"} for name in ("path_key", "path", "id")]
    if field == "PATH":
        return tail
    primary = {
        "RELEVANCE": "_score",
        "NAME": "name_key",
        "MODIFIED_AT": modified_field,
        "SIZE": "size",
    }[field]
    return [{primary: direction.lower()}, *tail]


class SearchSnapshot:
    def __init__(self, engine, manifest):
        self.engine, self.manifest = engine, manifest
        self.root = manifest["root"]
        self.deadline = None
        self._compiled_schema = None

    def _request(self, body):
        if self.deadline is not None and monotonic() >= self.deadline:
            raise unavailable()
        value = self.engine.request(
            "POST",
            "/_search?allow_partial_search_results=false",
            {
                "pit": {"id": self.manifest["_pit_id"], "keep_alive": "24h"},
                "timeout": "25s",
                **body,
            },
        )
        _complete(value)
        total = value.get("hits", {}).get("total")
        if total is not None and total.get("relation") != "eq":
            raise unavailable()
        return value

    def _item(self, source):
        if self._compiled_schema is None:
            self._compiled_schema = compile_schema(self.manifest["_schema"])
        return build_item(
            self.root["root_id"],
            self.root["display_prefix"],
            source["path"],
            source["size"],
            source["modified"],
            self.manifest["_schema"],
            source["id"],
            compiled_schema=self._compiled_schema,
        )

    def _selection(self, request):
        _validate_context(self.root, request)
        selected = request.get("selected_marker_ids", [])
        if not selected:
            return []
        if len(selected) != len(set(selected)) or len(selected) > MAX_DEPTH:
            raise ApiError("INVALID_MARKER_SELECTION", "Недопустимая цепочка маркеров", 422)
        value = self._request({"query": query_dsl("", selected), "size": 1, "track_total_hits": False})
        hits = value["hits"]["hits"]
        markers = self._item(hits[0]["_source"])["markers"][: len(selected)] if hits else []
        if [m["marker_id"] for m in markers] != selected:
            raise ApiError("INVALID_MARKER_SELECTION", "Недопустимая цепочка маркеров", 422)
        return markers

    def _facets(self, query, depth, prefix, first=None):
        groups, after = {}, None
        while True:
            if first is not None:
                response, first = first, None
            else:
                response = self._request(
                    {
                        "size": 0,
                        "track_total_hits": False,
                        "query": query,
                        "aggs": self._aggregation(depth, after),
                    }
                )
            aggregation = response.get("aggregations", {}).get("facet", {})
            buckets = aggregation.get("buckets", [])
            for bucket in buckets:
                marker = json.loads(bucket["key"]["marker"])
                groups[marker["marker_id"]] = marker, bucket["doc_count"]
            if len(groups) > MAX_FACETS:
                # v1 has no facet paging; never return an incomplete success.
                raise unavailable()
            following = aggregation.get("after_key")
            if len(buckets) < 1000 or following is None:
                break
            if following == after:
                raise unavailable()
            after = following
        return _facet_from_groups(groups, prefix)

    @staticmethod
    def _aggregation(depth, after=None):
        composite = {"size": 1000, "sources": [{"marker": {"terms": {"field": f"f{depth}"}}}]}
        if after:
            composite["after"] = after
        return {"facet": {"composite": composite}}

    def _maximum_score_query(self, text, selected, candidates):
        parsed = _parse_query(text)
        if len(parsed.terms) + len(parsed.phrases) > 8:
            return None
        chosen = []
        groups = []
        for (term,) in parsed.terms:
            token = _encoded_token(term)
            levels = {}
            for field, weight in FIELDS:
                levels.setdefault(weight * 2, []).append({"term": {field: token}})
                levels.setdefault(weight, []).append({"prefix": {field: token}})
            groups.append(levels)
        for phrase in parsed.phrases:
            levels = {}
            for field, weight in FIELDS:
                levels.setdefault(weight * 2 * len(phrase), []).append(
                    {"match_phrase": {field: _encoded_stream(phrase)}}
                )
            groups.append(levels)
        for levels in groups:
            # Every alternative has a constant, integer score.  One score-sorted
            # probe identifies the highest attainable level for this clause;
            # trying the levels one-by-one made an eight-part query issue up to
            # 64 sequential engine requests.
            alternatives = [
                {"constant_score": {"filter": condition, "boost": score}}
                for score, conditions in levels.items()
                for condition in conditions
            ]
            probe = self._request(
                {
                    "query": {
                        "bool": {
                            "filter": [candidates],
                            "must": [{"dis_max": {"queries": alternatives, "tie_breaker": 0}}],
                        }
                    },
                    "size": 1,
                    "track_total_hits": False,
                    "_source": False,
                    "sort": [{"_score": "desc"}],
                }
            )
            hits = probe["hits"]["hits"]
            score = hits[0].get("_score") if hits else None
            if type(score) not in {int, float} or score not in levels:
                raise unavailable()
            chosen.append({"bool": {"should": levels[score], "minimum_should_match": 1}})
        # Independent per-clause maxima are an upper bound. If their
        # intersection cannot fill top-k, fall back to the complete scorer.
        return {"bool": {"filter": [candidates, *chosen]}}

    def search(self, request, limit=100):
        self.deadline = monotonic() + 30
        selected = self._selection(request)
        parsed = _parse_query(request.get("query_text", ""))
        has_text = bool(parsed.terms or parsed.phrases)
        if request.get("sort", {}).get("field") == "RELEVANCE" and not has_text:
            raise ApiError("INVALID_QUERY", "RELEVANCE требует непустой текст", 400)
        ordering = _sort(
            request.get("sort", {}),
            modified_field="modified_key"
            if self.manifest.get("_search_format") == SEARCH_FORMAT
            else "modified",
        )
        idle = not selected and not has_text
        text = request.get("query_text", "")
        marker_ids = request.get("selected_marker_ids", [])
        query = candidate_dsl(text, marker_ids)
        value = self._request(
            {
                "query": query,
                "size": 0,
                "track_total_hits": True,
                "aggs": self._aggregation(len(selected)),
            }
        )
        total = None if idle else value["hits"]["total"]["value"]
        hits = []
        if not idle and total:
            if request["sort"]["field"] == "RELEVANCE":
                best = self._request(
                    {
                        "query": candidate_dsl(text, marker_ids, exact_name=True),
                        "size": limit,
                        "track_total_hits": False,
                        "sort": _sort({"field": "PATH", "direction": "ASC"}),
                    }
                )
                hits = best["hits"]["hits"]
                if len(hits) < min(limit, total) and total > _MAX_SCORE_PROBE_THRESHOLD:
                    maximum = self._maximum_score_query(text, marker_ids, query)
                    if maximum is not None:
                        hits = self._request(
                            {
                                "query": maximum,
                                "size": limit,
                                "track_total_hits": False,
                                "sort": _sort({"field": "PATH", "direction": "ASC"}),
                            }
                        )["hits"]["hits"]
                if len(hits) < min(limit, total):
                    hits = self._request(
                        {
                            "query": query_dsl(text, marker_ids),
                            "size": limit,
                            "track_total_hits": False,
                            "sort": ordering,
                        }
                    )["hits"]["hits"]
            else:
                hits = self._request(
                    {"query": query, "size": limit, "track_total_hits": False, "sort": ordering}
                )["hits"]["hits"]
        items = [self._item(hit["_source"]) for hit in hits]
        return {
            "request_state_id": request["request_state_id"],
            "mode": "IDLE" if idle else "RESULTS",
            "root_id": self.root["root_id"],
            "schema_set_version": self.root["schema_set_version"],
            "index_generation": self.root["index_generation"],
            "ranking_profile_version": RANKING_PROFILE_VERSION,
            "applied_query_text": parsed.applied_text,
            "selected_markers": selected,
            "total": total,
            "returned_count": len(items),
            "result_limit": limit,
            "limited": total is not None and total > limit,
            "items": items,
            "next_facet": self._facets(query, len(selected), request.get("facet_prefix", ""), value),
            "freshness": _freshness(self.root),
        }

    def facet(self, request):
        self.deadline = monotonic() + 30
        selected = self._selection(request)
        query = candidate_dsl(request.get("query_text", ""), request.get("selected_marker_ids", []))
        return {
            "request_state_id": request["request_state_id"],
            "root_id": self.root["root_id"],
            "schema_set_version": self.root["schema_set_version"],
            "index_generation": self.root["index_generation"],
            "facet": self._facets(query, len(selected), request.get("facet_prefix", "")),
        }
