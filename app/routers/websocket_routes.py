# app/routers/websocket_routes.py - FULLY CORRECTED

import base64
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Response
from datetime import datetime
import time
import uuid
import io
import asyncio
from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents, SpeakOptions

from app.core.config import DEEPGRAM_API_KEY, logger
from app.core.connection_manager import manager
from app.models.mock_stt import mock_stt
from app.services.groq_client import groq_client
from app.services.transcript_service import process_final_transcript, end_active_session
from app.services.conversation_manager import conversation_manager

router = APIRouter()
deepgram = DeepgramClient(DEEPGRAM_API_KEY)

READ_TIMEOUT_SECONDS = 15

from app.routers.mock_routes import synthesize_audio_file

import re

def normalize_e164(num: str) -> str:
    """Normalize any Twilio or local number to +E.164 format."""
    if not num:
        return None
    digits = re.sub(r"\D", "", num)
    # Always prefix with '+' and country code
    if len(digits) == 10:
        digits = "1" + digits
    return f"+{digits}"

async def _safe_send_greeting(websocket):
    """Send greeting non-blocking after Twilio connects."""
    try:
        await asyncio.sleep(0.7)
        logger.info("📞 Sending greeting to caller...")
        await _send_greeting_to_caller(websocket)
    except Exception as e:
        logger.warning(f"⚠️ Greeting failed: {e}")



# ✅ THIS FUNCTION MUST BE CALLED - SEE handle_real_time_transcript()
async def send_audio_response_to_twilio(websocket: WebSocket, text: str, session_id: str):
    """
    Convert AI response to mu-law audio and send back to Twilio caller.
    
    CRITICAL: This function MUST be called from handle_real_time_transcript()
    """
    if not websocket:
        logger.error("❌ No websocket connection to send audio")
        return
    
    try:
        logger.info(f"🔊 Converting AI response to audio: {text[:50]}...")
        
        # Generate TTS audio (returns bytes in mu-law format)
        audio_data = await synthesize_audio_file(text, language="en")
        
        if not audio_data:
            logger.error("❌ TTS generation failed - audio_data is None or empty")
            return
        
        logger.info(f"📤 Sending {len(audio_data)} bytes of mu-law audio to caller")
        
        # Twilio expects base64-encoded audio in media events
        import base64
        audio_payload = base64.b64encode(audio_data).decode('utf-8')
        
        # Create media event for Twilio
        media_event = {
            "event": "media",
            "media": {
                "payload": audio_payload
            }
        }
        
        # Send audio back through WebSocket
        await websocket.send_json(media_event)
        logger.info("✅ Audio response sent to caller")
        
    except Exception as e:
        logger.error(f"❌ Failed to send audio response: {e}", exc_info=True)


async def handle_real_time_transcript(
    transcript: str, 
    stt_lang_hint: str = "en",
    websocket: WebSocket = None  # ✅ CRITICAL PARAMETER
):
    """
    Process transcript, generate TTS, send audio to caller, and broadcast to clients
    
    CRITICAL: websocket parameter MUST be passed from on_transcript() callback
    """
    try:
        logger.info(f"🎯 Processing real-time transcript: {transcript}")
        
        # 1. Process the transcript to get AI response
        session_id, entry = await process_final_transcript(transcript, stt_lang_hint=stt_lang_hint)
        
        # 2. ✅ CRITICAL: Send audio response back to caller
        if entry.get("ai_response") and websocket:
            logger.info(f"📱 Calling send_audio_response_to_twilio() to send TTS to caller")
            await send_audio_response_to_twilio(websocket, entry["ai_response"], session_id)
        elif entry.get("ai_response") and not websocket:
            logger.warning(f"⚠️ NO WEBSOCKET - Cannot send audio to caller! websocket={websocket}")
        elif not entry.get("ai_response"):
            logger.warning(f"⚠️ NO AI RESPONSE - Nothing to convert to audio")
        
        # 3. Add session context
        entry["session_id"] = session_id
        entry["sentiment"] = conversation_manager.sessions.get(session_id, {}).get("overall_sentiment", "neutral")
        
        # 4. Broadcast to all connected clients (for dashboard/UI)
        logger.info("📡 Broadcasting to connected clients")
        await manager.broadcast(entry)
        
        return entry
        
    except Exception as e:
        logger.error(f"❌ Error in handle_real_time_transcript: {e}", exc_info=True)
        import traceback
        logger.error(traceback.format_exc())


