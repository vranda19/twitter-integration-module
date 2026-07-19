-- ============================================================================
-- Migration: 002_create_twitter_posts.sql
-- Purpose:   Audit trail + scheduling contract for tweets and threads.
--
-- twitter_posts       -> one row per "publish action" (a single tweet OR a thread)
-- twitter_post_items  -> one row per individual tweet within that action
--                        (exactly 1 row for a single tweet, N rows for a thread)
--
-- WHY THIS EXISTS (see app/repositories/twitter_post_repository.py docstring):
--   1. Audit trail independent of Twitter's own history
--   2. Scheduling handoff contract for another team member's Celery worker
--   3. Thread rollback bookkeeping (which items succeeded before a failure)
-- ============================================================================

create table if not exists public.twitter_posts (
    id                   uuid primary key default gen_random_uuid(),
    user_id              uuid not null references auth.users(id) on delete cascade,
    twitter_account_id   uuid not null references public.twitter_accounts(id) on delete cascade,

    post_type            text not null check (post_type in ('single', 'thread')),
    status               text not null check (status in ('draft', 'scheduled', 'publishing', 'published', 'failed')),

    scheduled_time       timestamptz,
    -- Open JSON bag for the scheduler-owning module to attach its own
    -- fields (celery_task_id, retry_count, queue_name, etc.) without
    -- requiring a migration on this table. See twitter_schedule_service.py.
    queue_metadata        jsonb not null default '{}'::jsonb,

    created_at           timestamptz not null default now(),
    updated_at           timestamptz not null default now()
);

comment on table public.twitter_posts is
    'One row per publish action (single tweet or thread). Scheduling metadata here is read by an external scheduler module, not executed by this module.';

create index if not exists idx_twitter_posts_user_id
    on public.twitter_posts (user_id);

create index if not exists idx_twitter_posts_account_id
    on public.twitter_posts (twitter_account_id);

-- Supports TwitterPostRepository.list_scheduled_due() efficiently.
create index if not exists idx_twitter_posts_scheduled_due
    on public.twitter_posts (status, scheduled_time)
    where status = 'scheduled';

create trigger trg_twitter_posts_updated_at
    before update on public.twitter_posts
    for each row
    execute function public.set_updated_at();


create table if not exists public.twitter_post_items (
    id                   uuid primary key default gen_random_uuid(),
    post_id              uuid not null references public.twitter_posts(id) on delete cascade,

    sequence_order       integer not null default 0,
    text                 text not null,
    media_ids            jsonb not null default '[]'::jsonb,

    twitter_tweet_id     text,
    status               text not null check (status in ('draft', 'scheduled', 'publishing', 'published', 'failed')),
    error_message        text,

    created_at           timestamptz not null default now(),

    constraint uq_twitter_post_items_post_sequence unique (post_id, sequence_order)
);

comment on table public.twitter_post_items is
    'Individual tweets within a post record. sequence_order preserves thread ordering; exactly 1 row for post_type=single.';

create index if not exists idx_twitter_post_items_post_id
    on public.twitter_post_items (post_id);
