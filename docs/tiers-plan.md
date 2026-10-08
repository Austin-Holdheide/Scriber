# Scribly Roadmap — Monetization + Launch (added Oct 1, 2026)

Status: PLAN ONLY — nothing started. Appended to the existing TODO list.

## Features
- **Embedded subtitles render + download** — burn subtitles into the video (ffmpeg `subtitles` filter, server-side render) and offer the baked-in download; also standalone `.srt`-with-video style. Watermark on free plan; premium toggle for watermark on/off.
- **Subtitle editing** — in-app editor for segment text (edit typos before export/render).
- **Upload video menu** — dedicated upload UI/flow.
- **Landing page for scribly.cc** — marketing page separate from the app.
- **Dev + prod environments** — separate stacks (frontend, API, Supabase project/DB, Stripe keys test vs live).
- **app.scribly.cc 1.0 launch** (note: typo'd "sribly" in original list).
- **Email setup** — `*@scribly.cc` addresses, verification emails (GoTrue SMTP config), password reset.

## Account tiers (Stripe)
### Free
- 1 video transcription / day (mainly email capture — ties to email verification)
- Share links expire after **1 day**
- Auto-delete video after **7 days** (cleanup job + countdown timer on video page, free users only)
- **500 MB** upload limit
- Video compression to **240p**
- **No diarization** (no speaker names)
- **15 min** video length limit
- No bulk upload
- Low priority in queue
- **14-day premium trial**
- Watermark on downloads + baked-in-subtitle video downloads

### Premium
- 50 videos / 12h (marketed as "100 videos a day")
- **5 GB** upload per video (auto-compressed to 720p)
- Share links expire after **30 days**
- No auto-delete
- **24 h** video length limit
- Diarization limit **10 videos / day**
- Bulk upload
- High priority in queue
- No watermark on downloads
- Subtitles baked into video, no watermark

## Open design questions / edits (from review)
1. **Two limiters per tier**: MB size limit AND length limit — enforce ONE pre-transcode (length via ffprobe is simpler; size allows huge-but-short). Recommend: length only for free (15 min), size only for premium (5 GB).
2. **"100/day" vs enforcement 50/12h** — fine as marketing, but quota code should implement the 50-per-12h sliding window (or simplify both tiers to X/day).
3. **Transcode pipeline doesn't exist yet** — 240p free / 720p premium auto-compress + subtitle burn-in all need ffmpeg worker jobs (CPU, not GPU). Estimate: a 1h video at 720p ≈ tens of minutes CPU. This is the biggest hidden work item.
4. **Quota tracking schema**: daily counters per user (transcriptions, diarizations, bytes) + reset windows; RQ already has deterministic job ids to key off.
5. **Queue priority**: RQ supports queue-level priority; cleanest is `high`/`low` queue pairs and enqueue per tier.
6. **Stripe wiring**: webhook receiver endpoint, `subscriptions` table (user_id, plan, trial_end, current_period_end), enforcement reads it; test mode in dev env.
7. **Trial mechanics**: 14-day trial = Stripe trial period; make sure free-tier limits apply after expiry and that diarization quota is enforced during trial.
8. **Auto-delete job**: daily cron sweeping videos older than 7 days for free users; must also delete thumbs/segments/artifacts and handle in-flight jobs.
9. **Email verification gating**: free tier's 1/day email capture assumes GoTrue confirmations are ON — currently self-hosted GoTrue may auto-confirm; needs SMTP + `MAILER_AUTOCONFIRM=false`.
10. **POC currently shares the prod DB** — the dev/prod split (#env item) fixes this; do it BEFORE launching any paid tier.
11. **Legal**: ToS/privacy covering video storage, auto-deletion, watermarked exports.
