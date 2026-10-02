# Database schema

The DDL is in [`app/db/schema.sql`](../app/db/schema.sql). It's SQLite so the
project runs with no database server. I kept it to standard SQL so moving to
Postgres only means changing types (`TEXT` timestamps to `timestamptz`,
`INTEGER` flags to `boolean`).

```
topics ─────────────┐
  │                 │
  │ 1..n            │ 0..1
user_topic_interests  circles ── circle_tags
  │                   │   │
users ── memberships ─┘   └── posts
  │                           │
  └───────── author ──────────┘
```

| Table | Key | Notes |
| --- | --- | --- |
| `topics` | `id`, unique `slug` | The 22-topic taxonomy. |
| `users` | `id` | Profile fields plus `profile_completeness`. |
| `user_topic_interests` | (`user_id`, `topic_id`) | Stated interests. |
| `circles` | `id`, unique `slug` | `topic_id` is nullable (two Circles have none). `max_members` NULL means uncapped. Activity rollups are columns. |
| `circle_tags` | (`circle_id`, `tag`) | Free-form tags. |
| `memberships` | (`user_id`, `circle_id`) | `role` is `member` or `leader`. |
| `posts` | `id` | Feed posts with reaction/comment/save counts (`activity.json`). |

## Decisions worth calling out

**Interests and tags are rows, not JSON arrays.** The recommender only needs
"what does this user like", which an array could answer. A join table also
answers the reverse question, "who is interested in negotiation", with an
index. That's the query a new-Circle announcement or a weekly digest would
need, so I paid the small cost up front.

**Tags are text, interests are foreign keys.** The README describes tags as
free-form, so I didn't force them through the taxonomy. Interests are picked
from the taxonomy, so they reference `topics` and the seed rejects unknown slugs.

**`member_count` stays denormalised on `circles`.** It's the same in the
product, and it saves a `COUNT(*)` per candidate on the hot path. The seed data
is consistent (I checked it against `memberships`). In production it would be
updated in the same transaction as the membership write.

**Activity rollups live on `circles`, engagement is computed from `posts`.**
`feed_posts_30d` and `chat_messages_30d` arrive pre-aggregated, as they would
from a feed or chat service. Engagement per post isn't given, so the repository
aggregates it from `posts` for the 30 days before `as_of`. At scale that
aggregate would be precomputed too (see the design doc).

**Constraints are enforced in the database.** `CHECK` constraints on the enums
(`format`, `access`, `join_policy`, `role`), on `max_members > 0` and on
`profile_completeness`, plus foreign keys. The seed runs `PRAGMA
foreign_key_check` and fails if anything doesn't line up.

## Indexes

| Index | Query it serves |
| --- | --- |
| `memberships` PK (`user_id`, `circle_id`) | "Which Circles is this user in?" Used to exclude them, and to infer interests for members who never picked any. |
| `idx_memberships_circle_role` (`circle_id`, `role`) | Leaders for the Circles we return. Also member listings. |
| `idx_posts_circle_created` (`circle_id`, `created_at`) | Engagement over the last 30 days. ISO-8601 strings sort correctly, so the range scan uses the index. |
| `idx_circles_public_activity` partial, `WHERE access = 'public'` | Candidate scan. Unlisted Circles are never recommended, so they aren't in the index. |
| `idx_circles_topic` | Candidates by topic, which matters once there are too many Circles to score all of them. |
| `idx_user_topic_interests_topic` | Reverse lookup: users interested in a topic. |
| `idx_circle_tags_tag` | Circles carrying a tag. |

With 40 Circles every query is instant either way. The indexes are there for
the access patterns, not this dataset.
