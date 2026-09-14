"""Data access layer.

`Repository` is the interface the rest of the app depends on. Two
implementations exist:

- `PostgresRepository` — real persistence via asyncpg, used whenever
  DATABASE_URL is configured.
- `InMemoryRepository` — process-memory dict store, used as the demo-mode
  fallback and in the test suite (so tests don't need a live database).

Keeping both behind the same interface means main.py, ai_router.py, and
sync.py never need to know which one is active.
"""
from __future__ import annotations

import abc
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional, Protocol

from .models import Conversation, Device, Message, SyncEvent


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class Repository(Protocol):
    async def create_device(self, installation_id: str, device_name: Optional[str], token_hash: str) -> Device: ...
    async def get_device_by_installation_id(self, installation_id: str) -> Optional[Device]: ...
    async def get_device_by_token_hash(self, token_hash: str) -> Optional[Device]: ...
    async def get_device_by_id(self, device_id: str) -> Optional[Device]: ...
    async def update_device_last_seen(self, device_id: str) -> None: ...
    async def rotate_device_token(self, device_id: str, new_token_hash: str) -> Device: ...

    async def create_conversation(self, device_id: str, title: str) -> Conversation: ...
    async def list_conversations(self, device_id: str, limit: int = 50, offset: int = 0) -> list[Conversation]: ...
    async def get_conversation(self, conversation_id: str, device_id: str) -> Optional[Conversation]: ...
    async def touch_conversation(self, conversation_id: str) -> None: ...
    async def ensure_conversation(self, conversation_id: str, device_id: str, title: str) -> Conversation: ...

    async def create_message(self, *, conversation_id: str, client_message_id: str, role: str,
                              content: str, output_mode: str, ai_mode: str, provider: str,
                              model: Optional[str], status: str = "completed") -> Message: ...
    async def get_message_by_client_id(self, client_message_id: str) -> Optional[Message]: ...
    async def list_messages(self, conversation_id: str, limit: int = 100) -> list[Message]: ...
    async def messages_for_device_since(self, device_id: str, since: Optional[datetime]) -> list[Message]: ...

    async def record_sync_event(self, device_id: str, client_message_id: str, event_type: str) -> SyncEvent: ...
    async def has_sync_event(self, client_message_id: str) -> bool: ...


