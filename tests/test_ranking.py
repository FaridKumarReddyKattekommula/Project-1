"""Unit tests for the ranking rules, using hand-built Circles rather than the seed data."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from app.models import Circle, UserProfile
from app.recommender.explain import explain
from app.recommender.ranker import Kind, Strategy, diversify, recommend, score_candidates
from app.recommender.scoring import (
    DEFAULT_CONFIG,
    access,
    health,
    ineligibility_reason,
    relevance,
)

NOW = datetime(2026, 9, 21, tzinfo=UTC)
LABELS = {"negotiation": "Negotiation", "confidence": "Confidence", "networking": "Networking"}


def make_circle(id: int, topic: str | None = "negotiation", **overrides) -> Circle:
    base = Circle(
        id=id,
        name=f"Circle {id}",
        slug=f"circle-{id}",
        description=None,
        topic=topic,
        topic_label=LABELS.get(topic or ""),
        tags=(),
        cover_image_url=None,
        format="virtual",
        access="public",
        join_policy="open",
        max_members=20,
        member_count=10,
        last_activity_at=NOW - timedelta(days=1),
        feed_posts_30d=12,
        chat_messages_30d=150,
        recent_posts=12,
        recent_engagement=180,
    )
    return replace(base, **overrides)


def make_user(interests=(), joined_topics=None, joined_ids=()) -> UserProfile:
    return UserProfile(
        id=1,
        first_name="Test",
        interests=tuple(interests),
        joined_topics=joined_topics or {},
        joined_circle_ids=frozenset(joined_ids),
    )


class TestEligibility:
    def test_full_circle_is_ineligible(self):
        c = make_circle(1, max_members=10, member_count=10)
        assert ineligibility_reason(c, NOW, DEFAULT_CONFIG) == "full"

    def test_uncapped_circle_is_never_full(self):
        c = make_circle(1, max_members=None, member_count=500)
        assert ineligibility_reason(c, NOW, DEFAULT_CONFIG) is None

    def test_stale_circle_is_inactive(self):
        c = make_circle(1, last_activity_at=NOW - timedelta(days=31))
        assert ineligibility_reason(c, NOW, DEFAULT_CONFIG) == "inactive"

    def test_recent_timestamp_but_no_posts_or_chat_is_inactive(self):
        c = make_circle(1, feed_posts_30d=0, chat_messages_30d=0)
        assert ineligibility_reason(c, NOW, DEFAULT_CONFIG) == "inactive"

    def test_unlisted_is_ineligible(self):
        assert ineligibility_reason(make_circle(1, access="unlisted"), NOW, DEFAULT_CONFIG)


class TestSignals:
    def test_topic_match_outweighs_tag_match(self):
        interests = {"negotiation": 1.0}
        by_topic, _ = relevance(make_circle(1, topic="negotiation"), interests)
        by_tag, _ = relevance(make_circle(2, topic="confidence", tags=("negotiation",)), interests)
        assert by_topic > by_tag > 0

    def test_tag_equal_to_topic_is_not_double_counted(self):
        c = make_circle(1, tags=("negotiation",))
        score, matches = relevance(c, {"negotiation": 1.0})
        assert score == DEFAULT_CONFIG.topic_match
        assert len(matches) == 1

    def test_health_rewards_activity(self):
        busy = health(make_circle(1), NOW)
        quiet = health(
            make_circle(
                2,
                feed_posts_30d=1,
                chat_messages_30d=2,
                recent_posts=1,
                recent_engagement=1,
                last_activity_at=NOW - timedelta(days=20),
            ),
            NOW,
        )
        assert busy.score > quiet.score
        assert 0 <= quiet.score <= busy.score <= 1

    def test_access_penalises_friction(self):
        easy = access(make_circle(1))
        hard = access(
            make_circle(
                2, join_policy="request", format="in_person", max_members=11, member_count=10
            )
        )
        assert easy == 1.0
        assert hard < easy


class TestRanking:
    def test_a_topic_match_beats_a_more_active_unrelated_circle(self):
        user = make_user(["negotiation"])
        match = make_circle(
            1,
            feed_posts_30d=3,
            chat_messages_30d=10,
            recent_posts=3,
            recent_engagement=10,
            last_activity_at=NOW - timedelta(days=10),
        )
        busy_other = make_circle(2, topic="networking")
        result = recommend(user, [busy_other, match], NOW, limit=5)
        assert [r.circle.id for r in result.items] == [1, 2]
        assert result.items[0].kind is Kind.MATCH
        assert result.items[1].kind is Kind.POPULAR

    def test_member_circles_are_excluded(self):
        user = make_user(["negotiation"], joined_ids=[1])
        result = score_candidates(user, [make_circle(1), make_circle(2)], NOW)
        assert [r.circle.id for r in result.items] == [2]
        assert result.excluded[1] == "already_member"

    def test_strategy_selection(self):
        assert recommend(make_user(["negotiation"]), [], NOW, 5).strategy is Strategy.INTERESTS
        inferred = make_user(joined_topics={"negotiation": "Circle 9"})
        assert recommend(inferred, [], NOW, 5).strategy is Strategy.MEMBERSHIPS
        assert recommend(make_user(), [], NOW, 5).strategy is Strategy.COLD_START

    def test_diversify_collapses_same_topic_and_keeps_alternatives(self):
        user = make_user(["negotiation", "confidence"])
        circles = [make_circle(i) for i in (1, 2, 3)] + [make_circle(4, topic="confidence")]
        result = recommend(user, circles, NOW, limit=5)

        assert [r.circle.id for r in result.items] == [1, 4]
        assert [c.id for c in result.items[0].similar] == [2, 3]

    def test_circles_without_topic_are_not_treated_as_duplicates(self):
        items = score_candidates(
            make_user(), [make_circle(1, topic=None), make_circle(2, topic=None)], NOW
        ).items
        assert len(diversify(items, limit=5, max_per_topic=1)) == 2

    def test_quiet_unrelated_circles_are_not_used_as_filler(self):
        user = make_user(["negotiation"])
        quiet = make_circle(
            1,
            topic="networking",
            feed_posts_30d=1,
            chat_messages_30d=1,
            recent_posts=1,
            recent_engagement=0,
            last_activity_at=NOW - timedelta(days=25),
        )
        result = score_candidates(user, [quiet], NOW)
        assert result.items == []
        assert result.excluded[1] == "not_relevant"


class TestExplanations:
    def _explain(self, user, circle):
        result = recommend(user, [circle], NOW, limit=1)
        return explain(result.items[0], user, result.strategy, LABELS)

    def test_interest_match_names_the_topic(self):
        summary, reasons = self._explain(make_user(["negotiation"]), make_circle(1))
        assert summary.startswith("Focused on negotiation, one of the topics you picked.")
        assert "12 posts in the last month" in summary
        assert {r.code for r in reasons} >= {"matches_interest", "active", "open_to_join"}

    def test_inferred_match_names_the_circle_they_are_in(self):
        user = make_user(joined_topics={"negotiation": "The Negotiation Table"})
        summary, _ = self._explain(user, make_circle(1))
        assert "like The Negotiation Table, a Circle you're already in" in summary

    def test_few_spots_left_is_called_out(self):
        _, reasons = self._explain(
            make_user(["negotiation"]), make_circle(1, max_members=11, member_count=10)
        )
        assert any(r.message == "Only 1 spot left." for r in reasons)

    def test_cold_start_never_claims_an_interest_match(self):
        summary, _ = self._explain(make_user(), make_circle(1))
        assert "you picked" not in summary
