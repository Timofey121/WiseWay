import json
import os
import uuid

import pytest

from test_search_golden import ROOT, build_items, golden, request
from wiseway.search import DEMO_SCHEMAS, facet, search
from wiseway.opensearch import OpenSearch, SearchSnapshot, document, mapping, query_dsl


def test_compact_document_preserves_tokens_and_limits():
    item = build_items(golden())["a-main"]
    encoded = document(item)
    assert encoded["path"] == item["location"]["relative_path"]
    assert "location" not in encoded
    assert encoded["f0"] == json.dumps(item["markers"][0], ensure_ascii=False, separators=(",", ":"))
    configured = mapping(2)
    assert configured["settings"]["number_of_shards"] == 2
    properties = configured["mappings"]["properties"]
    for field in ("id", "path", "name_key", "path_key", "modified", "f0", "f63"):
        assert properties[field]["index"] is False
        assert properties[field]["doc_values"] is True
    with pytest.raises(ValueError):
        mapping(0)


def test_new_physical_index_uses_path_sort_and_omits_unused_doc_values(engine, indexed):
    rows = list(build_items(golden()).values())[:2]
    _, name = indexed(rows)
    settings = engine.request("GET", f"/{name}/_settings?flat_settings=true")[name]["settings"]
    assert settings["index.sort.field"] == ["path_key", "path", "id"]
    assert settings["index.sort.order"] == ["asc", "asc", "asc"]
    properties = engine.request("GET", f"/{name}/_mapping")[name]["mappings"]["properties"]
    assert properties["marker_ids"]["doc_values"] is False
    assert properties["deleted"]["doc_values"] is False
    for field in ("id", "path", "name_key", "path_key", "modified", "f0", "f63"):
        assert properties[field]["index"] is False
        assert properties[field]["type"] == "keyword"
        # The engine omits the default true value when returning a keyword mapping.
        assert properties[field].get("doc_values", True) is True


def test_query_scoring_has_no_bm25_or_user_query_string():
    body = query_dsl('rep "orion 2031"', [])
    clauses = body["bool"]["must"]
    assert len(clauses) == 2
    assert clauses[0]["dis_max"]["tie_breaker"] == 0
    assert all("constant_score" in x for x in clauses[0]["dis_max"]["queries"])


@pytest.fixture
def engine():
    url = os.getenv("WISEWAY_TEST_SEARCH_URL")
    if not url:
        pytest.skip("Set WISEWAY_TEST_SEARCH_URL for isolated OpenSearch integration tests")
    with OpenSearch(url, allow_http=True) as client:
        yield client


@pytest.fixture
def indexed(engine):
    names = []
    pits = []

    def create(rows, root=ROOT):
        name = "wiseway-test-" + uuid.uuid4().hex
        names.append(name)
        engine.create(name, shards=2)
        engine.bulk(name, [(document(row), 1) for row in rows])
        pit = engine.publish(name)
        pits.append(pit)
        return SearchSnapshot(
            engine, {"root": root, "_pit_id": pit, "_schema": DEMO_SCHEMAS["schema-demo-1"]}
        ), name

    yield create
    for pit in pits:
        engine.close_pit(pit)
    for name in names:
        engine.request("DELETE", "/" + name)


@pytest.mark.parametrize("case", golden()["cases"], ids=lambda case: case["id"])
def test_real_engine_matches_golden(indexed, case):
    items = build_items(golden())
    rows = [items[item_id] for item_id in case["items"]]
    snapshot, _ = indexed(rows)
    for text in case.get("queries") or [case["query"]]:
        body = {**request(case, items), "query_text": text}
        assert snapshot.search(body) == search(ROOT, rows, body)
        assert snapshot.facet(body) == facet(ROOT, rows, body)


