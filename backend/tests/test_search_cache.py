from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest

from wiseway.search_cache import SearchCache


def test_identical_concurrent_queries_share_one_computation():
    cache = SearchCache(max_bytes=10000)
    calls = 0
    lock = threading.Lock()
    ready = threading.Barrier(8)

    def one(n):
        nonlocal calls
        ready.wait(timeout=5)

        def compute():
            nonlocal calls
            with lock:
                calls += 1
            time.sleep(0.02)
            return {"request_state_id": str(n), "items": [{"id": "row"}]}

        return cache.get("generation", "search", {"request_state_id": str(n), "q": "x"}, compute)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(one, range(8)))
    assert calls == 1
    assert [r["request_state_id"] for r in results] == [str(n) for n in range(8)]
    results[0]["items"].clear()
    assert results[1]["items"] == [{"id": "row"}]


def test_cache_is_bounded_generation_scoped_and_does_not_cache_errors():
    now = [1]
    cache = SearchCache(max_bytes=100, max_entries=2, ttl=5, clock=lambda: now[0])
    calls = []

    def result():
        calls.append(1)
        return {"request_state_id": "state", "x": "a"}

    body = {"request_state_id": "state"}
    cache.get("first", "search", body, result)
    cache.get("first", "search", body, result)
    assert len(calls) == 1
    cache.get("second", "search", body, result)
    assert len(calls) == 2
    now[0] += 6
    cache.get("second", "search", body, result)
    assert len(calls) == 3
    for n in range(20):
        cache.get(str(n), "search", body, result)
    assert cache.bytes <= 100 and len(cache.values) <= 2
    with pytest.raises(ValueError):
        cache.get("broken", "search", body, lambda: (_ for _ in ()).throw(ValueError()))
    cache.get("broken", "search", body, result)
