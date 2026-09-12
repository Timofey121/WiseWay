"""A slow read must leave the SQLite writer available to the worker."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from test_api import login


def test_search_computation_does_not_hold_sqlite_writer(client, configured, monkeypatch):
    from wiseway import search as search_module

    login(client)
    root = client.get("/api/v1/roots").json()["items"][0]
    entered, release = Event(), Event()
    original = search_module.search

    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(search_module, "search", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(
            client.post,
            "/api/v1/search",
            json={
                "request_state_id": "state-concurrent-read",
                "root_id": root["root_id"],
                "schema_set_version": root["schema_set_version"],
                "selected_marker_ids": [],
                "query_text": "atlas",
                "sort": {"field": "RELEVANCE", "direction": "DESC"},
                "facet_prefix": "",
            },
        )
        try:
            assert entered.wait(5)
            connection = sqlite3.connect(configured.database, timeout=0.1)
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.rollback()
            finally:
                connection.close()
        finally:
            release.set()
        response = running.result(timeout=5)
        assert response.status_code == 200, response.text


def test_authentication_read_does_not_wait_for_unrelated_writer(client, configured):
    from wiseway.auth import Auth

    login(client)
    token = client.cookies.get("wiseway_session")
    auth = Auth(client.app.state.ctx.store, configured)
    blocked = False
    with ThreadPoolExecutor(max_workers=1) as pool:
        with client.app.state.ctx.store.transaction():
            task = pool.submit(auth.authenticate, token)
            # Avoid a deadlock on a broken implementation: release the writer before joining.
            try:
                actor = task.result(timeout=0.2)[1]
            except TimeoutError:
                blocked = True
        actor = task.result(timeout=5)[1]
    assert not blocked, "Authentication reads blocked behind the SQLite writer"
    assert actor["login"] == "worker-atlas"


def test_audit_filtering_does_not_hold_sqlite_writer(client, configured, monkeypatch):
    from wiseway import app as app_module

    login(client)
    entered, release = Event(), Event()
    original = app_module.query_events

    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(app_module, "query_events", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            client.post,
            "/api/v1/audit/query",
            json={
                "company_id": None,
                "from": "2020-01-01T00:00:00Z",
                "to": "2099-01-01T00:00:00Z",
                "actor_id": None,
                "action": None,
                "result": None,
                "query_text": "",
                "cursor": None,
                "limit": 100,
            },
        )
        try:
            assert entered.wait(5)
            connection = sqlite3.connect(configured.database, timeout=0.1)
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.rollback()
            finally:
                connection.close()
        finally:
            release.set()
        response = pending.result(timeout=5)
        assert response.status_code == 200, response.text
