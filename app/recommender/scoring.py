"""Signals used to rank Circles.

Each function returns a number in a known range and is deliberately simple, so
a ranking can be explained to a member (and debugged by us) one signal at a time.
All tunables live in RankingConfig.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime

from app.models import Circle


@dataclass(frozen=True)
class RankingConfig:
    # Final score = relevance * w_relevance + health * w_health + access * w_access.
    # A primary-topic match alone contributes 0.6, more than health + access can
    # ever add (0.4), so a healthy Circle on a topic the member picked always
    # outranks a healthy Circle on a topic she didn't.
    w_relevance: float = 0.6
    w_health: float = 0.25
    w_access: float = 0.15

    # Relevance: how much each kind of match is worth, before weighting.
    topic_match: float = 1.0  # the Circle's primary topic is one of her interests
    tag_match: float = 0.3  # a secondary tag matches; tags are noisy, so worth much less
    inferred_interest_weight: float = 0.6  # interests guessed from Circles she's in

    # Eligibility: Circles failing these are never recommended.
    inactive_after_days: float = 30.0
    min_posts_or_chat_30d: int = 1

    # Health normalisation. Values at or above these count as "fully active".
    posts_target: int = 12
    chat_target: int = 150
    engagement_per_post_target: float = 15.0
    recency_half_life_days: float = 14.0

    # Access: friction to actually joining and attending.
    request_to_join_factor: float = 0.8
    # Circles carry no location, so we can't tell whether an in-person Circle is
    # anywhere near the member. Online and hybrid Circles are reachable by anyone.
    in_person_factor: float = 0.75
    few_spots_threshold: int = 2
    few_spots_factor: float = 0.85

    # At most this many Circles per primary topic in one list. Near-identical
    # Circles beyond the cap are attached to the one we show as alternatives.
    max_per_topic: int = 1

    # Below this health a Circle won't be suggested as a general "popular" pick.
    min_health_for_filler: float = 0.45

    cold_start_health_weight: float = 0.7
    cold_start_access_weight: float = 0.3

    health_mix: dict[str, float] = field(
        default_factory=lambda: {"posts": 0.35, "chat": 0.2, "recency": 0.25, "engagement": 0.2}
    )


DEFAULT_CONFIG = RankingConfig()


def days_since(ts: datetime, as_of: datetime) -> float:
    return max((as_of - ts).total_seconds() / 86400, 0.0)


def ineligibility_reason(circle: Circle, as_of: datetime, cfg: RankingConfig) -> str | None:
    """Why a Circle can't be recommended, or None if it can."""
    if circle.access != "public":
        return "not_public"
    if circle.is_full:
        return "full"
    if days_since(circle.last_activity_at, as_of) > cfg.inactive_after_days:
        return "inactive"
    if circle.feed_posts_30d + circle.chat_messages_30d < cfg.min_posts_or_chat_30d:
        return "inactive"
    return None


@dataclass(frozen=True)
class Health:
    score: float
    posts: float
    chat: float
    recency: float
    engagement: float


def health(circle: Circle, as_of: datetime, cfg: RankingConfig = DEFAULT_CONFIG) -> Health:
    posts = min(circle.feed_posts_30d / cfg.posts_target, 1.0)
    # Chat volume varies by orders of magnitude between Circles; log-scale it so
    # one very chatty group doesn't drown out everything else.
    chat = min(math.log1p(circle.chat_messages_30d) / math.log1p(cfg.chat_target), 1.0)
    recency = 0.5 ** (days_since(circle.last_activity_at, as_of) / cfg.recency_half_life_days)
    # Average reactions + comments + saves per recent post: are people responding,
    # or is one person posting into the void?
    per_post = circle.recent_engagement / circle.recent_posts if circle.recent_posts else 0.0
    engagement = min(per_post / cfg.engagement_per_post_target, 1.0)

    mix = cfg.health_mix
    score = (
        mix["posts"] * posts
        + mix["chat"] * chat
        + mix["recency"] * recency
        + mix["engagement"] * engagement
    )
    return Health(score=score, posts=posts, chat=chat, recency=recency, engagement=engagement)


def access(circle: Circle, cfg: RankingConfig = DEFAULT_CONFIG) -> float:
    factor = 1.0
    if circle.join_policy == "request":
        factor *= cfg.request_to_join_factor
    if circle.format == "in_person":
        factor *= cfg.in_person_factor
    spots = circle.spots_left
    if spots is not None and spots <= cfg.few_spots_threshold:
        factor *= cfg.few_spots_factor
    return factor


@dataclass(frozen=True)
class Match:
    topic: str
    via: str  # "topic" or "tag"
    weight: float  # 1.0 for stated interests, lower for inferred ones


def relevance(
    circle: Circle, interests: dict[str, float], cfg: RankingConfig = DEFAULT_CONFIG
) -> tuple[float, list[Match]]:
    """Score how well a Circle lines up with the member's interests.

    interests maps topic slug -> confidence (1.0 stated, lower when inferred).
    """
    matches: list[Match] = []
    score = 0.0
    if circle.topic and circle.topic in interests:
        w = interests[circle.topic]
        score += cfg.topic_match * w
        matches.append(Match(circle.topic, "topic", w))
    for tag in circle.tags:
        if tag != circle.topic and tag in interests:
            w = interests[tag]
            score += cfg.tag_match * w
            matches.append(Match(tag, "tag", w))
    return score, matches
