-- W16 cheap wins migration (run on CT 201 supabase-db)
-- 1) dedicated cancel flag: worker heartbeats rewrite stage/progress every 5s,
--    so a stage-based cancel marker would be clobbered.
alter table public.jobs add column if not exists cancel_requested boolean not null default false;

-- 2) cancelled status for videos (jobs.stage is free-text, videos.status is CHECK-constrained)
alter table public.videos drop constraint if exists videos_status_check;
alter table public.videos add constraint videos_status_check
  check (status = any (array['uploaded'::text, 'queued'::text, 'transcribing'::text,
                             'done'::text, 'failed'::text, 'cancelled'::text]));
