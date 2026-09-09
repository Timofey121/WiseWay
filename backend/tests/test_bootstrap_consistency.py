from __future__ import annotations

import json

import pytest

from wiseway.common import Settings
from wiseway.seed import initialize
from wiseway.services import Context
from wiseway.storage import Store


def _marker(settings, **values):
    settings.sandbox_dir.mkdir(parents=True)
    (settings.sandbox_dir / ".wiseway-sandbox.json").write_text(json.dumps(values), encoding="utf-8")


def _password_hash(settings):
    context = Context(settings)
    try:
        with context.store.transaction(write=False) as tx:
            return tx.require("user", "user-worker-atlas")["password_hash"]
    finally:
        context.close()


def test_context_rejects_completed_marker_without_seeded_database(tmp_path):
    settings = Settings(data_dir=tmp_path / "missing-state", sandbox_dir=tmp_path / "sandbox")
    _marker(settings, product="Wise Way", synthetic=True, bootstrap_complete=True)

    with pytest.raises(RuntimeError, match="Initialize the synthetic sandbox"):
        Context(settings)


def test_initialize_rejects_completed_marker_without_database(tmp_path):
    settings = Settings(data_dir=tmp_path / "missing-state", sandbox_dir=tmp_path / "sandbox")
    _marker(settings, product="Wise Way", synthetic=True, bootstrap_complete=True)

    with pytest.raises(RuntimeError, match="Initialize the synthetic sandbox"):
        initialize(settings, password="must not initialize")

    assert not settings.database.exists()
    assert list(settings.sandbox_dir.iterdir()) == [settings.sandbox_dir / ".wiseway-sandbox.json"]


def test_context_rejects_marker_for_another_product(tmp_path):
    settings = Settings(data_dir=tmp_path / "state", sandbox_dir=tmp_path / "sandbox")
    _marker(settings, product="Other", synthetic=True, bootstrap_complete=True)

    with pytest.raises(RuntimeError, match="Initialize the synthetic sandbox"):
        Context(settings)


def test_context_rejects_partial_marker_with_empty_database(tmp_path):
    settings = Settings(data_dir=tmp_path / "state", sandbox_dir=tmp_path / "sandbox")
    _marker(settings, product="Wise Way", synthetic=True, bootstrap_complete=False)
    Store(settings.database)

    with pytest.raises(RuntimeError, match="Initialize the synthetic sandbox"):
        Context(settings)


def test_initialize_rejects_completed_marker_with_empty_database(tmp_path):
    settings = Settings(data_dir=tmp_path / "state", sandbox_dir=tmp_path / "sandbox")
    _marker(settings, product="Wise Way", synthetic=True, bootstrap_complete=True)
    Store(settings.database)

    with pytest.raises(RuntimeError, match="Initialize the synthetic sandbox"):
        initialize(settings, password="must not reset")

    with Store(settings.database).transaction(write=False) as tx:
        assert tx.get("bootstrap", "seed-v1") is None
        assert tx.list("user") == []
    assert list(settings.sandbox_dir.iterdir()) == [settings.sandbox_dir / ".wiseway-sandbox.json"]


def test_context_requires_complete_bootstrap_record(tmp_path):
    settings = Settings(data_dir=tmp_path / "state", sandbox_dir=tmp_path / "sandbox")
    _marker(settings, product="Wise Way", synthetic=True, bootstrap_complete=False)
    with Store(settings.database).transaction() as tx:
        tx.put("bootstrap", "seed-v1", {"complete": False})

    with pytest.raises(RuntimeError, match="Initialize the synthetic sandbox"):
        Context(settings)


def test_repeat_initialize_leaves_completed_seed_and_password_unchanged(tmp_path):
    settings = Settings(data_dir=tmp_path / "state", sandbox_dir=tmp_path / "sandbox")
    initialize(settings, password="first synthetic password")
    marker = settings.sandbox_dir / ".wiseway-sandbox.json"
    original_marker = marker.read_bytes()
    original_file = (settings.sandbox_dir / "Incoming" / "Atlas" / "invoice-1001.pdf").read_bytes()
    original_hash = _password_hash(settings)

    initialize(settings, password="different synthetic password")

    assert marker.read_bytes() == original_marker
    assert (settings.sandbox_dir / "Incoming" / "Atlas" / "invoice-1001.pdf").read_bytes() == original_file
    assert _password_hash(settings) == original_hash


def test_initialize_resumes_a_seeded_interrupted_bootstrap(tmp_path):
    settings = Settings(data_dir=tmp_path / "state", sandbox_dir=tmp_path / "sandbox")
    initialize(settings, password="first synthetic password")
    marker = settings.sandbox_dir / ".wiseway-sandbox.json"
    marker.write_text(
        json.dumps({"product": "Wise Way", "synthetic": True, "bootstrap_complete": False}), encoding="utf-8"
    )
    original_hash = _password_hash(settings)

    initialize(settings, password="different synthetic password")

    assert json.loads(marker.read_text(encoding="utf-8"))["bootstrap_complete"] is True
    context = Context(settings)
    try:
        with context.store.transaction(write=False) as tx:
            assert tx.require("bootstrap", "seed-v1")["complete"] is True
    finally:
        context.close()
    assert _password_hash(settings) == original_hash
