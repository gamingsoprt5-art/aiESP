from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from . import ai_router, device_auth, sync
from .config import settings, validate_startup_config
from .database import close_repository, get_repository, init_repository
from .local_ai import check_local_ai_status
from .models import Device, Message
from .online_ai import AIProviderError
from .schemas import (
    ChatRequest,
    ChatResponse,
    ConversationCreateRequest,
    ConversationOut,
    DeviceRegisterRequest,
    DeviceRegisterResponse,
    DeviceRotateTokenResponse,
    HealthResponse,
    LocalAIStatusResponse,
    MessageOut,
    SyncPullResponse,
    SyncPushRequest,
    SyncPushResponse,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("smart-glasses.main")

limiter = Limiter(key_func=get_remote_address)
_startup_warnings: list[str] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _startup_warnings
    _startup_warnings = validate_startup_config()
    await init_repository()
    log.info("Server siap di port %s", settings.port)
    yield
    await close_repository()


app = FastAPI(title="AI Smart Glasses API", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _msg_out(m: Message) -> MessageOut:
    return MessageOut(
        id=m.id, conversation_id=m.conversation_id, client_message_id=m.client_message_id,
        role=m.role, content=m.content, output_mode=m.output_mode, ai_mode=m.ai_mode,
        provider=m.provider, model=m.model, status=m.status, created_at=m.created_at,
    )


# =========================================================================
# Health
# =========================================================================
@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        mode="postgres" if settings.database_url else "demo",
        warnings=_startup_warnings,
    )


# =========================================================================
# Devices (anonymous identity)
# =========================================================================
@app.post("/api/devices/register", response_model=DeviceRegisterResponse)
@limiter.limit("10/minute")
async def register_device(request: Request, body: DeviceRegisterRequest):
    repo = get_repository()
    existing = await repo.get_device_by_installation_id(body.installation_id)
    if existing:
        # Re-registration (e.g. app reinstalled config restored) issues a fresh token.
        token = device_auth.generate_device_token()
        await repo.rotate_device_token(existing.id, device_auth.hash_token(token))
        return DeviceRegisterResponse(device_id=existing.id, device_token=token, already_registered=True)

    token = device_auth.generate_device_token()
    device = await repo.create_device(body.installation_id, body.device_name, device_auth.hash_token(token))
    return DeviceRegisterResponse(device_id=device.id, device_token=token, already_registered=False)


@app.post("/api/devices/rotate-token", response_model=DeviceRotateTokenResponse)
async def rotate_token(device: Device = Depends(device_auth.get_current_device)):
    repo = get_repository()
    new_token = device_auth.generate_device_token()
    await repo.rotate_device_token(device.id, device_auth.hash_token(new_token))
    return DeviceRotateTokenResponse(device_id=device.id, device_token=new_token)


# =========================================================================
# Conversations
# =========================================================================
@app.post("/api/conversations", response_model=ConversationOut)
async def create_conversation(body: ConversationCreateRequest, device: Device = Depends(device_auth.get_current_device)):
    repo = get_repository()
    conv = await repo.create_conversation(device.id, body.title or "Percakapan baru")
    return ConversationOut(id=conv.id, title=conv.title, created_at=conv.created_at, updated_at=conv.updated_at)


@app.get("/api/conversations", response_model=list[ConversationOut])
async def list_conversations(device: Device = Depends(device_auth.get_current_device)):
    repo = get_repository()
    convs = await repo.list_conversations(device.id)
    return [ConversationOut(id=c.id, title=c.title, created_at=c.created_at, updated_at=c.updated_at) for c in convs]


@app.get("/api/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def get_messages(conversation_id: str, device: Device = Depends(device_auth.get_current_device)):
    repo = get_repository()
    conv = await repo.get_conversation(conversation_id, device.id)
    if conv is None:
        raise HTTPException(404, "Percakapan tidak ditemukan.")
    msgs = await repo.list_messages(conversation_id)
    return [_msg_out(m) for m in msgs]


# =========================================================================
# Chat (online-first, real-time)
# =========================================================================
@app.post("/api/chat", response_model=ChatResponse)
@limiter.limit(settings.rate_limit)
async def chat(request: Request, body: ChatRequest, device: Device = Depends(device_auth.get_current_device)):
    repo = get_repository()

    if body.conversation_id:
        conv = await repo.get_conversation(body.conversation_id, device.id)
        if conv is None:
            # The client (offline-first frontend) generates its own conversation
            # id locally before this conversation has ever reached the server —
            # treat it as authoritative and create it now instead of 404ing.
            conv = await repo.ensure_conversation(body.conversation_id, device.id, body.text[:60])
            if conv.device_id != device.id:
                raise HTTPException(403, "Percakapan ini milik perangkat lain.")
    else:
        conv = await repo.create_conversation(device.id, body.text[:60])

    history = [{"role": h.role, "content": h.content} for h in body.history[-settings.max_history_messages:]]

    user_msg = await repo.create_message(
        conversation_id=conv.id, client_message_id=body.client_message_id, role="user",
        content=body.text, output_mode=body.output_mode, ai_mode=body.ai_mode,
        provider="client", model=None, status="completed",
    )

    try:
        result = await ai_router.route_chat(
            history=history, user_text=body.text, output_mode=body.output_mode, ai_mode=body.ai_mode
        )
    except AIProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    assistant_msg = await repo.create_message(
        conversation_id=conv.id, client_message_id=body.client_message_id + ":assistant", role="assistant",
        content=result.text, output_mode=body.output_mode, ai_mode=result.ai_mode,
        provider=result.provider, model=result.model, status="completed",
    )

    return ChatResponse(conversation_id=conv.id, user_message=_msg_out(user_msg), assistant_message=_msg_out(assistant_msg))


# =========================================================================
# Sync (offline-first catch-up)
# =========================================================================
@app.post("/api/sync/push", response_model=SyncPushResponse)
async def sync_push(body: SyncPushRequest, device: Device = Depends(device_auth.get_current_device)):
    repo = get_repository()
    results = await sync.push_batch(repo, device, body.items)
    return SyncPushResponse(
        results=results,
        synced_count=sum(1 for r in results if r.status == "created"),
        duplicate_count=sum(1 for r in results if r.status == "duplicate"),
        error_count=sum(1 for r in results if r.status == "error"),
    )


@app.get("/api/sync/pull", response_model=SyncPullResponse)
async def sync_pull(since: Optional[datetime] = None, device: Device = Depends(device_auth.get_current_device)):
    repo = get_repository()
    msgs = await sync.pull_since(repo, device, since)
    return SyncPullResponse(messages=[_msg_out(m) for m in msgs], server_time=datetime.now(timezone.utc))


# =========================================================================
# Local AI status (for the frontend's online/offline badge)
# =========================================================================
@app.get("/api/local-ai/status", response_model=LocalAIStatusResponse)
async def local_ai_status():
    return LocalAIStatusResponse(**await check_local_ai_status())


# =========================================================================
# Static frontend (PWA)
# =========================================================================
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
