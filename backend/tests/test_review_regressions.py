"""Contract cases independently derived during the backend review."""

import errno

import pytest

from test_api import login
from test_search import ROOT, item, request
from wiseway.audit import emit
from wiseway.common import timestamp
from wiseway.search import search


@pytest.mark.parametrize("field", ["NAME", "SIZE", "MODIFIED_AT"])
def test_descending_primary_sort_keeps_tied_paths_ascending(field):
    first = item("a", "Archive/Atlas/Orion_2031/Data/report.pdf")
    second = item("b", "Archive/Atlas/Orion_2031/Reports/report.pdf")
    result = search(ROOT, [second, first], request("report", sort={"field": field, "direction": "DESC"}))
    assert [value["item_id"] for value in result["items"]] == ["a", "b"]


def test_unrecognized_path_remains_searchable_by_plain_text():
    value = item("lost", "Archive/Atlas/UnknownProject/OtherDirectory/lost.pdf")
    result = search(ROOT, [value], request("unknown other"))
    assert result["total"] == 1
    assert result["items"][0]["structure_status"] == "UNRECOGNIZED"


def test_audit_interval_handles_fractional_seconds_numerically(client):
    login(client)
    actor = client.get("/api/v1/session").json()["actor"]
    with client.app.state.ctx.store.transaction() as tx:
        inside = emit(tx, actor, "DRAFT_SAVED", "request-inside", now=timestamp("2031-01-01T12:00:00.1Z"))
        emit(tx, actor, "DRAFT_SAVED", "request-outside", now=timestamp("2031-01-01T12:00:01.1Z"))
    response = client.post(
        "/api/v1/audit/query",
        json={
            "from": "2031-01-01T12:00:00Z",
            "to": "2031-01-01T12:00:01Z",
            "company_id": None,
            "actor_id": None,
            "action": None,
            "result": None,
            "query_text": "",
            "cursor": None,
            "limit": 100,
        },
    )
    assert response.status_code == 200, response.text
    assert [event["event_id"] for event in response.json()["items"]] == [inside["event_id"]]


def test_unreadable_subdirectory_does_not_publish_partial_generation(client, monkeypatch):
    from wiseway.indexer import Indexer
    from wiseway import filesystem

    ctx = client.app.state.ctx
    with ctx.store.transaction(write=False) as tx:
        before = tx.require("index", "archive-root")
    real_open = filesystem.os.open

    def unavailable(path, flags, *args, **kwargs):
        if path == "Atlas" and flags & filesystem.os.O_DIRECTORY:
            raise PermissionError(errno.EACCES, "synthetic denied directory")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(filesystem.os, "open", unavailable)
    Indexer(ctx).scan()
    with ctx.store.transaction(write=False) as tx:
        after = tx.require("index", "archive-root")
    assert after["root"]["index_generation"] == before["root"]["index_generation"]
    assert after["items"] == before["items"]
    assert after["freshness"]["status"] == "STALE"
