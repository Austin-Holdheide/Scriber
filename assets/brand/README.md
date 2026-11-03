# Scribly brand assets

Everything here is generated from the same two values the site already uses: the spark glyph
and the palette (`#0f1115` background, `#2563eb` accent). If the mark changes, change it in one
place and re-render — do not hand-edit the PNGs.

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
