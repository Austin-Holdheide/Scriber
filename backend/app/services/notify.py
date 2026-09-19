"""W12: ntfy push notifications — job done/failed.

Self-hosted ntfy on CT 203 (http://192.168.1.203:9095, no auth on LAN).
Topic: per-user derived from user_id prefix (stable, unguessable-ish).
Users subscribe their phone to topic: scriber-<first 8 chars of their user id>.
Config via env: NTFY_URL (default http://192.168.1.203:9095), NTFY_ENABLED (default true).
"""
import os
import logging
from urllib import request as _rq

log = logging.getLogger("scriber.notify") if False else None
import logging
log = logging.getLogger("scriber.notify")

NTFY_URL = os.getenv("NTFY_URL", "http://192.168.1.203:9095")
NTFY_ENABLED = os.getenv("NTFY_ENABLED", "1") not in ("0", "false", "no")


def topic_for(user_id: str) -> str:
    """Stable per-user topic: scriber-<8 chars>. Subscribe once in the ntfy app."""
    return f"scriber-{user_id.replace('-', '')[:10].lower()}"


def notify(user_id: str, title: str, message: str, priority: str = "default", tags: str = ""):
    """Fire-and-forget push. Never raises (notifications must not break jobs)."""
    if not NTFY_URL:
        return
    try:
        body = (
            f"topic: {topic_for(user_id)}\n"
            f"title: {title}\n"
            f"priority: {priority}\n"
            + (f"tags: {tags}\n" if tags else "")
            + f"\n{message}"
        ).encode()
        req = _rq.Request(
            f"{NTFY_URL.rstrip('/')}",
            data=body,
            headers={"Content-Type": "text/plain"},
        )
        with _rq.urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                logging.getLogger("scriber.notify").warning("ntfy returned %s", resp.status)
    except Exception as e:
        logging.getLogger("scriber.notify").warning("ntfy notify failed (non-fatal): %s", e)
