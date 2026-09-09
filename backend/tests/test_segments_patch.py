"""Segments PATCH tests (auth + ownership run before DB)."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_patch_requires_auth():
    r = client.patch("/api/segments/1", json={"text": "x"})
    assert r.status_code == 401


def test_patch_rejects_garbage_token():
    r = client.patch("/api/segments/1", json={"text": "x"},
                     headers={"Authorization": "Bearer bad.token.here"})
    assert r.status_code == 401


def test_patch_rejects_blank():
    # blank text is a 401 here because auth runs first; the validator is unit-level
    from app.routers.segments import SegmentUpdate
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        SegmentUpdate(text="   ")