async def _send_greeting_to_caller(websocket: WebSocket):
    """Send welcome greeting to caller via TTS"""
    try:
        greeting = "Hello, welcome to Servoice. How may I help you?"
        logger.info(f"🎤 Sending greeting: {greeting}")
        
        audio_data = await synthesize_audio_file(greeting, "en")
        if audio_data:
            audio_payload = base64.b64encode(audio_data).decode('utf-8')
            media_event = {
                "event": "media",
                "media": {
                    "payload": audio_payload
                }
            }
            await websocket.send_json(media_event)
            logger.info("✅ Greeting sent to caller")
            await asyncio.sleep(1)
        else:
            logger.error("❌ Failed to generate greeting audio")
    except Exception as e:
        logger.error(f"❌ Error sending greeting: {e}", exc_info=True)

@router.websocket("/audio/test")
async def audio_stream_test(websocket: WebSocket):
    """
    Minimal echo WebSocket endpoint for testing Twilio connectivity.
    Use this to verify Twilio can connect before debugging the full /audio endpoint.
    """
    client_host = websocket.client.host if websocket.client else "unknown"
    logger.info(f"🧪 TEST WebSocket connection attempt from {client_host} to /audio/test")
    
    try:
        await websocket.accept()
        logger.info(f"✅ TEST WebSocket /audio/test ACCEPTED from {client_host}")
        
        # Echo back any messages received
        while True:
            try:
                msg = await websocket.receive()
                logger.info(f"🧪 TEST: Received message type: {list(msg.keys())}")
                
                if "text" in msg:
                    logger.info(f"🧪 TEST: Text content: {msg['text'][:200]}")
                    # Echo it back
                    await websocket.send_json({"echo": msg["text"], "status": "ok"})
                elif "bytes" in msg:
                    logger.info(f"🧪 TEST: Binary data ({len(msg['bytes'])} bytes)")
                    await websocket.send_json({"echo": "binary", "size": len(msg["bytes"]), "status": "ok"})
                else:
                    logger.warning(f"🧪 TEST: Unknown message format: {msg}")
                    
            except WebSocketDisconnect:
                logger.info("🧪 TEST: Client disconnected")
                break
                
    except Exception as e:
        logger.error(f"❌ TEST WebSocket error: {e}", exc_info=True)
    finally:
        logger.info("🧪 TEST: Closing test WebSocket")


@router.websocket("/transcripts/stream")
async def transcript_stream(websocket: WebSocket):
    """Stream for real-time transcript updates"""
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            logger.debug(f"Received on transcript stream: {data}")
    except WebSocketDisconnect:
        logger.info("Transcript stream client disconnected")
    finally:
        await manager.disconnect(websocket)

@router.post("/tts")
async def tts_endpoint(request: dict):
    text = request.get("text", "")
    if not text.strip():
        return {"error": "No text provided"}

    try:
        options = SpeakOptions(model="aura-2-thalia-en")
        buffer = io.BytesIO()
        deepgram.speak.v("1").stream(
            buffer,
            {"text": text},
            options
        )
        buffer.seek(0)
        return Response(
            content=buffer.read(),
            media_type="audio/mpeg"
        )
    except Exception as e:
        return {"error": str(e)}


