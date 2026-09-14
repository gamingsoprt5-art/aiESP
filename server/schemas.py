from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---- devices ----
class DeviceRegisterRequest(BaseModel):
    installation_id: str = Field(..., min_length=8, max_length=128)
    device_name: Optional[str] = Field(default=None, max_length=80)


class DeviceRegisterResponse(BaseModel):
    device_id: str
    device_token: str
    already_registered: bool


class DeviceRotateTokenResponse(BaseModel):
    device_id: str
    device_token: str


# ---- conversations ----
class ConversationCreateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=120)


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


# ---- messages / chat ----
class HistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=4000)


class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    client_message_id: str = Field(..., min_length=8, max_length=128)
    text: str = Field(..., min_length=1, max_length=4000)
    output_mode: Literal["voice", "text"] = "voice"
    ai_mode: Literal["online", "offline", "auto"] = "online"
    history: list[HistoryItem] = Field(default_factory=list, max_length=20)


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    client_message_id: str
    role: str
    content: str
    output_mode: str
    ai_mode: str
    provider: str
    model: Optional[str]
    status: str
    created_at: datetime


class ChatResponse(BaseModel):
    conversation_id: str
    user_message: MessageOut
    assistant_message: MessageOut


# ---- sync ----
class SyncPushItem(BaseModel):
    client_message_id: str
    conversation_id: str
    conversation_title: Optional[str] = None
    role: Literal["user", "assistant"]
    content: str
    output_mode: Literal["voice", "text"]
    ai_mode: Literal["online", "offline"]
    provider: str = "offline"
    model: Optional[str] = None
    created_at: Optional[datetime] = None


class SyncPushRequest(BaseModel):
    items: list[SyncPushItem] = Field(default_factory=list, max_length=200)


class SyncPushResult(BaseModel):
    client_message_id: str
    status: Literal["created", "duplicate", "error"]
    detail: Optional[str] = None


class SyncPushResponse(BaseModel):
    results: list[SyncPushResult]
    synced_count: int
    duplicate_count: int
    error_count: int


class SyncPullResponse(BaseModel):
    messages: list[MessageOut]
    server_time: datetime


# ---- misc ----
class LocalAIStatusResponse(BaseModel):
    available: bool
    base_url: str
    configured_model: str
    model_ready: bool
    installed_models: list[str]


class HealthResponse(BaseModel):
    status: str
    mode: Literal["postgres", "demo"]
    warnings: list[str]
