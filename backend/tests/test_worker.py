from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wiseway.common import Settings
from wiseway.filesystem import SafeFilesystem
from wiseway.storage import Store
from wiseway.worker import Worker


class _Context:
    def __init__(self, root: Path) -> None:
        self.settings = Settings(data_dir=root / "state", sandbox_dir=root / "sandbox")
        self.store = Store(self.settings.database)
        self.fs = SafeFilesystem(self.settings.sandbox_dir)
        self.bases = {
            "incoming-root": "incoming",
            "archive-root": "archive",
            "manual-root": "manual",
            "quarantine-root": "quarantine",
        }

    def close(self) -> None:
        self.fs.close()

    def location(self, tx, root_id, relative):
        return {"root_id": root_id, "relative_path": relative, "display_path": f"DEMO:/{root_id}/{relative}"}

    def physical(self, tx, location):
        return f"{self.bases[location['root_id']]}/{location['relative_path']}"

    def exists(self, tx, location):
        return self.fs.exists(self.physical(tx, location))


class WorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for directory in ("incoming/team", "archive/team", "manual/team", "quarantine/team"):
            (self.root / "sandbox" / directory).mkdir(parents=True)
        self.ctx = _Context(self.root)
        with self.ctx.store.transaction() as tx:
            tx.put("company", "company-1", {"company_id": "company-1", "_folder": "team"})

    def tearDown(self) -> None:
        self.ctx.close()
        self.temp.cleanup()

    def _location(self, root_id: str, path: str) -> dict:
        return {"root_id": root_id, "relative_path": path, "display_path": f"DEMO:/{root_id}/{path}"}

    def _attempt(self, predicted: str, reason=None, target=None) -> str:
        source = self._location("incoming-root", "team/file.txt")
        source_file = self.root / "sandbox/incoming/team/file.txt"
        source_file.write_bytes(b"content")
        fingerprint = self.ctx.fs.stat("incoming/team/file.txt")
        item = {
            "item_id": "item-1",
            "item_revision": 1,
            "company_id": "company-1",
            "filename": "file.txt",
            "source": source,
            "status": "PROCESSING",
            "selectable": False,
            "_fingerprint": fingerprint,
        }
        attempt_id = "attempt-1"
        outcome = {
            "attempt_id": attempt_id,
            "item_id": "item-1",
            "item_revision": 1,
            "state": "PENDING",
            "reason_code": None,
            "source": source,
            "planned_target": target,
            "actual_location": None,
            "matched_rule": None,
            "started_at": None,
            "finished_at": None,
        }
        attempt = {
            "attempt_id": attempt_id,
            "batch_id": "batch-1",
            "company_id": "company-1",
            "actor": {"user_id": "user-1", "login": "worker", "display_name": "Worker", "role": "WORKER"},
            "request_id": "request-1",
            "item": item,
            "plan": {
                "predicted_state": predicted,
                "reason_code": reason,
                "target": target,
                "selected_rule": None,
            },
            "outcome": outcome,
            "phase": "QUEUED",
            "intent_target": None,
            "intended_state": None,
            "intended_reason": None,
        }
        with self.ctx.store.transaction() as tx:
            tx.put("queue", "item-1", item)
            tx.put("attempt", attempt_id, attempt)
            tx.put("claim", "item-1", {"attempt_id": attempt_id, "batch_id": "batch-1"})
        return attempt_id

    def test_moves_a_planned_file_and_finishes_once(self) -> None:
        target = self._location("archive-root", "team/file.txt")
        self._attempt("WILL_MOVE", target=target)

        self.assertEqual(Worker(self.ctx).run_once(), 1)
        with self.ctx.store.transaction(write=False) as tx:
            attempt = tx.require("attempt", "attempt-1")
            queue = tx.require("queue", "item-1")
            self.assertEqual(attempt["phase"], "DONE")
            self.assertEqual(attempt["outcome"]["state"], "SORTED")
            self.assertEqual(attempt["outcome"]["actual_location"], target)
            self.assertTrue(queue["_departed"])
            self.assertIsNone(tx.get("claim", "item-1"))
            self.assertEqual(len(tx.events()), 2)
        self.assertFalse((self.root / "sandbox/incoming/team/file.txt").exists())
        self.assertEqual((self.root / "sandbox/archive/team/file.txt").read_bytes(), b"content")

    def test_no_scenario_moves_to_flat_manual_review(self) -> None:
        self._attempt("WILL_MANUAL_REVIEW", reason="NO_SCENARIO")

        Worker(self.ctx).run_once()
        with self.ctx.store.transaction(write=False) as tx:
            outcome = tx.require("attempt", "attempt-1")["outcome"]
            self.assertEqual((outcome["state"], outcome["reason_code"]), ("MANUAL_REVIEW", "NO_SCENARIO"))
            self.assertEqual(outcome["actual_location"]["relative_path"], "team/file.txt")
        self.assertTrue((self.root / "sandbox/manual/team/file.txt").is_file())

    def test_occupied_target_requires_decision_without_move(self) -> None:
        target = self._location("archive-root", "team/file.txt")
        (self.root / "sandbox/archive/team/file.txt").write_bytes(b"existing")
        self._attempt("REQUIRES_DECISION", reason="TARGET_OCCUPIED", target=target)

        Worker(self.ctx).run_once()
        with self.ctx.store.transaction(write=False) as tx:
            outcome = tx.require("attempt", "attempt-1")["outcome"]
            self.assertEqual(
                (outcome["state"], outcome["reason_code"]), ("REQUIRES_DECISION", "TARGET_OCCUPIED")
            )
        self.assertEqual((self.root / "sandbox/incoming/team/file.txt").read_bytes(), b"content")
        self.assertEqual((self.root / "sandbox/archive/team/file.txt").read_bytes(), b"existing")
        with self.ctx.store.transaction(write=False) as tx:
            item = tx.require("queue", "item-1")
            self.assertTrue(item["selectable"])
            self.assertEqual(item["status"], "REQUIRES_DECISION")
            self.assertEqual(len(tx.events()), 2)

    def test_changed_source_restarts_readiness_with_a_new_revision(self) -> None:
        target = self._location("archive-root", "team/file.txt")
        self._attempt("WILL_MOVE", target=target)
        (self.root / "sandbox/incoming/team/file.txt").write_bytes(b"changed content")

        Worker(self.ctx).run_once()

        with self.ctx.store.transaction(write=False) as tx:
            item = tx.require("queue", "item-1")
            outcome = tx.require("attempt", "attempt-1")["outcome"]
            self.assertEqual((outcome["state"], outcome["reason_code"]), ("SKIPPED", "SOURCE_CHANGED"))
            self.assertEqual(
                (item["status"], item["item_revision"], item["selectable"]), ("WAITING_READY", 2, False)
            )

    def test_restart_finalizes_proven_completed_intent_without_second_move(self) -> None:
        target = self._location("archive-root", "team/file.txt")
        self._attempt("WILL_MOVE", target=target)
        with self.ctx.store.transaction() as tx:
            attempt = tx.require("attempt", "attempt-1")
            attempt.update(
                phase="INTENT", intent_target=target, intended_state="SORTED", intended_reason=None
            )
            attempt["outcome"].update(state="PROCESSING", started_at="2026-01-01T00:00:00Z")
            tx.put("attempt", "attempt-1", attempt)
        fingerprint = self.ctx.fs.stat("incoming/team/file.txt")
        self.ctx.fs.rename_no_replace("incoming/team/file.txt", "archive/team/file.txt", fingerprint)

        self.assertTrue(Worker(self.ctx).recover("attempt-1"))
        with self.ctx.store.transaction(write=False) as tx:
            self.assertEqual(tx.require("attempt", "attempt-1")["outcome"]["state"], "SORTED")
        self.assertEqual((self.root / "sandbox/archive/team/file.txt").read_bytes(), b"content")

    def test_recovery_retries_only_when_source_is_unchanged_and_target_is_free(self) -> None:
        target = self._location("archive-root", "team/file.txt")
        self._attempt("WILL_MOVE", target=target)
        with self.ctx.store.transaction() as tx:
            attempt = tx.require("attempt", "attempt-1")
            attempt.update(
                phase="RECOVERY_REQUIRED", intent_target=target, intended_state="SORTED", intended_reason=None
            )
            attempt["outcome"].update(state="RECOVERY_REQUIRED", reason_code="RECOVERY_REQUIRED")
            tx.put("attempt", "attempt-1", attempt)

        self.assertTrue(Worker(self.ctx).recover("attempt-1"))
        self.assertTrue((self.root / "sandbox/archive/team/file.txt").is_file())
        with self.ctx.store.transaction(write=False) as tx:
            self.assertEqual(tx.require("attempt", "attempt-1")["outcome"]["state"], "SORTED")

    def test_technical_failure_quarantines_with_a_complete_card(self) -> None:
        target = self._location("archive-root", "team/file.txt")
        self._attempt("WILL_MOVE", target=target)
        real_move = self.ctx.fs.rename_no_replace

        def fail_primary(source, destination, expected):
            if destination.startswith("archive/"):
                raise OSError("simulated primary failure")
            return real_move(source, destination, expected)

        self.ctx.fs.rename_no_replace = fail_primary
        Worker(self.ctx).run_once()
        self.ctx.fs.rename_no_replace = real_move

        with self.ctx.store.transaction(write=False) as tx:
            outcome = tx.require("attempt", "attempt-1")["outcome"]
            cards = tx.list("quarantine")
            self.assertEqual((outcome["state"], outcome["reason_code"]), ("QUARANTINED", "TECHNICAL_ERROR"))
            self.assertEqual(len(cards), 1)
            self.assertIsNotNone(cards[0]["quarantined_at"])
            self.assertEqual(cards[0]["source_attempt_id"], "attempt-1")

    def test_restart_after_quarantine_move_creates_the_missing_card_without_repeating_move(self) -> None:
        target = self._location("archive-root", "team/file.txt")
        self._attempt("WILL_MOVE", target=target)
        quarantine_target = self._location("quarantine-root", "team/attempt-1_file.txt")
        with self.ctx.store.transaction() as tx:
            attempt = tx.require("attempt", "attempt-1")
            attempt.update(
                phase="INTENT",
                intent_target=quarantine_target,
                intended_state="QUARANTINED",
                intended_reason="TECHNICAL_ERROR",
            )
            attempt["outcome"].update(state="PROCESSING", started_at="2026-01-01T00:00:00Z")
            tx.put("attempt", "attempt-1", attempt)
        fingerprint = self.ctx.fs.stat("incoming/team/file.txt")
        self.ctx.fs.rename_no_replace(
            "incoming/team/file.txt", "quarantine/team/attempt-1_file.txt", fingerprint
        )

        self.assertEqual(Worker(self.ctx).run_once(), 1)
        with self.ctx.store.transaction(write=False) as tx:
            self.assertEqual(tx.require("attempt", "attempt-1")["outcome"]["state"], "QUARANTINED")
            card = tx.require("quarantine", "quarantine-attempt-1")
            self.assertEqual(card["location"], quarantine_target)
            self.assertIsNotNone(card["quarantined_at"])

    def test_unresolved_recovery_reports_false_to_operator(self) -> None:
        target = self._location("archive-root", "team/file.txt")
        self._attempt("WILL_MOVE", target=target)
        (self.root / "sandbox/incoming/team/file.txt").unlink()
        with self.ctx.store.transaction() as tx:
            attempt = tx.require("attempt", "attempt-1")
            attempt.update(phase="RECOVERY_REQUIRED")
            tx.put("attempt", "attempt-1", attempt)

        self.assertFalse(Worker(self.ctx).recover("attempt-1"))
        with self.ctx.store.transaction(write=False) as tx:
            self.assertEqual(tx.require("attempt", "attempt-1")["phase"], "RECOVERY_REQUIRED")

    def test_transient_preflight_error_retries_accepted_plan_with_one_start_event(self) -> None:
        target = self._location("archive-root", "team/file.txt")
        self._attempt("WILL_MOVE", target=target)
        real_stat = self.ctx.fs.stat
        calls = 0

        def fail_once(path):
            nonlocal calls
            if path == "incoming/team/file.txt" and calls == 0:
                calls += 1
                raise OSError("temporary metadata failure")
            return real_stat(path)

        self.ctx.fs.stat = fail_once
        Worker(self.ctx).run_once()
        self.ctx.fs.stat = real_stat
        self.assertTrue(Worker(self.ctx).recover("attempt-1"))

        with self.ctx.store.transaction(write=False) as tx:
            attempt = tx.require("attempt", "attempt-1")
            self.assertEqual(attempt["outcome"]["state"], "SORTED")
            starts = [e for e in tx.events() if e["action"] == "FILE_ATTEMPT_STARTED"]
            self.assertEqual(len(starts), 1)


if __name__ == "__main__":
    unittest.main()
