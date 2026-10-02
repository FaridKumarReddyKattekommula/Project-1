"""Plain domain objects passed between the data layer and the recommender.

The recommender only ever sees these, never a database row, so it can be unit
tested with hand-built objects and doesn't care where the data came from.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Leader:
    user_id: int
    first_name: str
    last_name: str
    job_title: str | None


@dataclass(frozen=True)
class Circle:
    id: int
    name: str
    slug: str
    description: str | None
    topic: str | None
    topic_label: str | None
    tags: tuple[str, ...]
    cover_image_url: str | None
    format: str
    access: str
    join_policy: str
    max_members: int | None
    member_count: int
    last_activity_at: datetime
    feed_posts_30d: int
    chat_messages_30d: int
    # Rolled up from posts in the 30 days before the reference date.
    recent_posts: int = 0
    recent_engagement: int = 0
    leaders: tuple[Leader, ...] = ()

    @property
    def spots_left(self) -> int | None:
        if self.max_members is None:
            return None
        return max(self.max_members - self.member_count, 0)

    @property
    def is_full(self) -> bool:
        return self.spots_left == 0


@dataclass(frozen=True)
class UserProfile:
    id: int
    first_name: str
    interests: tuple[str, ...]
    # topic slug -> name of a Circle the user is already in with that topic
    joined_topics: dict[str, str] = field(default_factory=dict)
    joined_circle_ids: frozenset[int] = frozenset()