def test_publication_isolation_and_versioned_tombstones(engine, indexed):
    rows = list(build_items(golden()).values())[:2]
    old, name = indexed(rows)
    body = {
        "request_state_id": "snapshot",
        "root_id": ROOT["root_id"],
        "schema_set_version": ROOT["schema_set_version"],
        "query_text": "",
        "selected_marker_ids": [rows[0]["markers"][0]["marker_id"]],
        "sort": {"field": "PATH", "direction": "ASC"},
    }
    expected = old.search(body)
    tombstone = {"id": rows[0]["item_id"], "deleted": True}
    engine.bulk(name, [(tombstone, 3)])
    engine.bulk(name, [(document(rows[0]), 2)])  # obsolete replay cannot resurrect it
    new_pit = engine.publish(name)
    try:
        assert old.search(body) == expected
        new = SearchSnapshot(engine, {**old.manifest, "_pit_id": new_pit})
        assert new.search(body) == search(ROOT, rows[1:], body)
    finally:
        engine.close_pit(new_pit)


def test_all_orders_unicode_and_top_k(indexed, monkeypatch):
    monkeypatch.setattr("wiseway.opensearch._MAX_SCORE_PROBE_THRESHOLD", 0)
    from test_search import ROOT as root, request as body
    from test_search_scale_review import _corpus, _selection

    rows = _corpus()
    snapshot, _ = indexed(rows, root)
    for text in ("report", "док", "10", '"orion 2031"', '"документ 2"', "atlas report"):
        for field in ("PATH", "NAME", "SIZE", "MODIFIED_AT", "RELEVANCE"):
            for direction in ("DESC",) if field == "RELEVANCE" else ("ASC", "DESC"):
                for selection in ([], _selection(rows, "Atlas")):
                    request_body = body(
                        query_text=text,
                        selected_marker_ids=selection,
                        sort={"field": field, "direction": direction},
                    )
                    assert snapshot.search(request_body, 7) == search(root, rows, request_body, 7)


@pytest.mark.parametrize(
    "url",
    [
        "http://remote:9200",
        "http://localhost:9200/path",
        "https://user:secret@localhost",
        "https://localhost?token=secret",
    ],
)
def test_transport_rejects_unsafe_origins(url):
    with pytest.raises(ValueError):
        OpenSearch(url)


def test_partial_bulk_and_shard_responses_fail_closed():
    from wiseway.common import ApiError
    from wiseway.opensearch import _complete

    for value in (
        {},
        {"_shards": {"total": 2, "successful": 1, "failed": 0}},
        {"timed_out": True, "_shards": {"total": 2, "successful": 2, "failed": 0}},
    ):
        with pytest.raises(ApiError, match="недоступен"):
            _complete(value)
    with OpenSearch("http://127.0.0.1:1", allow_http=True) as client:
        client.request = lambda *a, **k: {"items": [{"index": {"status": 429}}]}
        with pytest.raises(ApiError):
            client.bulk("wiseway-test", [({"id": "test", "deleted": True}, 1)])


def test_exact_facets_span_multiple_composite_pages(indexed):
    from wiseway.search import build_item

    schema = {
        "schema_set_version": "wide-schema",
        "root_levels": [("level-section", "Раздел", [f"Folder {n}" for n in range(1003)], False)],
        "tail_by_company": {},
    }
    root = {**ROOT, "schema_set_version": "wide-schema"}
    rows = [
        build_item(
            root["root_id"],
            root["display_prefix"],
            f"Folder {n}/report.txt",
            1,
            root["indexed_at"],
            schema,
            f"wide-{n}",
        )
        for n in range(1003)
    ]
    snapshot, _ = indexed(rows, root)
    snapshot.manifest["_schema"] = schema
    body = {
        "request_state_id": "wide",
        "root_id": root["root_id"],
        "schema_set_version": "wide-schema",
        "query_text": "report",
        "selected_marker_ids": [],
        "facet_prefix": "Folder 10",
        "sort": {"field": "PATH", "direction": "ASC"},
    }
    assert snapshot.search(body, 7) == search(root, rows, body, 7)
    assert snapshot.facet(body) == facet(root, rows, body)


