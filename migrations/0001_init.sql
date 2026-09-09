-- Scriber schema v1 (applied 2026-09-05)
-- NOTE: this is a reconstruction from the applied version; see plan files for history.
create extension if not exists pgcrypto;

create table if not exists public.videos (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  filename text not null,
  storage_path text not null,
  size_bytes bigint,
  duration_s numeric,
  language text,
  status text not null default 'uploaded' check (status in ('uploaded','queued','transcribing','done','failed')),
  created_at timestamptz not null default now()
);
alter table public.videos enable row level security;
create policy "videos_owner_all" on public.videos for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create table if not exists public.transcripts (
  id uuid primary key default gen_random_uuid(),
  video_id uuid not null references public.videos(id) on delete cascade,
  model text not null,
  full_text text,
  srt_path text,
  vtt_path text,
  created_at timestamptz not null default now()
);
alter table public.transcripts enable row level security;
create policy "transcripts_owner_all" on public.transcripts for all
  using (exists (select 1 from public.videos v where v.id = video_id and v.user_id = auth.uid()))
  with check (exists (select 1 from public.videos v where v.id = video_id and v.user_id = auth.uid()));

create table if not exists public.segments (
  id bigint generated always as identity primary key,
  transcript_id uuid not null references public.transcripts(id) on delete cascade,
  start_ms int not null,
  end_ms int not null,
  speaker text,
  text text not null,
  confidence numeric
);
create index segments_transcript_idx on public.segments(transcript_id, start_ms);
alter table public.segments enable row level security;
create policy "segments_owner_all" on public.segments for all
  using (exists (select 1 from public.transcripts t join public.videos v on v.id = t.video_id where t.id = transcript_id and v.user_id = auth.uid()))
  with check (exists (select 1 from public.transcripts t join public.videos v on v.id = t.video_id where t.id = transcript_id and v.user_id = auth.uid()));

create table if not exists public.jobs (
  id uuid primary key default gen_random_uuid(),
  video_id uuid not null references public.videos(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  stage text not null default 'queued',
  progress int not null default 0 check (progress between 0 and 100),
  error text,
  updated_at timestamptz not null default now()
);
alter table public.jobs enable row level security;
create policy "jobs_owner_all" on public.jobs for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

alter publication supabase_realtime add table public.jobs;
