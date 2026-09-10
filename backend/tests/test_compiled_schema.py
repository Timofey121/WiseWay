from copy import deepcopy

import pytest

from wiseway.search import build_item, compile_schema


def _schema():
    companies = ["Atlas", "Нова", "München"]
    projects = [f"Проект-{number:04d}" for number in range(128)]
    return {
        "schema_set_version": "schema-compiled-test",
        "root_levels": [
            ["section", "Раздел", ["Archive"], False],
            ["company", "Компания", companies, False],
            ["project", "Проект", projects, False],
        ],
        "tail_by_company": {
            "atlas": [["category", "Категория", ["Reports", "Данные"], False]],
            "нова": [["category", "Категория", ["Reports", "Данные"], False]],
        },
    }


@pytest.mark.parametrize(
    "path",
    [
        "Archive/ATLAS/ПРОЕКТ-0007/Данные/Документ-12.pdf",
        "Archive/Нова/Проект-0001/Reports/файл.txt",
        "Archive/Atlas/Неизвестный/Reports/file.txt",
        "Archive/Atlas/Проект-0001",
        "Archive/Atlas/Проект-0001/Reports/extra/file.txt",
    ],
)
def test_compiled_schema_matches_direct_build_for_valid_and_invalid_paths(path):
    schema = _schema()
    expected = build_item("root", "Отображение", path, 17, "2026-01-01T00:00:00Z", schema, "file-1")

    actual = build_item(
        "root",
        "Отображение",
        path,
        17,
        "2026-01-01T00:00:00Z",
        schema,
        "file-1",
        compiled_schema=compile_schema(schema),
    )

    assert actual == expected


def test_compiled_schema_snapshots_values_and_preserves_raw_marker_casing():
    schema = _schema()
    compiled = compile_schema(schema)
    before = build_item(
        "root",
        "",
        "Archive/ATLAS/ПРОЕКТ-0007/Данные/Документ-12.pdf",
        17,
        "2026-01-01T00:00:00Z",
        schema,
        "file-1",
        compiled_schema=compiled,
    )
    changed = deepcopy(schema)
    changed["root_levels"][1][2][:] = ["Different"]
    changed["tail_by_company"]["atlas"][0][2][:] = ["Other"]

    after = build_item(
        "root",
        "",
        "Archive/ATLAS/ПРОЕКТ-0007/Данные/Документ-12.pdf",
        17,
        "2026-01-01T00:00:00Z",
        changed,
        "file-1",
        compiled_schema=compiled,
    )

    assert after == before
    assert [marker["raw_value"] for marker in after["markers"]] == [
        "Archive",
        "ATLAS",
        "ПРОЕКТ-0007",
        "Данные",
    ]


def test_compiled_schema_does_not_share_mutable_schema_values():
    schema = _schema()
    compiled = compile_schema(schema)
    schema["root_levels"][2][2].append("Future-project")

    original = build_item(
        "root",
        "",
        "Archive/Atlas/Future-project/Reports/file.txt",
        1,
        "2026-01-01T00:00:00Z",
        schema,
        "file-2",
        compiled_schema=compiled,
    )

    assert original["structure_status"] == "UNRECOGNIZED"


def test_direct_build_keeps_unrelated_schema_tail_lazy():
    schema = _schema()
    schema["tail_by_company"]["unused"] = [["unused", "Unused", [None], False]]

    item = build_item(
        "root",
        "",
        "Archive/Atlas/Проект-0001/Reports/file.txt",
        1,
        "2026-01-01T00:00:00Z",
        schema,
        "file-3",
    )

    assert item["structure_status"] == "VALID"
    assert [marker["marker_id"] for marker in item["markers"]] == [
        "marker-fc09fc52096aae368699",
        "marker-c0217432c88484775adc",
        "marker-f89d4df40838aa93ac09",
        "marker-010c5456419654798de4",
    ]


def test_archive_import_compiles_one_schema_snapshot_per_run(configured, tmp_path, monkeypatch):
    import wiseway.archive_import as archive_import
    from test_archive_import import Engine, root_id, row, source
    from wiseway.archive_import import ArchiveImporter
    from wiseway.services import Context

    ctx = Context(configured)
    try:
        calls = 0
        original = compile_schema

        def counted(schema):
            nonlocal calls
            calls += 1
            return original(schema)

        monkeypatch.setattr(archive_import, "compile_schema", counted, raising=False)
        manifest = source(tmp_path / "full.ndjson", [row("file-1"), row("file-2"), row("file-3")])

        ArchiveImporter(ctx, Engine(), batch_size=1).run(root_id(ctx), manifest)

        assert calls == 1
    finally:
        ctx.close()


