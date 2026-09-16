"""Online AI provider — tries a fallback CHAIN of AI APIs.

Fixed order: Gemini (native Google Search grounding, genuinely free) ->
OpenRouter -> Z.ai -> NVIDIA (OpenAI-compatible). Any provider without an
API key configured (see config.py) is skipped entirely.
"""
from __future__ import annotations

import logging
import re

import httpx

from .config import settings
from .models import AIResult

log = logging.getLogger("smart-glasses.online_ai")


class AIProviderError(RuntimeError):
    pass


def strip_reasoning_tags(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


async def _call_openai_compatible(*, name: str, base_url: str, api_key: str, model: str,
                                   messages: list[dict], output_mode: str) -> AIResult:
    max_tokens = 280 if output_mode == "voice" else 1800
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.5}
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


def _messages_to_gemini_contents(messages: list[dict]) -> tuple[str, list[dict]]:
    system_text = ""
    contents: list[dict] = []
    for m in messages:
        if m["role"] == "system":
            system_text = (system_text + "\n" + m["content"]).strip()
            continue
        role = "model" if m["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})
    return system_text, contents


async def _call_gemini(*, base_url: str, api_key: str, model: str,
                        messages: list[dict], output_mode: str) -> AIResult:
    max_tokens = 280 if output_mode == "voice" else 1800
    system_text, contents = _messages_to_gemini_contents(messages)
    url = f"{base_url.rstrip('/')}/models/{model}:generateContent"

    payload = {
        "contents": contents,
        "tools": [{"google_search": {}}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.5},
    }
    if system_text:
        payload["systemInstruction"] = {"parts": [{"text": system_text}]}

    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}

    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise AIProviderError("[gemini] timeout — server AI tidak merespons.") from exc
    except httpx.RequestError as exc:
        raise AIProviderError(f"[gemini] tidak bisa dihubungi: {exc}") from exc

    if resp.status_code in (401, 403):
        raise AIProviderError(f"[gemini] API key ditolak ({resp.status_code}) — periksa kembali key-nya.")
    if resp.status_code == 429:
        raise AIProviderError("[gemini] rate limit / kuota gratis harian tercapai (429).")
    if resp.status_code >= 400:
        raise AIProviderError(f"[gemini] error {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError) as exc:
        raise AIProviderError("[gemini] format respons tidak sesuai dugaan.") from exc

    text = strip_reasoning_tags(text)
    if not text:
        raise AIProviderError("[gemini] mengembalikan jawaban kosong.")

    return AIResult(text=text, provider="online:gemini", model=model, ai_mode="online")


class OnlineAIProvider:
    name = "online"

    async def chat(self, messages: list[dict], output_mode: str) -> AIResult:
        chain = settings.online_provider_chain()
        if not chain:
            raise AIProviderError(
                "Tidak ada provider AI online yang dikonfigurasi "
                "(GEMINI_API_KEY / OPENROUTER_API_KEY / ZAI_API_KEY / NVIDIA_API_KEY semuanya kosong)."
            )

        errors: list[str] = []
        for provider in chain:
            try:
                if provider["kind"] == "gemini":
                    return await _call_gemini(
                        base_url=provider["base_url"], api_key=provider["api_key"],
                        model=provider["model"], messages=messages, output_mode=output_mode,
                    )
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
