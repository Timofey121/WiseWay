"""Consistency and visibility checks for the immutable audit-read cache."""

from wiseway.audit import emit, visible_events
from wiseway.storage import UnitOfWork


def test_audit_cache_byte_budget_counts_utf8_bytes(client, monkeypatch):
    import json
    import wiseway.services as services

    context = client.app.state.ctx
    event = {"event_id": "unicode-event", "comment": "я" * 100}
    encoded = json.dumps(event, ensure_ascii=False)
    monkeypatch.setattr(services, "MAX_AUDIT_CACHE_BYTES", len(encoded) + 1)
    with context.store.transaction() as writer:
        writer.append_event(event)
    with context.store.transaction(write=False) as reader:
        assert context.read_audit(reader) == [event]
    assert context._audit_cache is None


def test_read_audit_reuses_the_same_append_only_snapshot_without_reparsing(client, monkeypatch):
    context = client.app.state.ctx
    calls = 0
    original = UnitOfWork.events

    def count_events(self):
        nonlocal calls
        calls += 1
        return original(self)

    monkeypatch.setattr(UnitOfWork, "events", count_events)
    with context.store.transaction(write=False) as first:
        first_events = context.read_audit(first)
    with context.store.transaction(write=False) as second:
        second_events = context.read_audit(second)

    assert calls == 1
    assert second_events is first_events


def test_read_audit_keeps_an_open_reader_on_its_original_snapshot_after_append(client):
    context = client.app.state.ctx
    actor = {"user_id": "audit-test", "login": "audit-test", "display_name": "Audit test", "role": "WORKER"}
    with context.store.transaction(write=False) as old_reader:
        before = context.read_audit(old_reader)
        with context.store.transaction() as writer:
            created = emit(writer, actor, "DRAFT_SAVED", "request-audit-cache", now=context.settings.clock())
        assert created["event_id"] not in {event["event_id"] for event in context.read_audit(old_reader)}
    with context.store.transaction(write=False) as new_reader:
        after = context.read_audit(new_reader)
    assert created["event_id"] in {event["event_id"] for event in after}
    assert len(after) == len(before) + 1


def test_cached_audit_events_still_hide_system_events_from_workers(client):
    context = client.app.state.ctx
    worker = {"user_id": "worker", "login": "worker", "display_name": "Worker", "role": "WORKER"}
    admin = {"user_id": "admin", "login": "admin", "display_name": "Admin", "role": "ADMIN"}
    with context.store.transaction() as writer:
        system = emit(writer, admin, "ACCOUNT_BLOCKED", "request-system", now=context.settings.clock())
    with context.store.transaction(write=False) as reader:
        cached = context.read_audit(reader)
        worker_visible = visible_events(reader, worker, events=cached)
        admin_visible = visible_events(reader, admin, events=cached)

    assert system["event_id"] not in {event["event_id"] for event in worker_visible}
    assert system["event_id"] in {event["event_id"] for event in admin_visible}
