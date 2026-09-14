from conftest import auth_headers


def _register(client, installation_id="chat-install-0001"):
    res = client.post("/api/devices/register", json={"installation_id": installation_id})
    return res.json()["device_token"]


def test_chat_creates_conversation_and_messages(client):
    headers = auth_headers(_register(client))
    res = client.post("/api/chat", headers=headers, json={
        "client_message_id": "msg-0001",
        "text": "Halo, apa kabar?",
        "output_mode": "voice",
        "ai_mode": "online",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["assistant_message"]["content"]
    assert data["assistant_message"]["ai_mode"] == "online"

    conv_id = data["conversation_id"]
    msgs = client.get(f"/api/conversations/{conv_id}/messages", headers=headers)
    assert msgs.status_code == 200
    assert len(msgs.json()) == 2  # user + assistant


def test_chat_offline_mode_uses_offline_provider(client):
    headers = auth_headers(_register(client, "chat-install-0002"))
    res = client.post("/api/chat", headers=headers, json={
        "client_message_id": "msg-offline-0001",
        "text": "Test offline",
        "output_mode": "text",
        "ai_mode": "offline",
    })
    assert res.status_code == 200
    assert res.json()["assistant_message"]["ai_mode"] == "offline"


def test_chat_is_idempotent_on_client_message_id(client):
    headers = auth_headers(_register(client, "chat-install-0003"))
    first = client.post("/api/chat", headers=headers, json={
        "client_message_id": "msg-dup-0001", "text": "Ping",
        "output_mode": "voice", "ai_mode": "online",
    }).json()

    second = client.post("/api/chat", headers=headers, json={
        "conversation_id": first["conversation_id"],
        "client_message_id": "msg-dup-0001", "text": "Ping",
        "output_mode": "voice", "ai_mode": "online",
    }).json()

    assert first["user_message"]["id"] == second["user_message"]["id"]
    assert first["assistant_message"]["id"] == second["assistant_message"]["id"]


def test_chat_requires_auth(client):
    res = client.post("/api/chat", json={
        "client_message_id": "msg-noauth-0001", "text": "Halo", "output_mode": "voice", "ai_mode": "online",
    })
    assert res.status_code == 401


def test_chat_accepts_client_generated_conversation_id(client):
    """Regression test: the browser frontend generates its own conversation_id
    locally (offline-first) before the conversation has ever reached the
    server. The very first message for that id must succeed, not 404."""
    headers = auth_headers(_register(client, "chat-install-0004"))
    client_generated_id = "99999999-9999-9999-9999-999999999999"
    res = client.post("/api/chat", headers=headers, json={
        "conversation_id": client_generated_id,
        "client_message_id": "msg-newconv-0001", "text": "halo",
        "output_mode": "voice", "ai_mode": "online",
    })
    assert res.status_code == 200
    assert res.json()["conversation_id"] == client_generated_id

    # A second message on the same (now-existing) conversation id must also work.
    res2 = client.post("/api/chat", headers=headers, json={
        "conversation_id": client_generated_id,
        "client_message_id": "msg-newconv-0002", "text": "apakah bisa?",
        "output_mode": "voice", "ai_mode": "online",
    })
    assert res2.status_code == 200
