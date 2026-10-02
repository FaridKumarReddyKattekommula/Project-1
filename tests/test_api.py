def test_unknown_user_is_404_with_error_envelope(client):
    resp = client.get("/v1/users/9999/recommendations")

    assert resp.status_code == 404
    error = resp.json()["error"]
    assert error["code"] == "user_not_found"
    assert error["request_id"] == resp.headers["x-request-id"]


def test_bad_input_is_422(client):
    assert client.get("/v1/users/abc/recommendations").status_code == 422
    assert client.get("/v1/users/0/recommendations").status_code == 422

    resp = client.get("/v1/users/7/recommendations", params={"limit": 0})
    assert resp.status_code == 422
    assert resp.json()["error"]["details"][0]["field"] == "limit"


def test_limit_is_respected_and_capped(client):
    assert len(client.get("/v1/users/7/recommendations?limit=2").json()["recommendations"]) == 2
    many = client.get("/v1/users/7/recommendations?limit=500").json()["recommendations"]
    assert len(many) <= 20


def test_debug_adds_breakdown_and_is_off_by_default(client):
    plain = client.get("/v1/users/15/recommendations").json()
    assert plain["recommendations"][0]["score_breakdown"] is None
    assert plain["excluded"] is None

    debug = client.get("/v1/users/15/recommendations?debug=true").json()
    breakdown = debug["recommendations"][0]["score_breakdown"]
    assert set(breakdown["health_components"]) == {"posts", "chat", "recency", "engagement"}
    assert debug["excluded"]


def test_recommended_circles_include_leaders(client):
    rec = client.get("/v1/users/23/recommendations").json()["recommendations"][0]
    assert rec["circle"]["leaders"], "every seeded Circle has a leader"


def test_incoming_request_id_is_echoed(client):
    resp = client.get("/healthz", headers={"X-Request-ID": "abc-123"})
    assert resp.headers["x-request-id"] == "abc-123"


def test_circle_detail(client):
    body = client.get("/v1/circles/22").json()
    assert body["name"] == "Level Up Collective"
    assert body["spots_left"] == 6
    assert body["leaders"]


def test_unlisted_circle_is_hidden(client):
    assert client.get("/v1/circles/21").status_code == 404
    assert client.get("/v1/circles/999").status_code == 404


def test_probes(client):
    assert client.get("/healthz").json()["status"] == "ok"
    ready = client.get("/readyz").json()
    assert ready["status"] == "ready"
    assert ready["as_of"].startswith("2026-09-21")


def test_openapi_schema_is_served(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/v1/users/{user_id}/recommendations" in paths
