"""Upload endpoint validation tests (no DB - just request validation)."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_upload_requires_user_header():
    r = client.post("/api/videos/upload", files={"file": ("a.mp4", b"x" * 100, "video/mp4")})
    assert r.status_code == 401


def test_upload_rejects_bad_ext():
    r = client.post(
        "/api/videos/upload",
        headers={"X-User-Id": "u1"},
        files={"file": ("a.exe", b"MZ", "application/octet-stream")},
    )
    assert r.status_code == 415