def test_real_import_through_authenticated_api(configured, engine, tmp_path):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from test_api import login
    from test_archive_import import row, source, root_id
    from wiseway.app import create_app
    from wiseway.archive_import import ArchiveImporter
    from wiseway.services import Context

    settings = replace(configured, search_url=os.environ["WISEWAY_TEST_SEARCH_URL"], search_allow_http=True)
    ctx = Context(settings)
    try:
        root = root_id(ctx)
        result = ArchiveImporter(ctx, engine, shards=2).run(root, source(tmp_path / "api.ndjson", [row()]))
        try:
            with TestClient(create_app(settings), base_url="http://localhost:8000") as client:
                body = {
                    "request_state_id": "integration",
                    "root_id": root,
                    "schema_set_version": "schema-demo-1",
                    "selected_marker_ids": [],
                    "query_text": "file",
                    "sort": {"field": "RELEVANCE", "direction": "DESC"},
                    "facet_prefix": "",
                }
                assert client.post("/api/v1/search", json=body).status_code == 401
                login(client)
                response = client.post("/api/v1/search", json=body)
                assert response.status_code == 200, response.text
                assert response.json()["total"] == 1
                assert response.json()["items"][0]["item_id"] == "file-1"
                assert "_pit_id" not in response.text
                with ctx.store.transaction(write=False) as tx:
                    manifest = tx.get("index", root)
                engine.close_pit(manifest["_pit_id"])
                assert client.post("/api/v1/search", json={**body, "query_text": "file 1"}).status_code == 503
        finally:
            engine.request("DELETE", "/" + result["index"])
    finally:
        ctx.close()


def test_long_encoded_tokens_are_not_split(indexed):
    from wiseway.search import build_item

    name = "я" * 100
    rows = [
        build_item(
            ROOT["root_id"],
            ROOT["display_prefix"],
            f"Archive/Atlas/Orion_2031/Reports/{name}.txt",
            1,
            ROOT["indexed_at"],
            DEMO_SCHEMAS["schema-demo-1"],
            "long-token",
        )
    ]
    snapshot, _ = indexed(rows)
    body = {
        "request_state_id": "long",
        "root_id": ROOT["root_id"],
        "schema_set_version": ROOT["schema_set_version"],
        "query_text": name,
        "selected_marker_ids": [],
        "sort": {"field": "RELEVANCE", "direction": "DESC"},
    }
    assert snapshot.search(body) == search(ROOT, rows, body)


def test_lost_snapshot_recovery_refuses_partial_delta(configured, engine, tmp_path):
    from test_archive_import import row, source, root_id
    from wiseway.archive_import import ArchiveImporter
    from wiseway.common import ApiError
    from wiseway.services import Context

    ctx = Context(configured)
    importer = ArchiveImporter(ctx, engine, shards=2)
    root = root_id(ctx)
    result = importer.run(root, source(tmp_path / "full.ndjson", [row()]))
    try:
        with ctx.store.transaction(write=False) as tx:
            old = tx.get("index", root)
        engine.close_pit(old["_pit_id"])
        assert importer.maintain() == {"renewed": 1}
        with ctx.store.transaction(write=False) as tx:
            recovered = tx.get("index", root)
        assert recovered["_pit_id"] != old["_pit_id"]
        assert recovered["root"]["index_generation"] != old["root"]["index_generation"]
        real_bulk = engine.bulk

        def failing_bulk(name, records):
            real_bulk(name, records)
            raise ApiError("SEARCH_UNAVAILABLE", status=503)

        engine.bulk = failing_bulk
        delta = source(tmp_path / "delta.ndjson", [row("next")])
        with pytest.raises(ApiError):
            importer.run(root, delta, mode="delta", base_generation=recovered["root"]["index_generation"])
        engine.bulk = real_bulk
        engine.close_pit(recovered["_pit_id"])
        with pytest.raises(RuntimeError, match="pending"):
            importer.maintain()
        importer.run(root, delta, mode="delta", base_generation=recovered["root"]["index_generation"])
        assert importer.maintain() == {"renewed": 1}
        with ctx.store.transaction(write=False) as tx:
            final = tx.get("index", root)
        engine.close_pit(final["_pit_id"])
    finally:
        ctx.close()
        engine.request("DELETE", "/" + result["index"])


