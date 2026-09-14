from conftest import auth_headers


def test_register_device_returns_token(client):
    res = client.post("/api/devices/register", json={"installation_id": "install-abc-00001"})
    assert res.status_code == 200
    data = res.json()
    assert data["device_id"]
    assert data["device_token"]
    assert data["already_registered"] is False


def test_register_same_installation_id_reissues_token(client):
    first = client.post("/api/devices/register", json={"installation_id": "dup-install-0001"}).json()
    second = client.post("/api/devices/register", json={"installation_id": "dup-install-0001"}).json()
    assert second["already_registered"] is True
    assert second["device_id"] == first["device_id"]
    # Re-registration rotates the token, so the old one must stop working.
    assert second["device_token"] != first["device_token"]


def test_protected_endpoint_without_token_rejected(client):
    res = client.get("/api/conversations")
    assert res.status_code == 401


def test_protected_endpoint_with_invalid_token_rejected(client):
    res = client.get("/api/conversations", headers=auth_headers("not-a-real-token"))
    assert res.status_code == 401


def test_rotate_token_invalidates_old_token(client, registered_device):
    old_token = registered_device["device_token"]

    res = client.post("/api/devices/rotate-token", headers=auth_headers(old_token))
    assert res.status_code == 200
    new_token = res.json()["device_token"]
    assert new_token != old_token

    res_old = client.get("/api/conversations", headers=auth_headers(old_token))
    assert res_old.status_code == 401

    res_new = client.get("/api/conversations", headers=auth_headers(new_token))
    assert res_new.status_code == 200
