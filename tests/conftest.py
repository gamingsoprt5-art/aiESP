import os
import sys
from pathlib import Path

import pytest

# Make the project root importable as `server.*` regardless of where pytest is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Force demo mode (in-memory repository) and dummy secrets for every test run,
# so the suite never needs a real PostgreSQL database or a real LLM API key.
os.environ["DATABASE_URL"] = ""
os.environ["DEVICE_SIGNING_SECRET"] = "test-signing-secret"
os.environ["LLM_API_KEY"] = "test-key"

from fastapi.testclient import TestClient  # noqa: E402

from server import ai_router  # noqa: E402
from server.main import app  # noqa: E402
from server.models import AIResult  # noqa: E402


@pytest.fixture(autouse=True)
def stub_ai_providers(monkeypatch):
    """Replace real network calls to online/offline AI with deterministic stubs."""

    async def fake_online_chat(self, messages, output_mode):
        return AIResult(text="Ini jawaban AI online (stub untuk pengujian).",
                        provider="online", model="stub-online-model", ai_mode="online")

    async def fake_offline_chat(self, messages, output_mode):
        return AIResult(text="Ini jawaban AI offline (stub untuk pengujian).",
                        provider="offline", model="stub-offline-model", ai_mode="offline")

    monkeypatch.setattr(ai_router.OnlineAIProvider, "chat", fake_online_chat)
    monkeypatch.setattr(ai_router.LocalAIProvider, "chat", fake_offline_chat)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def registered_device(client):
    res = client.post("/api/devices/register", json={"installation_id": "fixture-install-0001"})
    assert res.status_code == 200
    return res.json()


def auth_headers(token: str) -> dict:
    return {"Authorization": "Device " + token}
