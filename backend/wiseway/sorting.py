from .audit import emit
from .common import ApiError, digest, public, uid, utc, timestamp
from .dictionaries import flattened_rules, rule_set
from .rules import plan_counts

QUEUE_STATES = (
    "DISCOVERED",
    "WAITING_READY",
    "READY",
    "PROCESSING",
    "REQUIRES_DECISION",
    "RECOVERY_REQUIRED",
    "MISSING",
)


def queue_items(tx, company_id, filters):
    states = filters["statuses"] or [s for s in QUEUE_STATES if s != "MISSING"]
    text = filters["query_text"].casefold()
    return sorted(
        [
            q
            for q in tx.list("queue")
            if q["company_id"] == company_id
            and not q.get("_departed")
            and q["status"] in states
            and (
                not text or text in q["filename"].casefold() or text in q["source"]["display_path"].casefold()
            )
        ],
        key=lambda q: (q["source"]["display_path"].casefold(), q["source"]["display_path"], q["item_id"]),
    )


def queue_generation(tx, company_id):
    return (
        "queue-"
        + digest(
            [public(q) for q in tx.list("queue") if q["company_id"] == company_id and not q.get("_departed")]
        )[:32]
    )


class SortingService:
    def __init__(self, ctx):
        self.ctx = ctx

    def handle(self, operation, tx, actor, params, body, request_id):
        if operation == "querySortingQueue":
            self.company(tx, body["company_id"])
            items = queue_items(tx, body["company_id"], body["filters"])
            all_items = [
                q
                for q in tx.list("queue")
                if q["company_id"] == body["company_id"] and not q.get("_departed")
            ]
            counts = {s: sum(q["status"] == s for q in all_items) for s in QUEUE_STATES}
            payload = {
                "queue_generation": queue_generation(tx, body["company_id"]),
                "items": [public(q) for q in items],
                "matching_count": len(items),
                "eligible_count": sum(q["selectable"] for q in items),
                "counters": {
                    "ready": counts["READY"],
                    "processing": counts["PROCESSING"],
                    "attention": counts["REQUIRES_DECISION"] + counts["RECOVERY_REQUIRED"],
                },
                "status_counts": [{"status": s, "count": counts[s]} for s in QUEUE_STATES],
            }
            return 200, self.ctx.page(
                tx, operation, actor, body, payload, cursor=body["cursor"], limit=body["limit"]
            )
        if operation == "createSortingSelection":
            return 201, self.selection(tx, actor, body)
        if operation == "createSortingPreview":
            selection = self.get_selection(tx, actor, body["selection_id"])
            self.check_selection(tx, selection)
            company = selection["company_id"]
            rows = self.ctx.plan(tx, selection["_items"], flattened_rules(tx, company), company)
            now = self.ctx.settings.clock()
            preview = {
                "preview_id": uid("preview"),
                "selection_id": selection["selection_id"],
                "company_id": company,
                "rule_set": rule_set(tx, company),
                "created_at": utc(now),
                "expires_at": utc(min(now + self.ctx.settings.ttl, timestamp(selection["expires_at"]))),
                "total": len(rows),
                "counts": plan_counts(rows),
                "rows": rows,
                "next_cursor": None,
                "_owner": actor["user_id"],
            }
            tx.put("preview", preview["preview_id"], preview)
            return 201, self.ctx.page(
                tx,
                "getSortingPreview",
                actor,
                {"preview_id": preview["preview_id"]},
                public(preview),
                field="rows",
            )
        if operation == "getSortingPreview":
            preview = tx.require("preview", params["preview_id"])
            self.owner(preview, actor)
            return 200, self.ctx.page(
                tx,
                operation,
                actor,
                params,
                public(preview),
                field="rows",
                cursor=params.get("cursor"),
                limit=params.get("limit", 100),
            )
        if operation == "createSortingBatch":
            return self.accept(tx, actor, body, request_id)
        if operation == "getSortingBatch":
            batch = self.ctx.batch(tx, params["batch_id"])
            return 200, self.ctx.page(
                tx,
                operation,
                actor,
                params,
                batch,
                field="outcomes",
                cursor=params.get("cursor"),
                limit=params.get("limit", 100),
            )
        if operation == "listSortingBatches":
            self.company(tx, params["company_id"])
            batches = [
                self.ctx.batch(tx, b["batch_id"])
                for b in tx.list("batch")
                if b["company_id"] == params["company_id"]
            ]
            keys = (
                "batch_id",
                "company_id",
                "actor",
                "status",
                "created_at",
                "finished_at",
                "selected_count",
                "completed_count",
                "counts",
            )
            items = [
                {k: b[k] for k in keys}
                for b in sorted(batches, key=lambda b: (b["created_at"], b["batch_id"]), reverse=True)
            ]
            return 200, self.ctx.page(
                tx,
                operation,
                actor,
                params,
                {"items": items},
                cursor=params.get("cursor"),
                limit=params.get("limit", 100),
            )
        raise KeyError(operation)

    def company(self, tx, company_id):
        if tx.get("company", company_id) is None:
            raise ApiError("VALIDATION_ERROR", "Неизвестная компания.", 422)

    def owner(self, obj, actor):
        if obj["_owner"] != actor["user_id"]:
            raise ApiError("FORBIDDEN", "Этот снимок принадлежит другому пользователю.", 403)

    def get_selection(self, tx, actor, key):
        selection = tx.require("selection", key)
        self.owner(selection, actor)
        return selection

    def selection(self, tx, actor, body):
        company = body["company_id"]
        self.company(tx, company)
        if body["mode"] == "EXPLICIT":
            items = []
            seen = set()
            for requested in body["items"]:
                item = tx.get("queue", requested["item_id"])
                if (
                    not item
                    or item["company_id"] != company
                    or item["item_id"] in seen
                    or item["item_revision"] != requested["item_revision"]
                    or not item["selectable"]
                ):
                    raise ApiError("SELECTION_CHANGED", "Выбор изменился; обновите очередь.", 409)
                seen.add(item["item_id"])
                items.append(item)
        else:
            items = [q for q in queue_items(tx, company, body["filters"]) if q["selectable"]]
            if len(items) != body["expected_eligible_count"]:
                raise ApiError("SELECTION_CHANGED", "Изменилось число доступных файлов.", 409)
        if not items:
            raise ApiError("EMPTY_SELECTION", "Выберите хотя бы один готовый файл.", 422)
        if len(items) > self.ctx.settings.max_batch_items:
            raise ApiError("BATCH_LIMIT_EXCEEDED", "Превышен размер партии.", 422)
        now = self.ctx.settings.clock()
        selection = {
            "selection_id": uid("selection"),
            "company_id": company,
            "mode": body["mode"],
            "selected_count": len(items),
            "created_at": utc(now),
            "expires_at": utc(now + self.ctx.settings.ttl),
            "queue_generation": queue_generation(tx, company),
            "_items": items,
            "_owner": actor["user_id"],
        }
        tx.put("selection", selection["selection_id"], selection)
        return public(selection)

    def check_selection(self, tx, selection):
        if timestamp(selection["expires_at"]) <= self.ctx.settings.clock():
            raise ApiError("SELECTION_EXPIRED", "Срок выбора истёк.", 409)
        for saved in selection["_items"]:
            # A competing accepted claim has its own per-file SKIPPED result.
            if tx.get("claim", saved["item_id"]):
                continue
            current = tx.get("queue", saved["item_id"])
            if not current or current["item_revision"] != saved["item_revision"] or not current["selectable"]:
                raise ApiError("SELECTION_CHANGED", "Исходные файлы изменились.", 409)
            if self.ctx.fs.stat(self.ctx.physical(tx, saved["source"])) != saved["_fingerprint"]:
                raise ApiError("SELECTION_CHANGED", "Исходные файлы изменились.", 409)

    def accept(self, tx, actor, body, request_id):
        selection = self.get_selection(tx, actor, body["selection_id"])
        previewed = body["execution_mode"] == "PREVIEWED"
        try:
            self.check_selection(tx, selection)
        except ApiError as error:
            # A preview promises a snapshot of the exact source revisions.  Once
            # the selection itself has not expired, any changed dependency makes
            # that preview stale rather than a generic selection conflict.
            if previewed and error.code == "SELECTION_CHANGED":
                raise ApiError("STALE_PREVIEW", "Прогноз устарел; выполните его заново.", 409) from None
            raise
        if selection.get("_batch_id"):
            raise ApiError("INVALID_STATE", "Этот выбор уже запущен.", 409)
        company = selection["company_id"]
        current_rule_set = rule_set(tx, company)
        rows = self.ctx.plan(tx, selection["_items"], flattened_rules(tx, company), company)
        if previewed:
            preview = tx.require("preview", body["preview_id"])
            self.owner(preview, actor)
            if (
                preview["selection_id"] != selection["selection_id"]
                or timestamp(preview["expires_at"]) <= self.ctx.settings.clock()
                or preview["rule_set"] != current_rule_set
                or digest(preview["rows"]) != digest(rows)
            ):
                raise ApiError("STALE_PREVIEW", "Прогноз устарел; выполните его заново.", 409)
            rows = preview["rows"]
        now = self.ctx.settings.clock()
        batch_id = uid("batch")
        batch = {
            "batch_id": batch_id,
            "company_id": company,
            "actor": actor,
            "selection_id": selection["selection_id"],
            "preview_id": body.get("preview_id"),
            "rule_set": current_rule_set,
            "status": "ACCEPTED",
            "created_at": utc(now),
            "started_at": None,
            "finished_at": None,
            "selected_count": len(rows),
            "completed_count": 0,
            "counts": {
                key: 0
                for key in (
                    "sorted",
                    "manual_review",
                    "requires_decision",
                    "quarantined",
                    "skipped",
                    "recovery_required",
                )
            },
            "outcomes": [],
            "next_cursor": None,
        }
        tx.insert("batch", batch_id, batch)
        emit(
            tx,
            actor,
            "BATCH_ACCEPTED",
            request_id,
            now=now,
            company_id=company,
            batch_id=batch_id,
            rule_set_id=current_rule_set["rule_set_id"],
        )
        for saved, row in zip(selection["_items"], rows):
            attempt_id = uid("attempt")
            occupied = tx.get("claim", saved["item_id"]) is not None
            outcome = {
                "attempt_id": attempt_id,
                "item_id": saved["item_id"],
                "item_revision": saved["item_revision"],
                "state": "SKIPPED" if occupied else "PENDING",
                "reason_code": "ALREADY_PROCESSING" if occupied else None,
                "source": saved["source"],
                "planned_target": row["target"],
                "actual_location": None,
                "matched_rule": row["selected_rule"],
                "started_at": None,
                "finished_at": utc(now) if occupied else None,
            }
            attempt = {
                "attempt_id": attempt_id,
                "batch_id": batch_id,
                "company_id": company,
                "actor": actor,
                "request_id": request_id,
                "item": saved,
                "plan": row,
                "outcome": outcome,
                "phase": "DONE" if occupied else "QUEUED",
                "intent_target": None,
                "intended_state": None,
                "intended_reason": None,
            }
            tx.insert("attempt", attempt_id, attempt)
            if occupied:
                emit(
                    tx,
                    actor,
                    "FILE_ATTEMPT_STARTED",
                    request_id,
                    now=now,
                    company_id=company,
                    batch_id=batch_id,
                    attempt_id=attempt_id,
                    item_id=saved["item_id"],
                    source=saved["source"],
                )
                emit(
                    tx,
                    actor,
                    "FILE_ATTEMPT_FINISHED",
                    request_id,
                    now=now,
                    result="ISSUE",
                    company_id=company,
                    batch_id=batch_id,
                    attempt_id=attempt_id,
                    item_id=saved["item_id"],
                    source=saved["source"],
                    reason_code="ALREADY_PROCESSING",
                )
            else:
                tx.insert("claim", saved["item_id"], {"attempt_id": attempt_id, "batch_id": batch_id})
                item = tx.require("queue", saved["item_id"])
                item.update(
                    status="PROCESSING", selectable=False, active_attempt_id=attempt_id, reason_code=None
                )
                tx.put("queue", item["item_id"], item)
        selection["_batch_id"] = batch_id
        tx.put("selection", selection["selection_id"], selection)
        result = self.ctx.batch(tx, batch_id)
        return 202, self.ctx.page(
            tx, "getSortingBatch", actor, {"batch_id": batch_id}, result, field="outcomes"
        )
