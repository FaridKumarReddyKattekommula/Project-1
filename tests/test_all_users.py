"""Properties that should hold for every member in the dataset, not just the planted ones."""

from datetime import datetime, timedelta

import pytest

ALL_USERS = range(1, 101)


@pytest.fixture(scope="module")
def memberships(db_path):
    import sqlite3

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT user_id, circle_id FROM memberships").fetchall()
    conn.close()
    out: dict[int, set[int]] = {}
    for user_id, circle_id in rows:
        out.setdefault(user_id, set()).add(circle_id)
    return out


@pytest.mark.parametrize("user_id", ALL_USERS)
def test_every_user_gets_sensible_recommendations(recs, memberships, user_id):
    body = recs(user_id)
    items = body["recommendations"]
    as_of = datetime.fromisoformat(body["as_of"])

    assert items, f"user {user_id} got no recommendations"
    assert [r["rank"] for r in items] == list(range(1, len(items) + 1))
    scores = [r["score"] for r in items]
    assert scores == sorted(scores, reverse=True)

    topics = [r["circle"]["topic"] for r in items if r["circle"]["topic"]]
    assert len(topics) == len(set(topics)), "one Circle per topic"

    for r in items:
        c = r["circle"]
        assert c["id"] not in memberships.get(user_id, set()), "already a member"
        assert c["spots_left"] is None or c["spots_left"] > 0, "full"
        assert as_of - datetime.fromisoformat(c["last_activity_at"]) <= timedelta(days=30)
        assert r["explanation"].strip()
        assert c["id"] not in {sim["id"] for sim in r["similar_circles"]}


def test_strategy_falls_back_to_memberships_without_interests(recs, conn):
    row = conn.execute(
        """SELECT u.id FROM users u
           WHERE NOT EXISTS (SELECT 1 FROM user_topic_interests i WHERE i.user_id = u.id)
             AND EXISTS (SELECT 1 FROM memberships m WHERE m.user_id = u.id)
           ORDER BY u.id LIMIT 1"""
    ).fetchone()
    body = recs(row["id"])

    assert body["strategy"] == "memberships"
    matches = [r for r in body["recommendations"] if r["kind"] == "match"]
    assert matches
    assert "already in" in matches[0]["explanation"]
