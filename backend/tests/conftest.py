import json
import os
import pathlib
import tempfile

import pytest

# A fresh SQLite file per test session, set before the app imports its engine.
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
# Tests never reach a paid API.
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("ELEVENLABS_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def owner():
    return {"X-Owner": "test-owner-0123456789abcdef"}


@pytest.fixture
def other():
    return {"X-Owner": "someone-else-0123456789abcd"}


@pytest.fixture
def example():
    return json.loads((ROOT / "shared" / "example-storyboard.json").read_text())
