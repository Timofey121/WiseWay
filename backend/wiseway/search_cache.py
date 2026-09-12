"""Small snapshot-scoped response cache with bounded stampede protection."""

from collections import OrderedDict
import hashlib
import json
from threading import Lock
from time import monotonic


class SearchCache:
    def __init__(self, *, max_bytes=8 * 1024 * 1024, max_entries=64, ttl=30, clock=monotonic):
        self.max_bytes, self.max_entries, self.ttl, self.clock = max_bytes, max_entries, ttl, clock
        self.values = OrderedDict()
        self.bytes = 0
        self.lock = Lock()
        # Fixed stripes bound synchronization state under arbitrary query input.
        self.stripes = [Lock() for _ in range(32)]

    def get(self, generation, operation, request, compute):
        if not self.max_bytes:
            return compute()
        body = {k: v for k, v in request.items() if k != "request_state_id"}
        key = hashlib.sha256(json.dumps([generation, operation, body], sort_keys=True).encode()).digest()
        with self.stripes[key[0] % len(self.stripes)]:
            with self.lock:
                saved = self.values.pop(key, None)
                if saved is not None:
                    self.bytes -= len(saved[1])
                    if saved[0] > self.clock():
                        self.values[key] = saved
                        self.bytes += len(saved[1])
                        return {**json.loads(saved[1]), "request_state_id": request["request_state_id"]}
            result = compute()
            payload = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()
            if len(payload) <= self.max_bytes:
                with self.lock:
                    while self.values and (
                        self.bytes + len(payload) > self.max_bytes or len(self.values) >= self.max_entries
                    ):
                        _, (_, removed) = self.values.popitem(last=False)
                        self.bytes -= len(removed)
                    self.values[key] = self.clock() + self.ttl, payload
                    self.bytes += len(payload)
            return result
