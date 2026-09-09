"""Explicit quarantine return with durable intent and no automatic second move."""

import fcntl
from contextlib import contextmanager

from .audit import emit
from .common import ApiError, digest, public, uid
from .filesystem import TargetExists


@contextmanager
def worker_lock(ctx):
    with (ctx.settings.data_dir / "worker.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class QuarantineService:
    def __init__(self, ctx):
        self.ctx = ctx

    def list_items(self, tx, actor, params):
        if tx.get("company", params["company_id"]) is None:
            raise ApiError("VALIDATION_ERROR", "Неизвестная компания.", 422)
        items = []
        for q in tx.list("quarantine"):
            if q["company_id"] == params["company_id"] and not q.get("_returned"):
                item = public(q)
                item["can_return"] = item["can_return"] and not self.ctx.exists(tx, item["original_location"])
                items.append(item)
        items.sort(key=lambda q: (q["quarantined_at"], q["quarantine_id"]), reverse=True)
        return 200, self.ctx.page(
            tx,
            "listQuarantineItems",
            actor,
            params,
            {"items": items},
            cursor=params.get("cursor"),
            limit=params.get("limit", 100),
        )

    def return_item(self, actor, params, body, request_id):
        key = digest([actor["user_id"], params["quarantine_id"], params["Idempotency-Key"]])
        with worker_lock(self.ctx):
            with self.ctx.store.transaction() as tx:
                record = tx.get("return_key", key)
                if record:
                    if record["hash"] != digest(body):
                        raise ApiError(
                            "IDEMPOTENCY_KEY_REUSED", "Ключ уже использован с другим запросом.", 409
                        )
                    operation = tx.require("return", record["operation_id"])
                else:
                    q = tx.require("quarantine", params["quarantine_id"])
                    if q.get("_returned") or q["recovery_operation_id"] or not q["can_return"]:
                        raise ApiError("INVALID_STATE", "Файл недоступен для возврата.", 409)
                    if q["revision"] != body["expected_revision"]:
                        raise ApiError("QUARANTINE_VERSION_CONFLICT", "Карточка карантина изменилась.", 409)
                    if not body["comment"].strip():
                        raise ApiError("VALIDATION_ERROR", "Введите комментарий.", 422)
                    if self.ctx.exists(tx, q["original_location"]):
                        raise ApiError("ORIGINAL_PATH_OCCUPIED", "Исходный путь занят.", 409)
                    source = self.ctx.physical(tx, q["location"])
                    expected = self.ctx.fs.stat(source)
                    if expected is None or (q.get("_fingerprint") and q["_fingerprint"] != expected):
                        raise ApiError("INVALID_STATE", "Файл карантина изменился или отсутствует.", 409)
                    operation = {
                        "operation_id": uid("return"),
                        "quarantine_id": q["quarantine_id"],
                        "actor": actor,
                        "request_id": request_id,
                        "body": body,
                        "phase": "INTENT",
                        "fingerprint": expected,
                        "source": q["location"],
                        "target": q["original_location"],
                    }
                    tx.insert("return", operation["operation_id"], operation)
                    tx.insert(
                        "return_key", key, {"hash": digest(body), "operation_id": operation["operation_id"]}
                    )
                    q.update(can_return=False, recovery_operation_id=operation["operation_id"])
                    tx.put("quarantine", q["quarantine_id"], q)
            if record:
                return self._resolve(operation)
            try:
                with self.ctx.store.transaction(write=False) as tx:
                    source = self.ctx.physical(tx, operation["source"])
                    target = self.ctx.physical(tx, operation["target"])
                self.ctx.fs.rename_no_replace(source, target, operation["fingerprint"])
            except TargetExists:
                with self.ctx.store.transaction() as tx:
                    q = tx.require("quarantine", operation["quarantine_id"])
                    q.update(can_return=True, recovery_operation_id=None)
                    tx.put("quarantine", q["quarantine_id"], q)
                    operation.update(phase="REJECTED", error="ORIGINAL_PATH_OCCUPIED")
                    tx.put("return", operation["operation_id"], operation)
                raise ApiError("ORIGINAL_PATH_OCCUPIED", "Исходный путь занят.", 409) from None
            except Exception:
                # A failed fsync may mean rename succeeded: resolve the observed identity first.
                return self._resolve(operation)
            # Native rename may report success before a later durability failure.
            # Resolve the observed identity before recording a completed return.
            return self._resolve(operation)

    def _resolve(self, operation):
        if operation["phase"] == "DONE":
            return 200, operation["result"]
        if operation["phase"] == "REJECTED":
            raise ApiError(operation["error"], "Исходный путь занят.", 409)
        try:
            with self.ctx.store.transaction(write=False) as tx:
                source = self.ctx.fs.stat(self.ctx.physical(tx, operation["source"]))
                target = self.ctx.fs.stat(self.ctx.physical(tx, operation["target"]))
        except Exception:
            # An unreadable postcondition is an unknown placement.  Persist the
            # recovery operation below; never retry a move from this path.
            source = target = None
        if source is None and target == operation["fingerprint"]:
            return self._finish(operation)
        with self.ctx.store.transaction() as tx:
            saved = tx.require("return", operation["operation_id"])
            if saved["phase"] != "RECOVERY_REQUIRED":
                saved["phase"] = "RECOVERY_REQUIRED"
                tx.put("return", saved["operation_id"], saved)
                q = tx.require("quarantine", saved["quarantine_id"])
                q["revision"] += 1
                tx.put("quarantine", q["quarantine_id"], q)
                emit(
                    tx,
                    saved["actor"],
                    "RECOVERY_REQUIRED",
                    saved["request_id"],
                    now=self.ctx.settings.clock(),
                    result="ISSUE",
                    operation_id=saved["operation_id"],
                    source_attempt_id=q["source_attempt_id"],
                    company_id=q["company_id"],
                    item_id=q["item_id"],
                    source=saved["source"],
                    target=saved["target"],
                    reason_code="RECOVERY_REQUIRED",
                    comment=saved["body"]["comment"],
                )
        raise ApiError(
            "RECOVERY_REQUIRED",
            "Возврат требует проверки размещения файла.",
            409,
            operation_id=operation["operation_id"],
        )

    def _finish(self, operation):
        with self.ctx.store.transaction() as tx:
            saved = tx.require("return", operation["operation_id"])
            if saved["phase"] == "DONE":
                return 200, saved["result"]
            q = tx.require("quarantine", saved["quarantine_id"])
            item = tx.require("queue", q["item_id"])
            item.update(
                item_revision=item["item_revision"] + 1,
                status="WAITING_READY",
                selectable=False,
                reason_code=None,
                active_attempt_id=None,
                source=q["original_location"],
                filename=q["original_location"]["relative_path"].split("/")[-1],
                _fingerprint=saved["fingerprint"],
                _departed=False,
                _observed_at=self.ctx.settings.clock(),
            )
            tx.put("queue", item["item_id"], item)
            q.update(revision=q["revision"] + 1, can_return=False, recovery_operation_id=None, _returned=True)
            tx.put("quarantine", q["quarantine_id"], q)
            result = {"return_operation_id": saved["operation_id"], "item": public(item)}
            saved.update(phase="DONE", result=result)
            tx.put("return", saved["operation_id"], saved)
            emit(
                tx,
                saved["actor"],
                "QUARANTINE_RETURNED",
                saved["request_id"],
                now=self.ctx.settings.clock(),
                operation_id=saved["operation_id"],
                source_attempt_id=q["source_attempt_id"],
                company_id=q["company_id"],
                item_id=q["item_id"],
                source=saved["source"],
                target=saved["target"],
                comment=saved["body"]["comment"],
            )
            return 200, result

    def reconcile(self):
        with worker_lock(self.ctx):
            with self.ctx.store.transaction(write=False) as tx:
                operations = [o for o in tx.list("return") if o["phase"] in ("INTENT", "RECOVERY_REQUIRED")]
            for operation in operations:
                try:
                    self._resolve(operation)
                except ApiError:
                    pass
