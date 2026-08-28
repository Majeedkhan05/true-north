-- ============================================================================
--  Brokerage-AI  —  PostgreSQL / Supabase schema  (region: ca-central-1)
--  Run in Supabase SQL editor, or:  psql "$DATABASE_URL" -f schema.sql
-- ============================================================================

create extension if not exists "pgcrypto";   -- gen_random_uuid()

-- ----------------------------------------------------------------------------
--  brokerages
-- ----------------------------------------------------------------------------
create table if not exists brokerages (
    id                      uuid primary key default gen_random_uuid(),
    email                   text not null unique,
    name                    text not null,
    language                text not null default 'en' check (language in ('en','fr')),
    postal_code             text,
    plan                    text not null default 'starter'
                                check (plan in ('starter','pro','enterprise')),
    stripe_customer_id      text,
    stripe_subscription_id  text,
    status                  text not null default 'inactive'
                                check (status in ('active','trialing','inactive','past_due','canceled')),
    doc_limit               integer default 100,          -- NULL = unlimited (enterprise)
    docs_used               integer not null default 0,
    quota_period_start      timestamptz not null default now(),
    created_at              timestamptz not null default now()
);

-- If upgrading an existing database, add the quota columns idempotently:
alter table brokerages add column if not exists doc_limit          integer default 100;
alter table brokerages add column if not exists docs_used          integer not null default 0;
alter table brokerages add column if not exists quota_period_start timestamptz not null default now();

create index if not exists idx_brokerages_stripe_customer on brokerages(stripe_customer_id);
create index if not exists idx_brokerages_stripe_sub      on brokerages(stripe_subscription_id);

-- ----------------------------------------------------------------------------
--  documents
-- ----------------------------------------------------------------------------
create table if not exists documents (
    id                uuid primary key default gen_random_uuid(),
    brokerage_id      uuid not null references brokerages(id) on delete cascade,
    file_hash         text not null,
    file_path         text,
    extracted_json    jsonb,
    confidence_score  numeric,
    status            text not null default 'processed'
                          check (status in ('processed','approved','failed')),
    draft_email       text,
    retry_count       integer not null default 0,
    created_at        timestamptz not null default now()
);

alter table documents add column if not exists retry_count integer not null default 0;

create index if not exists idx_documents_brokerage on documents(brokerage_id);
-- Dedup is scoped per-brokerage: same file may legitimately reach two brokerages.
create unique index if not exists uq_documents_brokerage_hash
    on documents(brokerage_id, file_hash);

-- ----------------------------------------------------------------------------
--  audit_logs
-- ----------------------------------------------------------------------------
create table if not exists audit_logs (
    id            bigserial primary key,
    brokerage_id  uuid references brokerages(id) on delete set null,
    document_id   uuid references documents(id) on delete set null,
    action        text not null,
    timestamp     timestamptz not null default now(),
    ip_address    text
);

create index if not exists idx_audit_brokerage on audit_logs(brokerage_id);

-- ============================================================================
--  ROW LEVEL SECURITY
--  Each brokerage may only see its own rows.
--
--  We expose the caller's brokerage id through a request-scoped GUC:
--      set local app.brokerage_id = '<uuid>';
--  The FastAPI layer sets this per request after authenticating the brokerage.
--  The Supabase service-role key bypasses RLS for admin/onboarding tasks.
-- ============================================================================

alter table brokerages enable row level security;
alter table documents  enable row level security;
alter table audit_logs enable row level security;

-- brokerages: a brokerage row is visible only to itself
drop policy if exists brokerages_isolation on brokerages;
create policy brokerages_isolation on brokerages
    using (id = nullif(current_setting('app.brokerage_id', true), '')::uuid);

-- documents: visible only to owning brokerage
drop policy if exists documents_isolation on documents;
create policy documents_isolation on documents
    using (brokerage_id = nullif(current_setting('app.brokerage_id', true), '')::uuid)
    with check (brokerage_id = nullif(current_setting('app.brokerage_id', true), '')::uuid);

-- audit_logs: visible only to owning brokerage (insert allowed for own id)
drop policy if exists audit_isolation on audit_logs;
create policy audit_isolation on audit_logs
    using (brokerage_id = nullif(current_setting('app.brokerage_id', true), '')::uuid)
    with check (brokerage_id = nullif(current_setting('app.brokerage_id', true), '')::uuid);

-- ----------------------------------------------------------------------------
--  90-day retention helper (called by cron_cleanup.py / pg_cron)
-- ----------------------------------------------------------------------------
create or replace function purge_old_documents() returns integer as $$
declare
    deleted integer;
begin
    with del as (
        delete from documents
        where created_at < now() - interval '90 days'
        returning id
    )
    select count(*) into deleted from del;
    return deleted;
end;
$$ language plpgsql;

-- Optional: schedule with pg_cron (Supabase) — runs daily at 03:00 UTC.
-- select cron.schedule('purge-old-documents', '0 3 * * *', 'select purge_old_documents();');
