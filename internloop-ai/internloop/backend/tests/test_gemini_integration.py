import pytest
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)

def test_ai_status_endpoint():
    r = c.get("/api/ai/status")
    assert r.status_code == 200
    data = r.json()
    assert "ok" in data
    assert data.get("model") == "gemini-3.5-flash-lite"

def test_ai_tutor_endpoint():
    r = c.post("/api/ai/tutor", json={
        "message": "Hello, can you explain what finding F-1 means in one sentence?",
        "history": []
    })
    assert r.status_code == 200
    data = r.json()
    assert "reply" in data
    assert len(data["reply"]) > 10
    assert data.get("model") == "gemini-3.5-flash-lite"