# =========================================================================
# In-memory implementation (demo mode + tests)
# =========================================================================
class InMemoryRepository:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.devices: dict[str, Device] = {}
        self.conversations: dict[str, Conversation] = {}
        self.messages: dict[str, Message] = {}
        self.sync_events: dict[str, SyncEvent] = {}

    # ---- devices ----
    async def create_device(self, installation_id, device_name, token_hash) -> Device:
        async with self._lock:
            d = Device(id=_new_id(), installation_id=installation_id, device_name=device_name,
                       token_hash=token_hash, created_at=_now())
            self.devices[d.id] = d
            return d

    async def get_device_by_installation_id(self, installation_id: str) -> Optional[Device]:
        return next((d for d in self.devices.values() if d.installation_id == installation_id), None)

    async def get_device_by_token_hash(self, token_hash: str) -> Optional[Device]:
        return next((d for d in self.devices.values() if d.token_hash == token_hash), None)

    async def get_device_by_id(self, device_id: str) -> Optional[Device]:
        return self.devices.get(device_id)

    async def update_device_last_seen(self, device_id: str) -> None:
        d = self.devices.get(device_id)
        if d:
            d.last_seen_at = _now()

    async def rotate_device_token(self, device_id: str, new_token_hash: str) -> Device:
        d = self.devices[device_id]
        d.token_hash = new_token_hash
        return d

    # ---- conversations ----
    async def create_conversation(self, device_id: str, title: str) -> Conversation:
        c = Conversation(id=_new_id(), device_id=device_id, title=title, created_at=_now(), updated_at=_now())
        self.conversations[c.id] = c
        return c

    async def list_conversations(self, device_id: str, limit: int = 50, offset: int = 0) -> list[Conversation]:
        items = [c for c in self.conversations.values() if c.device_id == device_id]
        items.sort(key=lambda c: c.updated_at, reverse=True)
        return items[offset:offset + limit]

    async def get_conversation(self, conversation_id: str, device_id: str) -> Optional[Conversation]:
        c = self.conversations.get(conversation_id)
        return c if c and c.device_id == device_id else None

    async def touch_conversation(self, conversation_id: str) -> None:
        c = self.conversations.get(conversation_id)
        if c:
            c.updated_at = _now()

    async def ensure_conversation(self, conversation_id: str, device_id: str, title: str) -> Conversation:
        existing = self.conversations.get(conversation_id)
        if existing:
            return existing
        c = Conversation(id=conversation_id, device_id=device_id, title=title, created_at=_now(), updated_at=_now())
        self.conversations[c.id] = c
        return c

    # ---- messages ----
    async def create_message(self, *, conversation_id, client_message_id, role, content, output_mode,
                              ai_mode, provider, model, status="completed") -> Message:
        existing = await self.get_message_by_client_id(client_message_id)
        if existing:
            return existing
        m = Message(id=_new_id(), conversation_id=conversation_id, client_message_id=client_message_id,
                    role=role, content=content, output_mode=output_mode, ai_mode=ai_mode, provider=provider,
                    model=model, status=status, created_at=_now())
        self.messages[m.id] = m
        await self.touch_conversation(conversation_id)
        return m

    async def get_message_by_client_id(self, client_message_id: str) -> Optional[Message]:
        return next((m for m in self.messages.values() if m.client_message_id == client_message_id), None)

    async def list_messages(self, conversation_id: str, limit: int = 100) -> list[Message]:
        items = [m for m in self.messages.values() if m.conversation_id == conversation_id]
        items.sort(key=lambda m: m.created_at)
        return items[-limit:]

    async def messages_for_device_since(self, device_id: str, since: Optional[datetime]) -> list[Message]:
        conv_ids = {c.id for c in self.conversations.values() if c.device_id == device_id}
        items = [m for m in self.messages.values() if m.conversation_id in conv_ids
                 and (since is None or m.created_at > since)]
        items.sort(key=lambda m: m.created_at)
        return items

    # ---- sync events ----
    async def record_sync_event(self, device_id: str, client_message_id: str, event_type: str) -> SyncEvent:
        e = SyncEvent(id=_new_id(), device_id=device_id, client_message_id=client_message_id,
                      event_type=event_type, created_at=_now())
        self.sync_events[e.id] = e
        return e

    async def has_sync_event(self, client_message_id: str) -> bool:
        return any(e.client_message_id == client_message_id for e in self.sync_events.values())


