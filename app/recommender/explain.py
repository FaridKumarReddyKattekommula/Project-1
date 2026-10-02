"""Member-facing explanations.

Built from templates rather than generated text so every sentence is backed by a
signal that actually influenced the ranking. We never say "matches your
interests" unless it did, and never call a Circle busy unless the numbers say so.
"""

from dataclasses import dataclass

from app.models import Circle, UserProfile
from app.recommender.ranker import Kind, Recommendation, Strategy

BUSY_CHAT_THRESHOLD = 75
VERY_ACTIVE_HEALTH = 0.75
FEW_SPOTS = 3

FORMAT_TEXT = {
    "virtual": "Meets online",
    "hybrid": "Meets online and in person",
    "in_person": "Meets in person",
}


@dataclass(frozen=True)
class Reason:
    code: str
    message: str


def _label(slug: str, labels: dict[str, str]) -> str:
    return labels.get(slug, slug.replace("-", " ")).lower()


def _and(items: list[str]) -> str:
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]


def _headline(
    rec: Recommendation, user: UserProfile, strategy: Strategy, labels: dict[str, str]
) -> Reason:
    if rec.kind is Kind.POPULAR:
        very_active = rec.health.score >= VERY_ACTIVE_HEALTH
        if strategy is not Strategy.COLD_START:
            text = (
                "A bit outside your topics, but it's one of the most active Circles on Lean In "
                "right now."
                if very_active
                else "A bit outside your topics, but it's active and welcoming new members."
            )
        elif rec.circle.topic:
            label = _label(rec.circle.topic, labels)
            text = (
                f"A {label} Circle that's one of the most active on Lean In right now."
                if very_active
                else f"A {label} Circle that's active and welcoming new members."
            )
        else:
            text = (
                "One of the most active Circles on Lean In right now."
                if very_active
                else "An active Circle that's welcoming new members."
            )
        return Reason("popular", text)

    # Primary-topic match first, then tag matches.
    matches = sorted(rec.matches, key=lambda m: m.via != "topic")
    names = [_label(m.topic, labels) for m in matches]
    via_topic = matches[0].via == "topic"

    if strategy is Strategy.MEMBERSHIPS:
        joined = user.joined_topics.get(matches[0].topic)
        verb = "Focused on" if via_topic else "Talks about"
        if joined:
            return Reason(
                "similar_to_joined",
                f"{verb} {names[0]}, like {joined}, a Circle you're already in.",
            )
        return Reason("similar_to_joined", f"{verb} {names[0]}, like Circles you're already in.")

    if len(names) == 2:
        return Reason("matches_interests", f"Covers {_and(names)}, both topics you picked.")
    if len(names) > 2:
        return Reason("matches_interests", f"Covers {_and(names)}, all topics you picked.")
    if via_topic:
        return Reason("matches_interest", f"Focused on {names[0]}, one of the topics you picked.")
    return Reason("matches_interest_tag", f"Often talks about {names[0]}, a topic you picked.")


def _activity(circle: Circle) -> Reason | None:
    posts = circle.feed_posts_30d
    busy_chat = circle.chat_messages_30d >= BUSY_CHAT_THRESHOLD
    if posts and busy_chat:
        text = f"{posts} posts in the last month, plus a busy group chat."
    elif posts:
        text = f"{posts} post{'s' if posts != 1 else ''} in the last month."
    elif busy_chat:
        text = "A busy group chat this month."
    else:
        return None
    return Reason("active", text)


def _logistics(circle: Circle) -> list[Reason]:
    out = [Reason(f"format_{circle.format}", FORMAT_TEXT[circle.format] + ".")]
    if circle.join_policy == "open":
        out.append(Reason("open_to_join", "Open to join."))
    else:
        out.append(Reason("request_to_join", "Join by request to the Circle leader."))
    spots = circle.spots_left
    if spots is not None and spots <= FEW_SPOTS:
        out.append(Reason("few_spots", f"Only {spots} spot{'s' if spots != 1 else ''} left."))
    return out


def explain(
    rec: Recommendation, user: UserProfile, strategy: Strategy, labels: dict[str, str]
) -> tuple[str, list[Reason]]:
    """Return a one-to-two sentence explanation plus the structured reasons behind it."""
    headline = _headline(rec, user, strategy, labels)
    activity = _activity(rec.circle)
    reasons = [headline]
    if activity:
        reasons.append(activity)
    summary = " ".join(r.message for r in reasons)
    reasons.extend(_logistics(rec.circle))
    return summary, reasons
