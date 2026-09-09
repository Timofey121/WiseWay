import pytest

from test_archive_import import Engine, row, source, root_id
from wiseway.archive_import import ArchiveImporter
from wiseway.common import ApiError
from wiseway.services import Context
from wiseway.search_outbox import enqueue_move, drain


def enqueue(ctx, root):
    with ctx.store.transaction() as tx:
        enqueue_move(
            tx,
            "attempt-1",
            "moved-1",
            {"root_id": root, "relative_path": "Archive/Atlas/Orion_2031/Reports/moved.txt"},
            {"size": 9, "mtime_ns": 1767225600000000000},
        )


def test_move_outbox_is_transactional_and_deduplicated(configured):
    ctx = Context(configured)
    try:
        root = root_id(ctx)
        with ctx.store.transaction() as tx:
            value = tx.require("root", root)
            value["_index_storage"] = "opensearch"
            tx.put("root", root, value)
        with pytest.raises(RuntimeError):
            with ctx.store.transaction() as tx:
                enqueue_move(
                    tx,
                    "failed",
                    "file-1",
                    {"root_id": root, "relative_path": "Archive/a.txt"},
                    {"size": 1, "mtime_ns": 0},
                )
                raise RuntimeError("rollback")
        enqueue(ctx, root)
        enqueue(ctx, root)
        with ctx.store.transaction(write=False) as tx:
            assert tx.connection.execute("SELECT count(*) FROM search_outbox").fetchone()[0] == 1
    finally:
        ctx.close()


def test_outbox_is_acknowledged_only_after_search_publication(configured, tmp_path):
    ctx, engine = Context(configured), Engine()
    try:
        importer = ArchiveImporter(ctx, engine)
        root = root_id(ctx)
        initial = importer.run(root, source(tmp_path / "initial.ndjson", [row()]))
        enqueue(ctx, root)
        engine.fail = True
        with pytest.raises(ApiError):
            drain(importer)
        with ctx.store.transaction(write=False) as tx:
            assert tx.connection.execute("SELECT count(*) FROM search_outbox").fetchone()[0] == 1
            assert tx.require("index", root)["root"]["index_generation"] == initial["generation"]
        engine.fail = False
        assert drain(importer) == 1
        assert drain(importer) == 0
        with ctx.store.transaction(write=False) as tx:
            assert tx.connection.execute("SELECT count(*) FROM search_outbox").fetchone()[0] == 0
        assert engine.docs[initial["index"]]["moved-1"][0]["size"] == 9
    finally:
        ctx.close()


def test_aborted_outbox_can_resume_after_full_rebuild(configured, tmp_path):
    ctx, engine = Context(configured), Engine()
    try:
        importer = ArchiveImporter(ctx, engine)
        root = root_id(ctx)
        importer.run(root, source(tmp_path / "initial.ndjson", [row()]))
        enqueue(ctx, root)
        engine.fail = True
        with pytest.raises(ApiError):
            drain(importer)
        importer.abort(root)
        engine.fail = False
        importer.run(root, source(tmp_path / "replacement.ndjson", [row("replacement")]))
        assert drain(importer) == 1
    finally:
        ctx.close()
