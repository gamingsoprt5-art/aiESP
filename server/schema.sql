-- AI Smart Glasses — PostgreSQL schema
-- Run this once against your DATABASE_URL (Supabase / Neon / any Postgres 14+).
-- Safe to re-run: every statement is idempotent.

create extension if not exists pgcrypto;

create table if not exists devices (
    id uuid primary key default gen_random_uuid(),
    installation_id text not null unique,
    device_name text,
    token_hash text not null,
    created_at timestamptz not null default now(),
    last_seen_at timestamptz
);

create table if not exists conversations (
    id uuid primary key default gen_random_uuid(),
    device_id uuid not null references devices(id) on delete cascade,
    title text not null default 'Percakapan baru',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists messages (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references conversations(id) on delete cascade,
    client_message_id text not null unique,
    role text not null check (role in ('user', 'assistant', 'system')),
    content text not null,
    output_mode text not null check (output_mode in ('voice', 'text')),
    ai_mode text not null check (ai_mode in ('online', 'offline')),
    provider text not null,
    model text,
    status text not null default 'completed' check (status in ('queued', 'processing', 'completed', 'failed')),
    created_at timestamptz not null default now(),
    synced_at timestamptz
);

create table if not exists sync_events (
    id uuid primary key default gen_random_uuid(),
    device_id uuid not null references devices(id) on delete cascade,
    client_message_id text not null unique,
    event_type text not null,
    created_at timestamptz not null default now()
);

create index if not exists conversations_device_idx on conversations(device_id, updated_at desc);
create index if not exists messages_conversation_idx on messages(conversation_id, created_at);
create index if not exists messages_created_idx on messages(created_at);
create index if not exists devices_installation_idx on devices(installation_id);
