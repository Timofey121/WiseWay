import sqlite3
from pathlib import Path

from wiseway.storage import Store


def test_existing_database_gets_pagination_indexes_without_losing_data(tmp_path):
    database = tmp_path / "state.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(Path("backend/wiseway/migrations/001_initial.sql").read_text())
        connection.execute("INSERT INTO objects VALUES('user','existing',?)", ('{"login":"preserved"}',))
    store = Store(database)
    with store.transaction(write=False) as tx:
        assert tx.require("user", "existing") == {"login": "preserved"}
        assert tx.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 2
        indexes = {row[1] for row in tx.connection.execute("PRAGMA index_list('objects')")}
        assert {"page_expiry", "page_owner_bytes"} <= indexes
