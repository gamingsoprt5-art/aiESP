# AI Smart Glasses

An AI voice/text assistant for smart glasses — FastAPI backend with a multi-provider AI fallback chain, a PostgreSQL-backed offline-first PWA frontend, and a starting-point ESP32 firmware.

Anonymous per-device authentication, real-time chat, offline sync, and installable web app — no vendor lock-in on the AI provider.

## Features

- **Multi-provider AI fallback chain** — Gemini (free, real Google Search grounding) → OpenRouter → Z.ai → NVIDIA, tried in order; any provider without a key is skipped, and a failing provider automatically falls through to the next one.
- **Offline AI** — falls back to a local [Ollama](https://ollama.com) model when there's no internet connection.
- **Anonymous, per-device auth** — each browser/device gets its own rotatable token; no accounts or passwords.
- **Offline-first PWA frontend** — IndexedDB storage, service worker, installable, works without a network connection and syncs automatically once back online.
- **Voice & text modes** — Web Speech API for speech-to-text/text-to-speech in the browser; responses are tuned differently for each mode (short & spoken vs. fuller & formatted).
- **Lightweight markdown rendering** — bold/italic/inline code render properly in the chat UI instead of showing raw symbols.
- **PostgreSQL persistence** with an in-memory demo-mode fallback when no database is configured, so the app is still runnable with zero setup.
- **ESP32 firmware starting point** — Wi-Fi, anonymous device registration, and `/api/chat` calls already wired up.

## Tech Stack

| Layer | Stack |
|---|---|
| Backend | FastAPI, asyncpg, Pydantic, slowapi (rate limiting) |
| Database | PostgreSQL (tested with [Supabase](https://supabase.com) and [Neon](https://neon.tech)) |
| Frontend | Vanilla JS, IndexedDB, Service Worker — no build step, no framework |
| AI (online) | Gemini, OpenRouter, Z.ai, NVIDIA NIM — any OpenAI-compatible endpoint works |
| AI (offline) | Ollama |
| Firmware | ESP32 (Arduino framework, PlatformIO) |

## Project Structure

```
ai-smart-glasses/
├── main.py                  # Root entrypoint re-export (for platforms that auto-detect main.py)
├── pyproject.toml           # Dependencies + explicit entrypoint for FastAPI Cloud
├── server/
│   ├── main.py               # FastAPI app & all routes
│   ├── config.py             # Environment-variable configuration
│   ├── database.py           # PostgreSQL connection pool + demo-mode fallback
│   ├── schema.sql            # Database schema (applied automatically on startup)
│   ├── models.py             # Device / Conversation / Message dataclasses
│   ├── repositories.py       # Data access layer (Postgres + in-memory)
│   ├── device_auth.py        # Anonymous per-device identity
│   ├── ai_router.py          # Prompt construction + online/offline routing
│   ├── online_ai.py          # Cloud AI provider chain (Gemini + OpenAI-compatible)
│   ├── local_ai.py           # Local AI provider (Ollama)
│   ├── sync.py               # Offline push/pull sync logic
│   ├── schemas.py            # Pydantic request/response models
│   ├── requirements.txt
│   └── static/                # PWA frontend
│       ├── index.html
│       ├── app.js              # IndexedDB, chat, sync, browser STT/TTS
│       ├── styles.css
│       ├── sw.js                # Service worker
│       └── manifest.json
├── esp32/                    # Firmware starting point (see below)
├── tests/                    # pytest suite
├── .env.example
└── render.yaml / .replit      # Deployment configs
```

## Getting Started

```bash
git clone <your-fork-url>
cd ai-smart-glasses
python -m venv .venv && source .venv/bin/activate   # .venv\Scripts\activate on Windows
pip install -r server/requirements.txt
cp .env.example .env
# fill in .env — see "AI Providers" below for at least one key

python -m uvicorn server.main:app --reload --port 8000
```

Open `http://localhost:8000` — it serves both the PWA frontend and the API from the same origin.

The app also runs with **zero configuration**: without any `.env` values it starts in demo mode (in-memory storage, cleared on restart) — useful for a quick look, and it logs a clear warning so you know persistence isn't on.

## Running Tests

```bash
pytest
```

The suite runs against the in-memory demo-mode repository with AI providers stubbed out, so it needs no real database or API keys.

## Environment Variables

See [`.env.example`](.env.example) for the full list with comments. The essentials:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string. Empty → in-memory demo mode. |
| `DEVICE_SIGNING_SECRET` | Keeps device tokens valid across server restarts. |
| `GEMINI_API_KEY` / `OPENROUTER_API_KEY` / `ZAI_API_KEY` / `NVIDIA_API_KEY` | At least one enables online AI chat. |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | Local model used for offline mode. |
| `DISABLE_DEVICE_AUTH` | Prototyping only — disables per-device auth entirely. Never enable in production. |

## Database

Any PostgreSQL works; [Supabase](https://supabase.com) and [Neon](https://neon.tech) both have workable free tiers. Copy the connection string into `DATABASE_URL`.

If your provider connects through a transaction-mode pooler (e.g. Supabase's pooler / PgBouncer), that's already handled — the connection pool is created with `statement_cache_size=0` for compatibility.

`server/schema.sql` is applied automatically on startup, so there's no manual migration step for a fresh database.

## AI Providers

Online chat tries providers in this fixed order, skipping any without a configured key:

| Order | Provider | Env var | Notes |
|---|---|---|---|
| 1 | Gemini | `GEMINI_API_KEY` | Free tier, native Google Search grounding — get a key at [aistudio.google.com](https://aistudio.google.com), no card required. |
| 2 | OpenRouter | `OPENROUTER_API_KEY` | Any model slug works; free-tier models are supported. |
| 3 | Z.ai | `ZAI_API_KEY` | |
| 4 | NVIDIA NIM | `NVIDIA_API_KEY` | |

`LLM_PROVIDER` is just a label used in logs — the fallback order above is always fixed regardless of its value.

**Offline mode** calls a local [Ollama](https://ollama.com) instance directly from the browser (`http://127.0.0.1:11434`), so it only works when Ollama is running on the same device that has the page open. Messages created offline are queued in IndexedDB and synced to the server automatically once the connection is back.

## Deployment

### FastAPI Cloud (recommended — no credit card)

```bash
pip install "fastapi[standard]"
fastapi login
fastapi cloud env set --secret DEVICE_SIGNING_SECRET "$(python -c 'import secrets; print(secrets.token_hex(32))')"
fastapi cloud env set --secret GEMINI_API_KEY "..."
fastapi deploy
```

The repo already has `pyproject.toml` with an explicit `[tool.fastapi] entrypoint = "server.main:app"` and a root-level `main.py`, so the entrypoint is auto-detected. GitHub integration is also available from the [FastAPI Cloud dashboard](https://dashboard.fastapicloud.com) if you'd rather connect a repo than use the CLI.

### Render.com (alternative)

`render.yaml` in this repo configures the build/start commands automatically — connect the repo as a Blueprint from the Render dashboard and fill in the secrets. Free tier sleeps after 15 minutes of inactivity (first request after that takes 30-50s to wake up).

## Firmware (ESP32)

`esp32/src/main.cpp` is a **starting point**, not a full implementation. It already handles Wi-Fi, anonymous device registration, and calling `/api/chat`. Not implemented (hardware-specific, needs physical hardware to build and test): microphone capture (I2S) → speech-to-text, and text-to-speech → speaker output. Comments in the file mark exactly where to wire in your audio driver.

## Security Notes

- Device tokens are stored server-side only as HMAC-SHA256 hashes, never in plaintext.
- `DISABLE_DEVICE_AUTH` and demo mode (no `DATABASE_URL`) are prototyping conveniences only — the server logs a loud warning on startup when either is active, and both should be off for any real deployment.
- Never commit a real `.env` file — `.gitignore` already excludes it.

## License

No license specified yet — add one (e.g. MIT) if you intend to open-source this.
