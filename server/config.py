"""
Application configuration.

All secrets and environment-specific values are read from environment
variables (or a local .env file when developing).

Online AI uses a fallback CHAIN across providers, tried in this fixed
order: Gemini -> OpenRouter -> Z.ai -> NVIDIA. Any provider without an
API key configured is skipped; if one provider errors out (timeout,
rate limit, etc.) the next one in the chain is tried automatically
before the whole request is considered failed.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("smart-glasses.config")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Server ---
    port: int = 8000
    cors_origins: str = "*"
    request_timeout_seconds: float = 30.0

    # --- Database (PostgreSQL via Supabase/Neon/etc.) ---
    database_url: str = ""

    # --- Device / auth ---
    device_signing_secret: str = ""
    # PROTOTYPING ONLY: skip device token verification entirely, all clients
    # share one conversation history. Never enable this in production.
    disable_device_auth: bool = False

    # --- Online AI fallback chain: Gemini (free search) -> OpenRouter -> Z.ai -> NVIDIA ---
    # llm_provider is kept for logging/reference of the "preferred" one;
    # the chain always tries all configured providers regardless.
    llm_provider: str = "Gemini"

    # Gemini uses Google's own free tier with real Google Search grounding
    # (genuinely free, no credit card) — tried first in the chain when configured.
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_model: str = "gemini-3.6-flash"

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "z-ai/glm-5.2:free"

    zai_api_key: str = ""
    zai_base_url: str = "https://api.z.ai/api/paas/v4/"
    zai_model: str = "glm-4.5-flash"

    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "nvidia/nemotron-3.5-lightning-30b-a3b"

    # --- Local AI (Ollama, via a companion gateway reachable from the browser) ---
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2:3b"

    # --- Limits ---
    rate_limit: str = "20/minute"
    max_prompt_chars: int = 4000
    max_history_messages: int = 20
    max_request_bytes: int = 200_000

    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def online_provider_chain(self) -> list[dict]:
        """Ordered list of configured online providers, skipping unset ones.

        Gemini goes first (native Google Search grounding, genuinely free);
        the rest are OpenAI-compatible providers as before.
        """
        candidates = [
            {"kind": "gemini", "name": "gemini", "base_url": self.gemini_base_url,
             "api_key": self.gemini_api_key, "model": self.gemini_model},
            {"kind": "openai", "name": "openrouter", "base_url": self.openrouter_base_url,
             "api_key": self.openrouter_api_key, "model": self.openrouter_model},
            {"kind": "openai", "name": "zai", "base_url": self.zai_base_url,
             "api_key": self.zai_api_key, "model": self.zai_model},
            {"kind": "openai", "name": "nvidia", "base_url": self.nvidia_base_url,
             "api_key": self.nvidia_api_key, "model": self.nvidia_model},
        ]
        return [c for c in candidates if c["api_key"]]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def validate_startup_config() -> list[str]:
    """Return a list of human-readable warnings about the current config.

    This never raises — the app is allowed to start in a degraded "demo"
    mode — but it must be loud about it, per the project's requirement
    that history is never silently lost.
    """
    warnings: list[str] = []

    if not settings.database_url:
        warnings.append(
            "DATABASE_URL belum diatur — server berjalan dalam MODE DEMO "
            "(riwayat percakapan hanya disimpan di memori proses dan akan "
            "HILANG saat server di-restart). Atur DATABASE_URL ke PostgreSQL "
            "(Supabase/Neon) untuk penyimpanan permanen."
        )

    if settings.disable_device_auth:
        warnings.append(
            "DISABLE_DEVICE_AUTH=true — autentikasi token perangkat DIMATIKAN. "
            "Semua klien berbagi satu riwayat percakapan yang sama, tanpa isolasi "
            "per-perangkat. Hanya untuk prototyping — JANGAN dipakai di produksi."
        )

    if not settings.device_signing_secret:
        warnings.append(
            "DEVICE_SIGNING_SECRET belum diatur — token perangkat akan di-hash "
            "dengan kunci sementara yang berubah setiap restart server, artinya "
            "SEMUA token perangkat lama menjadi tidak valid setelah restart. "
            "Atur DEVICE_SIGNING_SECRET agar konsisten antar-restart."
        )

    if not settings.online_provider_chain():
        warnings.append(
            "Tidak ada provider AI online yang dikonfigurasi (GEMINI_API_KEY / "
            "OPENROUTER_API_KEY / ZAI_API_KEY / NVIDIA_API_KEY semuanya kosong) — "
            "permintaan chat mode online akan gagal sampai minimal satu key diisi."
        )

    for w in warnings:
        log.warning(w)

    return warnings
