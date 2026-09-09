"""Short-lived signed tokens for <audio>/<video> src URLs.

Media elements can't send Authorization headers, so the player first fetches a
signed token (JWT-authenticated JSON endpoint) and appends it as ?mt=...
Stateless HMAC - works across uvicorn workers, no storage.
"""
import hashlib
import hmac
import time

from app.config import settings

TTL_SECONDS = 600  # 10 minutes: enough for any playback session + seeks


def _secret() -> bytes:
    if not settings.media_token_secret:
        raise RuntimeError("MEDIA_TOKEN_SECRET not set")
    return settings.media_token_secret.encode()


def issue(video_id: str, user_id: str) -> str:
    expires = int(time.time()) + TTL_SECONDS
    payload = f"{video_id}:{user_id}:{expires}"
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{expires}:{sig}"


def verify(video_id: str, user_id: str, token: str) -> bool:
    try:
        expires_str, sig = token.split(":", 1)
        expires = int(expires_str)
    except (ValueError, AttributeError):
        return False
    if expires < time.time():
        return False
    payload = f"{video_id}:{user_id}:{expires}"
    expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(sig, expected)
