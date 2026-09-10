import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BENCHMARKS = Path(__file__).parents[1] / "benchmarks"
if str(BENCHMARKS) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS))

from archive_capacity import CapacityRun, run_query_measurement, run_query_phase  # noqa: E402
from archive_corpus import (  # noqa: E402
    count_residue,
    diverse_marker_id,
    diverse_row,
    diverse_schema,
    expected_broad_ids,
    expected_company_facets,
    expected_family_ids,
)
from test_archive_import import Engine  # noqa: E402
from wiseway.services import Context  # noqa: E402
from wiseway.common import ApiError  # noqa: E402


class CapacityEngine(Engine):
    def request(self, method, path, body=None):
        if method == "GET" and path == "/_nodes/stats/fs":
            return {"nodes": {"capacity-test": {"fs": {"total": {"available_in_bytes": 10**15}}}}}
        return super().request(method, path, body)


def test_engine_bulk_failure_records_incomplete_run_without_claiming_target(configured, tmp_path):
    ctx, engine = Context(configured), CapacityEngine()
    try:
        directory = tmp_path / "capacity"
        run = CapacityRun(directory, ctx, engine, chunk_records=2, min_free_bytes=0)
        engine.fail = True
        with pytest.raises(ApiError):
            run.build(4)
        report = json.loads((directory / "capacity-result.json").read_text())
        assert report["status"] == "INCOMPLETE"
        assert report["completed_records"] == 0
        assert report["pending_chunk"] == {"start": 0, "end": 2}
    finally:
        ctx.close()


def test_diverse_corpus_has_declared_cardinality_and_schema_valid_rows():
    schema = diverse_schema()
    levels = schema["root_levels"]
    assert len(levels[1][2]) == 64
    assert len(levels[2][2]) == 128
    assert len(levels[3][2]) == 8
    rows = [diverse_row(number) for number in range(32)]
    assert len({row["relative_path"].rsplit("/", 1)[1].split("-", 1)[0] for row in rows}) == 32
    assert rows[0]["relative_path"] == diverse_row(0)["relative_path"]
    assert rows[0]["item_id"] != rows[1]["item_id"]


def test_diverse_oracle_derives_counts_markers_and_natural_top_ids_without_search_code():
    assert count_residue(100, 32, 0) == 4
    assert count_residue(100, 64, 63) == 1
    assert expected_family_ids(200_000, "PATH", "ASC", 3) == [
        "diverse-000000000",
        "diverse-000065536",
        "diverse-000131072",
    ]
    assert expected_family_ids(100, "NAME", "DESC", 3) == [
        "diverse-000000096",
        "diverse-000000064",
        "diverse-000000032",
    ]
    assert diverse_marker_id("level-company", "Company00", ("Archive",)).startswith("marker-")


def test_diverse_broad_and_facet_oracles_include_only_existing_records():
    assert expected_broad_ids(3) == ["diverse-000000000", "diverse-000000001", "diverse-000000002"]
    assert expected_company_facets(3) == {"Company00": 1, "Company01": 1, "Company02": 1}
    assert expected_family_ids(33, "RELEVANCE", "DESC") == ["diverse-000000000", "diverse-000000032"]


def test_query_exception_persists_failed_report_and_exits_nonzero(tmp_path):
    with pytest.raises(SystemExit) as stopped:
        run_query_phase(tmp_path, {"completed_records": 3}, lambda: (_ for _ in ()).throw(ConnectionError()))
    assert stopped.value.code == 1
    saved = json.loads((tmp_path / "capacity-result.json").read_text())
    assert saved["status"] == "FAILED"
    assert saved["completed_records"] == 3
    assert saved["error"] == "ConnectionError"


def test_query_measurement_uses_rotated_generation_refuses_pending_and_holds_writer_lock(tmp_path):
    class Run:
        def __init__(self, progress):
            self.progress = progress

        def maintain_before_query(self):
            return self.progress

    original = {"completed_records": 10, "generation": "old", "index": "same", "pending_chunk": None}
    rotated = {**original, "generation": "new"}
    action_called = []

    def action(progress):
        action_called.append(progress)
        with pytest.raises(RuntimeError, match="Another capacity benchmark"):
            with __import__("archive_capacity")._capacity_lock(tmp_path):
                pass
        return {"passed": True}

    result = run_query_measurement(tmp_path, Run(rotated), original, action)
    assert result["generation"] == "new"
    assert action_called == [rotated]
    assert json.loads((tmp_path / "capacity-result.json").read_text())["generation"] == "new"

    pending = Run({**rotated, "pending_chunk": {"start": 10, "end": 12}})
    with pytest.raises(RuntimeError, match="pending"):
        run_query_measurement(tmp_path, pending, result, lambda _: pytest.fail("workload must not run"))
    assert json.loads((tmp_path / "capacity-result.json").read_text())["generation"] == "new"


def test_diverse_capacity_installs_private_schema_before_its_first_import(configured, tmp_path):
    ctx, engine = Context(configured), CapacityEngine()
    try:
        result = CapacityRun(
            tmp_path / "capacity", ctx, engine, chunk_records=2, corpus="diverse", min_free_bytes=0
        ).build(2)
        with ctx.store.transaction(write=False) as tx:
            root = tx.require("root", "archive-root")
        assert root["schema_set_version"] == "capacity-diverse-v1"
        assert root["_schema"] == diverse_schema()
        assert len(engine.docs[result["index"]]) == 2
    finally:
        ctx.close()


