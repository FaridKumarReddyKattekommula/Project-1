import sqlite3
from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request

from app import repository as repo
from app.api.schemas import (
    CircleOut,
    CircleRef,
    ErrorResponse,
    HealthResponse,
    LeaderOut,
    ReasonOut,
    RecommendationOut,
    RecommendationsResponse,
    ScoreBreakdown,
)
from app.config import Settings, get_settings
from app.db import connect
from app.errors import NotFoundError
from app.models import Circle, Leader
from app.recommender.explain import explain
from app.recommender.ranker import recommend

router = APIRouter()


def get_conn(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[sqlite3.Connection]:
    conn = connect(settings.database_path)
    try:
        yield conn
    finally:
        conn.close()


def get_as_of(request: Request) -> datetime:
    as_of: datetime = request.app.state.as_of
    return as_of


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
AsOf = Annotated[datetime, Depends(get_as_of)]

NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}}


def leader_out(leader: Leader) -> LeaderOut:
    return LeaderOut(
        user_id=leader.user_id,
        first_name=leader.first_name,
        last_name=leader.last_name,
        job_title=leader.job_title,
    )


def circle_out(circle: Circle, leaders: tuple[Leader, ...] | None = None) -> CircleOut:
    return CircleOut(
        id=circle.id,
        name=circle.name,
        slug=circle.slug,
        description=circle.description,
        topic=circle.topic,
        topic_label=circle.topic_label,
        tags=list(circle.tags),
        cover_image_url=circle.cover_image_url,
        format=circle.format,
        join_policy=circle.join_policy,
        member_count=circle.member_count,
        max_members=circle.max_members,
        spots_left=circle.spots_left,
        last_activity_at=circle.last_activity_at,
        feed_posts_30d=circle.feed_posts_30d,
        chat_messages_30d=circle.chat_messages_30d,
        leaders=[leader_out(x) for x in (circle.leaders if leaders is None else leaders)],
    )


@router.get(
    "/v1/users/{user_id}/recommendations",
    response_model=RecommendationsResponse,
    responses=NOT_FOUND,
    summary="Ranked Circles a member should join, each with a reason",
    tags=["recommendations"],
)
def get_recommendations(
    conn: Conn,
    as_of: AsOf,
    settings: Annotated[Settings, Depends(get_settings)],
    user_id: Annotated[int, Path(ge=1)],
    limit: Annotated[int | None, Query(ge=1, description="Defaults to 5, capped at 20")] = None,
    debug: Annotated[bool, Query(description="Include score breakdowns and exclusions")] = False,
) -> RecommendationsResponse:
    user = repo.get_user(conn, user_id)
    if user is None:
        raise NotFoundError("user_not_found", f"User {user_id} does not exist")

    n = min(limit or settings.default_limit, settings.max_limit)
    candidates = repo.candidate_circles(conn, user, as_of)
    result = recommend(user, candidates, as_of, n)

    labels = repo.topic_labels(conn)
    leaders = repo.leaders_for(conn, [r.circle.id for r in result.items])

    items = []
    for rank, rec in enumerate(result.items, start=1):
        summary, reasons = explain(rec, user, result.strategy, labels)
        items.append(
            RecommendationOut(
                rank=rank,
                circle=circle_out(rec.circle, leaders.get(rec.circle.id, ())),
                kind=rec.kind.value,
                explanation=summary,
                reasons=[ReasonOut(code=r.code, message=r.message) for r in reasons],
                similar_circles=[CircleRef(id=c.id, name=c.name, slug=c.slug) for c in rec.similar],
                score=round(rec.score, 4),
                score_breakdown=ScoreBreakdown(
                    relevance=round(rec.relevance, 4),
                    health=round(rec.health.score, 4),
                    access=round(rec.access, 4),
                    health_components={
                        "posts": round(rec.health.posts, 4),
                        "chat": round(rec.health.chat, 4),
                        "recency": round(rec.health.recency, 4),
                        "engagement": round(rec.health.engagement, 4),
                    },
                    matched_topics=[m.topic for m in rec.matches],
                )
                if debug
                else None,
            )
        )

    return RecommendationsResponse(
        user_id=user.id,
        strategy=result.strategy.value,
        as_of=as_of,
        recommendations=items,
        excluded=result.excluded if debug else None,
    )


@router.get(
    "/v1/circles/{circle_id}",
    response_model=CircleOut,
    responses=NOT_FOUND,
    summary="A single Circle with its activity and leaders",
    tags=["circles"],
)
def get_circle(conn: Conn, as_of: AsOf, circle_id: Annotated[int, Path(ge=1)]) -> CircleOut:
    circle = repo.get_circle(conn, circle_id, as_of)
    if circle is None or circle.access != "public":
        raise NotFoundError("circle_not_found", f"Circle {circle_id} does not exist")
    return circle_out(circle)


@router.get("/healthz", response_model=HealthResponse, tags=["ops"], summary="Liveness probe")
def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/readyz",
    response_model=HealthResponse,
    responses={503: {"model": ErrorResponse}},
    tags=["ops"],
    summary="Readiness probe: the database is reachable",
)
def readyz(conn: Conn, as_of: AsOf) -> HealthResponse:
    conn.execute("SELECT 1 FROM circles LIMIT 1").fetchone()
    return HealthResponse(status="ready", as_of=as_of)
