-- W12: share links - expiring, read-only transcript sharing
create table if not exists public.share_links (
  id          uuid primary key default gen_random_uuid(),
  video_id    uuid not null references public.videos(id) on delete cascade,
  user_id     uuid not null references auth.users(id) on delete cascade,
  token       text not null unique,
  expires_at  timestamptz not null,
  created_at  timestamptz not null default now(),
  revoked     boolean not null default false
);
create index if not exists share_links_token_idx on public.share_links (token);
alter table public.share_links enable row level security;
drop policy if exists "share_links_owner_all" on public.share_links;
create policy "share_links_owner_all" on public.share_links
  for all using (uid() = user_id) with check (uid() = user_id);
