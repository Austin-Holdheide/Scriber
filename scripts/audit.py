#!/usr/bin/env python3
"""Consistency audit for Scribly.

Runs with the standard library only, from the repo root, and exits non-zero on
anything that must not ship. Warnings are things worth a look, not failures.

The point is the invariants that quietly rot: plan numbers that disagree with
`quota.py`, emoji creeping back into the UI, a page hero built on `<header>`
(the global topbar rule mangles it), colours outside the palette, and README
images that point at files nobody committed.

    python3 scripts/audit.py            # check
    python3 scripts/audit.py --strict   # warnings count as failures (for CI)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STRICT = "--strict" in sys.argv

errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def need(rel: str) -> str:
    p = ROOT / rel
    if not p.exists():
        err(f"missing file: {rel}")
        return ""
    return p.read_text(encoding="utf-8")


# ----------------------------------------------------------------- 1. plans
def plan_spec() -> dict:
    """Read the real limits out of quota.py so the audit cannot drift from the code."""
    q = need("backend/app/services/quota.py")
    if not q:
        return {}

    def env(name: str, default: int) -> int:
        # defaults are written as "5 * 1024" / "15 * 60" / "24 * 3600", so evaluate them
        m = re.search(rf'_env_int\("{name}",\s*([0-9 *]+)', q)
        if not m:
            return default
        try:
            return int(eval(m.group(1).strip(), {"__builtins__": {}}, {}))
        except Exception:
            return default

    def lit(name: str, default: int) -> int:
        m = re.search(rf"{name}=([0-9]+)", q)
        return int(m.group(1)) if m else default

    return {
        "free": {
            "upload_mb": env("QUOTA_FREE_MAX_UPLOAD_MB", 500),
            "duration_s": env("QUOTA_FREE_MAX_DURATION_S", 900),
            "uploads": env("QUOTA_FREE_UPLOADS", 1),
            "window_s": env("QUOTA_FREE_WINDOW_S", 86400),
            "diarizations": env("QUOTA_FREE_DIARIZATIONS", 0),
            "share_days": lit("share_max_days", 7),
        },
        "premium": {
            "upload_mb": env("QUOTA_PREMIUM_MAX_UPLOAD_MB", 5120),
            "duration_s": env("QUOTA_PREMIUM_MAX_DURATION_S", 86400),
            "uploads": env("QUOTA_PREMIUM_UPLOADS", -1),
            "window_s": 0,
            "diarizations": env("QUOTA_PREMIUM_DIARIZATIONS", 10),
            "share_days": 30,
        },
    }


def human_mb(mb: int) -> str:
    return f"{mb / 1024:.0f} GB" if mb >= 1024 else f"{mb} MB"


def human_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} s"
    if seconds % 3600 == 0:
        return f"{seconds // 3600} hours" if seconds >= 7200 else "1 hour"
    return f"{seconds // 60} min"


def check_plan_numbers() -> None:
    spec = plan_spec()
    if not spec:
        return
    free, pro = spec["free"], spec["premium"]

    # the numbers every surface must agree on
    expected = {
        "free size": human_mb(free["upload_mb"]),
        "pro size": human_mb(pro["upload_mb"]),
        "free length": human_duration(free["duration_s"]).replace(" hours", " hours"),
        "pro length": human_duration(pro["duration_s"]),
    }

    pro_tsx = need("frontend/src/pages/Pro.tsx")
    terms = need("landing/terms.html")
    landing = need("landing/index.html")

    for label, value in expected.items():
        if value not in pro_tsx:
            err(f"Pro.tsx does not mention the {label} ({value!r}) from quota.py")
        if value not in terms:
            err(f"terms.html does not mention the {label} ({value!r}) from quota.py")

    # diarization allowance is the number most likely to drift
    if pro["diarizations"] and f"{pro['diarizations']} per day" not in pro_tsx:
        err(f"Pro.tsx does not state {pro['diarizations']} diarizations per day")
    if pro["share_days"] and f"{pro['share_days']} days" not in pro_tsx:
        err(f"Pro.tsx does not state {pro['share_days']}-day shares")

    # published prices, in every place a customer can read them
    for price, where in (("$9", "Pro.tsx"), ("$90", "Pro.tsx")):
        if price not in pro_tsx:
            err(f"{where} is missing the published price {price}")
    for price in ("$9", "$90"):
        if price not in landing:
            warn(f"landing/index.html no longer mentions {price} (expected in #pricing)")


# ----------------------------------------------------------------- 2. copy
# pictographs, flags and the spark glyphs; ✓ ✕ ← are typographic symbols and allowed
EMOJI = re.compile("[\U0001F000-\U0001FAFF\U0001F1E6-\U0001F1FF\u2726\u2727\u2728\u2733\u2734]")


def check_no_emoji() -> None:
    """No emoji in UI copy, and never the spark glyph (it renders as tofu in some clients)."""
    targets = list((ROOT / "frontend/src").rglob("*.tsx")) + list((ROOT / "frontend/src").rglob("*.ts"))
    targets += list((ROOT / "landing").glob("*.html"))
    for p in targets:
        rel = p.relative_to(ROOT)
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            for m in EMOJI.finditer(line):
                err(f"emoji/glyph {m.group(0)!r} in {rel}:{i} — use inline SVG instead")


def check_banned_copy() -> None:
    """Positioning that was deliberately removed must not come back."""
    banned = {
        "self-hosted": "self-hosting claims were removed from the public copy",
        "self hosted": "self-hosting claims were removed from the public copy",
        "in development": "pre-launch badge was removed",
        "early access is open": "signups are real now",
    }
    for rel in ["landing/index.html", "landing/terms.html", "landing/privacy.html", "frontend/src/pages/Pro.tsx"]:
        text = read(rel).lower()
        for phrase, why in banned.items():
            if phrase in text:
                err(f"{rel} still says {phrase!r} — {why}")


# ----------------------------------------------------------------- 3. markup
def check_header_hero() -> None:
    """`<header>` is styled as the flex topbar globally; a page hero built on it breaks."""
    pages = list((ROOT / "frontend/src/pages").glob("*.tsx"))
    for p in pages:
        text = p.read_text(encoding="utf-8")
        if "<header" in text:
            err(f"{p.relative_to(ROOT)} uses <header> — the global topbar rule will mangle the layout; use a div")


def check_meta() -> None:
    for rel in ["landing/index.html", "frontend/index.html"]:
        text = read(rel)
        if not text:
            continue
        if 'name="description"' not in text:
            err(f"{rel} has no <meta name=\"description\">")
        if rel.startswith("landing") and 'property="og:description"' not in text:
            warn(f"{rel} has no og:description (link previews will fall back)")
        m = re.search(r'name="description"\s+content="([^"]*)"', text)
        if m and len(m.group(1)) < 40:
            warn(f"{rel} meta description is only {len(m.group(1))} chars")


# ----------------------------------------------------------------- 4. colours
PALETTE = {
    "#0f1115", "#161a22", "#1b2029", "#262a33", "#3a3f4b", "#e6e8eb", "#9aa1ad",
    "#2563eb", "#1d4ed8", "#7ba6ff", "#f87171", "#4ade80", "#93c5fd", "#c8ced8",
    "#cfe0ff", "#eaf1ff", "#9aa3b0", "#6f7683", "#c6ccd4", "#1e2430", "#2f4a80",
    "#450a0a", "#7f1d1d", "#3b82f6", "#93b4ff", "#5b6270", "#0a0c10", "#11141a",
}


def check_colours() -> None:
    """Report colours that are not in the documented palette — drift, not always a bug."""
    seen: dict[str, set[str]] = {}
    for p in list((ROOT / "frontend/src").rglob("*.tsx")):
        for hexcode in re.findall(r"#[0-9a-fA-F]{6}\b", p.read_text(encoding="utf-8")):
            h = hexcode.lower()
            if h not in PALETTE:
                seen.setdefault(h, set()).add(str(p.relative_to(ROOT)))
    for h, files in sorted(seen.items()):
        warn(f"off-palette colour {h} in {', '.join(sorted(files)[:3])}")


# ----------------------------------------------------------------- 5. docs
def check_readme_images() -> None:
    text = read("README.md")
    for ref in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text):
        if ref.startswith("http"):
            continue
        if not (ROOT / ref).exists():
            err(f"README references {ref} which is not in the repo")


def check_docs_present() -> None:
    for rel in ["docs/HANDOFF.md", "CHANGELOG.md", "assets/brand/README.md"]:
        need(rel)


# ----------------------------------------------------------------- 6. secrets
def check_no_secrets() -> None:
    """Keys must never land in the repo. Cheap patterns only — this is a tripwire."""
    patterns = [
        (r"sk_(test|live)_[A-Za-z0-9]{10,}", "a Stripe secret key"),
        (r"whsec_[A-Za-z0-9]{10,}", "a Stripe webhook secret"),
        (r"SUPABASE_SERVICE_KEY\s*=\s*ey[A-Za-z0-9]", "a Supabase service key"),
        (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "a private key"),
    ]
    skip_dirs = {".git", "node_modules", "dist", "__pycache__"}
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.suffix in {".png", ".jpg", ".ico", ".zip", ".bundle"}:
            continue
        if skip_dirs & set(p.parts):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern, what in patterns:
            if re.search(pattern, text):
                err(f"{p.relative_to(ROOT)} looks like it contains {what}")


def main() -> int:
    checks = [
        check_plan_numbers, check_no_emoji, check_banned_copy, check_header_hero,
        check_meta, check_colours, check_readme_images, check_docs_present, check_no_secrets,
    ]
    for check in checks:
        try:
            check()
        except Exception as exc:  # a broken check must not hide the others
            err(f"{check.__name__} crashed: {exc}")

    for e in errors:
        print(f"ERROR   {e}")
    for w in warnings:
        print(f"WARN    {w}")
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")

    if errors:
        return 1
    if STRICT and warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
