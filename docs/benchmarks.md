# ASR Benchmarks — Tesla P4 (int8) vs CPU

Test clip: jfk.wav x10 (~110s real speech, VAD off). Load = model load time.
RTF = transcribe_time / audio_time (lower = better; <1 = faster than realtime).

## GPU — Tesla P4 (204), CUDA int8 (CTranslate2 + cublas/cudnn cu12 pip wheels)
| Model | Load (s) | Transcribe (s) | RTF | Speedup vs realtime |
|---|---|---|---|---|
| small | - | 18.7 | 0.17 | ~6x |
| medium | - | 44.7 | 0.41 | ~2.5x |
| large-v3-turbo | - | 14.2 | **0.13** | **~8x** |

## CPU — 203 (14 vCPU threads, int8)
| Model | Transcribe (s) | RTF | Notes |
|---|---|---|---|
| small | 70.9 | 0.65 | ~1.5x realtime |
| medium | 178.2 | 1.63 | slower than realtime |

## Decision
- **Production default: large-v3-turbo / cuda / int8** (best RTF AND best accuracy class)
- CPU 203 fallback: small int8 (0.65 RTF = 1-hr video in ~40 min) — medium on CPU is pointless
- large-v3 (non-turbo) skipped: slower than turbo with no quality win for this use case
- Note: earlier synthetic-sine bench showed bogus RTF 0.005 (VAD skipped non-speech) - real-speech numbers above are authoritative.

## Soak test (W6-polish, Sep 8)
- 2 parallel jobs: distributed across 204+205, both done|100 concurrently
- Kill-worker-mid-transcribe: RQ requeued job, other worker finished it -> no lost jobs, no zombies
- DB after tests: 12 videos / 4 transcripts / 35 segments / 11 jobs, 122MB on NFS

## Operational notes
- RQ 2.12: `job_id` is a RESERVED enqueue kwarg (sets the job's redis id) — passing data with
  that name silently drops it. Our data param is `job_row_id`.
- SIGKILLed workers leave stale `rq:worker:<name>` registrations → next start fails with
  "active worker named ... already". Fix: `redis-cli del rq:worker:<name>` then restart.

## Real-world long-file validation (Sep 10, 2026)
| File | Length | Size | Result |
|---|---|---|---|
| WAN Show ep (mp4) | 3h42m | 416MB | 3882 segments, done, in sync hour+ into playback |
| SCANTRON (mp4) | 36:38 | 93MB | 418 segments, done, in sync |

Hardening from these two files (all fixed & committed):
- Chunked transcription (10-min chunks, VAD off per chunk) - fixes OOM on long files
- Duration-aware VAD policy - fixes timestamp drift (was 60s over 50min)
- PostgREST 1000-row cap - transcripts now paged (FBI: 2172 segs were silently halved)
- RFC 5987 filename headers - non-latin1 filenames (full-width ？) crashed downloads
