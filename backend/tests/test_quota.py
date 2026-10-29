"""F-7/T-3 quota rules — pure unit tests, no database required.

Every DB touch in app.services.quota goes through plan_name_for/used, so those
get monkeypatched and the rest is arithmetic. Keeping these DB-free means they
run in under a second and pin the *policy* rather than the plumbing.
"""
import pytest
from fastapi import HTTPException

from app.services import quota


@pytest.fixture(autouse=True)
def no_db(monkeypatch):
    """Default: free plan, nothing used this window."""
    monkeypatch.setattr(quota, "plan_name_for", lambda _uid: "free")
    monkeypatch.setattr(quota, "used", lambda *_a, **_k: 0)


def _detail(exc: HTTPException) -> dict:
    assert isinstance(exc.value.detail, dict), "errors must carry a structured detail"
    return exc.value.detail


def test_free_plan_shape_matches_the_plan_doc():
    free = quota.PLANS["free"]
    assert free.max_duration_s == 15 * 60
    assert free.uploads_per_window == 1
    assert free.window_s == 24 * 3600
    assert free.diarizations_per_day == 0
    assert free.share_max_days == 7
    assert free.retention_days == 7


def test_premium_plan_shape_matches_the_plan_doc():
    pro = quota.PLANS["premium"]
    assert pro.max_upload_bytes == 5 * 1024 * quota.MB
    assert pro.uploads_per_window == 50
    assert pro.window_s == 12 * 3600
    assert pro.diarizations_per_day == 10
    assert pro.share_max_days == 30
    assert pro.retention_days == 0


def test_unknown_or_missing_subscription_falls_back_to_free(monkeypatch):
    monkeypatch.setattr(quota, "plan_name_for", lambda _uid: "platinum-deluxe")
    assert quota.plan_for("u1").name == "free"


def test_free_allows_the_first_upload():
    plan = quota.check_transcription("u1")
    assert plan.name == "free"


def test_free_blocks_the_second_upload_with_429(monkeypatch):
    monkeypatch.setattr(quota, "used", lambda *_a, **_k: 1)
    with pytest.raises(HTTPException) as e:
        quota.check_transcription("u1")
    assert e.value.status_code == 429
    d = _detail(e)
    assert d["error"] == "quota_exceeded"
    assert d["kind"] == "transcription"
    assert d["limit"] == 1 and d["used"] == 1
    assert "message" in d


def test_premium_fifty_per_twelve_hours(monkeypatch):
    monkeypatch.setattr(quota, "plan_name_for", lambda _uid: "premium")
    monkeypatch.setattr(quota, "used", lambda uid, kind, window_s, **_k: 49 if window_s == 12 * 3600 else 0)
    assert quota.check_transcription("u1").name == "premium"  # 49 used, one left

    monkeypatch.setattr(quota, "used", lambda *_a, **_k: 50)
    with pytest.raises(HTTPException) as e:
        quota.check_transcription("u1")
    assert e.value.status_code == 429


def test_free_diarization_is_locked_not_unlimited():
    """Regression: 0 used to mean 'unlimited', which let free accounts diarize."""
    assert quota.PLANS["free"].diarizations_per_day == 0
    assert quota.PLANS["admin"].diarizations_per_day == quota.UNLIMITED
    with pytest.raises(HTTPException) as e:
        quota.check_diarization("u1")
    assert e.value.status_code == 402


def test_unlimited_sentinel_does_not_look_like_a_cap():
    admin = quota.PLANS["admin"]
    assert admin.max_upload_bytes == quota.UNLIMITED < 0
    # the streaming guard is `0 < cap < written`, so -1 must never trip it
    written = 10 * 1024 * quota.MB
    assert not (0 < admin.max_upload_bytes < written)


def test_admin_is_unlimited_and_never_queries_usage(monkeypatch):
    monkeypatch.setattr(quota, "plan_name_for", lambda _uid: "admin")

    def boom(*_a, **_k):
        raise AssertionError("admin must not hit the usage table")
    monkeypatch.setattr(quota, "used", boom)

    assert quota.check_transcription("u1").name == "admin"
    assert quota.check_diarization("u1").name == "admin"
    quota.check_size(quota.PLANS["admin"], 40 * 1024 * quota.MB)   # no raise
    quota.check_duration(quota.PLANS["admin"], 4 * 3600)          # no raise


def test_oversized_upload_is_413_with_numbers():
    plan = quota.PLANS["free"]
    with pytest.raises(HTTPException) as e:
        quota.check_size(plan, plan.max_upload_bytes + 1)
    assert e.value.status_code == 413
    d = _detail(e)
    assert d["limit_bytes"] == plan.max_upload_bytes
    assert d["size_bytes"] == plan.max_upload_bytes + 1


def test_upload_exactly_at_the_cap_is_allowed():
    plan = quota.PLANS["free"]
    quota.check_size(plan, plan.max_upload_bytes)  # boundary: allowed


def test_overlong_media_is_422_and_reports_minutes():
    plan = quota.PLANS["free"]
    with pytest.raises(HTTPException) as e:
        quota.check_duration(plan, plan.max_duration_s + 30)
    assert e.value.status_code == 422
    assert "min" in _detail(e)["message"]


def test_unknown_duration_does_not_reject(monkeypatch):
    """ffprobe can fail on odd containers; that must not block a paying upload."""
    quota.check_duration(quota.PLANS["free"], None)


def test_diarization_is_locked_on_free():
    with pytest.raises(HTTPException) as e:
        quota.check_diarization("u1")
    assert e.value.status_code == 402
    assert _detail(e)["error"] == "feature_locked"


def test_diarization_capped_on_premium(monkeypatch):
    monkeypatch.setattr(quota, "plan_name_for", lambda _uid: "premium")
    monkeypatch.setattr(quota, "used", lambda *_a, **_k: 10)
    with pytest.raises(HTTPException) as e:
        quota.check_diarization("u1")
    assert e.value.status_code == 429


@pytest.mark.parametrize("requested,expected", [(None, 7), (30, 7), (1, 1), (0, 1), (-5, 1)])
def test_share_ttl_clamped_to_free(requested, expected):
    assert quota.share_days_for("u1", requested) == expected


def test_share_ttl_premium_allows_thirty(monkeypatch):
    monkeypatch.setattr(quota, "plan_name_for", lambda _uid: "premium")
    assert quota.share_days_for("u1", 30) == 30
    assert quota.share_days_for("u1", 999) == 30


def test_limits_payload_is_ui_ready(monkeypatch):
    monkeypatch.setattr(quota, "used", lambda *_a, **_k: 1)
    p = quota.limits_payload("u1")
    assert p["plan"] == "free"
    assert p["usage"]["transcriptions_left"] == 0
    assert p["limits"]["max_duration_s"] == 15 * 60
