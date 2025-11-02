import os
import wave
import asyncio
import pytest
from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents


@pytest.mark.integration
def test_deepgram_transcription():
    DG_KEY = os.getenv("DEEPGRAM_API_KEY")
    if not DG_KEY:
        pytest.skip("No DEEPGRAM_API_KEY set, skipping integration test")

    if not os.path.exists("tests/sample.wav"):
        pytest.skip("Missing tests/sample.wav (16kHz mono PCM)")

    dg_client = DeepgramClient(DG_KEY)
    loop = asyncio.get_event_loop()
    done = asyncio.Event()

    async def run_test():
        dg_socket = dg_client.listen.live.v("1")

        @dg_socket.on(LiveTranscriptionEvents.Transcript)
        def handle_transcript(_, result, **kwargs):
            if result.is_final and result.channel.alternatives[0].transcript.strip():
                print("Transcript:", result.channel.alternatives[0].transcript)
                done.set()

        options = LiveOptions(
            model="nova-3",
            language="en-US",
            sample_rate=16000,
            channels=1,
            encoding="linear16"
        )
        dg_socket.start(options)

        with wave.open("tests/sample.wav", "rb") as wf:
            while True:
                data = wf.readframes(4000)
                if not data:
                    break
                dg_socket.send(data)

        await asyncio.wait_for(done.wait(), timeout=10)
        dg_socket.finish()

    loop.run_until_complete(run_test())
