from conftest import auth_headers


def _register(client, installation_id="sync-install-0001"):
    res = client.post("/api/devices/register", json={"installation_id": installation_id})
    return res.json()["device_token"]


def test_sync_push_then_pull_roundtrip(client):
    headers = auth_headers(_register(client))
    conv_id = "11111111-1111-1111-1111-111111111111"

    push_body = {
        "items": [{
            "client_message_id": "offline-msg-0001",
            "conversation_id": conv_id,
            "conversation_title": "Percakapan Offline",
            "role": "user",
            "content": "Pesan yang dibuat saat offline",
            "output_mode": "voice",
            "ai_mode": "offline",
            "provider": "offline",
        }]
    }

    res = client.post("/api/sync/push", headers=headers, json=push_body)
    assert res.status_code == 200
    assert res.json()["synced_count"] == 1
    assert res.json()["error_count"] == 0

    pull = client.get("/api/sync/pull", headers=headers)
    assert pull.status_code == 200
    contents = [m["content"] for m in pull.json()["messages"]]
    assert "Pesan yang dibuat saat offline" in contents


def test_sync_push_is_idempotent(client):
    headers = auth_headers(_register(client, "sync-install-0002"))
    push_body = {
        "items": [{
            "client_message_id": "offline-msg-dup-0001",
            "conversation_id": "22222222-2222-2222-2222-222222222222",
            "role": "user",
            "content": "Pesan duplikat",
            "output_mode": "text",
            "ai_mode": "offline",
        }]
    }

    first = client.post("/api/sync/push", headers=headers, json=push_body).json()
    second = client.post("/api/sync/push", headers=headers, json=push_body).json()

    assert first["synced_count"] == 1
    assert second["synced_count"] == 0
    assert second["duplicate_count"] == 1


def test_sync_requires_auth(client):
    res = client.get("/api/sync/pull")
    assert res.status_code == 401