def test_capacity_run_builds_in_small_immutable_chunks_and_removes_acknowledged_source(configured, tmp_path):
    ctx, engine = Context(configured), CapacityEngine()
    try:
        run = CapacityRun(tmp_path / "capacity", ctx, engine, chunk_records=2, min_free_bytes=0)
        result = run.build(5)
        assert result["completed_records"] == 5
        assert result["chunks_completed"] == 3
        assert len(engine.docs[result["index"]]) == 5
        assert not list((tmp_path / "capacity" / "chunks").glob("*.ndjson"))
        progress = json.loads((tmp_path / "capacity" / "progress.json").read_text())
        assert progress["completed_records"] == 5
        assert progress["generation"] == result["generation"]
    finally:
        ctx.close()


def test_capacity_run_resumes_the_same_pending_delta_after_publish_before_checkpoint(
    configured, tmp_path, monkeypatch
):
    ctx, engine = Context(configured), CapacityEngine()
    try:
        run = CapacityRun(tmp_path / "capacity", ctx, engine, chunk_records=2, min_free_bytes=0)
        original = run._checkpoint
        calls = 0

        def crash_after_second_publish(progress, result, end):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("interrupted after publication")
            return original(progress, result, end)

        monkeypatch.setattr(run, "_checkpoint", crash_after_second_publish)
        with pytest.raises(RuntimeError, match="after publication"):
            run.build(4)
        assert engine.publications == 2
        assert json.loads((tmp_path / "capacity" / "progress.json").read_text())["pending_chunk"] == {
            "start": 2,
            "end": 4,
        }
        assert len(list((tmp_path / "capacity" / "chunks").glob("*.ndjson"))) == 1

        monkeypatch.setattr(run, "_checkpoint", original)
        result = run.build(4)
        assert result["completed_records"] == 4
        # Replaying the source consults the importer journal and never republishes it.
        assert engine.publications == 2
        assert len(engine.docs[result["index"]]) == 4
    finally:
        ctx.close()


def test_capacity_run_refuses_config_mismatch_and_preserves_progress(configured, tmp_path):
    ctx, engine = Context(configured), CapacityEngine()
    try:
        directory = tmp_path / "capacity"
        CapacityRun(directory, ctx, engine, chunk_records=2, min_free_bytes=0).build(2)
        with pytest.raises(ValueError, match="configuration"):
            CapacityRun(directory, ctx, engine, chunk_records=3)
        assert json.loads((directory / "progress.json").read_text())["completed_records"] == 2
    finally:
        ctx.close()


def test_capacity_run_refuses_a_changed_pending_immutable_manifest(configured, tmp_path):
    ctx, engine = Context(configured), CapacityEngine()
    try:
        run = CapacityRun(tmp_path / "capacity", ctx, engine, chunk_records=2, min_free_bytes=0)
        engine.fail = True
        with pytest.raises(Exception):
            run.build(2)
        pending = next((tmp_path / "capacity" / "chunks").glob("*.ndjson"))
        pending.write_bytes(pending.read_bytes() + b"{}\n")
        engine.fail = False
        with pytest.raises(ValueError, match="unfinished"):
            run.build(2)
    finally:
        ctx.close()


def test_capacity_run_stops_before_new_chunk_when_free_space_floor_is_breached(configured, tmp_path):
    ctx, engine = Context(configured), CapacityEngine()
    try:
        run = CapacityRun(
            tmp_path / "capacity", ctx, engine, chunk_records=2, min_free_bytes=100, free_bytes=lambda _: 99
        )
        with pytest.raises(RuntimeError, match="free space"):
            run.build(2)
        assert not list((tmp_path / "capacity" / "chunks").glob("*.ndjson"))
    finally:
        ctx.close()


def test_capacity_manifest_is_atomic_when_row_generation_is_interrupted(configured, tmp_path):
    ctx, engine = Context(configured), CapacityEngine()
    try:
        run = CapacityRun(tmp_path / "capacity", ctx, engine, chunk_records=2, min_free_bytes=0)

        def interrupted(number):
            if number == 1:
                raise KeyboardInterrupt
            return {
                "op": "upsert",
                "item_id": "file-0",
                "relative_path": "Archive/Atlas/Orion_2031/Reports/a.txt",
                "size_bytes": 1,
                "modified_at": "2026-01-01T00:00:00Z",
            }

        run.corpus = SimpleNamespace(row=interrupted, name="baseline", schema=None)
        with pytest.raises(KeyboardInterrupt):
            run._manifest(0, 2)
        assert not list((tmp_path / "capacity" / "chunks").iterdir())
    finally:
        ctx.close()


def test_capacity_resume_pins_pending_chunk_end_when_target_is_extended(configured, tmp_path):
    ctx, engine = Context(configured), CapacityEngine()
    try:
        run = CapacityRun(tmp_path / "capacity", ctx, engine, chunk_records=2, min_free_bytes=0)
        run.build(2)
        engine.fail = True
        with pytest.raises(Exception):
            run.build(3)
        engine.fail = False
        result = run.build(5)
        assert result["completed_records"] == 5
        assert engine.publications == 3
    finally:
        ctx.close()


def test_capacity_fails_closed_on_malformed_engine_filesystem_stats(configured, tmp_path):
    ctx = Context(configured)

    class BadStatsEngine(CapacityEngine):
        def request(self, *_):
            return {"nodes": {}}

    try:
        run = CapacityRun(tmp_path / "capacity", ctx, BadStatsEngine(), chunk_records=2, min_free_bytes=0)
        with pytest.raises(RuntimeError, match="filesystem"):
            run.build(2)
    finally:
        ctx.close()


def test_capacity_refuses_a_symlinked_benchmark_directory(configured, tmp_path):
    ctx, engine = Context(configured), CapacityEngine()
    try:
        target = tmp_path / "target"
        target.mkdir()
        (tmp_path / "capacity").symlink_to(target, target_is_directory=True)
        with pytest.raises(ValueError, match="symlink"):
            CapacityRun(tmp_path / "capacity", ctx, engine)
    finally:
        ctx.close()