def test_full_import_renews_old_pit_before_replacing_the_published_pointer(configured, tmp_path):
    from test_archive_import import Engine, root_id, row, source
    from wiseway.archive_import import ArchiveImporter
    from wiseway.services import Context

    ctx, engine = Context(configured), Engine()
    try:
        importer = ArchiveImporter(ctx, engine, batch_size=1)
        root = root_id(ctx)
        first = importer.run(root, source(tmp_path / "initial.ndjson", [row("old")]))
        with ctx.store.transaction(write=False) as tx:
            old_pit = tx.require("index", root)["_pit_id"]
        renewals, pointer_during_build = [], []

        def request(method, path, body):
            renewals.append((method, path, body["pit"]["id"]))
            return {"_shards": {"total": 1, "successful": 1, "failed": 0}}

        original_bulk = engine.bulk

        def bulk(name, records):
            with ctx.store.transaction(write=False) as tx:
                pointer_during_build.append(tx.require("index", root)["_pit_id"])
            return original_bulk(name, records)

        engine.request, engine.bulk = request, bulk
        replacement = importer.run(root, source(tmp_path / "replacement.ndjson", [row("new")]))

        assert first["generation"] != replacement["generation"]
        assert renewals == [("POST", "/_search?allow_partial_search_results=false", old_pit)]
        assert pointer_during_build == [old_pit]
        with ctx.store.transaction(write=False) as tx:
            assert tx.require("index", root)["_pit_id"] != old_pit
    finally:
        ctx.close()


def test_delta_resumes_after_a_lost_old_pit_without_republishing_it(configured, tmp_path):
    from test_archive_import import Engine, root_id, row, source
    from wiseway.archive_import import ArchiveImporter
    from wiseway.common import ApiError
    from wiseway.services import Context

    ctx, engine = Context(configured), Engine()
    try:
        importer = ArchiveImporter(ctx, engine)
        root = root_id(ctx)
        first = importer.run(root, source(tmp_path / "initial.ndjson", [row("old")]))
        with ctx.store.transaction(write=False) as tx:
            old_pointer = tx.require("index", root)["_pit_id"]
        engine.request = lambda *_: {"_shards": {"total": 1, "successful": 0, "failed": 1}}
        delta = source(tmp_path / "delta.ndjson", [row("new")])
        engine.fail = True

        with pytest.raises(ApiError):
            importer.run(root, delta, mode="delta", base_generation=first["generation"])

        with ctx.store.transaction(write=False) as tx:
            assert tx.require("index", root)["_pit_id"] == old_pointer
        engine.fail = False
        result = importer.run(root, delta, mode="delta", base_generation=first["generation"])

        with ctx.store.transaction(write=False) as tx:
            current = tx.require("index", root)
        assert result["index"] == first["index"]
        assert current["_pit_id"] != old_pointer
        assert engine.docs[first["index"]]["new"][0]["path"].endswith("new.txt")
    finally:
        ctx.close()


def test_long_import_renews_old_pit_while_hashing_and_batching(configured, tmp_path, monkeypatch):
    import wiseway.archive_import as archive_import
    from test_archive_import import Engine, root_id, row, source
    from wiseway.archive_import import ArchiveImporter
    from wiseway.services import Context

    ctx, engine = Context(configured), Engine()
    try:
        importer = ArchiveImporter(ctx, engine, batch_size=1)
        root = root_id(ctx)
        importer.run(root, source(tmp_path / "initial.ndjson", [row("old")]))
        with ctx.store.transaction(write=False) as tx:
            old_pit = tx.require("index", root)["_pit_id"]
        renewals = []
        engine.request = lambda method, path, body: (
            renewals.append(body["pit"]["id"]) or {"_shards": {"total": 1, "successful": 1, "failed": 0}}
        )
        ticks = iter((0, 301, 302, 601, 602, 603, 604, 605, 606))
        monkeypatch.setattr(archive_import, "monotonic", lambda: next(ticks), raising=False)

        importer.run(
            root,
            source(tmp_path / "replacement.ndjson", [row("new-1"), row("new-2"), row("new-3")]),
        )

        assert renewals == [old_pit, old_pit, old_pit]
    finally:
        ctx.close()
