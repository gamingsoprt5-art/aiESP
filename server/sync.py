"""Push/pull sync so messages created while offline reach the server
(and other devices, in principle) once connectivity returns.

Idempotency is the whole point here: a flaky connection may cause the
client to retry a push, so every message is keyed by a client-generated
`client_message_id`. Re-sending the same id is always safe — it never
creates a duplicate row.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .models import Device
from .repositories import Repository
from .schemas import SyncPushItem, SyncPushResult


async def push_batch(repo: Repository, device: Device, items: list[SyncPushItem]) -> list[SyncPushResult]:
    results: list[SyncPushResult] = []

    for item in items:
        try:
            already_existed = await repo.get_message_by_client_id(item.client_message_id) is not None

            await repo.ensure_conversation(
                item.conversation_id, device.id, item.conversation_title or "Percakapan (offline)"
            )
            await repo.create_message(
                conversation_id=item.conversation_id,
                client_message_id=item.client_message_id,
                role=item.role,
                content=item.content,
                output_mode=item.output_mode,
                ai_mode=item.ai_mode,
                provider=item.provider,
                model=item.model,
                status="completed",
            )
            await repo.record_sync_event(device.id, item.client_message_id, "push")

            results.append(SyncPushResult(
                client_message_id=item.client_message_id,
                status="duplicate" if already_existed else "created",
            ))
        except Exception as exc:  # noqa: BLE001 — one bad item must not abort the whole batch
            results.append(SyncPushResult(
                client_message_id=item.client_message_id, status="error", detail=str(exc)
            ))

    return results


async def pull_since(repo: Repository, device: Device, since: Optional[datetime]):
    return await repo.messages_for_device_since(device.id, since)
