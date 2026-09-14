"""Local/offline AI provider — talks to a local Ollama instance.

Ollama typically runs on the same machine as the browser (127.0.0.1),
so this is normally called from a small local gateway or directly from
the frontend when offline — but the server also exposes it directly for
setups where the server itself has access to Ollama (e.g. a home hub).
"""
from __future__ import annotations

import logging

import httpx

from .config import settings
from .models import AIResult
from .online_ai import AIProviderError, strip_reasoning_tags

log = logging.getLogger("smart-glasses.local_ai")


class LocalAIProvider:
    name = "offline"

    async def chat(self, messages: list[dict], output_mode: str) -> AIResult:
        url = settings.ollama_base_url.rstrip("/") + "/api/chat"
        payload = {
            "model": settings.ollama_model,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": 220 if output_mode == "voice" else 900},
        }
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                resp = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise AIProviderError("AI lokal (Ollama) tidak merespons (timeout).") from exc
        except httpx.RequestError as exc:
            raise AIProviderError(
                f"Tidak bisa menghubungi Ollama di {settings.ollama_base_url}. "
                f"Pastikan Ollama berjalan dan model '{settings.ollama_model}' sudah di-pull. ({exc})"
            ) from exc

        if resp.status_code >= 400:
            raise AIProviderError(f"Ollama mengembalikan error {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        text = strip_reasoning_tags((data.get("message") or {}).get("content", "")).strip()
        if not text:
            raise AIProviderError("AI lokal mengembalikan jawaban kosong.")

        return AIResult(text=text, provider="offline", model=settings.ollama_model, ai_mode="offline")


async def check_local_ai_status() -> dict:
    """Used by GET /api/local-ai/status so the frontend can show a badge."""
    url = settings.ollama_base_url.rstrip("/") + "/api/tags"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url)
        available = resp.status_code == 200
        models = [m.get("name") for m in resp.json().get("models", [])] if available else []
    except Exception:
        available = False
        models = []

    return {
        "available": available,
        "base_url": settings.ollama_base_url,
        "configured_model": settings.ollama_model,
        "model_ready": settings.ollama_model in models if available else False,
        "installed_models": models,
    }
