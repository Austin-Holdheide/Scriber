# W10 — Diarization Plan (pyannote 3.1 on Tesla P4)

> Written 9/18 from live recon. Next session: execute step-by-step, no research needed.
> Every version/size/gate below is verified as of this date.

## Goal
Label each segment with a speaker ("Speaker 1", "Speaker 2", ...) in the existing
`segments.speaker` column, with a naming UI in the viewer.

## Recon results (verified)
- **GPU**: 2× Tesla P4 (Pascal, **compute cap 6.1**, driver 550.163.01). 7,680 MiB each, idle 0 MiB.
  Whisper large-v3-turbo int8 uses ~2.5 GB → ~5 GB free for diarization per worker.
- **CTs**: 204/205 — Python 3.11.2, venv `/opt/scriber/venv`, disk 9.3G/12G free, RAM 8 GB.
  Already installed: faster-whisper 1.1.1, ctranslate2 4.8.2, **onnxruntime 1.29.0**,
  huggingface_hub 1.30.0, nvidia-cublas-cu12 12.9, nvidia-cudnn-cu12 9.25 (pip wheels).
- **NFS**: 1.2 TB free — HF cache lives on NFS, shared by 204+205 (already 3.5G whisper models at
  `~/.cache/huggingface`).
- **huggingface.co reachable** from 204 (200).
- **Gated models**: BOTH `pyannote/speaker-diarization-3.1` AND `pyannote/segmentation-3.0`
  are `gated: auto` → require HF account + accept-conditions ONCE (web UI), then a
  **HF read token** with `read` role. Token does NOT exist yet on 204 (grep = 0).
- **torch**: Pascal needs cu121 or cu118 builds (sm_61 kernels included).
  - cu121 cp311: torch 2.5.1+cu121 exists (~906 MB wheel)
  - **Recommendation: torch 2.5.1+cu121** (matches CUDA 12 runtime already in venv; cu118 is the
    fallback if cu121 misbehaves; torch 2.6+cu118 exists too but bigger jump).
  - torchaudio 2.5.1+cu121 must match torch (needed by pyannote audio I/O via soundfile fallback —
    install it to be safe, small wheel).
- **pyannote.audio 3.1.0** deps: lightning>=2.0.1, speechbrain>=0.5.14, pyannote.core/metrics/
  pipeline/database, asteroid-filterbanks, einops, omegaconf, pytorch-metric-learning,
  soundfile, tensorboardX, semver, rich. Installs fine on py3.11 (no pinned torch conflicts —
  torch installed separately).
- **Worker stage hook point**: `tasks.py` transcribe_job — between `transcribing` (ends ~85%) and
  `writing` (88%): add `diarizing` stage (jobs.stage is free-text; UI already renders unknown
  stages as working badge). Segments already have `speaker` column; viewer already renders it.
- **Supabase Realtime**: jobs UPDATE events already stream; `cancel_requested` boolean already
  wired — diarization stage must also honor it (long GPU stage ~ RTF 0.05–0.1 of audio length).

