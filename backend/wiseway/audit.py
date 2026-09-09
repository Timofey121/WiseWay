from .common import ApiError, timestamp, uid, utc

SYSTEM_ACTIONS = {
    "LOGIN_SUCCEEDED",
    "LOGIN_FAILED",
    "LOGOUT",
    "ACCOUNT_BLOCKED",
    "ACCOUNT_CREATED",
    "ACCOUNT_UNBLOCKED",
    "PASSWORD_CHANGED",
}


def emit(tx, actor, action, request_id, *, now=None, result="SUCCESS", **links):
    event = dict.fromkeys(
        (
            "operation_id",
            "source_attempt_id",
            "company_id",
            "dictionary_id",
            "version_id",
            "rule_set_id",
            "batch_id",
            "attempt_id",
            "item_id",
            "source",
            "target",
            "reason_code",
            "comment",
        )
    )
    event.update(
        event_id=uid("event"),
        occurred_at=utc(now),
        actor=actor,
        category="SYSTEM" if action in SYSTEM_ACTIONS else "BUSINESS",
        action=action,
        result=result,
        request_id=request_id,
    )
    event.update(links)
    tx.append_event(event)
    return event


def visible_events(tx, actor, *, events=None):
    source = tx.events() if events is None else events
    return [e for e in source if actor["role"] == "ADMIN" or e["category"] == "BUSINESS"]


def query_events(tx, actor, body, *, events=None):
    start, end = timestamp(body["from"]), timestamp(body["to"])
    if start >= end:
        raise ApiError("VALIDATION_ERROR", "Начало периода должно предшествовать концу.", 422)
    if body["action"] in SYSTEM_ACTIONS and actor["role"] != "ADMIN":
        raise ApiError("FORBIDDEN", "Системный журнал доступен администратору.", 403)
    events = visible_events(tx, actor) if events is None else events
    text = body["query_text"].casefold()
    return sorted(
        [
            e
            for e in events
            if start <= timestamp(e["occurred_at"]) < end
            and all(body[k] is None or e[k] == body[k] for k in ("company_id", "action", "result"))
            and (body["actor_id"] is None or (e["actor"] and e["actor"]["user_id"] == body["actor_id"]))
            and (
                not text
                or any(
                    text in (e.get(k) or {}).get("display_path", "").casefold() for k in ("source", "target")
                )
            )
        ],
        key=lambda e: (timestamp(e["occurred_at"]), e["event_id"]),
        reverse=True,
    )
