import json
import shutil

import pytest

from app.config import ROOT
from app.db import connect
from app.db.seed import SeedError, seed


def test_seed_loads_every_row(db_path):
    conn = connect(db_path)
    counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("topics", "users", "circles", "memberships", "posts")
    }
    conn.close()
    assert counts == {"topics": 22, "users": 100, "circles": 40, "memberships": 441, "posts": 386}


def test_seed_does_not_overwrite_without_force(db_path):
    assert seed(db_path, ROOT / "data") is False


def test_bad_data_fails_loudly_and_leaves_nothing_behind(tmp_path):
    data = tmp_path / "data"
    shutil.copytree(ROOT / "data", data)
    users = json.loads((data / "users.json").read_text())
    users[0]["topic_interests"] = ["not-a-real-topic"]
    (data / "users.json").write_text(json.dumps(users))

    target = tmp_path / "out.db"
    with pytest.raises(SeedError, match="not-a-real-topic"):
        seed(target, data)
    assert not target.exists()
    assert not target.with_suffix(".tmp").exists()