## Model sizes (disk, after download)
- segmentation-3.0: ~9 MB · wespeaker/embedding (via diarization-3.1 config): ~70 MB
- speaker-diarization-3.1 config bundles both. Total < 100 MB (tiny vs whisper's 3.5 GB).

## Execution steps (in order)

### 1) HF account + token (user does this once, 2 min)
1. huggingface.co → sign in (free account)
2. Open https://hf.co/pyannote/speaker-diarization-3.1 → accept the user conditions
3. Open https://hf.co/pyannote/segmentation-3.0 → accept conditions too
4. Settings → Access Tokens → New token (role: **read**) → copy value
5. Give token to the session (or put it on 204 at `/opt/scriber/.env` as `HF_TOKEN=hf_xxx`)

### 2) Install deps on 204 (and 205) — ~1.5 GB disk, ~3 min
```bash
pct exec 204 -- bash -c '/opt/scriber/venv/bin/pip install \
  torch==2.5.1+cu121 torchaudio==2.5.1+cu121 \
  --index-url https://download.pytorch.org/whl/cu121'
pct exec 204 -- bash -c '/opt/scriber/venv/bin/pip install "pyannote.audio==3.1.0" \
  "huggingface_hub>=0.23"'
# verify CUDA works for torch:
pct exec 204 -- bash -c '/opt/scriber/venv/bin/python -c "import torch; print(torch.__version__, torch.cuda.is_available())"'
# MUST print: 2.5.1+cu121 True
```
If `torch.cuda.is_available()` is False → driver/kernel mismatch; try cu118 build instead.

### 3) HF cache on NFS (shared 204+205, survives CT rebuild)
```bash
# on 204 (env for all worker services): add to /opt/scriber/.env
HF_TOKEN=hf_xxx
HF_HOME=/mnt/media/hf-cache
pct exec 204 -- mkdir -p /mnt/media/hf-cache
# pre-download models (one time, ~100 MB):
pct exec 204 -- bash -c 'set -a; . /opt/scriber/.env; set +a; /opt/scriber/venv/bin/python -c "
from huggingface_hub import snapshot_download
snapshot_download("pyannote/speaker-diarization-3.1", endpoint="https://huggingface.co")
print("diarization model cached")
"'
# repeat the same .env + pip steps on 205
```

### 4) Smoke test standalone (before touching tasks.py)
```bash
pct exec 204 -- bash -c 'set -a; . /opt/scriber/.env; set +a; /opt/scriber/venv/bin/python -c "
from pyannote.audio import Pipeline
p = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=True)
import sys
out = p("/mnt/media/videos/a5733d15-a94a-4587-8de3-d1adcc518292/00cf0cb5-6b10-415c-9101-1c24da91b601.mp4")
for turn, _, spk in list(out.itertracks(yield_label=True))[:8]:
    print(round(turn.start,1), round(turn.end,1), spk)
"'
```
Success = printed (start, end, SPEAKER_00) tuples. Note RTF (time vs 36-min file).

### 5) Wire into tasks.py (small diff)
- New service `app/services/diarize.py` on worker CTs:
  - lazy `_pipeline` singleton (like `_model` in tasks.py)
  - `assign_speakers(segments, wav_path) -> segments` — run pipeline once, map each
    segment's midpoint to the overlapping speaker turn (`SPEAKER_00` → "Speaker 1"…)
  - VRAM guard: run BEFORE whisper model unload? No — keep whisper loaded; diarization
    fits in the ~5 GB headroom. If OOM → set `PYANNOTE_DEVICE=cpu` env fallback.
- tasks.py: after transcription completes, if env `DIARIZATION_ENABLED=1` (default off →
  per-video toggle later): `_set_job(job_row_id, "diarizing", 86)`, `_check_cancel`,
  `segments = assign_speakers(segments, str(wav))`, then continue to writing.
- jobs.stage UI: "diarizing" shows as working badge automatically (frontend stageLabel
  fallback) — optionally add explicit label.

### 6) Frontend speaker naming UI (VideoPage.tsx)
- Segments already render `s.speaker`. Add: distinct colors per speaker (CSS nth),
  rename modal: per distinct speaker value → user-typed name → PATCH `/api/segments/{id}`
  bulk update (new endpoint `POST /api/videos/{id}/speakers` with map {SPEAKER_0: "Alice"})
  → updates all segments of that transcript.

### 7) Rollout: env flag + one video test, then enable fleet-wide
- Default OFF (`DIARIZATION_ENABLED=0` in .env) — flip per test, then on for both GPU CTs.
- CPU worker 203: leave diarization OFF (RTF would be terrible on 14 threads).

## Risks / gotchas (from recon)
- torch cu121 wheel is 906 MB → 204 has 9.3 GB free; install AFTER backing up nothing
  (venv is disposable, runbook documents rebuild).
- lightning installs pytorch-lightning deps → watch for numpy 2.x conflicts; pin
  `numpy<2.3` only if errors appear (currently numpy 2.4.6 works with ctranslate2).
- pyannote imports `torch.audiomentations` + `torchmetrics` transitively (installed with it).
- **Do NOT touch** the pinned 6.14 kernel / driver 550 during this work.
- Segments-to-turn mapping: whisper segments can span turn boundaries — use midpoint;
  optionally split segment text at boundary (v1.1: keep midpoint, simple).
