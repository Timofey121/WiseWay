"""Backend-executable acceptance checks for Q-004 through Q-014.

The expected IDs in this module are written from the synthetic corpus below,
instead of being calculated through the search implementation under test.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from wiseway.indexer import Indexer
from wiseway.search import DEMO_SCHEMAS, build_item

from test_api import login


def _request(root: dict, state: str, query: str = "", *, markers: list[str] | None = None, sort=None):
    return {
        "request_state_id": state,
        "root_id": root["root_id"],
        "schema_set_version": root["schema_set_version"],
        "selected_marker_ids": markers or [],
        "query_text": query,
        "sort": sort or {"field": "PATH", "direction": "ASC"},
        "facet_prefix": "",
    }


def _publish_index(client, root_id: str, paths: list[tuple[str, str]]) -> dict:
    """Replace one synthetic index with explicitly named acceptance fixtures."""
    ctx = client.app.state.ctx
    with ctx.store.transaction() as tx:
        root = tx.require("root", root_id)
        root = {**root, "index_generation": "acceptance-search-generation"}
        items = [
            build_item(
                root_id,
                root["display_prefix"],
                path,
                ordinal,
                f"2031-01-{(ordinal % 28) + 1:02d}T00:00:00Z",
                DEMO_SCHEMAS[root["schema_set_version"]],
                item_id,
            )
            for ordinal, (item_id, path) in enumerate(paths)
        ]
        tx.put("root", root_id, root)
        tx.put("index", root_id, {"root": root, "items": items})
    return root


def test_q011_ranking_ties_and_schema_change_are_checked_at_the_http_boundary(client):
    login(client)
    root = _publish_index(
        client,
        "archive-root",
        [
            ("exact", "Archive/Atlas/Orion_2031/Reports/Atlas.txt"),
            ("prefix", "Archive/Nova/Polaris_2030/North/Reports/Atlasical.txt"),
        ],
    )
    ranked = client.post(
        "/api/v1/search",
        json=_request(root, "q011-rank", "atlas", sort={"field": "RELEVANCE", "direction": "DESC"}),
    )
    assert ranked.status_code == 200, ranked.text
    assert ranked.json()["index_generation"] == "acceptance-search-generation"
    assert [item["item_id"] for item in ranked.json()["items"]] == ["exact", "prefix"]

    root = _publish_index(
        client,
        "archive-root",
        [
            ("tie-10", "Archive/Atlas/Orion_2031/Reports/Report 10.txt"),
            ("tie-2", "Archive/Atlas/Orion_2031/Reports/Report 2.txt"),
        ],
    )
    tied = client.post(
        "/api/v1/search",
        json=_request(root, "q011-tie", "report", sort={"field": "RELEVANCE", "direction": "DESC"}),
    )
    assert tied.status_code == 200, tied.text
    assert [item["item_id"] for item in tied.json()["items"]] == ["tie-2", "tie-10"]

    stale_schema = client.post(
        "/api/v1/search",
        json={
            **_request(root, "q011-stale", "atlas", sort={"field": "RELEVANCE", "direction": "DESC"}),
            "schema_set_version": "obsolete-schema",
        },
    )
    assert stale_schema.status_code == 409
    assert stale_schema.json()["error"]["code"] == "SCHEMA_VERSION_CHANGED"


def test_q012_unrecognized_marker_is_terminal_and_raw_case_variants_remain_distinct(client):
    login(client)
    root = _publish_index(
        client,
        "archive-root",
        [
            ("upper", "Archive/Atlas/Orion_2031/Reports/upper.txt"),
            ("lower", "Archive/atlas/Orion_2031/Reports/lower.txt"),
            ("invalid", "Archive/Atlas/NotAProject/Reports/lost.txt"),
        ],
    )
    variants = client.post(
        "/api/v1/search",
        json=_request(root, "q012-variants", "atlas", sort={"field": "PATH", "direction": "ASC"}),
    )
    assert variants.status_code == 200, variants.text
    rows = {row["item_id"]: row for row in variants.json()["items"]}
    assert set(rows) == {"upper", "lower", "invalid"}
    assert rows["upper"]["markers"][1]["marker_id"] != rows["lower"]["markers"][1]["marker_id"]
    assert rows["invalid"]["structure_status"] == "UNRECOGNIZED"
    assert rows["invalid"]["structure_issue"]["code"] == "INVALID_LEVEL_VALUE"

    archive_marker = rows["invalid"]["markers"][0]["marker_id"]
    atlas_marker = rows["invalid"]["markers"][1]["marker_id"]
    invalid_marker = rows["invalid"]["markers"][2]["marker_id"]
    terminal = client.post(
        "/api/v1/search",
        json=_request(root, "q012-terminal", markers=[archive_marker, atlas_marker, invalid_marker]),
    )
    assert terminal.status_code == 200, terminal.text
    assert terminal.json()["next_facet"] is None
    unknown = client.post(
        "/api/v1/search",
        json=_request(root, "q012-unknown", markers=[archive_marker, atlas_marker, "marker-unknown"]),
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "INVALID_MARKER_SELECTION"


def test_q014_real_external_create_rename_and_delete_are_visible_only_as_current_metadata(client, configured):
    """The indexer sees filesystem metadata changes without reading file content."""
    login(client)
    context = client.app.state.ctx
    folder = configured.sandbox_dir / "Archive/Atlas/Orion_2031/Reports"
    created = folder / "createdonly.weird"
    created.write_bytes(b"contenttokenonly")
    Indexer(context).scan()
    with context.store.transaction(write=False) as tx:
        root = tx.require("index", "archive-root")["root"]

    created_result = client.post(
        "/api/v1/search",
        json=_request(root, "q014-created", "createdonly", sort={"field": "RELEVANCE", "direction": "DESC"}),
    )
    assert created_result.status_code == 200, created_result.text
    assert [row["filename"] for row in created_result.json()["items"]] == ["createdonly.weird"]
    content_result = client.post(
        "/api/v1/search",
        json=_request(
            root, "q014-content", "contenttokenonly", sort={"field": "RELEVANCE", "direction": "DESC"}
        ),
    )
    assert content_result.status_code == 200
    assert content_result.json()["total"] == 0

    renamed = folder / "renamedonly.weird"
    created.rename(renamed)
    Indexer(context).scan()
    old_name = client.post(
        "/api/v1/search",
        json=_request(root, "q014-old", "createdonly", sort={"field": "RELEVANCE", "direction": "DESC"}),
    )
    new_name = client.post(
        "/api/v1/search",
        json=_request(root, "q014-new", "renamedonly", sort={"field": "RELEVANCE", "direction": "DESC"}),
    )
    assert old_name.status_code == new_name.status_code == 200
    assert old_name.json()["total"] == 0
    assert [row["filename"] for row in new_name.json()["items"]] == ["renamedonly.weird"]

    renamed.unlink()
    Indexer(context).scan()
    deleted = client.post(
        "/api/v1/search",
        json=_request(root, "q014-deleted", "renamedonly", sort={"field": "RELEVANCE", "direction": "DESC"}),
    )
    assert deleted.status_code == 200
    assert deleted.json()["total"] == 0


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses directory read permissions")
def test_q014_permission_denied_scan_keeps_published_generation_and_recovers(client, configured):
    """A real unreadable child directory must leave the last complete index intact."""
    login(client)
    context = client.app.state.ctx
    folder = configured.sandbox_dir / "Archive/Atlas/Orion_2031/Reports"
    original_mode = folder.stat().st_mode & 0o777
    with context.store.transaction(write=False) as tx:
        before = tx.require("index", "archive-root")
        before_generation = before["root"]["index_generation"]
        before_ids = [item["item_id"] for item in before["items"]]
    try:
        folder.chmod(0)
        Indexer(context).scan()
    finally:
        folder.chmod(original_mode)
    with context.store.transaction(write=False) as tx:
        failed = tx.require("index", "archive-root")
        progress = tx.require("index_progress", "archive-root")
    assert failed["root"]["index_generation"] == before_generation
    assert [item["item_id"] for item in failed["items"]] == before_ids
    assert failed["freshness"]["status"] == "STALE"
    assert progress["status"] == "FAILED"

    Indexer(context).scan()
    with context.store.transaction(write=False) as tx:
        recovered = tx.require("index", "archive-root")
        progress = tx.require("index_progress", "archive-root")
    assert recovered["root"]["index_generation"] == before_generation
    assert recovered["freshness"]["status"] == "CURRENT"
    assert progress["status"] == "COMPLETE"


def test_q014_separate_worker_process_observes_new_file_within_refresh_budget(client, configured):
    """A local worker process discovers a small synthetic file well below the 300 s contract bound."""
    csrf = login(client)
    context = client.app.state.ctx
    environment = {
        **os.environ,
        "WISEWAY_DATA_DIR": str(configured.data_dir),
        "WISEWAY_SANDBOX_DIR": str(configured.sandbox_dir),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "wiseway", "worker"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        initial_deadline = time.monotonic() + 10
        while time.monotonic() < initial_deadline:
            with context.store.transaction(write=False) as tx:
                if tx.get("operator_state", "worker", {}).get("last_completed_at"):
                    break
            time.sleep(0.1)
        else:
            raise AssertionError("separate worker did not complete its initial cycle")

        filename = "file-acceptance-worker-refresh.pdf"
        (configured.sandbox_dir / "Incoming/Atlas" / filename).write_bytes(b"worker refresh")
        company = client.get("/api/v1/companies").json()["items"][0]["company_id"]
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            response = client.post(
                "/api/v1/sorting/queue/query",
                json={
                    "company_id": company,
                    "filters": {"statuses": ["READY"], "query_text": filename},
                    "cursor": None,
                    "limit": 100,
                },
            )
            assert response.status_code == 200, response.text
            if [item["filename"] for item in response.json()["items"]] == [filename]:
                break
            time.sleep(0.1)
        else:
            raise AssertionError("worker did not publish the new READY file within 20 seconds")
        assert csrf
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        assert process.returncode in {-15, 0}


def test_q004_q006_two_roots_idle_facets_and_missing_root_are_server_verified(client):
    login(client)
    roots = client.get("/api/v1/roots")
    assert roots.status_code == 200, roots.text
    searchable = {root["root_id"]: root for root in roots.json()["items"]}
    assert set(searchable) == {"archive-root", "reference-root"}

    archive = searchable["archive-root"]
    idle = client.post("/api/v1/search", json=_request(archive, "q004-idle"))
    assert idle.status_code == 200, idle.text
    assert idle.json()["mode"] == "IDLE"
    assert idle.json()["items"] == []
    assert idle.json()["total"] is None
    assert idle.json()["next_facet"]["level_id"] == "level-section"
    assert [option["raw_value"] for option in idle.json()["next_facet"]["options"]] == ["Archive"]
    reference = searchable["reference-root"]
    reference_idle = client.post("/api/v1/search", json=_request(reference, "q004-reference-idle"))
    assert reference_idle.status_code == 200, reference_idle.text
    assert (
        reference_idle.json()["mode"],
        reference_idle.json()["items"],
        reference_idle.json()["total"],
    ) == (
        "IDLE",
        [],
        None,
    )
    assert [option["raw_value"] for option in reference_idle.json()["next_facet"]["options"]] == ["Archive"]

    # A root is mandatory: there is no global-search fallback in the HTTP API.
    missing_root = client.post(
        "/api/v1/search",
        json={key: value for key, value in _request(archive, "q004-no-root").items() if key != "root_id"},
    )
    assert missing_root.status_code == 422
    assert missing_root.json()["error"]["code"] == "VALIDATION_ERROR"

    facet = client.post(
        "/api/v1/search/facet",
        json={key: value for key, value in _request(archive, "q006-facet", "atlas").items() if key != "sort"},
    )
    assert facet.status_code == 200, facet.text
    assert facet.json()["request_state_id"] == "q006-facet"
    assert facet.json()["facet"]["level_id"] == "level-section"
    selected_facet = client.post(
        "/api/v1/search/facet",
        json={
            **{key: value for key, value in _request(archive, "q006-selected").items() if key != "sort"},
            "selected_marker_ids": [idle.json()["next_facet"]["options"][0]["marker_id"]],
        },
    )
    assert selected_facet.status_code == 200, selected_facet.text
    assert selected_facet.json()["facet"]["level_id"] == "level-company"
    assert [option["raw_value"] for option in selected_facet.json()["facet"]["options"]] == ["Atlas", "Nova"]


def test_q007_to_q013_search_and_phrase_boundaries_sorting_and_limit_through_api(client):
    login(client)
    root = _publish_index(
        client,
        "archive-root",
        [
            ("path-hit", "Archive/Atlas/Orion_2031/Reports/atlas-reports.txt"),
            ("only-atlas", "Archive/Atlas/Orion_2031/Data/atlas.txt"),
            ("only-reports", "Archive/Nova/Polaris_2030/North/Reports/readme.txt"),
        ],
    )
    and_result = client.post(
        "/api/v1/search",
        json=_request(root, "q007-and", "ATLAS reports", sort={"field": "RELEVANCE", "direction": "DESC"}),
    )
    assert and_result.status_code == 200, and_result.text
    assert [row["item_id"] for row in and_result.json()["items"]] == ["path-hit"]

    paths = [
        ("phrase-hit", "Archive/Atlas/Orion_2031/Reports/Atlas-Main-Metrics.txt"),
        ("phrase-gap", "Archive/Atlas/Orion_2031/Reports/Atlas-Final-Main-Metrics.txt"),
        ("phrase-prefix", "Archive/Atlas/Orion_2031/Reports/Atlas-Maintenance-Metrics.txt"),
        ("phrase-reversed", "Archive/Atlas/Orion_2031/Reports/Main-Atlas-Metrics.txt"),
        ("separator-space", "Archive/Atlas/Orion_2031/Reports/met rics.txt"),
        ("separator-dash", "Archive/Atlas/Orion_2031/Reports/met-rics.txt"),
        ("separator-under", "Archive/Atlas/Orion_2031/Reports/met_rics.txt"),
        ("separator-dot", "Archive/Atlas/Orion_2031/Reports/met.rics.txt"),
        ("separator-slash", "Archive/Atlas/Orion_2031/Reports/met/rics.txt"),
        ("separator-backslash", "Archive/Atlas/Orion_2031/Reports/met\\rics.txt"),
        ("separator-digit", "Archive/Atlas/Orion_2031/Reports/met2rics.txt"),
        ("inner-substring", "Archive/Atlas/Orion_2031/Reports/symmetry.txt"),
    ]
    root = _publish_index(client, "archive-root", paths)

    phrase = client.post(
        "/api/v1/search",
        json=_request(
            root, "q008-phrase", '"atlas main" met', sort={"field": "RELEVANCE", "direction": "DESC"}
        ),
    )
    assert phrase.status_code == 200, phrase.text
    assert [row["item_id"] for row in phrase.json()["items"]] == ["phrase-hit"]

    boundaries = client.post(
        "/api/v1/search",
        json=_request(root, "q009-boundaries", "met", sort={"field": "PATH", "direction": "ASC"}),
    )
    assert boundaries.status_code == 200, boundaries.text
    assert {row["item_id"] for row in boundaries.json()["items"]} >= {
        "separator-space",
        "separator-dash",
        "separator-under",
        "separator-dot",
        "separator-slash",
        "separator-backslash",
        "separator-digit",
    }
    assert "inner-substring" not in {row["item_id"] for row in boundaries.json()["items"]}

    root = _publish_index(
        client,
        "archive-root",
        [
            (f"limit-{number:03d}", f"Archive/Atlas/Orion_2031/Reports/limit-{number}.txt")
            for number in range(103)
        ],
    )
    limited = client.post(
        "/api/v1/search",
        json=_request(root, "q013-limit", "limit", sort={"field": "PATH", "direction": "ASC"}),
    )
    assert limited.status_code == 200, limited.text
    payload = limited.json()
    assert (payload["total"], payload["returned_count"], payload["result_limit"], payload["limited"]) == (
        103,
        100,
        100,
        True,
    )
    assert [row["item_id"] for row in payload["items"][:3]] == ["limit-000", "limit-001", "limit-002"]
    assert payload["items"][-1]["item_id"] == "limit-099"
    assert {
        "filename",
        "location",
        "markers",
        "extension",
        "size_bytes",
        "modified_at",
        "structure_status",
    } <= set(payload["items"][0])
