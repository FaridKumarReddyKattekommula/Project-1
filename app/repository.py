"""SQL access. Everything that knows about tables lives here."""

import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from app.models import Circle, Leader, UserProfile

ACTIVITY_WINDOW = timedelta(days=30)


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_ts(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def latest_activity(conn: sqlite3.Connection) -> datetime | None:
    row = conn.execute(
        """SELECT MAX(ts) FROM (
               SELECT MAX(last_activity_at) AS ts FROM circles
               UNION ALL
               SELECT MAX(created_at) FROM posts
           )"""
    ).fetchone()
    return parse_ts(row[0]) if row and row[0] else None


def topic_labels(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["slug"]: r["label"] for r in conn.execute("SELECT slug, label FROM topics")}


def get_user(conn: sqlite3.Connection, user_id: int) -> UserProfile | None:
    user = conn.execute("SELECT id, first_name FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        return None

    interests = tuple(
        r["slug"]
        for r in conn.execute(
            """SELECT t.slug FROM user_topic_interests uti
               JOIN topics t ON t.id = uti.topic_id
               WHERE uti.user_id = ? ORDER BY t.slug""",
            (user_id,),
        )
    )

    joined_ids: set[int] = set()
    joined_topics: dict[str, str] = {}
    for r in conn.execute(
        """SELECT c.id, c.name, t.slug AS topic FROM memberships m
           JOIN circles c ON c.id = m.circle_id
           LEFT JOIN topics t ON t.id = c.topic_id
           WHERE m.user_id = ? ORDER BY m.joined_at""",
        (user_id,),
    ):
        joined_ids.add(r["id"])
        if r["topic"]:
            joined_topics.setdefault(r["topic"], r["name"])

    return UserProfile(
        id=user["id"],
        first_name=user["first_name"],
        interests=interests,
        joined_topics=joined_topics,
        joined_circle_ids=frozenset(joined_ids),
    )


_CIRCLE_SELECT = """
    SELECT c.*, t.slug AS topic, t.label AS topic_label,
           COALESCE(p.post_count, 0) AS recent_posts,
           COALESCE(p.engagement, 0) AS recent_engagement,
           (SELECT GROUP_CONCAT(tag, ',') FROM circle_tags ct WHERE ct.circle_id = c.id) AS tag_list
    FROM circles c
    LEFT JOIN topics t ON t.id = c.topic_id
    LEFT JOIN (
        SELECT circle_id,
               COUNT(*) AS post_count,
               SUM(reaction_count + comment_count + save_count) AS engagement
        FROM posts
        WHERE created_at >= :since AND created_at <= :as_of
        GROUP BY circle_id
    ) p ON p.circle_id = c.id
"""


def _to_circle(row: sqlite3.Row, leaders: tuple[Leader, ...] = ()) -> Circle:
    return Circle(
        id=row["id"],
        name=row["name"],
        slug=row["slug"],
        description=row["description"],
        topic=row["topic"],
        topic_label=row["topic_label"],
        tags=tuple(sorted(row["tag_list"].split(","))) if row["tag_list"] else (),
        cover_image_url=row["cover_image_url"],
        format=row["format"],
        access=row["access"],
        join_policy=row["join_policy"],
        max_members=row["max_members"],
        member_count=row["member_count"],
        last_activity_at=parse_ts(row["last_activity_at"]),
        feed_posts_30d=row["feed_posts_30d"],
        chat_messages_30d=row["chat_messages_30d"],
        recent_posts=row["recent_posts"],
        recent_engagement=row["recent_engagement"],
        leaders=leaders,
    )


def _window(as_of: datetime) -> dict[str, str]:
    return {"since": format_ts(as_of - ACTIVITY_WINDOW), "as_of": format_ts(as_of)}


def candidate_circles(conn: sqlite3.Connection, user: UserProfile, as_of: datetime) -> list[Circle]:
    """Public Circles the user isn't already in, with activity rollups attached.

    Fullness and inactivity are judged by the recommender, not filtered here,
    so the rules sit next to the scoring they interact with and stay testable.
    """
    rows = conn.execute(
        _CIRCLE_SELECT
        + """
        WHERE c.access = 'public'
          AND NOT EXISTS (
              SELECT 1 FROM memberships m WHERE m.circle_id = c.id AND m.user_id = :user_id
          )
        ORDER BY c.id""",
        {**_window(as_of), "user_id": user.id},
    ).fetchall()
    return [_to_circle(r) for r in rows]


def get_circle(conn: sqlite3.Connection, circle_id: int, as_of: datetime) -> Circle | None:
    row = conn.execute(
        _CIRCLE_SELECT + " WHERE c.id = :circle_id",
        {**_window(as_of), "circle_id": circle_id},
    ).fetchone()
    if row is None:
        return None
    return _to_circle(row, leaders_for(conn, [circle_id]).get(circle_id, ()))


def leaders_for(
    conn: sqlite3.Connection, circle_ids: Iterable[int]
) -> dict[int, tuple[Leader, ...]]:
    ids = list(circle_ids)
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    out: dict[int, list[Leader]] = defaultdict(list)
    for r in conn.execute(
        f"""SELECT m.circle_id, u.id, u.first_name, u.last_name, u.job_title
            FROM memberships m JOIN users u ON u.id = m.user_id
            WHERE m.role = 'leader' AND m.circle_id IN ({placeholders})
            ORDER BY m.circle_id, m.joined_at""",
        ids,
    ):
        out[r["circle_id"]].append(Leader(r["id"], r["first_name"], r["last_name"], r["job_title"]))
    return {cid: tuple(leaders) for cid, leaders in out.items()}
