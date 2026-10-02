import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import ROOT, Settings
from app.db import connect
from app.db.seed import seed
from app.main import create_app


@pytest.fixture(scope="session")
def db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("db") / "circles.db"
    seed(path, ROOT / "data")
    return path


@pytest.fixture(scope="session")
def settings(db_path: Path) -> Settings:
    return Settings(database_path=db_path, auto_seed=False, log_level="WARNING")


@pytest.fixture(scope="session")
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    c = connect(db_path)
    yield c
    c.close()


@pytest.fixture
def recs(client: TestClient):
    """Fetch recommendations for a user and return the parsed body."""

    def get(user_id: int, **params) -> dict:
        resp = client.get(f"/v1/users/{user_id}/recommendations", params=params)
        assert resp.status_code == 200, resp.text
        return resp.json()

    return get
