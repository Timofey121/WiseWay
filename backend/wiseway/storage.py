"""Transactional SQLite storage. A unit of work never escapes its connection."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .common import ApiError


class UnitOfWork:
    def __init__(self, connection):
        self.connection = connection

    def get(self, kind, key, default=None):
        row = self.connection.execute(
            "SELECT body FROM objects WHERE kind=? AND id=?", (kind, key)
        ).fetchone()
        return json.loads(row[0]) if row else default

    def require(self, kind, key):
        value = self.get(kind, key)
        if value is None:
            raise ApiError("NOT_FOUND", "Объект не найден.", 404)
        return value

    def put(self, kind, key, value):
        self.connection.execute(
            "INSERT INTO objects(kind,id,body) VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body",
            (kind, key, json.dumps(value, ensure_ascii=False)),
        )

    def insert(self, kind, key, value):
        self.connection.execute(
            "INSERT INTO objects(kind,id,body) VALUES(?,?,?)",
            (kind, key, json.dumps(value, ensure_ascii=False)),
        )

    def delete(self, kind, key):
        self.connection.execute("DELETE FROM objects WHERE kind=? AND id=?", (kind, key))

    def list(self, kind):
        return [
            json.loads(row[0])
            for row in self.connection.execute("SELECT body FROM objects WHERE kind=? ORDER BY id", (kind,))
        ]

    def append_event(self, event):
        self.connection.execute(
            "INSERT INTO audit(id,body) VALUES(?,?)",
            (event["event_id"], json.dumps(event, ensure_ascii=False)),
        )

    def events(self):
        return [
            json.loads(row[0]) for row in self.connection.execute("SELECT body FROM audit ORDER BY seq DESC")
        ]


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript((Path(__file__).parent / "migrations" / "001_initial.sql").read_text())
        path.chmod(0o600)

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @contextmanager
    def transaction(self, write=True):
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield UnitOfWork(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
