from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse


def uid(prefix="id"):
    return f"{prefix}-{uuid.uuid4().hex}"


def utc(value=None):
    return (
        datetime.fromtimestamp(time.time() if value is None else value, timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def public(value):
    return {k: v for k, v in value.items() if not k.startswith("_")}


class ApiError(Exception):
    def __init__(
        self,
        code,
        message="Операция не может быть выполнена.",
        status=422,
        *,
        operation_id=None,
        retryable=False,
        fields=None,
    ):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.operation_id, self.retryable, self.fields = operation_id, retryable, fields or []

    def body(self, request_id):
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "request_id": request_id,
                "operation_id": self.operation_id,
                "retryable": self.retryable,
                "field_errors": self.fields,
            }
        }


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("WISEWAY_DATA_DIR", ".wiseway/state")).absolute()
    )
    sandbox_dir: Path = field(
        default_factory=lambda: Path(os.getenv("WISEWAY_SANDBOX_DIR", ".wiseway/sandbox")).absolute()
    )
    allowed_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            os.getenv(
                "WISEWAY_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000,http://localhost:5173"
            ).split(",")
        )
    )
    secure_cookie: bool = field(
        default_factory=lambda: os.getenv("WISEWAY_SECURE_COOKIE", "false").lower() == "true"
    )
    result_limit: int = 100
    max_batch_items: int = 1000
    ttl: int = 300
    readiness_seconds: int = 5
    absolute_session_seconds: int = 28800
    idle_session_seconds: int = 1800
    worker_stale_seconds: int = field(
        default_factory=lambda: int(os.getenv("WISEWAY_WORKER_STALE_SECONDS", "900"))
    )
    trusted_proxy_headers: bool = field(
        default_factory=lambda: os.getenv("WISEWAY_TRUST_PROXY_HEADERS", "false").lower() == "true"
    )
    clock: Callable[[], float] = field(default=time.time, repr=False, compare=False)

    def __post_init__(self):
        if self.result_limit not in (10, 100):
            raise ValueError("Demo result limit must be 10 or 100")
        if self.worker_stale_seconds < 60:
            raise ValueError("Worker stale threshold must be at least 60 seconds")
        if not self.allowed_origins or "*" in self.allowed_origins:
            raise ValueError("Explicit UI origins required")
        for origin in self.allowed_origins:
            if not isinstance(origin, str):
                raise ValueError("Origins must be absolute HTTP(S) origins")
            parsed = urlparse(origin)
            try:
                port = parsed.port
            except ValueError as error:
                raise ValueError("Origins must be absolute HTTP(S) origins") from error
            if (
                any(character.isspace() for character in origin)
                or "\\" in origin
                or parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.params
                or parsed.query
                or parsed.fragment
                or port is None
                and parsed.netloc.endswith(":")
            ):
                raise ValueError("Origins must be absolute HTTP(S) origins")
            loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            if not self.secure_cookie and not loopback:
                raise ValueError("HTTP demo is loopback-only; use secure cookies for HTTPS origins")
            if parsed.scheme == "http" and not loopback:
                raise ValueError("HTTP demo is loopback-only; use HTTPS for non-loopback origins")

    @property
    def database(self):
        return self.data_dir / "wiseway.sqlite3"

    def app_config(self):
        return {
            "api_contract_version": "1.1.0",
            "display_timezone": "Europe/Moscow",
            "search_result_limit": self.result_limit,
            "max_batch_items": self.max_batch_items,
            "max_query_length": 512,
            "preview_ttl_seconds": self.ttl,
            "snapshot_ttl_seconds": self.ttl,
            "simulation_ttl_seconds": self.ttl,
            "batch_poll_interval_ms": 1000,
            "audit_poll_interval_ms": 30000,
        }
