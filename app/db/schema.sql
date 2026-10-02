-- Circle recommendations schema (SQLite dialect, kept close to standard SQL so it
-- ports to Postgres with type changes only: TEXT timestamps -> timestamptz,
-- INTEGER booleans -> boolean).
--
-- Timestamps are stored as ISO-8601 UTC strings ("2026-09-20T18:00:00.000Z").
-- That format sorts lexicographically, so range filters on created_at use indexes.

PRAGMA foreign_keys = ON;

CREATE TABLE topics (
    id      INTEGER PRIMARY KEY,
    slug    TEXT    NOT NULL UNIQUE,
    label   TEXT    NOT NULL,
    domain  TEXT    NOT NULL
);

CREATE TABLE users (
    id                    INTEGER PRIMARY KEY,
    first_name            TEXT    NOT NULL,
    last_name             TEXT    NOT NULL,
    has_photo             INTEGER NOT NULL CHECK (has_photo IN (0, 1)),
    bio                   TEXT,
    job_title             TEXT,
    company               TEXT,
    industry              TEXT,
    location              TEXT,
    joined_at             TEXT    NOT NULL,
    profile_completeness  REAL    NOT NULL CHECK (profile_completeness BETWEEN 0 AND 1)
);

-- Stated interests are a many-to-many between users and the topic taxonomy.
-- A join table (rather than a JSON column) lets us ask "who cares about X"
-- cheaply, which is the query a topic-launch or digest job would run.
CREATE TABLE user_topic_interests (
    user_id   INTEGER NOT NULL REFERENCES users(id)  ON DELETE CASCADE,
    topic_id  INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, topic_id)
);
CREATE INDEX idx_user_topic_interests_topic ON user_topic_interests (topic_id);

CREATE TABLE circles (
    id                 INTEGER PRIMARY KEY,
    name               TEXT    NOT NULL,
    slug               TEXT    NOT NULL UNIQUE,
    description        TEXT,
    topic_id           INTEGER REFERENCES topics(id),   -- nullable: some Circles have no topic
    cover_image_url    TEXT,
    format             TEXT    NOT NULL CHECK (format IN ('in_person', 'virtual', 'hybrid')),
    access             TEXT    NOT NULL CHECK (access IN ('public', 'unlisted')),
    join_policy        TEXT    NOT NULL CHECK (join_policy IN ('open', 'request')),
    max_members        INTEGER CHECK (max_members IS NULL OR max_members > 0),  -- NULL = uncapped
    -- Denormalised from memberships, as in the product. Reading it avoids a
    -- COUNT(*) per candidate on the hot path; writers keep it in sync.
    member_count       INTEGER NOT NULL DEFAULT 0 CHECK (member_count >= 0),
    created_at         TEXT    NOT NULL,
    -- Activity rollups. In production these come from the feed/chat services
    -- on a schedule; here they arrive pre-aggregated in the seed data.
    last_activity_at   TEXT    NOT NULL,
    feed_posts_30d     INTEGER NOT NULL DEFAULT 0,
    chat_messages_30d  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_circles_topic ON circles (topic_id);
-- Only public Circles are ever recommended, so the candidate scan uses this.
CREATE INDEX idx_circles_public_activity ON circles (last_activity_at) WHERE access = 'public';

-- Tags are free-form, so they are stored as text rather than a topics FK.
-- (In this dataset they happen to reuse topic slugs.)
CREATE TABLE circle_tags (
    circle_id  INTEGER NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
    tag        TEXT    NOT NULL,
    PRIMARY KEY (circle_id, tag)
);
CREATE INDEX idx_circle_tags_tag ON circle_tags (tag);

CREATE TABLE memberships (
    user_id    INTEGER NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
    circle_id  INTEGER NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
    role       TEXT    NOT NULL CHECK (role IN ('member', 'leader')),
    joined_at  TEXT    NOT NULL,
    PRIMARY KEY (user_id, circle_id)   -- also serves "which Circles is this user in"
);
-- "Who leads this Circle" and member listings.
CREATE INDEX idx_memberships_circle_role ON memberships (circle_id, role);

CREATE TABLE posts (
    id              INTEGER PRIMARY KEY,
    circle_id       INTEGER NOT NULL REFERENCES circles(id) ON DELETE CASCADE,
    author_user_id  INTEGER NOT NULL REFERENCES users(id),
    body            TEXT    NOT NULL,
    reaction_count  INTEGER NOT NULL DEFAULT 0,
    comment_count   INTEGER NOT NULL DEFAULT 0,
    save_count      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL
);
-- Engagement rollup reads "posts for circle X since date D".
CREATE INDEX idx_posts_circle_created ON posts (circle_id, created_at);
