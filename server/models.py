"""Plain dataclasses representing database rows.

Kept independent of any ORM so the same shapes work whether a row came
from asyncpg (PostgreSQL) or from the in-memory demo-mode store.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

OutputMode = Literal["voice", "text"]
AiMode = Literal["online", "offline"]
MessageRole = Literal["user", "assistant", "system"]
MessageStatus = Literal["queued", "processing", "completed", "failed"]


@dataclass
class Device:
    id: str
    installation_id: str
    device_name: Optional[str]
    token_hash: str
    created_at: datetime
    last_seen_at: Optional[datetime] = None


@dataclass
class Conversation:
    id: str
    device_id: str
    title: str
    created_at: datetime
    updated_at: datetime


@dataclass
class Message:
    id: str
    conversation_id: str
    client_message_id: str
    role: MessageRole
    content: str
    output_mode: OutputMode
    ai_mode: AiMode
    provider: str
    model: Optional[str]
    status: MessageStatus
    created_at: datetime
    synced_at: Optional[datetime] = None


@dataclass
class SyncEvent:
    id: str
    device_id: str
    client_message_id: str
    event_type: str
    created_at: datetime


@dataclass
class AIResult:
    """Result returned by any AIProvider (online or offline)."""
    text: str
    provider: str
    model: Optional[str]
    ai_mode: AiMode
    extra: dict = field(default_factory=dict)
