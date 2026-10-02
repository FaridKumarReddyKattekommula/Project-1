"""Load the JSON snapshot in data/ into a fresh SQLite database.

    python -m app.db.seed            # uses CIRCLES_DATA_DIR / CIRCLES_DATABASE_PATH
    python -m app.db.seed --force    # rebuild even if the database exists

The database is built in a temporary file and moved into place at the end, so a
failed or interrupted seed never leaves a half-loaded database behind.
"""

import argparse
import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.db import SCHEMA_PATH, connect

log = logging.getLogger(__name__)


class SeedError(Exception):
    pass


def _load(data_dir: Path, name: str) -> list[dict[str, Any]]:
    path = data_dir / f"{name}.json"
    if not path.exists():
        raise SeedError(f"missing data file: {path}")
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise SeedError(f"{path} should contain a JSON array")
    return rows


def _populate(conn: sqlite3.Connection, data_dir: Path) -> dict[str, int]:
    topics = _load(data_dir, "topics")
    users = _load(data_dir, "users")
    circles = _load(data_dir, "circles")
    memberships = _load(data_dir, "memberships")
    posts = _load(data_dir, "activity")

    topic_ids: dict[str, int] = {t["slug"]: t["id"] for t in topics}

    def topic_id(slug: str | None, where: str) -> int | None:
        if slug is None:
            return None
        if slug not in topic_ids:
            raise SeedError(f"unknown topic slug {slug!r} in {where}")
        return topic_ids[slug]

    conn.executemany(
        "INSERT INTO topics (id, slug, label, domain) VALUES (:id, :slug, :label, :domain)",
        topics,
    )

    conn.executemany(
        """INSERT INTO users (id, first_name, last_name, has_photo, bio, job_title, company,
                              industry, location, joined_at, profile_completeness)
           VALUES (:id, :first_name, :last_name, :has_photo, :bio, :job_title, :company,
                   :industry, :location, :joined_at, :profile_completeness)""",
        [{**u, "has_photo": int(u["has_photo"])} for u in users],
    )
    conn.executemany(
        "INSERT INTO user_topic_interests (user_id, topic_id) VALUES (?, ?)",
        [
            (u["id"], topic_id(slug, f"user {u['id']}"))
            for u in users
            for slug in dict.fromkeys(u["topic_interests"])
        ],
    )

    conn.executemany(
        """INSERT INTO circles (id, name, slug, description, topic_id, cover_image_url, format,
                                access, join_policy, max_members, member_count, created_at,
                                last_activity_at, feed_posts_30d, chat_messages_30d)
           VALUES (:id, :name, :slug, :description, :topic_id, :cover_image_url, :format,
                   :access, :join_policy, :max_members, :member_count, :created_at,
                   :last_activity_at, :feed_posts_30d, :chat_messages_30d)""",
        [{**c, "topic_id": topic_id(c["topic"], f"circle {c['id']}")} for c in circles],
    )
    # Some Circles list the same tag twice; the primary key collapses them.
    conn.executemany(
        "INSERT OR IGNORE INTO circle_tags (circle_id, tag) VALUES (?, ?)",
        [(c["id"], tag) for c in circles for tag in c["tags"]],
    )

    conn.executemany(
        """INSERT INTO memberships (user_id, circle_id, role, joined_at)
           VALUES (:user_id, :circle_id, :role, :joined_at)""",
        memberships,
    )
    conn.executemany(
        """INSERT INTO posts (id, circle_id, author_user_id, body, reaction_count,
                              comment_count, save_count, created_at)
           VALUES (:id, :circle_id, :author_user_id, :body, :reaction_count,
                   :comment_count, :save_count, :created_at)""",
        posts,
    )

    return {
        "topics": len(topics),
        "users": len(users),
        "circles": len(circles),
        "memberships": len(memberships),
        "posts": len(posts),
    }


def seed(database_path: Path, data_dir: Path, *, force: bool = False) -> bool:
    """Build the database. Returns False if it already existed and force is off."""
    if database_path.exists() and not force:
        return False

    database_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = database_path.with_suffix(".tmp")
    tmp_path.unlink(missing_ok=True)

    conn = connect(tmp_path, read_only=False)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        with conn:
            counts = _populate(conn, data_dir)
        problems = conn.execute("PRAGMA foreign_key_check").fetchall()
        if problems:
            raise SeedError(f"foreign key violations after load: {[tuple(p) for p in problems]}")
        conn.execute("ANALYZE")
    except BaseException:
        conn.close()
        tmp_path.unlink(missing_ok=True)
        raise
    conn.close()

    os.replace(tmp_path, database_path)
    log.info("seeded %s: %s", database_path, counts)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="rebuild an existing database")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()
    if not seed(settings.database_path, settings.data_dir, force=args.force):
        print(f"{settings.database_path} already exists; use --force to rebuild")


if __name__ == "__main__":
    main()
