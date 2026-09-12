from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

from test_api import login


def test_slow_search_does_not_block_session_requests(client, monkeypatch):
    import wiseway.app as application

    login(client)
    original = application.dispatch
    started, release, lock = Event(), Event(), Lock()
    active = 0

    def blocked(ctx, tx, name, actor, params, body, request_id):
        nonlocal active
        if name == "searchFiles":
            with lock:
                active += 1
                if active == 4:
                    started.set()
            assert release.wait(5)
        return original(ctx, tx, name, actor, params, body, request_id)

    monkeypatch.setattr(application, "dispatch", blocked)
    body = {
        "request_state_id": "slow",
        "root_id": "archive-root",
        "schema_set_version": "schema-demo-1",
        "selected_marker_ids": [],
        "query_text": "report",
        "sort": {"field": "RELEVANCE", "direction": "DESC"},
        "facet_prefix": "",
    }
    with ThreadPoolExecutor(max_workers=5) as pool:
        searches = [pool.submit(client.post, "/api/v1/search", json=body) for _ in range(4)]
        try:
            assert started.wait(3)
            session = pool.submit(client.get, "/api/v1/session")
            assert session.result(timeout=1).status_code == 200
        finally:
            release.set()
            for future in searches:
                future.result(timeout=5)
