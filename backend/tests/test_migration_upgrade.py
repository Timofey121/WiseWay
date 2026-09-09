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
        expected_version = max(
            int(path.name.split("_", 1)[0]) for path in Path("backend/wiseway/migrations").glob("*.sql")
        )
        assert (
            tx.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            == expected_version
        )
        indexes = {row[1] for row in tx.connection.execute("PRAGMA index_list('objects')")}
        assert {"page_expiry", "page_owner_bytes", "attempt_batch_lookup", "queue_company_order"} <= indexes
        audit_indexes = {row[1] for row in tx.connection.execute("PRAGMA index_list('audit')")}
        assert "audit_utc_event_order" in audit_indexes
