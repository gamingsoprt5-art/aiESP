"""Routes a chat request to the right AI provider and shapes the prompt.

Two independent axes:
  - output_mode: "voice" (short, spoken-style answers for the glasses'
    speaker) vs "text" (fuller answers for the on-screen/phone view).
  - ai_mode: "online" (cloud LLM) vs "offline" (local Ollama). The
    client tells us which one it wants per-request, since only the
    client reliably knows its own connectivity; "auto" lets the server
    try online first and gracefully fall back to offline.
"""
from __future__ import annotations

import logging

from .local_ai import LocalAIProvider
from .models import AIResult
from .online_ai import AIProviderError, OnlineAIProvider

log = logging.getLogger("smart-glasses.ai_router")

_online = OnlineAIProvider()
_offline = LocalAIProvider()

VOICE_SYSTEM_PROMPT = (
    "Anda adalah asisten suara pada kacamata pintar. Jawab singkat, jelas, dan "
    "langsung ke inti — maksimal 2-3 kalimat pendek, karena jawaban ini akan "
    "dibacakan lewat text-to-speech. Hindari daftar bernomor, tabel, blok kode, "
    "atau format markdown apa pun. Jawab dalam bahasa yang sama dengan pertanyaan "
    "pengguna."
)

TEXT_SYSTEM_PROMPT = (
    "Anda adalah asisten AI pada aplikasi pendamping kacamata pintar. Jawab dengan "
    "jelas dan terstruktur; boleh memakai daftar atau paragraf pendek bila membantu "
    "pemahaman. Jawab dalam bahasa yang sama dengan pertanyaan pengguna."
)


def build_messages(history: list[dict], user_text: str, output_mode: str) -> list[dict]:
    system_prompt = VOICE_SYSTEM_PROMPT if output_mode == "voice" else TEXT_SYSTEM_PROMPT
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_text})
    return messages


async def route_chat(*, history: list[dict], user_text: str, output_mode: str, ai_mode: str) -> AIResult:
    messages = build_messages(history, user_text, output_mode)

    if ai_mode == "online":
        return await _online.chat(messages, output_mode)

    if ai_mode == "offline":
        return await _offline.chat(messages, output_mode)

    if ai_mode == "auto":
        try:
            return await _online.chat(messages, output_mode)
        except AIProviderError as online_err:
            log.warning("Online AI gagal, mencoba fallback offline: %s", online_err)
            try:
                return await _offline.chat(messages, output_mode)
            except AIProviderError as offline_err:
                raise AIProviderError(
                    f"Online gagal ({online_err}) dan offline juga gagal ({offline_err})."
                ) from offline_err

    raise AIProviderError(f"ai_mode tidak dikenali: {ai_mode!r} (gunakan 'online', 'offline', atau 'auto').")
