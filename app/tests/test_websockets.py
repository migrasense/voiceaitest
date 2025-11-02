from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_websocket_transcripts_stream():
    """Unit-level test for /transcripts/stream WebSocket."""
    with client.websocket_connect("/transcripts/stream") as websocket:
        # Send fake transcript payload
        websocket.send_text("hello test")

        # Expect an echo/response back
        message = websocket.receive_text()
        assert "hello test" in message



def test_websocket_audio_connect():
    """Unit-level test for /audio WebSocket connection."""
    with client.websocket_connect("/audio") as websocket:
        websocket.send_text("pause")
        websocket.send_text("resume")
        # No exception means success
        assert True
        websocket.close()
