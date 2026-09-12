import sqlite3
from pathlib import Path
import shutil

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


def test_existing_sqlite_search_rows_get_normalized_modified_sort_keys(tmp_path):
    database = tmp_path / "state.sqlite3"
    legacy_migrations = tmp_path / "legacy-migrations"
    legacy_migrations.mkdir()
    migration_dir = Path("backend/wiseway/migrations")
    for source in migration_dir.glob("*.sql"):
        if int(source.name.split("_", 1)[0]) < 9:
            shutil.copy2(source, legacy_migrations / source.name)
    Store(database, migration_dir=legacy_migrations)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO search_generations(generation_id,root_id,state,created_at) VALUES(?,?,?,?)",
            ("legacy", "root", "READY", "2026-01-01T00:00:00Z"),
        )
        connection.execute(
            "INSERT INTO search_items(generation_id,item_no,item_id,body,filename_key,path_key,relative_path,modified_at,size_bytes) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            ("legacy", 0, "whole", "{}", b"a", b"a", "a.txt", "2026-01-01T00:00:00Z", 1),
        )
        connection.execute(
            "INSERT INTO search_items(generation_id,item_no,item_id,body,filename_key,path_key,relative_path,modified_at,size_bytes) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            ("legacy", 1, "fraction", "{}", b"b", b"b", "b.txt", "2026-01-01T00:00:00.001Z", 1),
        )
        connection.commit()

    Store(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT item_id FROM search_items ORDER BY modified_key,path_key,item_id"
        ).fetchall() == [("whole",), ("fraction",)]
        assert connection.execute(
            "SELECT modified_key FROM search_items WHERE item_id='whole'"
        ).fetchone() == ("2026-01-01T00:00:00.",)
