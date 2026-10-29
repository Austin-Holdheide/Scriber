-- 0008: who wants Pro (T-1 stand-in until Stripe checkout exists)
--
-- The plan-limit notification offers "Upgrade to Pro", but there is no checkout
-- yet, so the honest thing it can do is record interest against the account.
-- One row per user; re-clicking is a no-op. Deliberately no email capture: the
-- account already has one, and we do not want a second marketing list.

create table if not exists public.pro_interest (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  plan_at_request text,
  note       text,
  created_at timestamptz not null default now()
);

create index if not exists pro_interest_created_idx on public.pro_interest (created_at desc);

alter table public.pro_interest enable row level security;

drop policy if exists pro_interest_own on public.pro_interest;
create policy pro_interest_own on public.pro_interest
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