# =========================================================================
# PostgreSQL implementation
# =========================================================================
class PostgresRepository:
    def __init__(self, pool) -> None:
        self.pool = pool

    @staticmethod
    def _row_to_device(r) -> Device:
        return Device(id=str(r["id"]), installation_id=r["installation_id"], device_name=r["device_name"],
                      token_hash=r["token_hash"], created_at=r["created_at"], last_seen_at=r["last_seen_at"])

    @staticmethod
    def _row_to_conversation(r) -> Conversation:
        return Conversation(id=str(r["id"]), device_id=str(r["device_id"]), title=r["title"],
                            created_at=r["created_at"], updated_at=r["updated_at"])

    @staticmethod
    def _row_to_message(r) -> Message:
        return Message(id=str(r["id"]), conversation_id=str(r["conversation_id"]),
                       client_message_id=r["client_message_id"], role=r["role"], content=r["content"],
                       output_mode=r["output_mode"], ai_mode=r["ai_mode"], provider=r["provider"],
                       model=r["model"], status=r["status"], created_at=r["created_at"],
                       synced_at=r["synced_at"])

    # ---- devices ----
    async def create_device(self, installation_id, device_name, token_hash) -> Device:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """insert into devices (installation_id, device_name, token_hash)
                   values ($1, $2, $3) returning *""",
                installation_id, device_name, token_hash,
            )
            return self._row_to_device(row)

    async def get_device_by_installation_id(self, installation_id: str) -> Optional[Device]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("select * from devices where installation_id = $1", installation_id)
            return self._row_to_device(row) if row else None

    async def get_device_by_token_hash(self, token_hash: str) -> Optional[Device]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("select * from devices where token_hash = $1", token_hash)
            return self._row_to_device(row) if row else None

    async def get_device_by_id(self, device_id: str) -> Optional[Device]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("select * from devices where id = $1", uuid.UUID(device_id))
            return self._row_to_device(row) if row else None

    async def update_device_last_seen(self, device_id: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("update devices set last_seen_at = now() where id = $1", uuid.UUID(device_id))

    async def rotate_device_token(self, device_id: str, new_token_hash: str) -> Device:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "update devices set token_hash = $2 where id = $1 returning *",
                uuid.UUID(device_id), new_token_hash,
            )
            return self._row_to_device(row)

    # ---- conversations ----
    async def create_conversation(self, device_id: str, title: str) -> Conversation:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "insert into conversations (device_id, title) values ($1, $2) returning *",
                uuid.UUID(device_id), title,
            )
            return self._row_to_conversation(row)

    async def list_conversations(self, device_id: str, limit: int = 50, offset: int = 0) -> list[Conversation]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "select * from conversations where device_id = $1 order by updated_at desc limit $2 offset $3",
                uuid.UUID(device_id), limit, offset,
            )
            return [self._row_to_conversation(r) for r in rows]

    async def get_conversation(self, conversation_id: str, device_id: str) -> Optional[Conversation]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "select * from conversations where id = $1 and device_id = $2",
                uuid.UUID(conversation_id), uuid.UUID(device_id),
            )
            return self._row_to_conversation(row) if row else None

    async def touch_conversation(self, conversation_id: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("update conversations set updated_at = now() where id = $1", uuid.UUID(conversation_id))

    async def ensure_conversation(self, conversation_id: str, device_id: str, title: str) -> Conversation:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """insert into conversations (id, device_id, title) values ($1, $2, $3)
                   on conflict (id) do update set id = excluded.id
                   returning *""",
                uuid.UUID(conversation_id), uuid.UUID(device_id), title,
            )
            return self._row_to_conversation(row)

    # ---- messages ----
    async def create_message(self, *, conversation_id, client_message_id, role, content, output_mode,
                              ai_mode, provider, model, status="completed") -> Message:
        existing = await self.get_message_by_client_id(client_message_id)
        if existing:
            return existing
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """insert into messages (conversation_id, client_message_id, role, content, output_mode,
                                          ai_mode, provider, model, status)
                   values ($1,$2,$3,$4,$5,$6,$7,$8,$9) returning *""",
                uuid.UUID(conversation_id), client_message_id, role, content, output_mode, ai_mode,
                provider, model, status,
            )
        await self.touch_conversation(conversation_id)
        return self._row_to_message(row)

    async def get_message_by_client_id(self, client_message_id: str) -> Optional[Message]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("select * from messages where client_message_id = $1", client_message_id)
            return self._row_to_message(row) if row else None

    async def list_messages(self, conversation_id: str, limit: int = 100) -> list[Message]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "select * from messages where conversation_id = $1 order by created_at desc limit $2",
                uuid.UUID(conversation_id), limit,
            )
            return [self._row_to_message(r) for r in reversed(rows)]

    async def messages_for_device_since(self, device_id: str, since: Optional[datetime]) -> list[Message]:
        async with self.pool.acquire() as conn:
            if since is None:
                rows = await conn.fetch(
                    """select m.* from messages m join conversations c on c.id = m.conversation_id
                       where c.device_id = $1 order by m.created_at""",
                    uuid.UUID(device_id),
                )
            else:
                rows = await conn.fetch(
                    """select m.* from messages m join conversations c on c.id = m.conversation_id
                       where c.device_id = $1 and m.created_at > $2 order by m.created_at""",
                    uuid.UUID(device_id), since,
                )
            return [self._row_to_message(r) for r in rows]

    # ---- sync events ----
    async def record_sync_event(self, device_id: str, client_message_id: str, event_type: str) -> SyncEvent:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """insert into sync_events (device_id, client_message_id, event_type)
                   values ($1,$2,$3) on conflict (client_message_id) do update set event_type = excluded.event_type
                   returning *""",
                uuid.UUID(device_id), client_message_id, event_type,
            )
            return SyncEvent(id=str(row["id"]), device_id=str(row["device_id"]),
                             client_message_id=row["client_message_id"], event_type=row["event_type"],
                             created_at=row["created_at"])

    async def has_sync_event(self, client_message_id: str) -> bool:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("select 1 from sync_events where client_message_id = $1", client_message_id)
            return row is not None
