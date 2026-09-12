"""Transactional SQLite storage. A unit of work never escapes its connection."""

import json
import hashlib
import re
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path

from .common import ApiError


class UnitOfWork:
    def __init__(self, connection, write=True):
        self.connection = connection
        self.write = write

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
    STARTUP_LOCK_TIMEOUT_SECONDS = 5

    def __init__(self, path: Path, *, migration_dir: Path | None = None):
        self.path = path
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        deadline = time.monotonic() + self.STARTUP_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                with closing(self.connect()) as connection:
                    # WAL is required for concurrent readers and the startup
                    # path never downgrades to a less durable journal mode.
                    connection.execute("PRAGMA journal_mode=WAL")
                    self._run_migrations(connection, migration_dir or Path(__file__).parent / "migrations")
                break
            except sqlite3.OperationalError as error:
                if not self._startup_lock_error(error) or time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)
        path.chmod(0o600)

    @staticmethod
    def _startup_lock_error(error: sqlite3.OperationalError) -> bool:
        code = getattr(error, "sqlite_errorcode", None)
        return isinstance(code, int) and (code & 0xFF) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}

    @staticmethod
    def _statements(source: str):
        """Split complete SQLite statements without executescript's implicit commits."""
        statement, result = "", []
        for character in source:
            statement += character
            if sqlite3.complete_statement(statement):
                result.append(statement)
                statement = ""
        if statement.strip():
            raise RuntimeError("Migration ends with an incomplete SQL statement")
        return result

    @staticmethod
    def _migration_files(migration_dir: Path):
        result = []
        for path in migration_dir.glob("*.sql"):
            try:
                version = int(path.name.split("_", 1)[0])
            except ValueError as error:
                raise RuntimeError(f"Invalid migration filename: {path.name}") from error
            result.append((version, path))
        if len({version for version, _ in result}) != len(result):
            raise RuntimeError("Duplicate migration version")
        return sorted(result)

    def _run_migrations(self, connection, migration_dir: Path):
        migrations = self._migration_files(migration_dir)
        for version, path in migrations:
            source = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(source.encode("utf-8")).hexdigest()
            connection.execute("BEGIN IMMEDIATE")
            try:
                exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
                ).fetchone()
                if exists:
                    columns = {row[1] for row in connection.execute("PRAGMA table_info(schema_migrations)")}
                    if "checksum" not in columns:
                        # Legacy ledgers only recorded versions. Their original source bytes
                        # cannot be reconstructed, so adopt the checked-in checksum once.
                        connection.execute("ALTER TABLE schema_migrations ADD COLUMN checksum TEXT")
                    future = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
                    if future is not None and future > migrations[-1][0]:
                        raise RuntimeError(f"Database has unknown future migration version {future}")
                    recorded = connection.execute(
                        "SELECT checksum FROM schema_migrations WHERE version=?", (version,)
                    ).fetchone()
                    if recorded is not None:
                        if recorded[0] is None:
                            connection.execute(
                                "UPDATE schema_migrations SET checksum=? WHERE version=?", (checksum, version)
                            )
                        elif recorded[0] != checksum:
                            raise RuntimeError(f"Migration checksum changed for version {version}")
                        connection.commit()
                        continue
                for statement in self._statements(source):
                    # 001/002 predate the checksum column and record only a
                    # version.  The runner owns ledger writes now.
                    if re.fullmatch(
                        r"\s*INSERT\s+OR\s+IGNORE\s+INTO\s+schema_migrations\s+VALUES\s*\(\s*\d+\s*\)\s*;\s*",
                        statement,
                        flags=re.IGNORECASE,
                    ):
                        continue
                    connection.execute(statement)
                # Legacy scripts insert their own version. New scripts do not need to.
                columns = {row[1] for row in connection.execute("PRAGMA table_info(schema_migrations)")}
                if "checksum" not in columns:
                    connection.execute("ALTER TABLE schema_migrations ADD COLUMN checksum TEXT")
                connection.execute(
                    "INSERT INTO schema_migrations(version, checksum) VALUES(?, ?) "
                    "ON CONFLICT(version) DO UPDATE SET checksum=excluded.checksum",
                    (version, checksum),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA temp_store=FILE")
        return connection

    @contextmanager
    def transaction(self, write=True):
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield UnitOfWork(connection, write=write)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
