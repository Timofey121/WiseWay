"""Shared transactional application context and immutable pagination."""

from pathlib import PurePosixPath
import json

from .common import ApiError, digest, public, uid, utc
from .filesystem import SafeFilesystem
from .rules import plan_rows
from .storage import Store


class Context:
    def __init__(self, settings):
        self.settings = settings
        marker = settings.sandbox_dir / ".wiseway-sandbox.json"
        if not marker.is_file() or json.loads(marker.read_text()).get("synthetic") is not True:
            raise RuntimeError("Initialize the synthetic sandbox before starting Wise Way")
        self.store = Store(settings.database)
        self.fs = SafeFilesystem(settings.sandbox_dir)
        if not self.fs.probe():
            self.fs.close()
            raise RuntimeError("Atomic no-replace rename is required")

    def close(self):
        self.fs.close()

    def location(self, tx, root_id, relative):
        root = tx.get("root", root_id)
        if root is None:
            raise ApiError("INVALID_TARGET", "Неизвестный логический корень.", 422)
        path = PurePosixPath(relative)
        if (
            not relative
            or "\\" in relative
            or relative.startswith("/")
            or any(p in ("", ".", "..") for p in relative.split("/"))
        ):
            raise ApiError("PATH_OUTSIDE_ROOT", "Путь должен находиться внутри корня.", 422)
        return {
            "root_id": root_id,
            "relative_path": str(path),
            "display_path": root["display_prefix"].rstrip("/") + "/" + str(path),
        }

    def physical(self, tx, location):
        checked = self.location(tx, location["root_id"], location["relative_path"])
        root = tx.require("root", checked["root_id"])
        return "/".join(p for p in (root["_base"], checked["relative_path"]) if p)

    def exists(self, tx, location):
        return self.fs.exists(self.physical(tx, location))

    def targets(self, tx, company_id):
        company = tx.require("company", company_id)
        result = []
        for target in company["_targets"]:
            loc = self.location(tx, target["root_id"], target["relative_directory"])
            if self.fs.is_directory(self.physical(tx, loc)):
                result.append({**target, "display_path": loc["display_path"]})
        return sorted(result, key=lambda value: (value["display_path"].casefold(), value["display_path"]))

    def ready_items(self, tx, company_id):
        return [
            public(q)
            for q in tx.list("queue")
            if q["company_id"] == company_id and q["status"] == "READY" and q["selectable"]
        ]

    def plan(self, tx, items, rules, company_id):
        company = tx.require("company", company_id)

        def source_info(location):
            meta = self.fs.stat(self.physical(tx, location))
            return (
                None
                if meta is None
                else {
                    "filename": location["relative_path"].split("/")[-1],
                    "location": location,
                    "size_bytes": meta["size"],
                    "modified_at": utc(meta["mtime_ns"] / 1e9),
                }
            )

        return plan_rows(
            items,
            rules,
            {"root_id": "manual-root", "relative_directory": company["_folder"]},
            lambda loc: self.exists(tx, loc),
            location=lambda root_id, relative: self.location(tx, root_id, relative),
            source_info=source_info,
        )

    def page(self, tx, scope, actor, query, payload, field="items", cursor=None, limit=100):
        filters = {k: v for k, v in query.items() if k not in ("cursor", "limit")}
        signature = digest(filters)
        offset = 0
        if cursor:
            saved = tx.get("cursor", cursor)
            if (
                saved is None
                or saved["scope"] != scope
                or saved["owner"] != actor["user_id"]
                or saved["query"] != signature
                or saved["expires"] <= self.settings.clock()
            ):
                raise ApiError("VALIDATION_ERROR", "Недействительный курсор страницы.", 422)
            payload, offset = saved["payload"], saved["offset"]
        result = {**payload, field: payload[field][offset : offset + limit], "next_cursor": None}
        if offset + limit < len(payload[field]):
            key = uid("cursor")
            tx.put(
                "cursor",
                key,
                {
                    "scope": scope,
                    "owner": actor["user_id"],
                    "query": signature,
                    "payload": payload,
                    "offset": offset + limit,
                    "expires": self.settings.clock() + 86400,
                },
            )
            result["next_cursor"] = key
        return result

    def batch(self, tx, batch_id):
        batch = public(tx.require("batch", batch_id))
        outcomes = [a["outcome"] for a in tx.list("attempt") if a["batch_id"] == batch_id]
        outcomes.sort(key=lambda o: o["attempt_id"])
        counts = {
            key: 0
            for key in (
                "sorted",
                "manual_review",
                "requires_decision",
                "quarantined",
                "skipped",
                "recovery_required",
            )
        }
        for outcome in outcomes:
            if outcome["state"].lower() in counts:
                counts[outcome["state"].lower()] += 1
        completed = sum(counts[k] for k in counts if k != "recovery_required")
        started = [o["started_at"] for o in outcomes if o["started_at"]]
        finished = [o["finished_at"] for o in outcomes if o["finished_at"]]
        if completed == batch["selected_count"]:
            status = "COMPLETED" if counts["sorted"] == completed else "COMPLETED_WITH_ISSUES"
        elif counts["recovery_required"]:
            status = "RECOVERY_REQUIRED"
        elif started:
            status = "RUNNING"
        else:
            status = "ACCEPTED"
        return {
            **batch,
            "outcomes": outcomes,
            "counts": counts,
            "completed_count": completed,
            "started_at": min(started) if started else None,
            "finished_at": max(finished) if completed == batch["selected_count"] and finished else None,
            "status": status,
            "next_cursor": None,
        }

    def idempotent(self, tx, operation, actor, key, body, action):
        record_id = digest([actor["user_id"], operation, key])
        previous = tx.get("idempotency", record_id)
        if previous:
            if previous["body"] != digest(body):
                raise ApiError("IDEMPOTENCY_KEY_REUSED", "Ключ уже использован с другим запросом.", 409)
            if "error" in previous:
                e = previous["error"]
                raise ApiError(e["code"], e["message"], e["status"], operation_id=e["operation_id"])
            return previous["status"], previous["result"]
        status, result = action()
        tx.insert("idempotency", record_id, {"body": digest(body), "status": status, "result": result})
        return status, result
