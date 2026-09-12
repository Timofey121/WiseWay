import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("batch_args,expected", [([], 1000), (["--batch-size", "5000"], 5000)])
def test_import_cli_forwards_bounded_batch_size(monkeypatch, batch_args, expected):
    from types import SimpleNamespace

    from wiseway import archive_import, cli, services

    calls = []

    class Importer:
        def __init__(self, ctx, engine, **kwargs):
            calls.append(kwargs)

        def run(self, root, manifest, **kwargs):
            return {"records": 1}

    monkeypatch.setattr(
        services, "Context", lambda _: SimpleNamespace(search_engine=lambda: object(), close=lambda: None)
    )
    monkeypatch.setattr(archive_import, "ArchiveImporter", Importer)
    cli.main(["import-archive", "archive-root", "/manifest.ndjson", *batch_args])
    assert calls == [{"shards": 8, "batch_size": expected}]


@pytest.mark.parametrize("size", ["0", "5001"])
def test_import_cli_rejects_invalid_batch_before_opening_state(monkeypatch, size):
    from wiseway import cli, services

    monkeypatch.setattr(services, "Context", lambda _: pytest.fail("Opened state for invalid input"))
    with pytest.raises(SystemExit) as error:
        cli.main(["import-archive", "archive-root", "/manifest.ndjson", "--batch-size", size])
    assert error.value.code == 2


def test_clean_init_status_tick_and_safe_repeat(tmp_path):
    env = {
        **os.environ,
        "WISEWAY_DATA_DIR": str(tmp_path / "state"),
        "WISEWAY_SANDBOX_DIR": str(tmp_path / "sandbox"),
    }
    result = subprocess.run(
        [sys.executable, "-m", "wiseway", "init-demo", "--password-stdin"],
        env=env,
        input="synthetic-cli-password\n",
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert "synthetic-cli-password" not in result.stdout
    result = subprocess.run(
        [sys.executable, "-m", "wiseway", "status"], env=env, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
    assert "COMPLETE" in result.stdout
    result = subprocess.run(
        [sys.executable, "-m", "wiseway", "tick"], env=env, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
