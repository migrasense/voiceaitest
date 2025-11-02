import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from fastapi.testclient import TestClient

@pytest.fixture
def client():
    return TestClient(app)

@pytest.mark.asyncio
async def test_mock_groq_hello():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {"message": "hello"}
        response = await ac.post("/mock/groq", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "greeting"
    assert "ai_response" in data


@pytest.mark.asyncio
async def test_mock_groq_default():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {"message": "unknown text"}
        response = await ac.post("/mock/groq", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "other"


@pytest.mark.asyncio
async def test_mock_conversation():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        payload = {"text": "Hello, I need help with billing"}
        response = await ac.post("/mock-conversation", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "intent" in data
    assert "ai_response" in data


@pytest.mark.asyncio
async def test_conversation_history_reset():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Reset conversation history
        reset_response = await ac.post("/reset-conversation")
        assert reset_response.status_code == 200

        # Check history is empty
        history_response = await ac.get("/conversation-history")
        assert history_response.status_code == 200
        history_data = history_response.json()
        assert history_data["total_messages"] == 0

@pytest.mark.asyncio
async def test_mock_conversation(client, monkeypatch):
    from app.services import groq_client

    def fake_detect_intent(text):
        return {
            "original_text": text,
            "translated_text": text,
            "detected_language": "en",
            "intent": "caregiver_reschedule",
            "urgent": False,
            "confidence": 0.95,
            "key_phrases": ["reschedule", "caregiver"],
            "ai_response": "We’ll help reschedule your caregiver.",
            "ai_response_translated": "We’ll help reschedule your caregiver."
        }

    monkeypatch.setattr(groq_client, "detect_intent", fake_detect_intent)

    response = client.post("/mock-conversation", json={"text": "Hi, I need to reschedule my caregiver for tomorrow."})
    data = response.json()

    assert data["intent"] == "caregiver_reschedule"
    assert "reschedule" in data["ai_response"].lower()


# # ----------------------
# # WEBSOCKET ROUTE TEST
# # ----------------------

# def test_websocket_transcripts_stream():
#     client = TestClient(app)
#     try:
#         with client.websocket_connect("/transcripts/stream") as websocket:
#             websocket.send_text("ping")
#             data = websocket.receive_text()
#             assert data == "pong"
#     except Exception as e:
#         # Allow normal disconnects
#         assert "WebSocketDisconnect" in str(type(e))

