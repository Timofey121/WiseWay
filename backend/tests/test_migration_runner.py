import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from wiseway.storage import Store


def _migration(directory: Path, version: int, sql: str):
    (directory / f"{version:03d}_test.sql").write_text(sql, encoding="utf-8")


def test_failed_migration_rolls_back_ddl_and_can_resume(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    _migration(
        migrations,
        1,
        "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY); INSERT INTO schema_migrations VALUES(1);",
    )
    _migration(migrations, 2, "CREATE TABLE transient(value TEXT); INSERT INTO missing VALUES(1);")
    database = tmp_path / "state.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        Store(database, migration_dir=migrations)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version FROM schema_migrations").fetchall() == [(1,)]
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='transient'").fetchone() is None
    _migration(migrations, 2, "CREATE TABLE transient(value TEXT); INSERT INTO transient VALUES('once');")
    Store(database, migration_dir=migrations)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT value FROM transient").fetchall() == [("once",)]


def test_migration_ledger_rejects_changed_checksum_and_concurrent_initializers(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    _migration(
        migrations,
        1,
        "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY); INSERT INTO schema_migrations VALUES(1);",
    )
    _migration(
        migrations,
        2,
        "CREATE TABLE applied_once(value TEXT UNIQUE); INSERT INTO applied_once VALUES('once');",
    )
    database = tmp_path / "state.sqlite3"
    # All constructors contend for the initial WAL mode switch and migration lock.
    for _ in range(4):
        barrier = Barrier(4)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: (barrier.wait(), Store(database, migration_dir=migrations))[1], range(4)))
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT value FROM applied_once").fetchall() == [("once",)]
    _migration(
        migrations,
        2,
        "CREATE TABLE applied_once(value TEXT UNIQUE); INSERT INTO applied_once VALUES('changed');",
    )
    with pytest.raises(RuntimeError, match="checksum"):
        Store(database, migration_dir=migrations)


def test_legacy_version_rows_adopt_current_checksums(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    _migration(
        migrations,
        1,
        "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY); INSERT INTO schema_migrations VALUES(1);",
    )
    database = tmp_path / "state.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript((migrations / "001_test.sql").read_text())
    Store(database, migration_dir=migrations)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version, length(checksum) FROM schema_migrations").fetchall() == [
            (1, 64)
        ]


def test_unknown_future_version_is_rejected(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    _migration(
        migrations,
        1,
        "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY); INSERT INTO schema_migrations VALUES(1);",
    )
    database = tmp_path / "state.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript((migrations / "001_test.sql").read_text())
        connection.execute("INSERT INTO schema_migrations VALUES(99)")
    with pytest.raises(RuntimeError, match="future"):
        Store(database, migration_dir=migrations)
