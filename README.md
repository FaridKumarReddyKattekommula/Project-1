# Circle Recommendations API

Given a Lean In member, return a ranked list of Circles she should join and a
short reason for each one.

Built with Python 3.11, FastAPI and SQLite. The design write-up is in
[docs/DESIGN.md](docs/DESIGN.md) and the schema notes are in
[docs/SCHEMA.md](docs/SCHEMA.md).

## Running it

You need Python 3.11+ (or Docker).

```bash
make install     # creates .venv and installs the app with dev tools
make run         # http://localhost:8000, interactive docs at /docs
```

The Makefile detects your OS (Mac/Linux or Windows) automatically. `make`
can't activate the venv in your terminal, so after `make install` activate it
yourself if you want to run `python`, `pip` or `uvicorn` by hand:

```bash
# Mac / Linux
source .venv/bin/activate

# Windows (Command Prompt)
.venv\Scripts\activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

`make run`, `make test` and the other targets work without activating.

Without `make`:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --port 8000
```

On first start the app builds `var/circles.db` from the JSON files in `data/`.
To rebuild it by hand: `make seed` (or `python -m app.db.seed --force`).

With Docker:

```bash
docker build -t circle-recommendations .
docker run --rm -p 8000:8000 circle-recommendations
```

## Trying it

```bash
curl localhost:8000/v1/users/23/recommendations
curl "localhost:8000/v1/users/15/recommendations?limit=3&debug=true"
curl localhost:8000/v1/circles/22
```

| Endpoint | What it does |
| --- | --- |
| `GET /v1/users/{id}/recommendations` | Ranked Circles with explanations. `limit` (default 5, max 20), `debug=true` adds score breakdowns and the list of filtered-out Circles. |
| `GET /v1/circles/{id}` | One public Circle with activity numbers and leaders. |
| `GET /healthz` | Liveness. |
| `GET /readyz` | Readiness: the database answers a query. |
| `GET /docs` | OpenAPI / Swagger UI. |

A trimmed response:

```json
{
  "user_id": 15,
  "strategy": "interests",
  "as_of": "2026-09-21T00:00:00Z",
  "recommendations": [
    {
      "rank": 1,
      "circle": { "id": 13, "name": "Confident Voices", "format": "in_person",
                  "join_policy": "open", "spots_left": 6, "leaders": [ ... ] },
      "kind": "match",
      "explanation": "Covers confidence and negotiation, both topics you picked. 14 posts in the last month.",
      "reasons": [
        { "code": "matches_interests", "message": "Covers confidence and negotiation, both topics you picked." },
        { "code": "active", "message": "14 posts in the last month." },
        { "code": "format_in_person", "message": "Meets in person." },
        { "code": "open_to_join", "message": "Open to join." }
      ],
      "similar_circles": [ { "id": 37, "name": "The Confidence Lab", "slug": "the-confidence-lab" } ],
      "score": 1.1261
    }
  ]
}
```

`explanation` is the text to show the member. `reasons` holds the same
information in structured form so a client can render badges ("Open to join",
"2 spots left") without parsing sentences. `similar_circles` lists
near-duplicates that were folded into this result.

Errors always look like
`{"error": {"code": "user_not_found", "message": "...", "request_id": "..."}}`,
and every response carries an `X-Request-ID` header that matches the access log.

## The planted scenarios

| Scenario | User | Result |
| --- | --- | --- |
| Cold start | 42 | `strategy: cold_start`. Five of the healthiest open Circles, each on a different topic, e.g. "A negotiation Circle that's one of the most active on Lean In right now." |
| Obvious matches | 7 | #6 Speak Up Circle (matches both her interests) then #5 Women Who Lead. |
| Duplicates | 15 | One Negotiation Circle (#11) with #10 and #12 under `similar_circles`. Her other interest, confidence, gets the top slot. |
| Full / inactive | 23 | #22 Level Up Collective first. #20 is excluded as full and #21 is never shown (inactive since February, and unlisted). |

These are checked in `tests/test_scenarios.py`. `tests/test_all_users.py` also
runs every one of the 100 members through the API and checks that nobody gets an
empty list, a Circle they're already in, a full or stale Circle, or two Circles
on the same topic.

## Development

```bash
make test        # pytest
make lint        # ruff + mypy (strict)
make check       # both
```

CI (`.github/workflows/ci.yml`) runs lint, types and tests, then builds the
Docker image and smoke-tests it.

### Layout

```
app/
  main.py               app factory, startup (seed if needed, resolve as_of)
  config.py             settings, all overridable with CIRCLES_* env vars
  api/routes.py         HTTP layer: validation, response shaping
  api/schemas.py        response models (these drive the OpenAPI docs)
  repository.py         all SQL
  models.py             plain dataclasses passed to the recommender
  recommender/
    scoring.py          eligibility rules, signals, tunable weights
    ranker.py           strategy choice, scoring, de-duplication
    explain.py          member-facing explanation text
  db/schema.sql         tables and indexes
  db/seed.py            JSON -> SQLite loader
data/                   the provided seed snapshot
tests/
```

### Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `CIRCLES_DATABASE_PATH` | `var/circles.db` | |
| `CIRCLES_DATA_DIR` | `data` | Source JSON for seeding. |
| `CIRCLES_AUTO_SEED` | `true` | Build the DB on startup if it's missing. |
| `CIRCLES_AS_OF` | latest activity in the data | Reference "now" for recency. See the design doc for why this isn't the wall clock. |
| `CIRCLES_DEFAULT_LIMIT` / `CIRCLES_MAX_LIMIT` | `5` / `20` | |
| `CIRCLES_LOG_LEVEL` | `INFO` | |
| `CIRCLES_LOG_JSON` | `false` | One JSON object per log line (on in the Docker image). |
| `CIRCLES_CORS_ORIGINS` | `[]` | JSON list, e.g. `'["http://localhost:3000"]'`. |
