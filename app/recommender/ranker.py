"""Turns a member and a set of candidate Circles into a ranked, de-duplicated list.

Steps:
  1. Work out what the member cares about (stated interests, else the topics of
     Circles she's already in, else nothing: cold start).
  2. Drop Circles she can't usefully join (full, inactive, not public).
  3. Score the rest on relevance, health and how easy they are to join.
  4. Walk the list best-first, keeping at most `max_per_topic` per topic, so
     three near-identical Negotiation Circles become one pick plus two alternatives.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.models import Circle, UserProfile
from app.recommender.scoring import (
    DEFAULT_CONFIG,
    Health,
    Match,
    RankingConfig,
    access,
    health,
    ineligibility_reason,
    relevance,
)


class Strategy(StrEnum):
    INTERESTS = "interests"  # ranked against topics she picked
    MEMBERSHIPS = "memberships"  # no stated interests; inferred from Circles she's in
    COLD_START = "cold_start"  # nothing to go on; healthiest low-friction Circles


class Kind(StrEnum):
    MATCH = "match"  # lines up with her interests
    POPULAR = "popular"  # no topical match, included because it's thriving


@dataclass
class Recommendation:
    circle: Circle
    kind: Kind
    score: float
    relevance: float
    health: Health
    access: float
    matches: list[Match]
    similar: list[Circle] = field(default_factory=list)


@dataclass
class RecommendationResult:
    strategy: Strategy
    interests: dict[str, float]
    items: list[Recommendation]
    excluded: dict[int, str]  # circle id -> reason, for debugging


def interest_profile(user: UserProfile, cfg: RankingConfig) -> tuple[dict[str, float], Strategy]:
    if user.interests:
        return {slug: 1.0 for slug in user.interests}, Strategy.INTERESTS
    if user.joined_topics:
        w = cfg.inferred_interest_weight
        return {slug: w for slug in user.joined_topics}, Strategy.MEMBERSHIPS
    return {}, Strategy.COLD_START


def score_candidates(
    user: UserProfile,
    candidates: list[Circle],
    as_of: datetime,
    cfg: RankingConfig = DEFAULT_CONFIG,
) -> RecommendationResult:
    interests, strategy = interest_profile(user, cfg)
    scored: list[Recommendation] = []
    excluded: dict[int, str] = {}

    for circle in candidates:
        if circle.id in user.joined_circle_ids:
            excluded[circle.id] = "already_member"
            continue
        reason = ineligibility_reason(circle, as_of, cfg)
        if reason:
            excluded[circle.id] = reason
            continue

        h = health(circle, as_of, cfg)
        a = access(circle, cfg)
        rel, matches = relevance(circle, interests, cfg)

        if strategy is Strategy.COLD_START:
            score = cfg.cold_start_health_weight * h.score + cfg.cold_start_access_weight * a
        else:
            score = cfg.w_relevance * rel + cfg.w_health * h.score + cfg.w_access * a

        if matches:
            kind = Kind.MATCH
        elif strategy is Strategy.COLD_START or h.score >= cfg.min_health_for_filler:
            kind = Kind.POPULAR
        else:
            excluded[circle.id] = "not_relevant"
            continue

        scored.append(Recommendation(circle, kind, score, rel, h, a, matches))

    # Ties broken by id so results are stable across requests.
    scored.sort(key=lambda r: (-r.score, r.circle.id))
    return RecommendationResult(strategy, interests, scored, excluded)


def diversify(items: list[Recommendation], limit: int, max_per_topic: int) -> list[Recommendation]:
    """Pick up to `limit` items best-first with at most `max_per_topic` per topic.

    A Circle skipped for its topic is attached to the first pick on that topic
    as a similar alternative, so the member can still find it in one tap.
    Circles without a topic are never treated as duplicates of each other.
    """
    picked: list[Recommendation] = []
    first_for_topic: dict[str, Recommendation] = {}
    per_topic: dict[str, int] = {}

    for item in items:
        topic = item.circle.topic
        if topic is not None and per_topic.get(topic, 0) >= max_per_topic:
            first_for_topic[topic].similar.append(item.circle)
            continue
        if len(picked) >= limit:
            continue
        picked.append(item)
        if topic is not None:
            per_topic[topic] = per_topic.get(topic, 0) + 1
            first_for_topic.setdefault(topic, item)

    return picked


def recommend(
    user: UserProfile,
    candidates: list[Circle],
    as_of: datetime,
    limit: int,
    cfg: RankingConfig = DEFAULT_CONFIG,
) -> RecommendationResult:
    result = score_candidates(user, candidates, as_of, cfg)
    result.items = diversify(result.items, limit, cfg.max_per_topic)
    return result
