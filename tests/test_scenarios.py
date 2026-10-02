"""The four planted scenarios from the dataset README."""


def ids(body: dict) -> list[int]:
    return [r["circle"]["id"] for r in body["recommendations"]]


def test_cold_start_user_gets_active_open_circles_across_topics(recs):
    body = recs(42)

    assert body["strategy"] == "cold_start"
    assert len(body["recommendations"]) == 5
    topics = [r["circle"]["topic"] for r in body["recommendations"] if r["circle"]["topic"]]
    assert len(topics) == len(set(topics)), "cold start list should not repeat a topic"
    for r in body["recommendations"]:
        assert r["kind"] == "popular"
        assert r["circle"]["feed_posts_30d"] >= 8
        # Nothing about "your interests" for someone who hasn't told us any.
        assert "you picked" not in r["explanation"]


def test_obvious_matches_rank_first(recs):
    body = recs(7)

    assert body["strategy"] == "interests"
    assert set(ids(body)[:2]) == {5, 6}
    by_id = {r["circle"]["id"]: r for r in body["recommendations"]}
    assert "public speaking" in by_id[6]["explanation"]
    assert "leadership skills" in by_id[5]["explanation"]
    assert 4 not in ids(body), "already a member of Circle 4"


def test_duplicate_circles_are_collapsed(recs):
    body = recs(15)
    dupes = {10, 11, 12}

    shown = [cid for cid in ids(body) if cid in dupes]
    assert len(shown) == 1
    pick = next(r for r in body["recommendations"] if r["circle"]["id"] == shown[0])
    assert {c["id"] for c in pick["similar_circles"]} == dupes - set(shown)
    # Her other interest gets a slot instead of a second Negotiation Circle.
    assert 13 in ids(body)[:2]


def test_full_and_inactive_circles_never_rank(recs):
    body = recs(23, limit=20)

    assert ids(body)[0] == 22
    assert 20 not in ids(body), "Circle 20 is at capacity"
    assert 21 not in ids(body), "Circle 21 has been inactive for months"
    excluded = recs(23, debug=True)["excluded"]
    assert excluded["20"] == "full"
