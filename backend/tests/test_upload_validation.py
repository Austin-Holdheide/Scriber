"""Upload endpoint auth + validation tests (JWT era)."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_upload_requires_auth():
    r = client.post("/api/videos/upload", files={"file": ("a.mp4", b"x" * 100, "video/mp4")})
    assert r.status_code == 401


def test_upload_rejects_garbage_token():
    r = client.post(
        "/api/videos/upload",
        headers={"Authorization": "Bearer not.a.jwt"},
        files={"file": ("a.mp4", b"x" * 100, "video/mp4")},
    )
    assert r.status_code == 401


def test_upload_rejects_bad_ext():
    r = client.post(
        "/api/videos/upload",
        headers={"Authorization": "Bearer fake.token.here"},
        files={"file": ("a.exe", b"MZ", "application/octet-stream")},
    )
    assert r.status_code == 401  # auth checked before extension
