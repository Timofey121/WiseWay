"""Durable executor for accepted sorting attempts."""

from __future__ import annotations

import fcntl
from contextlib import contextmanager

from .audit import emit
from .common import utc
from .filesystem import PostRenameChanged, SourceChanged, TargetExists


@contextmanager
def _worker_lock(ctx):
    ctx.settings.data_dir.mkdir(parents=True, exist_ok=True)
    with (ctx.settings.data_dir / "worker.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class Worker:
    def __init__(self, ctx):
        self.ctx = ctx

    def run_once(self) -> int:
        """Process currently durable work once; another worker gets zero."""
        with _worker_lock(self.ctx) as held:
            if not held:
                return 0
            with self.ctx.store.transaction(write=False) as tx:
                attempts = [
                    a["attempt_id"]
                    for a in tx.list("attempt")
                    if a["phase"] in ("QUEUED", "INTENT", "RECOVERY_REQUIRED")
                ]
            processed = 0
            for attempt_id in attempts:
                try:
                    if self._run(attempt_id):
                        processed += 1
                except Exception:
                    # A broken adapter must not strand unrelated accepted work.
                    self._recovery_required(attempt_id)
                    processed += 1
            return processed

    def recover(self, attempt_id: str) -> bool:
        """Reconcile one persisted intent without guessing its filesystem outcome."""
        with _worker_lock(self.ctx) as held:
            if not held:
                return False
            self._recover(attempt_id, allow_quarantine_retry=True)
            with self.ctx.store.transaction(write=False) as tx:
                attempt = tx.get("attempt", attempt_id)
                return bool(attempt and attempt["phase"] == "DONE")

    def _run(self, attempt_id: str) -> bool:
        with self.ctx.store.transaction(write=False) as tx:
            attempt = tx.get("attempt", attempt_id)
        if not attempt or attempt["phase"] not in ("QUEUED", "INTENT", "RECOVERY_REQUIRED"):
            return False
        if attempt["phase"] in ("INTENT", "RECOVERY_REQUIRED"):
            return self._recover(attempt_id)

        item = attempt["item"]
        source = self._physical(item["source"])
        try:
            observed = self.ctx.fs.stat(source)
        except Exception:
            return self._recovery_required(attempt_id)
        if observed is None:
            self._finish(attempt_id, "SKIPPED", "SOURCE_MISSING", None)
            return True
        if observed != item["_fingerprint"]:
            self._finish(attempt_id, "SKIPPED", "SOURCE_CHANGED", item["source"])
            return True

        plan = attempt["plan"]
        state = plan["predicted_state"]
        if state == "REQUIRES_DECISION":
            self._finish(attempt_id, "REQUIRES_DECISION", plan["reason_code"], item["source"])
            return True
        if state == "WILL_MOVE":
            self._intent(attempt_id, plan["target"], "SORTED", None)
        elif state == "WILL_MANUAL_REVIEW":
            target = self._manual_target(attempt)
            if self._exists(target):
                self._finish(attempt_id, "REQUIRES_DECISION", "MANUAL_REVIEW_NAME_OCCUPIED", item["source"])
                return True
            self._intent(attempt_id, target, "MANUAL_REVIEW", plan["reason_code"])
        else:
            self._finish(attempt_id, "SKIPPED", "SOURCE_CHANGED", item["source"])
            return True
        return self._execute_intent(attempt_id)

    def _recover(self, attempt_id: str, *, allow_quarantine_retry: bool = False) -> bool:
        with self.ctx.store.transaction(write=False) as tx:
            attempt = tx.get("attempt", attempt_id)
        if not attempt or attempt["phase"] not in ("INTENT", "RECOVERY_REQUIRED"):
            return False
        target = attempt.get("intent_target")
        if not target:
            if attempt["phase"] == "RECOVERY_REQUIRED":
                try:
                    unchanged = (
                        self.ctx.fs.stat(self._physical(attempt["item"]["source"]))
                        == attempt["item"]["_fingerprint"]
                    )
                except Exception:
                    unchanged = False
                if unchanged:
                    # No intent had been persisted, so no filesystem mutation
                    # was attempted.  It is safe to retry the accepted plan.
                    with self.ctx.store.transaction() as tx:
                        saved = tx.require("attempt", attempt_id)
                        saved["phase"] = "QUEUED"
                        saved["outcome"].update(
                            state="PENDING", reason_code=None, actual_location=None, finished_at=None
                        )
                        tx.put("attempt", attempt_id, saved)
                    return self._run(attempt_id)
            return self._recovery_required(attempt_id)
        fingerprint = attempt["item"]["_fingerprint"]
        source_physical = self._physical(attempt["item"]["source"])
        target_physical = self._physical(target)
        source_present = self.ctx.fs.stat(source_physical) == fingerprint
        target_present = self.ctx.fs.stat(target_physical) == fingerprint
        target_occupied = self.ctx.fs.exists(target_physical)
        if not source_present and target_present:
            self._finish(attempt_id, attempt["intended_state"], attempt["intended_reason"], target)
            return True
        may_retry = attempt["intended_state"] != "QUARANTINED" or allow_quarantine_retry
        if source_present and not target_occupied and may_retry:
            # The source is conclusively unchanged and the target is free: retry
            # exactly the original durable intent, never a newly calculated plan.
            with self.ctx.store.transaction() as tx:
                saved = tx.require("attempt", attempt_id)
                saved["phase"] = "INTENT"
                tx.put("attempt", attempt_id, saved)
            return self._execute_intent(attempt_id)
        return self._recovery_required(
            attempt_id, actual_location=attempt["item"]["source"] if source_present else None
        )

    def _intent(self, attempt_id: str, target: dict, state: str, reason: str | None) -> None:
        with self.ctx.store.transaction() as tx:
            attempt = tx.require("attempt", attempt_id)
            if attempt["phase"] != "QUEUED":
                return
            now = self.ctx.settings.clock()
            attempt.update(phase="INTENT", intent_target=target, intended_state=state, intended_reason=reason)
            attempt["outcome"].update(state="PROCESSING", reason_code=None)
            self._start_attempt(tx, attempt, now, target)
            tx.put("attempt", attempt_id, attempt)

    def _execute_intent(self, attempt_id: str) -> bool:
        with self.ctx.store.transaction(write=False) as tx:
            attempt = tx.require("attempt", attempt_id)
            if attempt["phase"] != "INTENT":
                return False
            source = self._physical(attempt["item"]["source"])
            target = self._physical(attempt["intent_target"])
            expected = attempt["item"]["_fingerprint"]
        try:
            self.ctx.fs.rename_no_replace(source, target, expected)
        except TargetExists:
            reason = (
                "MANUAL_REVIEW_NAME_OCCUPIED"
                if attempt["intended_state"] == "MANUAL_REVIEW"
                else "TARGET_OCCUPIED"
            )
            self._finish(attempt_id, "REQUIRES_DECISION", reason, attempt["item"]["source"])
            return True
        except PostRenameChanged:
            # The native move may already have changed either entry.  Never
            # reinterpret this known post-move ambiguity as a safe quarantine.
            return self._recovery_required(attempt_id)
        except SourceChanged:
            current = self.ctx.fs.stat(source)
            self._finish(
                attempt_id,
                "SKIPPED",
                "SOURCE_MISSING" if current is None else "SOURCE_CHANGED",
                attempt["item"]["source"] if current is not None else None,
            )
            return True
        except Exception:
            # An error after a native rename (for example fsync) is ambiguous.
            # Quarantine only when the original source is still proven present.
            return self._quarantine_or_recover(attempt_id)
        if self.ctx.fs.stat(target) != expected:
            return self._recovery_required(attempt_id)
        with self.ctx.store.transaction(write=False) as tx:
            fresh = tx.require("attempt", attempt_id)
        self._finish(attempt_id, fresh["intended_state"], fresh["intended_reason"], fresh["intent_target"])
        return True

    def _quarantine_or_recover(self, attempt_id: str) -> bool:
        with self.ctx.store.transaction(write=False) as tx:
            attempt = tx.require("attempt", attempt_id)
        item, fingerprint = attempt["item"], attempt["item"]["_fingerprint"]
        if self.ctx.fs.stat(self._physical(item["source"])) != fingerprint:
            return self._recovery_required(attempt_id)
        target = self._quarantine_target(attempt)
        if self._exists(target):
            # No quarantine rename was attempted, and the source identity was
            # just proven.  Keep that observed placement for the operator;
            # unlike a post-rename failure it is not ambiguous.
            return self._recovery_required(attempt_id, actual_location=item["source"])
        # A quarantine move is a new filesystem intent.  It must be durable
        # before the filesystem call, otherwise a crash cannot be reconciled.
        with self.ctx.store.transaction() as tx:
            saved = tx.require("attempt", attempt_id)
            saved.update(
                intent_target=target, intended_state="QUARANTINED", intended_reason="TECHNICAL_ERROR"
            )
            tx.put("attempt", attempt_id, saved)
        try:
            self.ctx.fs.rename_no_replace(self._physical(item["source"]), self._physical(target), fingerprint)
        except Exception:
            return self._recovery_required(attempt_id)
        if self.ctx.fs.stat(self._physical(target)) != fingerprint:
            return self._recovery_required(attempt_id)
        self._finish(attempt_id, "QUARANTINED", "TECHNICAL_ERROR", target)
        return True

    def _finish(self, attempt_id: str, state: str, reason: str | None, actual: dict | None) -> None:
        with self.ctx.store.transaction() as tx:
            attempt = tx.require("attempt", attempt_id)
            if attempt["phase"] == "DONE":
                return
            now = self.ctx.settings.clock()
            outcome = attempt["outcome"]
            self._start_attempt(tx, attempt, now, attempt.get("intent_target"))
            outcome.update(state=state, reason_code=reason, actual_location=actual, finished_at=utc(now))
            attempt.update(phase="DONE", outcome=outcome)
            tx.put("attempt", attempt_id, attempt)
            item = tx.require("queue", attempt["item"]["item_id"])
            if state == "REQUIRES_DECISION":
                item.update(
                    status="REQUIRES_DECISION", selectable=True, active_attempt_id=None, reason_code=reason
                )
            elif state == "SKIPPED" and reason == "SOURCE_MISSING":
                item.update(status="MISSING", selectable=False, active_attempt_id=None, reason_code=reason)
            elif state == "SKIPPED" and reason == "SOURCE_CHANGED":
                current = self.ctx.fs.stat(self._physical(attempt["item"]["source"]))
                if current is None:
                    item.update(
                        status="MISSING",
                        selectable=False,
                        active_attempt_id=None,
                        reason_code="SOURCE_MISSING",
                    )
                else:
                    item.update(
                        item_revision=item["item_revision"] + 1,
                        status="WAITING_READY",
                        selectable=False,
                        active_attempt_id=None,
                        reason_code="SOURCE_CHANGED",
                        _fingerprint=current,
                        size_bytes=current["size"],
                        modified_at=utc(current["mtime_ns"] / 1e9),
                        _observed_at=now,
                    )
            else:
                # Completed moves leave the incoming queue.  The canonical
                # internal record is retained for audit/recovery but hidden
                # from all queue filters through this marker.
                item.update(
                    status="MISSING",
                    selectable=False,
                    active_attempt_id=None,
                    reason_code=reason,
                    _departed=True,
                )
            tx.put("queue", item["item_id"], item)
            tx.delete("claim", item["item_id"])
            if state == "QUARANTINED":
                self._put_quarantine(tx, attempt, actual, now)
            result = "SUCCESS" if state == "SORTED" else "ISSUE"
            emit(
                tx,
                attempt["actor"],
                "FILE_ATTEMPT_FINISHED",
                attempt["request_id"],
                now=now,
                result=result,
                company_id=attempt["company_id"],
                batch_id=attempt["batch_id"],
                attempt_id=attempt_id,
                item_id=item["item_id"],
                source=attempt["item"]["source"],
                target=actual,
                reason_code=reason,
            )

    def _recovery_required(self, attempt_id: str, *, actual_location: dict | None = None) -> bool:
        with self.ctx.store.transaction() as tx:
            attempt = tx.require("attempt", attempt_id)
            if attempt["phase"] == "DONE":
                return False
            if attempt["phase"] != "RECOVERY_REQUIRED":
                now = self.ctx.settings.clock()
                self._start_attempt(tx, attempt, now, attempt.get("intent_target"))
                attempt.update(phase="RECOVERY_REQUIRED")
                attempt["outcome"].update(
                    state="RECOVERY_REQUIRED",
                    reason_code="RECOVERY_REQUIRED",
                    actual_location=actual_location,
                    finished_at=None,
                )
                tx.put("attempt", attempt_id, attempt)
                item = tx.require("queue", attempt["item"]["item_id"])
                item.update(status="RECOVERY_REQUIRED", selectable=False, reason_code="RECOVERY_REQUIRED")
                tx.put("queue", item["item_id"], item)
                emit(
                    tx,
                    attempt["actor"],
                    "RECOVERY_REQUIRED",
                    attempt["request_id"],
                    now=now,
                    result="ISSUE",
                    operation_id=attempt_id,
                    source_attempt_id=attempt_id,
                    company_id=attempt["company_id"],
                    batch_id=attempt["batch_id"],
                    attempt_id=attempt_id,
                    item_id=item["item_id"],
                    source=attempt["item"]["source"],
                    target=attempt.get("intent_target"),
                    reason_code="RECOVERY_REQUIRED",
                )
        return True

    @staticmethod
    def _start_attempt(tx, attempt: dict, now: float, target: dict | None) -> None:
        if attempt["outcome"]["started_at"] is not None:
            return
        attempt["outcome"]["started_at"] = utc(now)
        emit(
            tx,
            attempt["actor"],
            "FILE_ATTEMPT_STARTED",
            attempt["request_id"],
            now=now,
            company_id=attempt["company_id"],
            batch_id=attempt["batch_id"],
            attempt_id=attempt["attempt_id"],
            item_id=attempt["item"]["item_id"],
            source=attempt["item"]["source"],
            target=target,
        )

    def _put_quarantine(self, tx, attempt: dict, target: dict, now: float) -> None:
        key = f"quarantine-{attempt['attempt_id']}"
        if tx.get("quarantine", key) is None:
            tx.put(
                "quarantine",
                key,
                {
                    "quarantine_id": key,
                    "revision": 1,
                    "item_id": attempt["item"]["item_id"],
                    "company_id": attempt["company_id"],
                    "filename": attempt["item"]["filename"],
                    "location": target,
                    "original_location": attempt["item"]["source"],
                    "reason_code": "TECHNICAL_ERROR",
                    "quarantined_at": utc(now),
                    "source_attempt_id": attempt["attempt_id"],
                    "recovery_operation_id": None,
                    "can_return": True,
                    "_fingerprint": attempt["item"]["_fingerprint"],
                },
            )

    def _manual_target(self, attempt: dict) -> dict:
        with self.ctx.store.transaction(write=False) as tx:
            company = tx.require("company", attempt["company_id"])
            return self.ctx.location(tx, "manual-root", f"{company['_folder']}/{attempt['item']['filename']}")

    def _quarantine_target(self, attempt: dict) -> dict:
        with self.ctx.store.transaction(write=False) as tx:
            company = tx.require("company", attempt["company_id"])
            return self.ctx.location(
                tx,
                "quarantine-root",
                f"{company['_folder']}/{attempt['attempt_id']}_{attempt['item']['filename']}",
            )

    def _physical(self, location: dict) -> str:
        with self.ctx.store.transaction(write=False) as tx:
            return self.ctx.physical(tx, location)

    def _exists(self, location: dict) -> bool:
        with self.ctx.store.transaction(write=False) as tx:
            return self.ctx.exists(tx, location)
