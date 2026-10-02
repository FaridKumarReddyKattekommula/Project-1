# Circle recommendations: technical design

## What I built

A FastAPI service backed by SQLite. `GET /v1/users/{id}/recommendations`
returns up to 5 Circles, each with one or two sentences written for the member,
structured reasons for the UI, and any near-duplicate Circles folded into it.
Ranking is plain, deterministic code. It happens in four steps:

1. **Work out what she cares about.** Use her stated interests. If she hasn't
   picked any (30 of the 100 members), use the topics of Circles she's already
   in, at lower weight. If there's nothing at all, it's a cold start.
2. **Drop what she can't usefully join.** Circles she's already in, unlisted
   Circles, full Circles (`member_count >= max_members`), and inactive ones (no
   activity in 30 days, or no posts or chat this month).
3. **Score.** `0.6 × relevance + 0.25 × health + 0.15 × access`.
4. **De-duplicate.** Walk the list best-first and keep one Circle per topic.
   Later ones on the same topic become `similar_circles` of the one shown.

## Signals, and why

| Signal | Used for | Why |
| --- | --- | --- |
| Stated interests vs. Circle `topic` | relevance (1.0) | The member told us. This is the strongest signal we have. |
| Interests vs. Circle `tags` | relevance (0.3) | Useful, but noisy: #6 Speak Up Circle is tagged "career-breaks". |
| Topics of joined Circles | relevance (0.6×) | A fair guess for members who skipped the interest picker. |
| Posts, chat volume, recency, engagement per post | health | A Circle is only useful if people show up. Chat is log-scaled. Recency halves every 14 days. Engagement separates real conversation from one person posting into the void. |
| `max_members`, `join_policy`, `format` | access, eligibility | Full means hidden. Request-to-join and in-person add friction. Circles have no location, so I can't tell whether an in-person Circle is near her. Online and hybrid Circles work for anyone. |
| `access` | eligibility | Unlisted Circles aren't meant to be discovered. |

I left out job title, industry, bio, location, photo and profile completeness.
Circles carry none of those fields, so there's nothing to match them against.
Using industry to guess interests ("she's in tech, so...") would be a stereotype,
not a signal. Profile completeness says something about the member, not about
which Circle fits her.

The weights do one thing on purpose: a primary-topic match is worth 0.6, which
is more than health and access combined can add. So a Circle on a topic she
picked always outranks one she didn't, and activity decides the order among
those. That's why #22 beats the busier but off-topic Circles for user 23.
Off-topic Circles only appear to fill the list, and only if they're clearly
healthy.

## Tradeoffs

- **Rules, not a model.** There's no interaction history to learn from, and
  "would a member understand why" is part of the brief. Every weight is in
  `RankingConfig` and every number can be shown with `debug=true`.
- **Templated explanations, not generated text.** Each sentence comes from a
  signal that actually moved the score, so we never claim a match that wasn't
  there or call a quiet Circle busy. The cost is less variety in the wording.
- **Hard cap of one per topic.** Simple, and it handles the duplicates case
  clearly. The downside: a member with only one interest sees just one Circle
  on it. `similar_circles` keeps the others one tap away instead of hiding them.
- **Exclude instead of down-rank.** Full and inactive Circles aren't shown at
  all. Recommending a Circle she can't join, or one that's gone quiet, is worse
  than a shorter list. That matters most for someone new whose first
  impression is that Circles are alive.
- **A fixed "now".** The data is a snapshot from 2026-09-21. Against the wall
  clock every Circle would look staler each day and eventually all would count
  as inactive. `as_of` defaults to the newest activity in the database and can
  be overridden.
- **Score everything per request.** Fine for 40 Circles (about 5ms). It isn't
  the plan for 170,000 (see below).

## Production scale

- **Candidate generation before scoring.** Pull candidates per interest topic
  through `idx_circles_topic`, plus a global "healthy Circles" pool for cold
  start and filler. Then score a few hundred, not every Circle.
- **Precompute Circle health.** Run a scheduled job, or a stream from the feed
  and chat services, to write health and engagement into a `circle_stats`
  table. Requests then read one row per Circle.
- **Cache per user** with a short TTL, invalidated when she joins a Circle or
  changes her interests. The response is identical for everyone with the same
  inputs, so it caches well.
- **Postgres** with a read replica for the API. The schema ports directly.
- **Location.** Add a location to in-person Circles and use distance from the
  member, instead of the flat in-person penalty.
- **Learn from outcomes.** Log impressions, clicks, join requests, joins, and
  whether people are still active after 30 days. Keep this rule-based ranker as
  the baseline and A/B test against it. The metric that matters is not clicks
  but whether she's still an engaged member a month later.
- **Better duplicate detection.** Text embeddings of Circle names and
  descriptions to find near-duplicates across different topics, not just the
  same one.
- **Ops.** Authentication (a member should only see her own recommendations),
  rate limiting, metrics (latency, empty-result rate, cold-start share), and
  tracing. Request IDs and structured logs are already in place.

## With more time

- Let cold-start members pick interests inline: return a `suggested_topics`
  list alongside the Circles.
- Spread recommendations so a small set of popular Circles doesn't fill up from
  recommendations alone. Boost small, healthy Circles that have room.
- Use leader profile and activity as a signal. Who leads a Circle matters a lot
  to whether it works.
- Tune the weights against real join and retention data rather than judgement.
