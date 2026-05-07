import pytest
import uuid
from pathlib import Path
from fastapi.testclient import TestClient
from webui.server import create_app


@pytest.fixture
def tmp_path():
    base = Path(__file__).resolve().parents[2] / "output" / "pytest-tmp"
    base.mkdir(parents=True, exist_ok=True)
    path = base / uuid.uuid4().hex
    path.mkdir()
    return path


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBUI_DATA_DIR", str(tmp_path))
    app = create_app()
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_runner():
    yield
    import webui.backend.runner as r
    r._proc = None
    r._started_at = None
    r._ended_at = None
    r._exit_code = None
    r._cmd = None
    r._mode = None
    r._log_lines = []
    r._seq_counter = 0
