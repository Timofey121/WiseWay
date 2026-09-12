import pytest


@pytest.fixture
def configured(tmp_path):
    from wiseway.common import Settings
    from wiseway.seed import initialize

    settings = Settings(data_dir=tmp_path / "state", sandbox_dir=tmp_path / "sandbox")
    initialize(settings, password="synthetic-test-password")
    return settings


@pytest.fixture
def client(configured):
    from fastapi.testclient import TestClient
    from wiseway.app import create_app

    with TestClient(create_app(configured), base_url="http://localhost:8000") as client:
        yield client