@router.websocket("/audio")
async def audio_stream(websocket: WebSocket):
    """
    Handles live Twilio streaming audio → Deepgram → AI → TTS → response.
    Refactored for Twilio compliance (instant accept, async-safe setup).
    """
    client_host = websocket.client.host if websocket.client else "unknown"
    logger.info(f"🔌 WebSocket connection attempt from {client_host} to /audio")

    try:
        # 1️⃣ Accept immediately (Twilio handshake requirement)
        await websocket.accept()
        logger.info(f"✅ WebSocket /audio ACCEPTED from {client_host}")
    except Exception as e:
        logger.error(f"❌ Failed to accept WebSocket: {e}", exc_info=True)
        return

    # ─────────────────────────────────────────────────────────────
    # PREP STATE
    # ─────────────────────────────────────────────────────────────
    import json, base64, time, asyncio, uuid
    from datetime import datetime
    from app.db.supabase import supabase
    from app.services.conversation_manager import conversation_manager

    phone_number = None
    company_id = office_id = phone_number_id = None
    caller_contact_id = None
    dg_socket = None
    session_id = None
    last_activity = {"ts": time.time()}
    watchdog_task = None
    current_loop = asyncio.get_event_loop()

    # ─────────────────────────────────────────────────────────────
    # GREETING (non-blocking)
    # ─────────────────────────────────────────────────────────────
    asyncio.create_task(_safe_send_greeting(websocket))

    # ─────────────────────────────────────────────────────────────
    # EVENT LOOP
    # ─────────────────────────────────────────────────────────────
    try:
        logger.info("🎧 Waiting for Twilio media stream events...")

        while True:
            msg = await websocket.receive()
            data = msg.get("text") or msg.get("bytes")

            # Log type of frame
            if "text" in msg:
                logger.debug(f"💬 Received text ({len(msg.get('text',''))} chars)")
            elif "bytes" in msg:
                logger.debug(f"🎤 Received {len(msg.get('bytes',b''))} bytes audio")

            # Handle text (Twilio JSON event)
            if isinstance(data, str):
                try:
                    event = json.loads(data)
                    event_type = event.get("event")
                except json.JSONDecodeError:
                    logger.warning(f"⚠️ Non-JSON text frame: {data[:100]}")
                    continue

                # ------------------------------
                # START EVENT
                # ------------------------------
                if event_type == "start":
                    logger.info("🚀 Twilio START event received")

                    start_info = event.get("start", {})
                    params = start_info.get("customParameters", {})
                    caller_id = params.get("caller")
                    receiver_id = params.get("receiver")

                    caller_number = normalize_e164(caller_id)
                    receiver_number = normalize_e164(receiver_id)
                    logger.info(f"📞 Caller: {caller_number} → Receiver: {receiver_number}")

                    # ── 1️⃣ Lookup agency line
                    try:
                        result = (
                            supabase.table("phone_numbers")
                            .select("id, company_id, office_id, e164")
                            .eq("e164", receiver_number)
                            .execute()
                        )
                        if result.data:
                            phone_data = result.data[0]
                            company_id = phone_data["company_id"]
                            office_id = phone_data["office_id"]
                            phone_number_id = phone_data["id"]
                            logger.info(f"🏢 Found agency: company_id={company_id}, office_id={office_id}")
                        else:
                            logger.warning(f"⚠️ Receiver {receiver_number} not found in DB")
                    except Exception as e:
                        logger.error(f"❌ Supabase lookup failed: {e}", exc_info=True)

                    # ── 2️⃣ Lookup or create contact
                    try:
                        contact_lookup = (
                            supabase.table("contacts").select("id").eq("phone_number", caller_number).execute()
                        )
                        if contact_lookup.data:
                            caller_contact_id = contact_lookup.data[0]["id"]
                        else:
                            inserted = (
                                supabase.table("contacts")
                                .insert({"phone_number": caller_number})
                                .execute()
                            )
                            caller_contact_id = inserted.data[0]["id"]
                        logger.info(f"👤 Caller contact ID = {caller_contact_id}")
                    except Exception as e:
                        logger.error(f"❌ Contact lookup failed: {e}", exc_info=True)

                    # ── 3️⃣ Start session
                    session_id = conversation_manager.start_session(
                        caller_id=caller_contact_id or caller_number
                    )
                    sess = conversation_manager.sessions.get(session_id)
                    if sess:
                        sess.update({
                            "company_id": company_id,
                            "office_id": office_id,
                            "phone_number_id": phone_number_id,
                            "caller_number": caller_number,
                            "receiver_number": receiver_number,
                        })
                    logger.info(f"🧠 Session {session_id} initialized")

                    # ── 4️⃣ Initialize Deepgram
                    from deepgram import LiveTranscriptionEvents, LiveOptions
                    dg_socket = deepgram.listen.websocket.v("1")

                    def on_transcript(self, result, **kwargs):
                        transcript = result.channel.alternatives[0].transcript
                        if not transcript.strip():
                            return
                        is_final = getattr(result, "is_final", False)
                        stt_lang_hint = getattr(result.metadata, "language", "en")
                        spanish_words = ["hola","gracias","por favor","adiós"]
                        if any(w in transcript.lower() for w in spanish_words):
                            stt_lang_hint = "es"

                        if not is_final:
                            asyncio.run_coroutine_threadsafe(
                                manager.broadcast({
                                    "type": "transcript",
                                    "transcript": transcript,
                                    "is_final": False,
                                    "language": stt_lang_hint,
                                    "timestamp": datetime.now().isoformat(),
                                }),
                                current_loop,
                            )
                            last_activity["ts"] = time.time()
                        else:
                            logger.info(f"📝 Final transcript: {transcript}")
                            asyncio.run_coroutine_threadsafe(
                                handle_real_time_transcript(transcript, stt_lang_hint, websocket),
                                current_loop,
                            )

                    def on_error(dg, error, **kwargs):
                        logger.error(f"❌ Deepgram error: {error}")

                    dg_socket.on(LiveTranscriptionEvents.Transcript, on_transcript)
                    dg_socket.on(LiveTranscriptionEvents.Error, on_error)

                    options = LiveOptions(
                        model="nova-2-general",
                        encoding="mulaw",
                        sample_rate=8000,
                        channels=1,
                        smart_format=True,
                        punctuate=True,
                        interim_results=True,
                        vad_events=True,
                    )

                    if not dg_socket.start(options):
                        logger.error("💥 Failed to start Deepgram socket")
                        await websocket.close()
                        return

                    logger.info("🎙️ Deepgram socket started with mu-law encoding")

                    # ── 5️⃣ Launch inactivity watchdog
                    async def inactivity_watchdog():
                        while True:
                            await asyncio.sleep(3)
                            if time.time() - last_activity["ts"] > 12:
                                logger.info("⏳ Inactivity detected — closing session")
                                try:
                                    if dg_socket:
                                        dg_socket.finish()
                                except Exception:
                                    pass
                                try:
                                    await end_active_session(session_id=session_id, caller_id=caller_number)
                                except Exception as e:
                                    logger.error(f"end_active_session failed: {e}")
                                break
                    watchdog_task = asyncio.create_task(inactivity_watchdog())

                # ------------------------------
                # MEDIA EVENT
                # ------------------------------
                elif event_type == "media":
                    audio_payload = event["media"]["payload"]
                    audio_bytes = base64.b64decode(audio_payload)
                    if dg_socket:
                        dg_socket.send(audio_bytes)
                        last_activity["ts"] = time.time()
                    else:
                        logger.warning("⚠️ Media received before Deepgram ready")

                # ------------------------------
                # STOP EVENT
                # ------------------------------
                elif event_type == "stop":
                    logger.info("🛑 Twilio stream stopped")
                    break

            # Raw binary (rare)
            elif isinstance(data, (bytes, bytearray)) and dg_socket:
                dg_socket.send(data)
                last_activity["ts"] = time.time()

    except WebSocketDisconnect:
        logger.info("🔌 Client disconnected from audio stream")
    except asyncio.CancelledError:
        logger.info("⏹️ WebSocket task cancelled")
    except Exception as e:
        logger.exception(f"❌ Audio stream error: {e}", exc_info=True)
    finally:
        try:
            if dg_socket:
                dg_socket.finish()
                logger.info("🏁 Deepgram socket closed")
            if watchdog_task:
                watchdog_task.cancel()
            await manager.disconnect(websocket)
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
