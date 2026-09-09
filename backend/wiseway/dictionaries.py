"""Dictionary, target-directory, and simulation application service."""

from __future__ import annotations

from typing import Any

from .audit import emit
from .common import ApiError, digest, public, uid, utc
from .rules import plan_counts


def rule_set(tx, company_id: str) -> dict[str, Any]:
    members = [
        {"dictionary_id": dictionary["dictionary_id"], "version_id": dictionary["active_version_id"]}
        for dictionary in tx.list("dictionary")
        if dictionary["company_id"] == company_id and dictionary["active_version_id"] is not None
    ]
    members.sort(key=lambda member: member["dictionary_id"])
    return {
        "rule_set_id": f"rule-set-{digest([company_id, members])[:24]}",
        "company_id": company_id,
        "members": members,
    }


def flattened_rules(tx, company_id: str, candidate: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return active rules, replacing a candidate dictionary by its draft."""
    result: list[dict[str, Any]] = []
    candidate_id = candidate and candidate["dictionary_id"]
    for dictionary in sorted(tx.list("dictionary"), key=lambda value: value["dictionary_id"]):
        if dictionary["company_id"] != company_id:
            continue
        if dictionary["dictionary_id"] == candidate_id:
            rules, version_id = candidate["draft"]["rules"], None
        elif dictionary["active_version_id"] is not None:
            version = tx.require("dictionary_version", dictionary["active_version_id"])
            rules, version_id = version["rules"], version["version_id"]
        else:
            continue
        result.extend(
            {**rule, "dictionary_id": dictionary["dictionary_id"], "version_id": version_id} for rule in rules
        )
    return result


class DictionaryService:
    def __init__(self, ctx) -> None:
        self.ctx = ctx

    def handle(self, operation_id, tx, actor, params, body, request_id):
        operations = {
            "listTargetDirectories": self._list_targets,
            "listDictionaries": self._list,
            "resolveTargetDirectory": self._resolve_target,
            "createDictionary": self._create,
            "getDictionary": self._get,
            "replaceDictionaryDraft": self._replace_draft,
            "listDictionaryVersions": self._list_versions,
            "getDictionaryVersion": self._get_version,
            "restoreDictionaryDraft": self._restore_draft,
            "createDictionarySimulation": self._simulate,
            "getSimulation": self._get_simulation,
            "publishDictionary": self._publish,
        }
        try:
            return operations[operation_id](tx, actor, params, body, request_id)
        except KeyError as error:
            raise RuntimeError(f"Unsupported dictionary operation: {operation_id}") from error

    def _list(self, tx, actor, params, body, request_id):
        tx.require("company", params["company_id"])
        items = [public(d) for d in tx.list("dictionary") if d["company_id"] == params["company_id"]]
        items.sort(key=lambda d: (d["name"].casefold(), d["name"], d["dictionary_id"]))
        return 200, {"items": items}

    def _list_targets(self, tx, actor, params, body, request_id):
        values = self.ctx.targets(tx, params["company_id"])
        return 200, self.ctx.page(
            tx,
            "targets",
            actor,
            params,
            {"items": values},
            cursor=params.get("cursor"),
            limit=params.get("limit", 100),
        )

    def _resolve_target(self, tx, actor, params, body, request_id):
        for target in self.ctx.targets(tx, params["company_id"]):
            if target["display_path"] == body["display_path"]:
                return 200, target
        raise ApiError("INVALID_TARGET", "Указанный каталог недоступен для компании.", 422)

    def _create(self, tx, actor, params, body, request_id):
        company_id, name = params["company_id"], body["name"].strip()
        tx.require("company", company_id)
        self._unique_name(tx, company_id, name)
        now = self.ctx.settings.clock()
        dictionary = {
            "dictionary_id": uid("dictionary"),
            "company_id": company_id,
            "name": name,
            "description": body["description"],
            "draft": {"draft_revision": 1, "rules": [], "based_on_version_id": None},
            "active_version_id": None,
            "versions_count": 0,
            "updated_at": utc(now),
            "updated_by": actor,
        }
        tx.insert("dictionary", dictionary["dictionary_id"], dictionary)
        emit(
            tx,
            actor,
            "DICTIONARY_CREATED",
            request_id,
            now=now,
            company_id=company_id,
            dictionary_id=dictionary["dictionary_id"],
        )
        return 201, public(dictionary)

    def _get(self, tx, actor, params, body, request_id):
        return 200, public(tx.require("dictionary", params["dictionary_id"]))

    def _replace_draft(self, tx, actor, params, body, request_id):
        dictionary = tx.require("dictionary", params["dictionary_id"])
        self._revision(dictionary, body["expected_draft_revision"])
        name = body["name"].strip()
        self._unique_name(tx, dictionary["company_id"], name, dictionary["dictionary_id"])
        self._validate_rules(tx, dictionary["company_id"], body["rules"])
        now = self.ctx.settings.clock()
        dictionary["name"], dictionary["description"] = name, body["description"]
        dictionary["draft"] = {
            "draft_revision": dictionary["draft"]["draft_revision"] + 1,
            "rules": body["rules"],
            "based_on_version_id": None,
        }
        dictionary["updated_at"], dictionary["updated_by"] = utc(now), actor
        tx.put("dictionary", dictionary["dictionary_id"], dictionary)
        emit(
            tx,
            actor,
            "DRAFT_SAVED",
            request_id,
            now=now,
            company_id=dictionary["company_id"],
            dictionary_id=dictionary["dictionary_id"],
        )
        return 200, public(dictionary)

    def _list_versions(self, tx, actor, params, body, request_id):
        dictionary = tx.require("dictionary", params["dictionary_id"])
        versions = [
            public(version)
            for version in tx.list("dictionary_version")
            if version["dictionary_id"] == dictionary["dictionary_id"]
        ]
        versions.sort(key=lambda version: version["version_number"], reverse=True)
        return 200, self.ctx.page(
            tx,
            "dictionary-versions",
            actor,
            params,
            {"items": versions},
            cursor=params.get("cursor"),
            limit=params.get("limit", 100),
        )

    def _get_version(self, tx, actor, params, body, request_id):
        version = tx.require("dictionary_version", params["version_id"])
        if version["dictionary_id"] != params["dictionary_id"]:
            raise ApiError("NOT_FOUND", "Версия не принадлежит справочнику.", 404)
        return 200, public(version)

    def _restore_draft(self, tx, actor, params, body, request_id):
        dictionary = tx.require("dictionary", params["dictionary_id"])
        self._revision(dictionary, body["expected_draft_revision"])
        version = tx.require("dictionary_version", body["version_id"])
        if version["dictionary_id"] != dictionary["dictionary_id"]:
            raise ApiError("NOT_FOUND", "Версия не принадлежит справочнику.", 404)
        now = self.ctx.settings.clock()
        self._unique_name(tx, dictionary["company_id"], version["name"], dictionary["dictionary_id"])
        dictionary["name"], dictionary["description"] = version["name"], version["description"]
        dictionary["draft"] = {
            "draft_revision": dictionary["draft"]["draft_revision"] + 1,
            "rules": version["rules"],
            "based_on_version_id": version["version_id"],
        }
        dictionary["updated_at"], dictionary["updated_by"] = utc(now), actor
        tx.put("dictionary", dictionary["dictionary_id"], dictionary)
        emit(
            tx,
            actor,
            "DICTIONARY_RESTORED",
            request_id,
            now=now,
            company_id=dictionary["company_id"],
            dictionary_id=dictionary["dictionary_id"],
            version_id=version["version_id"],
        )
        return 200, public(dictionary)

    def _simulate(self, tx, actor, params, body, request_id):
        dictionary = tx.require("dictionary", params["dictionary_id"])
        self._revision(dictionary, body["expected_draft_revision"])
        now = self.ctx.settings.clock()
        items, rules = (
            self.ctx.ready_items(tx, dictionary["company_id"]),
            flattened_rules(tx, dictionary["company_id"], dictionary),
        )
        rows = self.ctx.plan(tx, items, rules, dictionary["company_id"])
        counts = plan_counts(rows)
        simulation = {
            "simulation_id": uid("simulation"),
            "dictionary_id": dictionary["dictionary_id"],
            "draft_revision": dictionary["draft"]["draft_revision"],
            "base_rule_set": rule_set(tx, dictionary["company_id"]),
            "ready_snapshot_id": uid("ready-snapshot"),
            "created_at": utc(now),
            "expires_at": utc(now + self.ctx.settings.ttl),
            "total": len(rows),
            "counts": counts,
            "warnings": ["EMPTY_READY_SET"] if not items else [],
            "rows": rows,
            "next_cursor": None,
            "_ready_digest": digest(items),
            "_rules_digest": digest(rules),
            "_owner": actor["user_id"],
            "_expires": now + self.ctx.settings.ttl,
        }
        tx.insert("simulation", simulation["simulation_id"], simulation)
        emit(
            tx,
            actor,
            "DICTIONARY_SIMULATED",
            request_id,
            now=now,
            company_id=dictionary["company_id"],
            dictionary_id=dictionary["dictionary_id"],
            rule_set_id=simulation["base_rule_set"]["rule_set_id"],
        )
        return 201, self.ctx.page(
            tx,
            "simulation",
            actor,
            {"simulation_id": simulation["simulation_id"]},
            public(simulation),
            field="rows",
        )

    def _get_simulation(self, tx, actor, params, body, request_id):
        simulation = tx.require("simulation", params["simulation_id"])
        return 200, self.ctx.page(
            tx,
            "simulation",
            actor,
            params,
            public(simulation),
            field="rows",
            cursor=params.get("cursor"),
            limit=params.get("limit", 100),
        )

    def _publish(self, tx, actor, params, body, request_id):
        dictionary = tx.require("dictionary", params["dictionary_id"])
        self._revision(dictionary, body["expected_draft_revision"])
        simulation = tx.require("simulation", body["simulation_id"])
        if simulation["dictionary_id"] != dictionary["dictionary_id"]:
            raise ApiError("STALE_SIMULATION", "Тест принадлежит другому справочнику.", 409)
        self._fresh_simulation(tx, actor, simulation)
        if simulation["counts"]["rule_conflicts"]:
            raise ApiError("RULE_CONFLICT", "Конфликт правил нужно устранить до публикации.", 409)
        if simulation["counts"]["no_scenario"] and not body["acknowledge_no_scenario"]:
            raise ApiError("NO_SCENARIO_ACK_REQUIRED", "Подтвердите отсутствие сценария.", 409)
        self._validate_rules(tx, dictionary["company_id"], dictionary["draft"]["rules"])
        if not body["comment"].strip():
            raise ApiError("VALIDATION_ERROR", "Введите комментарий.", 422)
        now = self.ctx.settings.clock()
        version = {
            "version_id": uid("version"),
            "dictionary_id": dictionary["dictionary_id"],
            "version_number": dictionary["versions_count"] + 1,
            "name": dictionary["name"],
            "description": dictionary["description"],
            "rules": dictionary["draft"]["rules"],
            "published_at": utc(now),
            "published_by": actor,
            "comment": body["comment"],
            "restored_from_version_id": dictionary["draft"]["based_on_version_id"],
        }
        tx.insert("dictionary_version", version["version_id"], version)
        dictionary["active_version_id"], dictionary["versions_count"] = (
            version["version_id"],
            version["version_number"],
        )
        dictionary["updated_at"], dictionary["updated_by"] = utc(now), actor
        tx.put("dictionary", dictionary["dictionary_id"], dictionary)
        current_set = rule_set(tx, dictionary["company_id"])
        emit(
            tx,
            actor,
            "DICTIONARY_PUBLISHED",
            request_id,
            now=now,
            company_id=dictionary["company_id"],
            dictionary_id=dictionary["dictionary_id"],
            version_id=version["version_id"],
            rule_set_id=current_set["rule_set_id"],
            comment=body["comment"],
        )
        return 201, {
            "dictionary": public(dictionary),
            "published_version": public(version),
            "rule_set": current_set,
        }

    def _fresh_simulation(self, tx, actor, simulation):
        dictionary = tx.require("dictionary", simulation["dictionary_id"])
        rules = flattened_rules(tx, dictionary["company_id"], dictionary)
        ready = self.ctx.ready_items(tx, dictionary["company_id"])
        if (
            self.ctx.settings.clock() >= simulation["_expires"]
            or dictionary["draft"]["draft_revision"] != simulation["draft_revision"]
            or rule_set(tx, dictionary["company_id"]) != simulation["base_rule_set"]
            or digest(rules) != simulation["_rules_digest"]
            or digest(ready) != simulation["_ready_digest"]
        ):
            raise ApiError("STALE_SIMULATION", "Тест устарел; создайте новый.", 409)

    def _revision(self, dictionary, expected):
        if dictionary["draft"]["draft_revision"] != expected:
            raise ApiError("DRAFT_VERSION_CONFLICT", "Черновик изменён другим пользователем.", 409)

    def _unique_name(self, tx, company_id, name, excluded=None):
        if not name:
            raise ApiError("VALIDATION_ERROR", "Имя справочника не может быть пустым.", 422)
        for dictionary in tx.list("dictionary"):
            if (
                dictionary["company_id"] == company_id
                and dictionary["dictionary_id"] != excluded
                and dictionary["name"].strip().casefold() == name.casefold()
            ):
                raise ApiError("DICTIONARY_NAME_CONFLICT", "Имя справочника уже используется.", 409)

    def _validate_rules(self, tx, company_id, rules):
        ids = set()
        targets = {
            (target["root_id"], target["relative_directory"]) for target in self.ctx.targets(tx, company_id)
        }
        for rule in rules:
            if rule["rule_id"] in ids:
                raise ApiError("VALIDATION_ERROR", "Идентификаторы правил должны быть уникальными.", 422)
            ids.add(rule["rule_id"])
            if (rule["target"]["root_id"], rule["target"]["relative_directory"]) not in targets:
                raise ApiError("INVALID_TARGET", "Целевой каталог недоступен для компании.", 422)
            stem = rule["target_stem"]
            if (
                not stem
                or len(stem) > 200
                or len(stem.encode("utf-8")) > 255
                or stem in (".", "..")
                or any(char in stem for char in "/\\\x00")
                or any(ord(char) < 32 or ord(char) == 127 for char in stem)
            ):
                raise ApiError("VALIDATION_ERROR", "Недопустимая основа целевого имени.", 422)
