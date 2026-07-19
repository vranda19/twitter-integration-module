-- ============================================================================
-- Migration: 001_create_twitter_accounts.sql
-- Purpose:   Stores one row per connected Twitter/X account per user.
--            Supports multiple Twitter accounts connected to the same user.
--
-- WHY encrypted TEXT columns for tokens (not a Postgres native encryption
-- feature): application-layer encryption (Fernet, see app/core/security.py)
-- means the encryption key never lives in the database itself — a leaked
-- DB backup or compromised service-role key alone cannot decrypt tokens.
-- ============================================================================

create extension if not exists "pgcrypto";

create table if not exists public.twitter_accounts (
    id                  uuid primary key default gen_random_uuid(),
    user_id             uuid not null references auth.users(id) on delete cascade,

    twitter_user_id     text not null,
    username            text not null,
    display_name        text not null,
    profile_image_url   text,

    -- Encrypted (Fernet ciphertext) — plaintext tokens NEVER touch this table.
    access_token        text not null,
    refresh_token       text,

    scope               text not null,
    expires_at          timestamptz not null,

    is_active           boolean not null default true,

    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),

    -- A user can only connect the same physical Twitter account once;
    -- reconnecting reactivates the existing row instead of duplicating it.
    constraint uq_twitter_accounts_user_twitter_user unique (user_id, twitter_user_id)
);

comment on table public.twitter_accounts is
    'One row per Twitter/X account connected by a user via OAuth 2.0. Tokens are encrypted at the application layer before storage.';
comment on column public.twitter_accounts.access_token is
    'Fernet-encrypted ciphertext. Decrypted only in app/core/security.py at point of use.';
comment on column public.twitter_accounts.refresh_token is
    'Fernet-encrypted ciphertext. NULL if offline.access scope was not granted.';

-- Indexes supporting the exact query patterns used in
-- app/repositories/twitter_account_repository.py
create index if not exists idx_twitter_accounts_user_id
    on public.twitter_accounts (user_id);

create index if not exists idx_twitter_accounts_user_active
    on public.twitter_accounts (user_id, is_active);

-- ----------------------------------------------------------------------------
-- Row Level Security
--
-- This backend module uses the Supabase SERVICE ROLE key (bypasses RLS)
-- and enforces user_id scoping manually in every repository query — see
-- app/core/supabase_client.py for the reasoning.
--
-- RLS is still enabled and a policy defined here so that:
--   (a) any FUTURE direct frontend-to-Supabase read (via anon key) is
--       automatically scoped to the user's own rows, as defense in depth
--   (b) the table never accidentally becomes fully open if RLS is later
--       relied upon by another part of the system
-- ----------------------------------------------------------------------------
alter table public.twitter_accounts enable row level security;

create policy "Users can view their own twitter accounts"
    on public.twitter_accounts
    for select
    using (auth.uid() = user_id);

create policy "Users can update their own twitter accounts"
    on public.twitter_accounts
    for update
    using (auth.uid() = user_id);

-- Note: INSERT/DELETE intentionally have no policy for the anon/authenticated
-- roles — those operations only happen via this backend's service-role
-- connection (OAuth callback creates rows; disconnect soft-deletes them).

-- ----------------------------------------------------------------------------
-- updated_at auto-touch trigger
-- ----------------------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

create trigger trg_twitter_accounts_updated_at
    before update on public.twitter_accounts
    for each row
    execute function public.set_updated_at();
