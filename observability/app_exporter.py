#!/usr/bin/env python3
"""Scriber app-metrics exporter - exposes business stats in Prometheus format on :9401.

Scrapes the Supabase REST API (service role) + Redis on every /metrics request.
Runs on 202 (has both the .env creds and network access to everything).
"""
import http.server
import os
import time
import urllib.request

BASE = os.getenv("SUPABASE_URL", "http://192.168.1.201:8000")
KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
REDIS_HOST = os.getenv("REDIS_HOST", "192.168.1.203")

CACHE = {"ts": 0.0, "body": ""}
CACHE_TTL = 15  # seconds: don't hammer supabase per scrape


def _rest(path: str) -> list:
    req = urllib.request.Request(
        f"{BASE}/rest/v1/{path}",
        headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        import json
        return json.loads(r.read().decode())


def _redis_int(cmd: str) -> int:
    import socket
    s = socket.create_connection((REDIS_HOST, 6379), timeout=5)
    s.sendall(f"{cmd}\r\n".encode())
    data = s.recv(256).decode(errors="replace").strip()
    s.close()
    # RESP integer reply looks like ":3" -> strip type prefix
    for line in reversed(data.split("\r\n")):
        if line.startswith(":"):
            return int(line[1:])
    return 0


def _count_from_range(r) -> int:
    """Parse PostgREST Content-Range '0-0/5' (or odd variants) -> total count int."""
    import re
    cr = r.headers.get("Content-Range", "")
    m = re.search(r"/(\d+)", cr)
    return int(m.group(1)) if m else 0


def collect() -> dict:
    stats = {}
    # videos by status (paged-safe: use count=exact via Prefer header)
    for status in ("done", "queued", "transcribing", "failed", "uploaded"):
        req = urllib.request.Request(
            f"{BASE}/rest/v1/videos?select=id&status=eq.{status}",
            headers={"apikey": KEY, "Authorization": f"Bearer {KEY}",
                     "Prefer": "count=exact", "Range": "0-0"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            stats[f"scriber_videos_status{{status=\"{status}\"}}"] = _count_from_range(r)

    # segments total via count=exact (paged len breaks at 1000)
    req = urllib.request.Request(
        f"{BASE}/rest/v1/segments?select=id",
        headers={"apikey": KEY, "Authorization": f"Bearer {KEY}",
                 "Prefer": "count=exact", "Range": "0-0"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        stats["scriber_segments_total"] = _count_from_range(r)


    # redis queue depth (gpu queue; fallback queue too)
    stats["scriber_queue_depth{queue=\"transcribe-gpu\"}"] = _redis_int("LLEN transcribe-gpu")
    stats["scriber_queue_depth{queue=\"transcribe\"}"] = _redis_int("LLEN transcribe")

    # storage bytes
    stats["scriber_media_bytes"] = 0  # filled by du below if possible
    return stats


def metrics() -> str:
    now = time.time()
    if now - CACHE["ts"] > CACHE_TTL:
        try:
            CACHE["body"] = collect()
            CACHE["ts"] = now
        except Exception as e:
            body = f"# collection error: {e}\n"
            return body
    lines = []
    for k, v in CACHE["body"].items():
        lines.append(f"# TYPE {k.split('{')[0]} gauge")
        lines.append(f"{k} {v}")
    return "\n".join(lines) + "\n"


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            body = metrics().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()
    def log_message(self, *a):
        pass


if __name__ == "__main__":
    http.server.HTTPServer(("0.0.0.0", 9401), H).serve_forever()
