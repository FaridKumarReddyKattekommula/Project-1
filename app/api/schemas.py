from datetime import datetime

from pydantic import BaseModel, Field


class LeaderOut(BaseModel):
    user_id: int
    first_name: str
    last_name: str
    job_title: str | None


class CircleRef(BaseModel):
    id: int
    name: str
    slug: str


class CircleOut(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None
    topic: str | None = Field(description="Primary topic slug; null for general-interest Circles")
    topic_label: str | None
    tags: list[str]
    cover_image_url: str | None
    format: str = Field(examples=["virtual"])
    join_policy: str = Field(examples=["open"])
    member_count: int
    max_members: int | None = Field(description="null means the Circle has no size cap")
    spots_left: int | None = Field(description="null when uncapped")
    last_activity_at: datetime
    feed_posts_30d: int
    chat_messages_30d: int
    leaders: list[LeaderOut]


class ReasonOut(BaseModel):
    code: str = Field(examples=["matches_interest"])
    message: str = Field(examples=["Focused on negotiation, one of the topics you picked."])


class ScoreBreakdown(BaseModel):
    relevance: float
    health: float
    access: float
    health_components: dict[str, float]
    matched_topics: list[str]


class RecommendationOut(BaseModel):
    rank: int
    circle: CircleOut
    kind: str = Field(description="'match' (fits her interests) or 'popular' (thriving Circle)")
    explanation: str = Field(description="Short, member-facing reason for the recommendation")
    reasons: list[ReasonOut] = Field(description="Structured reasons, for UI badges")
    similar_circles: list[CircleRef] = Field(
        description="Near-duplicate Circles on the same topic, collapsed into this one"
    )
    score: float = Field(description="Ranking score. Only meaningful relative to other results.")
    score_breakdown: ScoreBreakdown | None = Field(
        default=None, description="Included when debug=true"
    )


class RecommendationsResponse(BaseModel):
    user_id: int
    strategy: str = Field(
        description="'interests', 'memberships' (inferred), or 'cold_start'",
        examples=["interests"],
    )
    as_of: datetime = Field(description="Reference time used for recency and activity windows")
    recommendations: list[RecommendationOut]
    excluded: dict[int, str] | None = Field(
        default=None, description="Circle id -> reason it was filtered out. debug=true only."
    )


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class HealthResponse(BaseModel):
    status: str
    as_of: datetime | None = None
