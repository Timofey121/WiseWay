"""The checked-in OpenAPI is both the public document and wire validator."""

from pathlib import Path
from functools import lru_cache
import json
import sysconfig

import yaml
from jsonschema import Draft202012Validator, FormatChecker, ValidationError, validators
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from .common import ApiError


class Contract:
    def __init__(self):
        path = Path(__file__).resolve().parents[2] / "contracts/openapi/wiseway-v1.yaml"
        if not path.is_file():
            path = Path(sysconfig.get_path("data")) / "share/wiseway/wiseway-v1.yaml"
        self.spec = yaml.safe_load(path.read_text())
        self.registry = Registry().with_resource(
            "urn:wiseway:api", Resource.from_contents(self.spec, default_specification=DRAFT202012)
        )
        self.validators = {}

        # Repeated immutable rows dominate large result validation. Cache only
        # exact JSON values, never object IDs; a changed field must be checked again.
        @lru_cache(maxsize=1024)
        def checked_row(reference, encoded):
            schema = self.resolve({"$ref": reference})
            return self.validator(schema).is_valid(json.loads(encoded))

        base_ref = Draft202012Validator.VALIDATORS["$ref"]
        reusable = {"#/components/schemas/SearchItem", "#/components/schemas/AuditEvent"}

        def response_ref(validator, reference, instance, schema):
            if reference in reusable:
                encoded = json.dumps(instance, ensure_ascii=False, separators=(",", ":"))
                if len(encoded) <= 16384:
                    if not checked_row(reference, encoded):
                        yield ValidationError("Invalid response row")
                    return
            yield from base_ref(validator, reference, instance, schema)

        self.response_validator_class = validators.extend(Draft202012Validator, {"$ref": response_ref})
        self.response_validators = {}

    def resolve(self, value):
        while isinstance(value, dict) and "$ref" in value:
            node = self.spec
            for part in value["$ref"][2:].split("/"):
                node = node[part.replace("~1", "/").replace("~0", "~")]
            value = node
        return value

    def validator(self, schema):
        key = id(schema)
        if key not in self.validators:
            self.validators[key] = Draft202012Validator(
                schema,
                registry=self.registry,
                _resolver=self.registry.resolver("urn:wiseway:api"),
                format_checker=FormatChecker(),
            )
        return self.validators[key]

    def check(self, schema, value):
        if not self.validator(schema).is_valid(value):
            # Validation errors may embed credentials or host paths: never copy them to the wire/log.
            raise ApiError("VALIDATION_ERROR", "Запрос не соответствует контракту.", 422)

    def request(self, operation, path_item, path_params, query, headers, body):
        parameters = [
            self.resolve(p) for p in path_item.get("parameters", []) + operation.get("parameters", [])
        ]
        result = {}
        known_queries = {p["name"] for p in parameters if p["in"] == "query"}
        if set(query.keys()) - known_queries:
            raise ApiError("VALIDATION_ERROR", "Неизвестный параметр запроса.", 422)
        for p in parameters:
            source = path_params if p["in"] == "path" else query if p["in"] == "query" else headers
            value = source.get(p["name"])
            if value is None:
                if p.get("required"):
                    raise ApiError("VALIDATION_ERROR", "Отсутствует обязательный параметр.", 422)
                if "default" in self.resolve(p["schema"]):
                    result[p["name"]] = self.resolve(p["schema"])["default"]
                continue
            schema = self.resolve(p["schema"])
            if p["in"] == "query" and len(query.getlist(p["name"])) != 1:
                raise ApiError("VALIDATION_ERROR", "Повторяющийся query-параметр.", 422)
            if schema.get("type") == "integer":
                try:
                    if not value.isdecimal():
                        raise ValueError
                    value = int(value)
                except (ValueError, AttributeError):
                    raise ApiError("VALIDATION_ERROR", "Ожидается целое число.", 422) from None
            self.check(p["schema"], value)
            result[p["name"]] = value
        if "requestBody" in operation:
            self.check(self.resolve(operation["requestBody"])["content"]["application/json"]["schema"], body)
        elif body is not None:
            raise ApiError("VALIDATION_ERROR", "Тело запроса не предусмотрено.", 422)
        return result

    def response(self, operation, status, value):
        response = self.resolve(operation["responses"].get(str(status), {}))
        schema = response.get("content", {}).get("application/json", {}).get("schema")
        valid = str(status) in operation["responses"]
        if valid and schema:
            key = id(schema)
            if key not in self.response_validators:
                self.response_validators[key] = self.response_validator_class(
                    schema,
                    registry=self.registry,
                    _resolver=self.registry.resolver("urn:wiseway:api"),
                    format_checker=FormatChecker(),
                )
            valid = self.response_validators[key].is_valid(value)
        if not valid:
            raise RuntimeError(f"Invalid response contract for {operation['operationId']} status={status}")
