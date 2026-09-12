import pytest


def _document(identity="file-1", payload="x"):
    return {"id": identity, "deleted": False, "payload": payload}


def test_encoded_bulk_batch_serializes_each_document_once(monkeypatch):
    import wiseway.opensearch as opensearch
    from wiseway.opensearch import BulkBatchBuilder

    document = _document()
    encoded = []
    original = opensearch._json

    def observe(value):
        encoded.append(value)
        return original(value)

    monkeypatch.setattr(opensearch, "_json", observe)
    builder = BulkBatchBuilder(target_bytes=1024, hard_limit_bytes=2048)

    assert builder.add(document, 7)
    batch = builder.finish()

    assert list(batch) == [(document, 7)]
    assert sum(value is document for value in encoded) == 1
    assert batch.payload.endswith(b"\n")


def test_encoded_bulk_batch_keeps_one_record_within_hard_limit_when_it_exceeds_target():
    from wiseway.opensearch import BulkBatchBuilder

    first, second = _document("first", "a" * 150), _document("second", "b" * 150)
    builder = BulkBatchBuilder(target_bytes=300, hard_limit_bytes=1024)

    assert builder.add(first, 1)
    assert not builder.add(second, 2)
    assert list(builder.finish()) == [(first, 1)]
    assert builder.add(second, 2)
    assert list(builder.finish()) == [(second, 2)]


def test_encoded_bulk_batch_rejects_a_record_above_transport_hard_limit():
    from wiseway.opensearch import BulkBatchBuilder

    with pytest.raises(ValueError, match="hard limit"):
        BulkBatchBuilder(target_bytes=32, hard_limit_bytes=64).add(_document(payload="x" * 128), 1)


def test_bulk_byte_limits_include_multibyte_utf8_and_action_lines():
    from wiseway.opensearch import BulkBatchBuilder

    doc = _document(payload="я" * 100)
    reference = BulkBatchBuilder()
    assert reference.add(doc, 1)
    payload = reference.finish().payload
    limit = len(payload) - 1
    assert len(payload.decode()) < limit
    with pytest.raises(ValueError, match="hard limit"):
        BulkBatchBuilder(target_bytes=limit, hard_limit_bytes=limit).add(doc, 1)


def test_preencoded_bulk_keeps_the_transport_record_count_bound():
    from wiseway.opensearch import BulkBatch, OpenSearch

    batch = BulkBatch(tuple((_document(), 1) for _ in range(5001)), b"\n")
    with OpenSearch("http://127.0.0.1:1", allow_http=True) as client:
        client.request = lambda *_args, **_kwargs: pytest.fail("Oversized batch reached the transport")
        with pytest.raises(ValueError, match="bulk batch"):
            client.bulk("wiseway-test", batch)


@pytest.mark.parametrize("target", [0, 16 * 1024**2 + 1])
def test_invalid_bulk_target_is_rejected_before_import_initialization(configured, target):
    from wiseway.archive_import import ArchiveImporter
    from types import SimpleNamespace

    with pytest.raises(ValueError, match="byte limits"):
        ArchiveImporter(SimpleNamespace(settings=configured), object(), bulk_target_bytes=target)
    assert not (configured.data_dir / "archive-import.sqlite3").exists()


def test_opensearch_bulk_sends_preencoded_payload_without_serializing_again(monkeypatch):
    import wiseway.opensearch as opensearch
    from wiseway.opensearch import BulkBatchBuilder, OpenSearch

    document = _document()
    builder = BulkBatchBuilder(target_bytes=1024, hard_limit_bytes=2048)
    assert builder.add(document, 1)
    batch = builder.finish()
    with OpenSearch("http://127.0.0.1:1", allow_http=True) as client:
        sent = []
        client.request = lambda *args, **kwargs: (
            sent.append((args, kwargs)) or {"items": [{"index": {"status": 201}}]}
        )
        monkeypatch.setattr(
            opensearch, "_json", lambda _: (_ for _ in ()).throw(AssertionError("serialized"))
        )

        client.bulk("wiseway-test", batch)

    assert sent[0][0][2] == batch.payload
    assert sent[0][1]["ndjson"] is True


def test_importer_checkpoints_before_an_overflow_pending_record(configured, tmp_path, monkeypatch):
    import sqlite3

    import wiseway.archive_import as archive_import
    from test_archive_import import Engine, root_id, row, source
    from wiseway.archive_import import ArchiveImporter
    from wiseway.common import ApiError
    from wiseway.services import Context

    ctx, engine = Context(configured), Engine()
    try:
        root = root_id(ctx)
        rows = [row("file-1"), row("file-2"), row("file-3")]
        manifest = source(tmp_path / "overflow.ndjson", rows)
        first_line_bytes = len((__import__("json").dumps(rows[0]) + "\n").encode())
        monkeypatch.setattr(archive_import, "BULK_TARGET_BYTES", 1, raising=False)
        importer = ArchiveImporter(ctx, engine, batch_size=3)
        calls = 0
        original = engine.bulk

        def fail_second_batch(name, records):
            nonlocal calls
            calls += 1
            original(name, records)
            if calls == 2:
                raise ApiError("SEARCH_UNAVAILABLE", status=503)

        engine.bulk = fail_second_batch
        with pytest.raises(ApiError):
            importer.run(root, manifest)
        with sqlite3.connect(importer.database) as db:
            saved = db.execute("SELECT byte_offset,records FROM imports").fetchone()
        assert saved == (first_line_bytes, 1)

        engine.bulk = original
        result = importer.run(root, manifest)
        assert result["records"] == 3
        assert set(engine.docs[result["index"]]) == {"file-1", "file-2", "file-3"}
    finally:
        ctx.close()