def test_tls_verifies_ca_and_hostname_and_uses_file_credentials(tmp_path):
    import base64
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import shutil
    import ssl
    import subprocess
    from threading import Thread
    from wiseway.common import ApiError

    executable = shutil.which("openssl")
    if not executable:
        pytest.skip("openssl executable is required for ephemeral TLS test certificates")
    cert, key = tmp_path / "test.pem", tmp_path / "test.key"
    subprocess.run(
        [
            executable,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        capture_output=True,
    )
    expected = "Basic " + base64.b64encode(b"test-user:test-password").decode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status = 200 if self.headers.get("Authorization") == expected else 401
            self.send_response(status)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    credentials = tmp_path / "credentials.json"
    credentials.write_text(json.dumps({"username": "test-user", "password": "test-password"}))
    try:
        port = server.server_port
        with OpenSearch(f"https://localhost:{port}", ca_file=cert, credentials_file=credentials) as client:
            assert client.request("GET", "/") == {}
        for url, ca in ((f"https://127.0.0.1:{port}", cert), (f"https://localhost:{port}", None)):
            with OpenSearch(url, ca_file=ca, credentials_file=credentials, timeout=3) as client:
                with pytest.raises(ApiError) as failure:
                    client.request("GET", "/")
                assert isinstance(failure.value.__context__, ssl.SSLCertVerificationError)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_wide_exact_name_ranking_keeps_lower_score_rows_out_of_top_k(indexed, monkeypatch):
    monkeypatch.setattr("wiseway.opensearch._MAX_SCORE_PROBE_THRESHOLD", 0)
    from wiseway.search import build_item

    rows = [
        build_item(
            ROOT["root_id"],
            ROOT["display_prefix"],
            f"Archive/Atlas/Orion_2031/Reports/{name}-{n}.txt",
            n,
            ROOT["indexed_at"],
            DEMO_SCHEMAS["schema-demo-1"],
            f"row-{n}",
        )
        for n, name in enumerate(["report"] * 220 + ["reporting"] * 120)
    ]
    snapshot, _ = indexed(rows)
    for text in ("report", "rep", '"report 10"', "atlas report"):
        body = {
            "request_state_id": "wide-ranking",
            "root_id": ROOT["root_id"],
            "schema_set_version": ROOT["schema_set_version"],
            "query_text": text,
            "selected_marker_ids": [],
            "sort": {"field": "RELEVANCE", "direction": "DESC"},
        }
        assert snapshot.search(body) == search(ROOT, rows, body)


def test_exact_filename_fast_path_does_not_admit_earlier_prefix_paths(indexed):
    """The maximum-score shortcut must use an exact filename term, not a prefix."""
    from wiseway.search import build_item

    rows = [
        *[
            build_item(
                ROOT["root_id"],
                ROOT["display_prefix"],
                f"Archive/Atlas/Polaris_2030/Reports/reporting-{number}.txt",
                number,
                ROOT["indexed_at"],
                DEMO_SCHEMAS["schema-demo-1"],
                f"prefix-{number}",
            )
            for number in range(100)
        ],
        *[
            build_item(
                ROOT["root_id"],
                ROOT["display_prefix"],
                f"Archive/Nova/Polaris_2030/North/Reports/report-{number}.txt",
                number,
                ROOT["indexed_at"],
                DEMO_SCHEMAS["schema-demo-1"],
                f"exact-{number}",
            )
            for number in range(100)
        ],
    ]
    snapshot, _ = indexed(rows)
    body = {
        "request_state_id": "exact-name",
        "root_id": ROOT["root_id"],
        "schema_set_version": ROOT["schema_set_version"],
        "query_text": "report",
        "selected_marker_ids": [],
        "sort": {"field": "RELEVANCE", "direction": "DESC"},
    }
    actual = snapshot.search(body)
    assert actual == search(ROOT, rows, body)
    assert all(item["item_id"].startswith("exact-") for item in actual["items"])


def test_eight_part_relevance_fallback_uses_bounded_engine_requests(indexed, monkeypatch):
    """A no-filename-match query must not make one round trip per score level."""
    from wiseway.search import build_item

    values = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel")
    schema = {
        "schema_set_version": "eight-levels",
        "root_levels": [(f"level-{number}", value, {value}, False) for number, value in enumerate(values)],
        "tail_by_company": {},
    }
    root = {**ROOT, "schema_set_version": "eight-levels"}
    rows = [
        build_item(
            root["root_id"],
            root["display_prefix"],
            "/".join((*values, f"neutral-{number}.txt")),
            number,
            root["indexed_at"],
            schema,
            f"eight-{number}",
        )
        for number in range(30)
    ]
    snapshot, _ = indexed(rows, root)
    snapshot.manifest["_schema"] = schema
    monkeypatch.setattr("wiseway.opensearch._MAX_SCORE_PROBE_THRESHOLD", 0)
    calls = []
    original = snapshot.engine.request

    def counted(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(snapshot.engine, "request", counted)
    body = {
        "request_state_id": "eight-parts",
        "root_id": root["root_id"],
        "schema_set_version": root["schema_set_version"],
        "query_text": " ".join(values),
        "selected_marker_ids": [],
        "sort": {"field": "RELEVANCE", "direction": "DESC"},
    }
    assert snapshot.search(body, 7) == search(root, rows, body, 7)
    # count/facet + exact-name fast path + one probe for each of the eight
    # clauses + maximum-score intersection.  A full scorer is only a fallback.
    assert len(calls) <= 11
    probes = [args[2] for args, _ in calls if args[2].get("_source") is False]
    assert len(probes) == 8
    assert all(probe["sort"] == [{"_score": "desc"}] for probe in probes)


def test_snapshot_compiles_schema_once_on_first_hydration(indexed, monkeypatch):
    from wiseway import opensearch

    rows = list(build_items(golden()).values())[:2]
    snapshot, _ = indexed(rows)
    calls = []
    original = opensearch.compile_schema

    def counted(schema):
        calls.append(schema)
        return original(schema)

    monkeypatch.setattr(opensearch, "compile_schema", counted)
    snapshot._item(document(rows[0]))
    snapshot._item(document(rows[1]))
    assert len(calls) == 1


def test_non_cooccurring_score_maxima_fall_back_to_exact_ranking(indexed, monkeypatch):
    from copy import deepcopy
    from wiseway.search import build_item

    monkeypatch.setattr("wiseway.opensearch._MAX_SCORE_PROBE_THRESHOLD", 0)
    schema = deepcopy(DEMO_SCHEMAS["schema-demo-1"])
    schema["root_levels"] = (
        *schema["root_levels"][:2],
        ("level-project", "Проект", frozenset({"A", "B"}), False),
    )
    rows = [
        build_item(
            ROOT["root_id"],
            ROOT["display_prefix"],
            f"Archive/Atlas/{project}/Reports/{filename}.txt",
            1,
            ROOT["indexed_at"],
            schema,
            f"row-{project}",
        )
        for project, filename in (("A", "B"), ("B", "A"))
    ]
    snapshot, _ = indexed(rows)
    snapshot.manifest["_schema"] = schema
    body = {
        "request_state_id": "fallback",
        "root_id": ROOT["root_id"],
        "schema_set_version": ROOT["schema_set_version"],
        "query_text": "a b",
        "selected_marker_ids": [],
        "sort": {"field": "RELEVANCE", "direction": "DESC"},
    }
    assert snapshot.search(body) == search(ROOT, rows, body)
