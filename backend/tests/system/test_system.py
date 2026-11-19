from app.main import app
from scripts.check_api_docs import find_problems


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "ok"}


def test_unknown_path_returns_unified_error(client):
    r = client.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    assert r.json()["code"] == "NOT_FOUND"


def test_api_docs_complete():
    assert find_problems(app.openapi()) == []
