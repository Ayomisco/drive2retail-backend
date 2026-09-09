def test_liveness_checks_nothing_external(client):
    """A database blip must not make the orchestrator kill healthy pods."""
    response = client.get("/health/live/")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
