# Scribly brand assets

Everything here is generated from the same two values the site already uses: the spark glyph
and the palette (`#0f1115` background, `#2563eb` accent). If the mark changes, change it in one
place and re-render — do not hand-edit the PNGs.

## Colour

| Role | Hex | Where it is used |
|---|---|---|
| Accent / brand | `#2563eb` | buttons, the spark, focus rings, highlighted UI |
| Accent (pressed) | `#1d4ed8` | hover/active state on accent buttons |
| Background | `#0f1115` | page background, app and site |
| Panel | `#161a22` | cards, notices, table headers |
| Panel (raised) | `#1b2029` | nested surfaces |
| Border | `#262a33` | dividers, card edges |
| Border (strong) | `#3a3f4b` | control outlines |
| Text | `#e6e8eb` | body copy |
| Text (muted) | `#9aa1ad` | secondary copy, plan lines |
| Link | `#7ba6ff` | link text on dark backgrounds |

Measured WCAG contrast (white text on the accent button is 5.17:1, which passes AA):

| Pair | Ratio | Verdict |
|---|---|---|
| `#ffffff` on `#2563eb` | 5.17:1 | AA — safe for button labels |
| `#ffffff` on `#1d4ed8` | 6.70:1 | AA |
| `#e6e8eb` on `#0f1115` | 15.39:1 | AAA |
| `#9aa1ad` on `#0f1115` | 7.27:1 | AAA |
| `#2563eb` on `#0f1115` | 3.66:1 | large text only — do not use the accent for body text on dark |
| `#2563eb` on `#ffffff` | 3.66:1 | large text only — do not use the accent for body text on white |

That last row is why link text is `#7ba6ff` rather than the accent: the accent is a **fill** colour.
For anything rendered as text, use the lighter link tint on dark and `#1d4ed8` on white.

## Stripe branding

Stripe asks for two colours and uses them differently:

- **Brand colour** — fills the pay button, with white text on top. Enter `#2563eb` (5.17:1).
- **Accent colour** — used for links and small highlights **on white**. Enter `#1d4ed8`, one step
  darker, because `#2563eb` on white is only 3.66:1 and would be hard to read at body size.

Both read as the same blue family, so Checkout still looks like the app while staying legible.

## Files

| File | Size | Use |
|---|---|---|
| `logo-icon.svg` | vector | source of truth for the app icon (spark on a rounded dark tile) |
| `logo-mark.svg` | vector | the spark alone, no tile — for dark or accent backgrounds |
| `png/logo-icon-1024.png` | 1024×1024 | high-DPI app icon, store listings, press |
| `png/logo-icon-512.png` | 512×512 | **the logo to upload to Stripe** (square, transparent outside the rounded corners) |
| `png/logo-icon-128.png` | 128×128 | small square: Stripe brand icon, favicons, avatars |
| `png/favicon-32.png` | 32×32 | legacy favicon for clients that ignore SVG |
| `png/logo-mark-512.png` | 512×512 | spark alone, transparent — place on any dark surface |
| `png/logo-wordmark-1200x300.png` | 1200×300 | lockup for **dark** backgrounds (light wordmark) |
| `png/logo-wordmark-dark-1200x300.png` | 1200×300 | lockup for **light** backgrounds (dark wordmark) |

## Stripe

- **Settings → Branding → Logo:** `png/logo-icon-512.png`. Stripe wants a square image of at
  least 512 px; the file is transparent outside the rounded corners so it sits on any card colour.
- **Brand icon / receipt icon:** `png/logo-icon-128.png`.
- **Accent colour:** `#2563eb`. **Background:** `#0f1115`.
- Do not upload the wordmark lockups as the logo — Stripe renders its own name next to the icon,
  and a lockup shows "Scribly" twice.

## Rules

- Clear space around the mark: at least the width of one spark point (about 12% of the icon).
- Minimum sizes: icon 24 px, mark 16 px. Below that the four points blur into a diamond.
- The spark is always `#2563eb`. Do not recolour it to match a partner's palette.
- Never place the light wordmark on a light background — use the `-dark` variant.

## Re-rendering

The PNGs were captured from `assets/brand/logo-*.svg` (and an HTML harness for the wordmark, since
the text needs a system font). To regenerate at another size, render the SVG at that exact pixel
size with a transparent background; keep the file names and sizes in the table above so the Stripe
uploads stay predictable.
