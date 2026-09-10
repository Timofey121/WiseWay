import json

import pytest

from wiseway.archive_import import ArchiveImporter
from wiseway.common import ApiError
from wiseway.services import Context


class Engine:
    def __init__(self):
        self.docs = {}
        self.fail = False
        self.publications = 0
        self.renewals = []

    def ensure(self, name, **kwargs):
        self.docs.setdefault(name, {})

    def bulk(self, name, records):
        for doc, version in records:
            old = self.docs[name].get(doc["id"])
            if old is None or old[1] <= version:
                self.docs[name][doc["id"]] = doc, version
        if self.fail:
            raise ApiError("SEARCH_UNAVAILABLE", status=503)

    def publish(self, name):
        self.publications += 1
        return f"pit-{self.publications}"

    def request(self, method, path, body):
        self.renewals.append((method, path, body))
        return {"_shards": {"total": 1, "successful": 1, "failed": 0}}

    def close_pit(self, pit):
        pass


def source(path, entries):
    path.write_text("".join(json.dumps(row) + "\n" for row in entries))
    return path


def row(identity="file-1"):
    return {
        "op": "upsert",
        "item_id": identity,
        "relative_path": f"Archive/Atlas/Orion_2031/Reports/{identity}.txt",
        "size_bytes": 5,
        "modified_at": "2026-01-01T00:00:00Z",
    }


def root_id(ctx):
    with ctx.store.transaction(write=False) as tx:
        return next(root["root_id"] for root in tx.list("root") if root.get("_searchable"))


def test_failed_bulk_resumes_without_partial_publication(configured, tmp_path):
    ctx, engine = Context(configured), Engine()
    try:
        root = root_id(ctx)
        path = source(tmp_path / "full.ndjson", [row("file-1"), row("file-2")])
        importer = ArchiveImporter(ctx, engine, batch_size=1)
        with ctx.store.transaction(write=False) as tx:
            previous = tx.get("index", root)
        engine.fail = True
        with pytest.raises(ApiError):
            importer.run(root, path)
        with ctx.store.transaction(write=False) as tx:
            assert tx.get("index", root) == previous
        engine.fail = False
        result = importer.run(root, path)
        assert result["records"] == 2
        assert len(engine.docs[result["index"]]) == 2
        assert engine.publications == 1
        assert importer.run(root, path) == result
        assert engine.publications == 1
    finally:
        ctx.close()


def test_delta_requires_current_base_and_keeps_tombstone(configured, tmp_path):
    ctx, engine = Context(configured), Engine()
    try:
        importer = ArchiveImporter(ctx, engine)
        root = root_id(ctx)
        first = importer.run(root, source(tmp_path / "full.ndjson", [row()]))
        delta = source(tmp_path / "delta.ndjson", [{"op": "delete", "item_id": "file-1"}])
        with pytest.raises(ValueError, match="base"):
            importer.run(root, delta, mode="delta", base_generation="wrong")
        second = importer.run(root, delta, mode="delta", base_generation=first["generation"])
        assert second["index"] == first["index"]
        assert second["generation"] != first["generation"]
        assert engine.docs[first["index"]]["file-1"][0]["deleted"] is True
    finally:
        ctx.close()


def test_changed_source_cannot_resume_partial_import(configured, tmp_path):
    ctx, engine = Context(configured), Engine()
    try:
        importer = ArchiveImporter(ctx, engine, batch_size=1)
        root = root_id(ctx)
        path = source(tmp_path / "full.ndjson", [row()])
        engine.fail = True
        with pytest.raises(ApiError):
            importer.run(root, path)
        engine.fail = False
        source(path, [row("changed")])
        with pytest.raises(ValueError, match="unfinished"):
            importer.run(root, path)
    finally:
        ctx.close()


@pytest.mark.parametrize(
    "bad",
    [
        {**row(), "relative_path": "../secret"},
        {**row(), "size_bytes": -1},
        {**row(), "size_bytes": True},
        {**row(), "modified_at": "bad"},
        {**row(), "item_id": ""},
        {"op": "delete", "item_id": "x"},
    ],
)
def test_invalid_initial_record_is_never_published(configured, tmp_path, bad):
    ctx, engine = Context(configured), Engine()
    try:
        with pytest.raises(ValueError):
            ArchiveImporter(ctx, engine).run(root_id(ctx), source(tmp_path / "bad.ndjson", [bad]))
        assert engine.publications == 0
    finally:
        ctx.close()


def test_abort_failed_delta_requires_full_rebuild(configured, tmp_path):
    ctx, engine = Context(configured), Engine()
    try:
        importer = ArchiveImporter(ctx, engine)
        root = root_id(ctx)
        first = importer.run(root, source(tmp_path / "initial.ndjson", [row()]))
        engine.fail = True
        with pytest.raises(ApiError):
            importer.run(
                root,
                source(tmp_path / "broken.ndjson", [row("new")]),
                mode="delta",
                base_generation=first["generation"],
            )
        importer.abort(root)
        engine.fail = False
        with pytest.raises(ValueError, match="full"):
            importer.run(
                root,
                source(tmp_path / "later.ndjson", [row("later")]),
                mode="delta",
                base_generation=first["generation"],
            )
        rebuilt = importer.run(root, source(tmp_path / "rebuilt.ndjson", [row("rebuilt")]))
        assert rebuilt["index"] != first["index"]
    finally:
        ctx.close()


def test_crash_between_publication_and_checkpoint_does_not_republish(configured, tmp_path, monkeypatch):
    ctx, engine = Context(configured), Engine()
    try:
        importer = ArchiveImporter(ctx, engine)
        root = root_id(ctx)
        manifest = source(tmp_path / "full.ndjson", [row()])
        finish = importer._finish

        def crash(*args):
            raise RuntimeError("simulated crash after pointer commit")

        monkeypatch.setattr(importer, "_finish", crash)
        with pytest.raises(RuntimeError, match="simulated"):
            importer.run(root, manifest)
        assert engine.publications == 1
        monkeypatch.setattr(importer, "_finish", finish)
        assert importer.run(root, manifest)["records"] == 1
        assert engine.publications == 1
    finally:
        ctx.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("item_id", "bad_id"),
        ("item_id", "a" * 97),
        ("relative_path", "Archive/a:b.txt"),
        ("relative_path", "Archive/a\x7f.txt"),
        ("size_bytes", 2**53),
        ("modified_at", "2026-01-01Z"),
    ],
)
def test_import_rejects_values_outside_public_contract(configured, tmp_path, field, value):
    ctx = Context(configured)
    try:
        with pytest.raises(ValueError):
            ArchiveImporter(ctx, Engine()).run(
                root_id(ctx), source(tmp_path / "invalid.ndjson", [{**row(), field: value}])
            )
    finally:
        ctx.close()
