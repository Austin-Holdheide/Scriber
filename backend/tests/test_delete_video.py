"""Delete endpoint auth tests (DB touched only after auth)."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_delete_requires_auth():
    r = client.delete("/api/videos/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 401


def test_delete_rejects_garbage_token():
    r = client.delete(
        "/api/videos/00000000-0000-0000-0000-000000000000",
        headers={"Authorization": "Bearer bad.token.here"},
    )
    assert r.status_code == 401
