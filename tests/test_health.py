def test_health_ok(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["mode"] == "demo"  # DATABASE_URL is empty in the test environment
    assert isinstance(data["warnings"], list)
