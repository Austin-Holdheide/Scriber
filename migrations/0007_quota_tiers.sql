-- 0007: F-7 (quota accounting) + T-3 (subscriptions / plan state)
--
-- Two tables and a trigger:
--   subscriptions  one row per account, decides what the account may do
--   usage_events   append-only log of the things we meter (transcription, diarization)
--
-- Counting in a log rather than a counter column means sliding windows work
-- (premium = 50 per rolling 12 h) and the numbers stay auditable. At our volume
-- the index scan is trivial; revisit if a user ever has millions of events.

create table if not exists public.subscriptions (
  user_id                uuid primary key references auth.users(id) on delete cascade,
  plan                   text not null default 'free' check (plan in ('free','premium','admin')),
  status                 text not null default 'active'
                         check (status in ('active','trialing','past_due','canceled')),
  trial_end              timestamptz,
  current_period_end     timestamptz,
  stripe_customer_id     text,
  stripe_subscription_id text,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now()
);

create table if not exists public.usage_events (
  id         bigserial primary key,
  user_id    uuid not null references auth.users(id) on delete cascade,
  kind       text not null check (kind in ('transcription','diarization')),
  video_id   uuid references public.videos(id) on delete set null,
  created_at timestamptz not null default now()
);
create index if not exists usage_events_user_kind_time_idx
  on public.usage_events (user_id, kind, created_at desc);

-- Every new account starts life on the free plan. Doing this in the database
-- (not in application code) means signups through any path - the app, the admin
-- API, a future invite flow - are covered.
create or replace function public.scribly_new_user_plan() returns trigger
language plpgsql security definer as $$
begin
  insert into public.subscriptions (user_id, plan) values (new.id, 'free')
  on conflict (user_id) do nothing;
  return new;
end $$;

drop trigger if exists scribly_new_user_plan on auth.users;
create trigger scribly_new_user_plan after insert on auth.users
  for each row execute function public.scribly_new_user_plan();

-- backfill accounts created before this migration
insert into public.subscriptions (user_id, plan)
select id, 'free' from auth.users
on conflict (user_id) do nothing;

-- keep updated_at honest
create or replace function public.scribly_touch_updated_at() returns trigger
language plpgsql as $$
begin new.updated_at = now(); return new; end $$;

drop trigger if exists subscriptions_touch on public.subscriptions;
create trigger subscriptions_touch before update on public.subscriptions
  for each row execute function public.scribly_touch_updated_at();

-- The operator account keeps full access so testing a 3-hour upload stays possible.
update public.subscriptions s set plan = 'admin', status = 'active'
 where s.user_id in (
   select id from auth.users
    where lower(email) in ('austin.holdheide@outlook.com')
 );

alter table public.subscriptions enable row level security;
drop policy if exists subscriptions_own_read on public.subscriptions;
create policy subscriptions_own_read on public.subscriptions
  for select using (auth.uid() = user_id);

alter table public.usage_events enable row level security;
drop policy if exists usage_events_own_read on public.usage_events;
create policy usage_events_own_read on public.usage_events
  for select using (auth.uid() = user_id);
