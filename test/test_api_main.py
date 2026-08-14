"""Integration test — backend/api/main.py (app FastAPI: routing, health, CORS)."""


def test_health_check(api_client):
    resp = api_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "Study Coach API"}


def test_docs_available(api_client):
    resp = api_client.get("/docs")
    assert resp.status_code == 200


def test_openapi_lists_all_routers(api_client):
    resp = api_client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert "/auth/register" in paths
    assert "/exams" in paths
    assert "/sessions" in paths
    assert "/sessions/{session_id}/tutor/start" in paths


def test_cors_headers_present_for_allowed_origin(api_client):
    resp = api_client.get("/health", headers={"Origin": "http://localhost:8501"})
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:8501"


def test_unknown_route_returns_404(api_client):
    resp = api_client.get("/does-not-exist")
    assert resp.status_code == 404
