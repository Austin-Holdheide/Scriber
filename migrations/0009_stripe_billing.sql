-- T-1 billing: webhook idempotency + the few fields Stripe needs to write.
--
-- stripe_events makes delivery retries no-ops: Stripe guarantees at-least-once,
-- so applying the same event twice would double-write an entitlement change.
-- RLS is on with no policies, so only the service key (the API) can read or write.

create table if not exists public.stripe_events (
  id           text primary key,          -- Stripe event id (evt_...)
  type         text,
  received_at  timestamptz not null default now()
);

create index if not exists stripe_events_received_idx
  on public.stripe_events (received_at desc);

alter table public.stripe_events enable row level security;

alter table public.subscriptions
  add column if not exists cancel_at_period_end boolean not null default false;

-- Stripe timestamps we keep beside the period end, so support can answer
-- "when did this lapse?" without opening the dashboard.
alter table public.subscriptions
  add column if not exists canceled_at timestamptz;

create index if not exists subscriptions_stripe_customer_idx
  on public.subscriptions (stripe_customer_id)
  where stripe_customer_id is not null;

-- housekeeping helper: prune webhook ids older than 90 days (Stripe retries for 3 days)
comment on table public.stripe_events is
  'Stripe webhook ids already applied. Safe to prune older than 90 days.';
