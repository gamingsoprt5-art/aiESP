"""Online AI provider — tries a fallback CHAIN of OpenAI-compatible APIs.

Fixed order: OpenRouter -> Z.ai -> NVIDIA. Any provider without an API
key configured (see config.py) is skipped entirely. If a configured
provider errors out (timeout, 401, 429, 5xx, empty response), the next
one in the chain is tried automatically. The whole chat() call only
raises AIProviderError once every configured provider has failed.
"""
from __future__ import annotations

import logging
import re

import httpx

from .config import settings
from .models import AIResult

log = logging.getLogger("smart-glasses.online_ai")


class AIProviderError(RuntimeError):
    """Raised when an AI provider (or the whole chain) cannot produce a response."""


def strip_reasoning_tags(text: str) -> str:
    """Remove <think>...</think> style reasoning blocks some models emit."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


async def _call_openai_compatible(*, name: str, base_url: str, api_key: str, model: str,
                                   messages: list[dict], output_mode: str) -> AIResult:
    max_tokens = 220 if output_mode == "voice" else 900
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.6}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise AIProviderError(f"[{name}] timeout — server AI tidak merespons.") from exc
    except httpx.RequestError as exc:
        raise AIProviderError(f"[{name}] tidak bisa dihubungi: {exc}") from exc

    if resp.status_code == 401:
        raise AIProviderError(f"[{name}] API key ditolak (401) — periksa kembali key-nya.")
    if resp.status_code == 429:
        raise AIProviderError(f"[{name}] rate limit tercapai (429).")
    if resp.status_code >= 400:
        raise AIProviderError(f"[{name}] error {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError) as exc:
        raise AIProviderError(f"[{name}] format respons tidak sesuai dugaan.") from exc

    text = strip_reasoning_tags(text)
    if not text:
        raise AIProviderError(f"[{name}] mengembalikan jawaban kosong.")

    return AIResult(text=text, provider=f"online:{name}", model=model, ai_mode="online")


class OnlineAIProvider:
    name = "online"

    async def chat(self, messages: list[dict], output_mode: str) -> AIResult:
        chain = settings.online_provider_chain()
        if not chain:
            raise AIProviderError(
                "Tidak ada provider AI online yang dikonfigurasi "
                "(OPENROUTER_API_KEY / ZAI_API_KEY / NVIDIA_API_KEY semuanya kosong)."
            )

        errors: list[str] = []
        for provider in chain:
            try:
                return await _call_openai_compatible(
                    name=provider["name"], base_url=provider["base_url"],
                    api_key=provider["api_key"], model=provider["model"],
                    messages=messages, output_mode=output_mode,
                )
            except AIProviderError as exc:
                log.warning("Provider online gagal, mencoba berikutnya: %s", exc)
                errors.append(str(exc))
                continue

        raise AIProviderError("Semua provider AI online gagal — " + " | ".join(errors))
