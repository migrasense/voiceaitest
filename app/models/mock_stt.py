from datetime import datetime

class MockSTT:
    """Simulates Deepgram's live transcription with text input."""
    def __init__(self):
        self.transcript_callback = None
        self.conversation_history = []

    def mock_receive_text(self, text: str, is_final: bool = True):
        if not self.transcript_callback:
            raise ValueError("No callback set for mock STT")

        self.conversation_history.append({
            "role": "user",
            "text": text,
            "timestamp": datetime.now().isoformat()
        })

        mock_result = type("MockResult", (), {
            "channel": type("MockChannel", (), {
                "alternatives": [type("MockAlt", (), {
                    "transcript": text,
                    "words": []
                })]
            }),
            "is_final": is_final
        })

        self.transcript_callback(None, mock_result)

mock_stt = MockSTT()
