"""Online AI provider — tries a fallback CHAIN of AI APIs.

Fixed order: Gemini (native Google Search grounding, genuinely free) ->
OpenRouter -> Z.ai -> NVIDIA (OpenAI-compatible). Any provider without an
API key configured (see config.py) is skipped entirely. If a configured
provider errors out (timeout, 401, 429, 5xx, empty response), the next
one in the chain is tried automatically. The whole chat() call only
raises AIProviderError once every configured provider has failed.

Four layers of defense against "reasoning leakage":
  1. Explicitly disable/exclude reasoning via each API's documented
     parameter (OpenRouter's `reasoning`, Gemini's `thinkingConfig`).
  2. Strip <think>...</think> blocks from the text, INCLUDING an
     unclosed opening tag (response cut off mid-thought).
  3. Detect PLAIN-TEXT reasoning leaks (no tags at all) — e.g. a response
     that starts with "Here's a thinking process: 1. Analyze User Input..."
     Common with free/small models that ignore the API-level "no reasoning"
     flags. We try to salvage the final answer (after a "Determine Response:"
     / "Final answer:" marker, or the last quoted draft of the reply); if the
     reasoning was cut off before any answer was produced (typical in voice
     mode, where max_tokens is small), the whole response is discarded and
     treated as a failure so the NEXT provider in the chain gets tried.
  4. NO_REASONING_SUFFIX is appended to every system message before the
     request, explicitly forbidding visible chain-of-thought.
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


# ---------------------------------------------------------------------------
# Layer 4: appended to every system message so the model outputs only the
# final answer. Small models sometimes ignore this, hence layers 1-3 below.
# ---------------------------------------------------------------------------
NO_REASONING_SUFFIX = (
    "\n\nOUTPUT DISIPLIN — SANGAT PENTING: outputmu dibacakan/ditampilkan apa "
    "adanya. Keluarkan LANGSUNG jawaban final mulai dari kalimat pertama. "
    "DILARANG KERAS menampilkan proses berpikir, analisis, atau perencanaan "
    "dalam bentuk apa pun — termasuk frasa seperti \"Here's a thinking "
    "process\", \"Analyze User Input\", \"Identify Persona/Constraints\", "
    "\"Determine Response\", \"Let me think\", penomoran langkah internal, "
    "atau pembahasan soal bahasa/format yang akan dipakai. Jangan menulis "
    "jawabanmu di dalam tanda kutip; tulis langsung sebagai kalimat normal. "
    "Tidak ada paragraf pembuka atau penjelasan meta — jawaban saja."
)

# Layer 3a: how a plain-text reasoning leak typically BEGINS. Matched only at
# the very start of the response, so legitimate answers are never touched.
_REASONING_PREAMBLE_RE = re.compile(
    r"""^\s*
    (?:
        here'?s\s+(?:a|my|the)?\s*(?:thinking|thought)\s*process
      | (?:my|the)\s+(?:thinking|thought)\s*process
      | thinking\s*process\s*:
      | chain[\s\-]*of[\s\-]*thought\s*:
      | let'?s\s+think
      | first,?\s+(?:i|we|let'?s)\b
      | okay,?\s+(?:so\s+)?(?:the\s+user|let'?s|i\b)
      | \d+\.\s+(?:analyze|identify|determine|understand)\b
      | reasoning\s*:
    )
    \s*""",
    re.IGNORECASE | re.VERBOSE,
)

# Layer 3b: markers that usually precede the actual final answer inside a
# leaked chain-of-thought.
_FINAL_ANSWER_MARKER_RE = re.compile(
    r"(?:^|\n)[ \t]*(?:\d+[.)]\s*)?"
    r"(?:final\s+answer|determine\s+(?:the\s+)?response|answer|response|"
    r"jawaban(?:\s+akhir)?|respon)\s*:\s*",
    re.IGNORECASE,
)

_LIST_LINE_RE = re.compile(r"^[ \t]*(?:\d+[.)]|[-*\u2022])\s+", re.MULTILINE)

# Phrases that mean a paragraph is still meta-commentary ABOUT the answer,
# not the answer itself.
_META_HINTS = (
    "analyze", "identify", "determine", "constraint", "persona", "user input",
    "user said", "user wrote", "response should", "should be", "respond with",
    "something like", "i'll respond", "i will respond", "i'll say",
    "language:", "tone:", "format:", "stt",
    "analisis", "langkah", "pengguna", "harus dijawab", "perlu dijawab",
    "jawabanmu", "jawabannya",
)

_TERMINATORS = (".", "!", "?", "\u2026", '"', "\u201d", "'", ")", "\uff01", "\uff1f", "\u3002")


def _salvage_final_answer(body: str) -> str:
    """Try to pull the usable final answer out of a leaked chain-of-thought.
    Returns "" when the reasoning was cut off before an answer was produced
    (the common case in voice mode), so the caller treats the response as
    failed and falls back to the next provider instead of reading the
    reasoning trace aloud to the user.
    """
    # A response cut off mid-reasoning has no usable answer at all.
    if not body.rstrip().endswith(_TERMINATORS):
        return ""

    # Cut at the LAST explicit "final answer"-style marker, if any.
    markers = list(_FINAL_ANSWER_MARKER_RE.finditer(body))
    tail = body[markers[-1].end():] if markers else body

    # Drop internal numbered/bulleted planning lines.
    tail = _LIST_LINE_RE.sub("", tail)

    # Models often draft the actual spoken reply inside quotes — prefer the
    # last quoted span.
    quotes = re.findall(r'"([^"\n]{2,400})"', tail)
    quotes = quotes or re.findall("\u201c([^\u201d\n]{2,400})\u201d", tail)
    if quotes:
        candidate = quotes[-1].strip()
        if candidate:
            return candidate

    # Otherwise accept the last paragraph only if it reads like a real
    # answer, not more meta-commentary about the answer.
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", tail) if p.strip()]
    if not paragraphs:
        return ""
    candidate = paragraphs[-1]
    lowered = candidate.lower()
    if any(hint in lowered for hint in _META_HINTS):
        return ""
    return candidate


def strip_reasoning_tags(text: str) -> str:
    """Remove reasoning blocks from a model response.

    Handles three shapes:
      1. <think>...</think> (and an unclosed <think> — response truncated
         mid-thought, so there is no usable answer left at all).
      2. Plain-text chain-of-thought starting the response (e.g.
         "Here's a thinking process: 1. Analyze User Input: ..."). We try to
         salvage the final answer; if none was produced, return "" so the
         caller treats it as a failed response and falls back.
      3. Otherwise return the text untouched.
    """
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    if "<think>" in text:
        text = text.split("<think>", 1)[0]

    preamble = _REASONING_PREAMBLE_RE.match(text)
    if preamble:
        salvaged = _salvage_final_answer(text[preamble.end():])
        if salvaged:
            log.info("Reasoning leak terdeteksi — jawaban final berhasil diselamatkan.")
            return salvaged.strip()
        log.info("Reasoning leak terdeteksi tanpa jawaban final (kemungkinan terpotong) — respons dibuang.")
        return ""

    return text.strip()


def _harden_system_prompts(messages: list[dict]) -> list[dict]:
    """Append NO_REASONING_SUFFIX to every system message (layer 4)."""
    return [
        {**m, "content": m["content"] + NO_REASONING_SUFFIX} if m.get("role") == "system" else m
        for m in messages
    ]


async def _call_openai_compatible(*, name: str, base_url: str, api_key: str, model: str,
                                   messages: list[dict], output_mode: str) -> AIResult:
    max_tokens = 280 if output_mode == "voice" else 1800
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.5,
        "reasoning": {"enabled": False},
    }
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
        choice = data["choices"][0]
        text = choice.get("message", {}).get("content") or ""
        finish_reason = choice.get("finish_reason")
    except (KeyError, IndexError) as exc:
        raise AIProviderError(f"[{name}] format respons tidak sesuai dugaan.") from exc

    if finish_reason == "length":
        log.warning("[%s] respons terpotong (finish_reason=length) — token habis, "
                    "kemungkinan saat model masih menulis reasoning.", name)

    text = strip_reasoning_tags(text)
    if not text:
        raise AIProviderError(f"[{name}] jawaban kosong/hanya berisi reasoning "
                              "(kemungkinan terpotong saat masih 'berpikir').")

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
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.5,
            "thinkingConfig": {"thinkingBudget": 0},
        },
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

    if resp.status_code == 401 or resp.status_code == 403:
        raise AIProviderError(f"[gemini] API key ditolak ({resp.status_code}) — periksa kembali key-nya.")
    if resp.status_code == 429:
        raise AIProviderError("[gemini] rate limit / kuota gratis harian tercapai (429).")
    if resp.status_code >= 400:
        raise AIProviderError(f"[gemini] error {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    try:
        candidate = data["candidates"][0]
        parts = candidate["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        finish_reason = candidate.get("finishReason")
    except (KeyError, IndexError) as exc:
        raise AIProviderError("[gemini] format respons tidak sesuai dugaan.") from exc

    if finish_reason == "MAX_TOKENS":
        log.warning("[gemini] respons terpotong (finishReason=MAX_TOKENS) — "
                    "kemungkinan token habis saat model masih menulis reasoning.")

    text = strip_reasoning_tags(text)
    if not text:
        raise AIProviderError("[gemini] jawaban kosong/hanya berisi reasoning "
                              "(kemungkinan terpotong saat masih 'berpikir').")

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

        messages = _harden_system_prompts(messages)

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
