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
    # ✅ CRITICAL: Log connection attempt BEFORE accepting
    client_host = websocket.client.host if websocket.client else "unknown"
    logger.info(f"🔌 WebSocket connection attempt from {client_host} to /audio")
    
    try:
        await websocket.accept()
        logger.info(f"✅ WebSocket /audio ACCEPTED from {client_host}")
    except Exception as e:
        logger.error(f"❌ Failed to accept WebSocket: {e}", exc_info=True)
        return
    
    # ✨ ADD THESE 2 LINES: (NEW!)
    logger.info("📞 Sending welcome greeting...")
    await _send_greeting_to_caller(websocket)

    import json, base64
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

    # Step 1: local test mode payload (for manual browser/mic tests)
    # ✅ Only wait for JSON if it's a test connection, Twilio will send events as text
    try:
        init_payload = await asyncio.wait_for(websocket.receive_json(), timeout=3)
        phone_number = (
            init_payload.get("from")
            or init_payload.get("caller")
            or init_payload.get("phone")
        )
        if phone_number:
            phone_number = normalize_e164(phone_number)
            logger.info(f"📞 Incoming call from {phone_number} (pre-init)")
    except asyncio.TimeoutError:
        logger.info("⌛ No initial JSON payload (expected for Twilio) - waiting for start event...")
    except Exception as e:
        logger.warning(f"⚠️ Exception receiving initial payload: {e} - continuing for Twilio...")

    # Step 2: Handle Twilio event stream
    try:
        logger.info("🎧 Entering Twilio event loop - waiting for events...")
        while True:
            msg = await websocket.receive()
            data = msg.get("text") or msg.get("bytes")
            
            # ✅ Log raw message type for debugging
            if "text" in msg:
                logger.debug(f"📨 Received text message ({len(msg.get('text', ''))} chars)")
            elif "bytes" in msg:
                logger.debug(f"📦 Received binary message ({len(msg.get('bytes', b''))} bytes)")

            if isinstance(data, str):
                try:
                    event = json.loads(data)
                    event_type = event.get("event")
                    logger.info(f"📥 Twilio event received: {event_type}")
                except json.JSONDecodeError as e:
                    logger.error(f"❌ Failed to parse event JSON: {data[:100]}... Error: {e}")
                    continue

                # ---- START event ----
                if event_type == "start":
                    logger.info("🚀 Received START event from Twilio!")
                    start_info = event.get("start", {})
                    params = start_info.get("customParameters", {})
                    caller_id = params.get("caller")
                    receiver_id = params.get("receiver")

                    caller_number = normalize_e164(caller_id)
                    receiver_number = normalize_e164(receiver_id)

                    logger.info(f"📞 Caller: {caller_number} → Receiver: {receiver_number}")

                    # 1️⃣ Lookup receiver (the agency/office number)
                    try:
                        office_lookup = (
                            supabase.table("phone_numbers")
                            .select("id, company_id, office_id, e164")
                            .eq("e164", receiver_number)
                            .execute()
                        )
                        if office_lookup.data:
                            phone_data = office_lookup.data[0]
                            company_id = phone_data.get("company_id")
                            office_id = phone_data.get("office_id")
                            phone_number_id = phone_data.get("id")
                            logger.info(f"🏢 Agency line → company_id={company_id}, office_id={office_id}")
                        else:
                            logger.warning(f"⚠️ Receiver number {receiver_number} not found in phone_numbers")
                    except Exception as e:
                        logger.error(f"❌ Supabase agency lookup failed: {e}", exc_info=True)

                    # 2️⃣ Lookup or create contact (the caller)
                    try:
                        contact_lookup = (
                            supabase.table("contacts")
                            .select("id")
                            .eq("phone_number", caller_number)
                            .execute()
                        )
                        if contact_lookup.data:
                            caller_contact_id = contact_lookup.data[0]["id"]
                            logger.info(f"👤 Existing contact found: {caller_contact_id}")
                        else:
                            inserted = (
                                supabase.table("contacts")
                                .insert({"phone_number": caller_number})
                                .execute()
                            )
                            caller_contact_id = inserted.data[0]["id"]
                            logger.info(f"🆕 Created new contact: {caller_contact_id}")
                    except Exception as e:
                        logger.error(f"❌ Contact lookup/creation failed: {e}", exc_info=True)

                    # 3️⃣ Start session linked to agency + caller
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
                        logger.info(f"🧠 Session {session_id} started with metadata attached")
                    else:
                        logger.error(f"❌ Session {session_id} not found")

                    # 🎧 Deepgram Setup
                    dg_socket = deepgram.listen.websocket.v("1")

                    def on_transcript(self, result, **kwargs):
                        transcript = result.channel.alternatives[0].transcript
                        if not transcript.strip():
                            return

                        is_final = getattr(result, "is_final", False)
                        stt_lang_hint = getattr(result.metadata, "language", "en")

                        # 🔤 Detect Spanish
                        spanish_words = [
                            "hola", "gracias", "por favor", "adiós", "buenos días",
                            "buenas tardes", "buenas noches", "sí", "con", "para",
                            "que", "como", "donde", "cuando", "porque", "necesito",
                            "ayuda", "información"
                        ]
                        if any(word in transcript.lower() for word in spanish_words):
                            stt_lang_hint = "es"

                        if not is_final:
                            asyncio.run_coroutine_threadsafe(
                                manager.broadcast({
                                    "message_id": str(uuid.uuid4()),
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
                            logger.info(f"📝 Final Transcript: {transcript}")
                            # ✅ CRITICAL: Pass websocket as third parameter
                            logger.info(f"🔄 Calling handle_real_time_transcript with websocket")
                            asyncio.run_coroutine_threadsafe(
                                handle_real_time_transcript(transcript, stt_lang_hint, websocket),
                                current_loop,
                            )

                    def on_error(dg, error, **kwargs):
                        logger.error(f"❌ Deepgram error: {error}")

                    dg_socket.on(LiveTranscriptionEvents.Transcript, on_transcript)
                    dg_socket.on(LiveTranscriptionEvents.Error, on_error)

                    # ✅ CRITICAL: encoding="mulaw" instead of "linear16"
                    options = LiveOptions(
                        model="nova-2-general",
                        encoding="mulaw",           # ✅ CORRECT
                        sample_rate=8000,
                        channels=1,
                        smart_format=True,
                        punctuate=True,
                        interim_results=True,
                        endpointing=300,
                        vad_events=True,
                    )

                    if not dg_socket.start(options):
                        logger.error("💥 Failed to start Deepgram socket")
                        await websocket.close()
                        return

                    logger.info("🚀 Deepgram socket started with mu-law encoding")

                    # 🕒 Inactivity Watchdog
                    async def inactivity_watchdog():
                        try:
                            while True:
                                await asyncio.sleep(2)
                                if time.time() - last_activity["ts"] > 10:
                                    logger.info("⏳ Inactivity detected — closing session")
                                    try:
                                        if dg_socket:
                                            dg_socket.finish()
                                    except Exception:
                                        pass
                                    try:
                                        await end_active_session(
                                            session_id=session_id,
                                            caller_id=caller_number,
                                        )
                                    except Exception as e:
                                        logger.error(f"end_active_session failed: {e}")
                                    break
                        except asyncio.CancelledError:
                            pass

                    watchdog_task = asyncio.create_task(inactivity_watchdog())

                # ---- MEDIA event ----
                elif event_type == "media":
                    audio_payload = event["media"]["payload"]
                    audio_bytes = base64.b64decode(audio_payload)
                    if dg_socket:
                        dg_socket.send(audio_bytes)
                        last_activity["ts"] = time.time()
                    else:
                        logger.warning("⚠️ Media received before Deepgram was ready")

                elif event_type == "stop":
                    logger.info("🛑 Twilio stream stopped.")
                    break

            elif isinstance(data, (bytes, bytearray)) and dg_socket:
                dg_socket.send(data)
                last_activity["ts"] = time.time()

    except WebSocketDisconnect:
        logger.info("🔌 Client disconnected from audio stream (WebSocketDisconnect)")
    except asyncio.CancelledError:
        logger.info("⏹️ WebSocket task cancelled")
    except Exception as e:
        logger.exception(f"❌ Audio stream error: {e}", exc_info=True)
    finally:
        if dg_socket:
            try:
                dg_socket.finish()
                logger.info("🏁 Deepgram socket finished")
            except Exception as e:
                logger.error(f"Error closing Deepgram socket: {e}")
        if watchdog_task:
            try:
                watchdog_task.cancel()
            except Exception:
                pass
        await manager.disconnect(websocket)




# @router.websocket("/audio")
# async def audio_stream(websocket: WebSocket):
#     await websocket.accept()
#     logger.info("✅ New audio stream connected")

#     # 🆕 Step 1: Resolve phone → company/office IDs from Supabase
#     from app.db.supabase import supabase
#     from app.services.conversation_manager import conversation_manager

#     # Example: if Twilio or frontend sends initial metadata (JSON)
#     phone_number = None
#     try:
#         init_payload = await asyncio.wait_for(websocket.receive_json(), timeout=3)
#         phone_number = init_payload.get("from") or init_payload.get("caller") or init_payload.get("phone")
#         logger.info(f"📞 Incoming call from {phone_number}")
#     except Exception:
#         logger.warning("⚠️ No initial JSON payload received; using fallback test number")
#         phone_number = "+18705551234"  # 🆕 fallback for local testing

#     # 🆕 Step 2: Lookup phone_number in Supabase to find company/office IDs
#     try:
#         phone_lookup = (
#             supabase.table("phone_numbers")
#             .select("id, company_id, office_id, e164")
#             .eq("e164", phone_number)
#             .execute()
#         )
#         if phone_lookup.data:
#             phone_data = phone_lookup.data[0]
#             company_id = phone_data["company_id"]
#             office_id = phone_data["office_id"]
#             phone_number_id = phone_data["id"]
#             logger.info(f"🔗 Linked phone {phone_number} → company={company_id}, office={office_id}")
#         else:
#             company_id = office_id = phone_number_id = None
#             logger.warning(f"⚠️ No phone match found for {phone_number}")
#     except Exception as e:
#         logger.error(f"❌ Phone lookup failed: {e}")
#         company_id = office_id = phone_number_id = None

#     # 🆕 Step 3: Start a new session and attach IDs
#     session_id = conversation_manager.start_session(caller_id=phone_number)
#     sess = conversation_manager.sessions[session_id]
#     sess.update({
#         "company_id": company_id,
#         "office_id": office_id,
#         "phone_number_id": phone_number_id,
#     })
#     logger.info(f"🧠 Session {session_id} started with metadata attached")

#     # --------------------------------------------------------------------
#     dg_socket = None
#     try:
#         dg_socket = deepgram.listen.websocket.v("1")
#         current_loop = asyncio.get_event_loop()

#         def on_transcript(self, result, **kwargs):
#             transcript = result.channel.alternatives[0].transcript
#             is_final = getattr(result, "is_final", False)
#             stt_lang_hint = getattr(result.metadata, "language", "en")

#             # Language override
#             spanish_words = ['hola', 'gracias', 'por favor', 'adiós', 'buenos días',
#                              'buenas tardes', 'buenas noches', 'sí', 'con', 'para',
#                              'que', 'como', 'donde', 'cuando', 'porque', 'necesito',
#                              'ayuda', 'información']
#             has_spanish_words = any(word in transcript.lower() for word in spanish_words)
#             stt_lang_hint = "es" if has_spanish_words else "en"

#             if not transcript.strip():
#                 return

#             # Broadcast interim transcripts
#             if not is_final:
#                 broadcast_payload = {
#                     "message_id": str(uuid.uuid4()),
#                     "type": "transcript",
#                     "transcript": transcript,
#                     "is_final": False,
#                     "language": stt_lang_hint,
#                     "timestamp": datetime.now().isoformat()
#                 }
#                 asyncio.run_coroutine_threadsafe(
#                     manager.broadcast(broadcast_payload),
#                     current_loop
#                 )
#                 last_activity["ts"] = time.time()

#             # Process final transcripts
#             if is_final:
#                 logger.info(f"📝 Final Transcript: {transcript}")
#                 asyncio.run_coroutine_threadsafe(
#                     handle_real_time_transcript(transcript, stt_lang_hint),
#                     current_loop
#                 )

#         def on_error(dg, error, **kwargs):
#             logger.error(f"❌ Deepgram error: {error}")

#         dg_socket.on(LiveTranscriptionEvents.Transcript, on_transcript)
#         dg_socket.on(LiveTranscriptionEvents.Error, on_error)

#         options = LiveOptions(
#             model="nova-2",
#             encoding="linear16",
#             sample_rate=16000,
#             channels=1,
#             smart_format=True,
#             punctuate=True,
#             interim_results=True,
#             endpointing=300,
#             vad_events=True
#         )

#         if not dg_socket.start(options):
#             logger.error("💥 Failed to start Deepgram socket")
#             await websocket.close()
#             return
#         logger.info("🚀 Deepgram socket started")

#         # Inactivity watchdog
#         INACTIVITY_SECS = 8
#         last_activity = {"ts": time.time()}

#         async def inactivity_watchdog():
#             try:
#                 while True:
#                     await asyncio.sleep(2)
#                     if time.time() - last_activity["ts"] > INACTIVITY_SECS:
#                         logger.info("⏳ Inactivity detected; ending Deepgram session and flushing conversation")
#                         try:
#                             dg_socket.finish()
#                         except Exception:
#                             pass
#                         try:
#                             # 🆕 Now passes session_id for proper flush
#                             await end_active_session(session_id=session_id, caller_id=phone_number)
#                         except Exception as e:
#                             logger.error(f"end_active_session failed: {e}")
#                         break
#             except asyncio.CancelledError:
#                 pass

#         watchdog_task = asyncio.create_task(inactivity_watchdog())

#         while True:
#             data = await websocket.receive_bytes()
#             if len(data) > 0:
#                 dg_socket.send(data)
#                 last_activity["ts"] = time.time()

#     except WebSocketDisconnect:
#         logger.info("🔌 Client disconnected from audio stream")
#     except Exception as e:
#         logger.exception(f"Audio stream error: {e}")
#     finally:
#         if dg_socket:
#             try:
#                 dg_socket.finish()
#                 logger.info("🏁 Deepgram socket finished")
#             except Exception as e:
#                 logger.error(f"Error closing Deepgram socket: {e}")
#         try:
#             watchdog_task.cancel()
#         except Exception:
#             pass
#         await manager.disconnect(websocket)


# @router.websocket("/audio")
# async def audio_stream(websocket: WebSocket):
#     await websocket.accept()
#     logger.info("✅ New audio stream connected")

#     dg_socket = None
#     try:
#         dg_socket = deepgram.listen.websocket.v("1")
#         current_loop = asyncio.get_event_loop()

#         def on_transcript(self, result, **kwargs):
#             transcript = result.channel.alternatives[0].transcript
#             is_final = getattr(result, "is_final", False)
#             stt_lang_hint = getattr(result.metadata, "language", "en")
            
#             # Override language detection with content-based detection for more accuracy
#             spanish_words = ['hola', 'gracias', 'por favor', 'adiós', 'buenos días', 'buenas tardes', 'buenas noches', 'sí', 'con', 'para', 'que', 'como', 'donde', 'cuando', 'porque', 'necesito', 'ayuda', 'información']
#             has_spanish_words = any(word in transcript.lower() for word in spanish_words)
#             if has_spanish_words:
#                 stt_lang_hint = "es"
#             else:
#                 stt_lang_hint = "en"
            
#             if not transcript.strip():
#                 return
            
#             # Broadcast ONLY interim transcripts to avoid duplicate finals
#             if not is_final:
#                 broadcast_payload = {
#                     "message_id": str(uuid.uuid4()),
#                     "type": "transcript",
#                     "transcript": transcript,
#                     "is_final": False,
#                     "language": stt_lang_hint,
#                     "timestamp": datetime.now().isoformat()
#                 }
#                 asyncio.run_coroutine_threadsafe(
#                     manager.broadcast(broadcast_payload),
#                     current_loop
#                 )
#                 # update inactivity clock
#                 last_activity["ts"] = time.time()

#             # For final transcripts, run the processing pipeline which will broadcast the enriched entry
#             if is_final:
#                 logger.info(f"📝 Final Transcript: {transcript}")
#                 asyncio.run_coroutine_threadsafe(
#                     handle_real_time_transcript(transcript, stt_lang_hint),
#                     current_loop
#                 )

#         def on_error(dg, error, **kwargs):
#             logger.error(f"❌ Deepgram error: {error}")

#         dg_socket.on(LiveTranscriptionEvents.Transcript, on_transcript)
#         dg_socket.on(LiveTranscriptionEvents.Error, on_error)

#         options = LiveOptions(
#             model="nova-2",
#             encoding="linear16",
#             sample_rate=16000,
#             channels=1,
#             smart_format=True,
#             punctuate=True,
#             interim_results=True,   # For real-time UI updates
#             endpointing=300,        # Trigger finals after ~300ms silence (more responsive for slow speakers)
#             vad_events=True         # Voice activity detection
#         )
        
#         if not dg_socket.start(options):
#             logger.error("💥 Failed to start Deepgram socket")
#             await websocket.close()
#             return
#         logger.info("🚀 Deepgram socket started")

#         # Inactivity watchdog to auto-end session if caller stops
#         INACTIVITY_SECS = 8
#         last_activity = {"ts": time.time()}

#         async def inactivity_watchdog():
#             try:
#                 while True:
#                     await asyncio.sleep(2)
#                     if time.time() - last_activity["ts"] > INACTIVITY_SECS:
#                         logger.info("⏳ Inactivity detected; ending Deepgram session and flushing conversation")
#                         try:
#                             dg_socket.finish()
#                         except Exception:
#                             pass
#                         # End active session and flush buffered messages
#                         try:
#                             await end_active_session(caller_id="unknown")
#                         except Exception as e:
#                             logger.error(f"end_active_session failed: {e}")
#                         break
#             except asyncio.CancelledError:
#                 pass

#         watchdog_task = asyncio.create_task(inactivity_watchdog())

#         while True:
#             data = await websocket.receive_bytes()
#             if len(data) > 0:
#                 dg_socket.send(data)
#                 last_activity["ts"] = time.time()

#     except WebSocketDisconnect:
#         logger.info("🔌 Client disconnected from audio stream")
#     except Exception as e:
#         logger.exception(f"Audio stream error: {e}")
#     finally:
#         if dg_socket:
#             try:
#                 dg_socket.finish()
#                 logger.info("🏁 Deepgram socket finished")
#             except Exception as e:
#                 logger.error(f"Error closing Deepgram socket: {e}")
#         try:
#             watchdog_task.cancel()
#         except Exception:
#             pass
#         await manager.disconnect(websocket)




# @router.websocket("/transcripts/stream")
# async def transcript_stream(websocket: WebSocket):
#     """Stream for real-time transcript updates"""
#     await manager.connect(websocket)
#     try:
#         while True:
#             # Keep connection alive and handle any incoming messages
#             data = await websocket.receive_text()
#             logger.debug(f"Received on transcript stream: {data}")
#     except WebSocketDisconnect:
#         logger.info("Transcript stream client disconnected")
#     finally:
#         manager.disconnect(websocket)

# @router.websocket("/audio")
# async def audio_stream(websocket: WebSocket):
#     # 💡 Only let the manager call websocket.accept() (avoid double-accept)
#     await manager.connect(websocket)
#     logger.info("✅ New audio stream connected")

#     dg_socket = None
#     try:
#         # Deepgram socket
#         dg_socket = deepgram.listen.websocket.v("1")

#         # Use the running loop (get_event_loop() can be quirky under uvicorn)
#         current_loop = asyncio.get_running_loop()

#         def on_transcript(_dg, result, **kwargs):
#             try:
#                 alt = result.channel.alternatives[0] if result and result.channel and result.channel.alternatives else None
#                 transcript = getattr(alt, "transcript", "") or ""
#                 is_final = bool(getattr(result, "is_final", False))
#                 if not transcript.strip():
#                     return

#                 if is_final:
#                     logger.info(f"📝 Final Transcript: {transcript}")
#                     # fire-and-forget the async pipeline
#                     asyncio.run_coroutine_threadsafe(
#                         handle_real_time_transcript(transcript),
#                         current_loop
#                     )
#                 else:
#                     logger.debug(f"(Interim) {transcript}")
#             except Exception as e:
#                 logger.error(f"Transcript callback error: {e}")

#         def on_error(_dg, error, **kwargs):
#             logger.error(f"❌ Deepgram error: {error}")

#         dg_socket.on(LiveTranscriptionEvents.Transcript, on_transcript)
#         dg_socket.on(LiveTranscriptionEvents.Error, on_error)

#         # Start Deepgram connection
#         options = LiveOptions(
#             model="nova-2",
#             encoding="linear16",
#             sample_rate=16000,
#             channels=1,
#             smart_format=True,
#             punctuate=True,
#         )

#         if dg_socket.start(options) is False:
#             logger.error("💥 Failed to start Deepgram socket")
#             await websocket.close()
#             return
#         logger.info("🚀 Deepgram socket started")

#         # Stream incoming mic bytes to Deepgram with a timeout to avoid 1011 spam
#         while True:
#             try:
#                 data = await asyncio.wait_for(websocket.receive_bytes(), timeout=READ_TIMEOUT_SECONDS)
#             except asyncio.TimeoutError:
#                 logger.warning("⏳ No audio received within timeout; closing Deepgram socket to avoid 1011.")
#                 try:
#                     dg_socket.finish()
#                 except Exception:
#                     pass
#                 await websocket.close()
#                 break

#             if data:  # only send non-empty frames
#                 try:
#                     dg_socket.send(data)
#                 except Exception as e:
#                     logger.error(f"Deepgram send failed: {e}")
#                     break

#     except WebSocketDisconnect:
#         logger.info("🔌 Client disconnected from audio stream")
#     except Exception as e:
#         logger.exception(f"💥 Audio stream error: {e}")
#     finally:
#         if dg_socket:
#             try:
#                 dg_socket.finish()
#                 logger.info("🏁 Deepgram socket finished")
#             except Exception as e:
#                 logger.error(f"Error closing Deepgram socket: {e}")
#         # Always unregister the websocket from the manager
#         try:
#             await manager.disconnect(websocket)
#         except Exception:
#             pass


# app/routers/websocket_routes.py
# import asyncio
# import time
# from fastapi import APIRouter, WebSocket, WebSocketDisconnect
# from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents
# from app.core.connection_manager import manager
# from app.core.config import DEEPGRAM_API_KEY, logger
# from app.services.transcript_service import on_error, on_transcript

# router = APIRouter()
# deepgram = DeepgramClient(DEEPGRAM_API_KEY)

# # Tunables
# DG_KEEPALIVE_SECS = 8          # send tiny text to keep DG WS alive (if supported)
# DG_IDLE_CLOSE_SECS = 30        # if no audio for X sec, end DG session quietly

# async def _dg_keepalive(live, is_open_fn):
#     """Periodically send a tiny text to DG to avoid idle timeout (if supported)."""
#     # Not all SDK versions expose send_text; detect gracefully.
#     send_text = getattr(live, "send_text", None)
#     if not callable(send_text):
#         return
#     try:
#         while is_open_fn():
#             await asyncio.sleep(DG_KEEPALIVE_SECS)
#             if is_open_fn():
#                 try:
#                     await send_text("keepalive")
#                 except Exception:
#                     break
#     except Exception:
#         pass

# async def _dg_idle_watchdog(live, last_activity_ref, is_open_fn):
#     """Close DG cleanly if we’ve been idle for too long (prevents 1011 + spam)."""
#     finish = getattr(live, "finish", None) or getattr(live, "close", None)
#     if not callable(finish):
#         return
#     try:
#         while is_open_fn():
#             await asyncio.sleep(2)
#             if time.time() - last_activity_ref["ts"] > DG_IDLE_CLOSE_SECS:
#                 try:
#                     await finish()
#                 except Exception:
#                     pass
#                 break
#     except Exception:
#         pass

# @router.websocket("/transcripts/stream")
# async def transcripts_stream(websocket: WebSocket):
#     """
#     WS the frontend connects to for receiving transcript/assistant messages.
#     We only manage the connection lifecycle here.
#     """
#     try:
#         await manager.connect(websocket)
#         # Keep the socket open; broadcast() will push to it
#         while True:
#             # This socket is *receive-less*: just await a ping to keep it alive.
#             await websocket.receive_text()
#     except WebSocketDisconnect:
#         pass
#     except Exception as e:
#         logger.error(f"/transcripts/stream error: {e}")
#     finally:
#         await manager.disconnect(websocket)

# @router.websocket("/audio")
# async def audio_stream(websocket: WebSocket):
#     """
#     Browser streams raw audio to us; we forward to Deepgram Live and relay results.
#     """
#     await manager.connect(websocket)
#     await websocket.accept()  # accept early to be safe

#     # Track last activity to detect long silences
#     last_activity = {"ts": time.time()}
#     closed = {"flag": False}

#     # Create Deepgram Live connection
#     # Wire callbacks to your transcript handlers
#     def _on_open(_, **kwargs):
#         logger.info("🚀 Deepgram socket started")

#     def _on_close(_, **kwargs):
#         logger.info("🔚 Deepgram socket closed")

#     def _on_transcript(dg, result, **kwargs):
#         # update activity when we receive a transcript event too
#         last_activity["ts"] = time.time()
#         try:
#             on_transcript(dg, result, **kwargs)
#         except Exception as e:
#             logger.error(f"on_transcript error: {e}")

#     def _on_error(dg, err, **kwargs):
#         try:
#             on_error(dg, err, **kwargs)
#         except Exception:
#             logger.error(f"Deepgram error: {err}")

#     live_opts = LiveOptions(
#         model="nova-2-general",
#         encoding="linear16",
#         sample_rate=16000,
#         interim_results=True,
#         vad_events=True,        # VAD updates count as activity
#         endpointing=True,
#     )

#     # Connect to Deepgram Live
#     live = deepgram.listen.websocket.v("1").connect(
#         options=live_opts,
#         handlers={
#             LiveTranscriptionEvents.Open: _on_open,
#             LiveTranscriptionEvents.Close: _on_close,
#             LiveTranscriptionEvents.Transcript: _on_transcript,
#             LiveTranscriptionEvents.Error: _on_error,
#         },
#     )

#     # Helper to know if session is still open
#     def is_open():
#         return not closed["flag"] and live is not None

#     # Start keepalive + idle watchdog
#     keep_task = asyncio.create_task(_dg_keepalive(live, is_open))
#     idle_task = asyncio.create_task(_dg_idle_watchdog(live, last_activity, is_open))

#     # Prepare sending audio frames
#     # v3 SDK uses `send()` for bytes, older versions may use `send_audio`
#     send_audio = getattr(live, "send", None) or getattr(live, "send_audio", None)

#     try:
#         while is_open():
#             msg = await websocket.receive()
#             if "bytes" in msg and msg["bytes"] is not None:
#                 last_activity["ts"] = time.time()
#                 data = msg["bytes"]
#                 try:
#                     await send_audio(data)  # type: ignore
#                 except Exception:
#                     # one-shot close to avoid log flood
#                     closed["flag"] = True
#                     break
#             elif "text" in msg and msg["text"] is not None:
#                 # frontend keepalives/pings — just bump activity
#                 last_activity["ts"] = time.time()
#             else:
#                 # client closed or sent nothing useful
#                 closed["flag"] = True
#                 break

#     except WebSocketDisconnect:
#         pass
#     except Exception as e:
#         logger.error(f"/audio loop error: {e}")
#     finally:
#         closed["flag"] = True
#         for t in (keep_task, idle_task):
#             t.cancel()
#         # Close Deepgram quietly
#         try:
#             fin = getattr(live, "finish", None) or getattr(live, "close", None)
#             if callable(fin):
#                 await fin()
#         except Exception:
#             pass
#         await manager.disconnect(websocket)
#         logger.info("🏁 Deepgram socket finished")
